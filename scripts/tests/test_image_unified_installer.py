"""Exercise the ISO build wrapper with isolated container, signing and sudo mocks."""
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('bootstrap_build', ROOT / 'scripts/bootstrap-build.py')
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)
vm_spec = importlib.util.spec_from_file_location('installer_vm', ROOT / 'scripts/test-unified-installer-vm.py')
vm = importlib.util.module_from_spec(vm_spec)
vm_spec.loader.exec_module(vm)
policy_spec = importlib.util.spec_from_file_location('storage_policy', ROOT / 'installer/unified/storage-policy.py')
policy = importlib.util.module_from_spec(policy_spec)
policy_spec.loader.exec_module(policy)


class UnifiedISO(unittest.TestCase):
    def test_vm_rebase_receipt_ignores_echoed_program_and_requires_completion(self):
        echo = "> print('REBASE_STAGED='+json.dumps({'target':target}), flush=True)\r\n"
        receipt = {'target': 'ghcr.io/pelagians/alma9-server@sha256:' + 'a' * 64,
                   'digest': 'sha256:' + 'a' * 64, 'revision': 'b' * 40}
        marker = 'REBASE_STAGED=' + json.dumps(receipt) + '\r\n'
        self.assertEqual(vm.staged_rebase(echo + '\x1b]0;terminal\x07' + marker), receipt)
        for output in (echo, marker + marker, 'REBASE_RESOLVED=' + json.dumps(receipt)):
            with self.assertRaises(RuntimeError):
                vm.staged_rebase(output)

    def test_vm_bootc_response_requires_a_real_native_digest(self):
        document = {'apiVersion': 'org.containers.bootc/v1', 'status': {'booted': {
            'image': {'imageDigest': 'sha256:' + 'a' * 64}}}}
        self.assertEqual(vm.bootc_document('\x1b]0;terminal\x07noise\n' + json.dumps(document)), document)
        for output in ('unrelated output', '{"apiVersion":"org.containers.bootc/v1","status":{}}'):
            with self.assertRaises(RuntimeError):
                vm.bootc_document(output)

    def test_vm_absolute_pointer_stays_inside_screenshot(self):
        calls = []
        qmp = vm.QMP.__new__(vm.QMP)
        qmp.call = lambda *args, **kwargs: calls.append((args, kwargs))
        qmp.click(640, 400, 1280, 800)
        self.assertEqual(calls[0][1]['events'][0]['data'], {'axis': 'x', 'value': 16384})
        self.assertEqual(calls[0][1]['events'][1]['data'], {'axis': 'y', 'value': 16384})
        for point in ((-1, 0), (1280, 0), (0, 800)):
            with self.assertRaises(ValueError):
                qmp.click(*point, 1280, 800)

    def test_vm_graphical_status_ignores_serial_echo(self):
        echo = "printf 'SESSION_RESULT=%s\\n' ...\r\n"
        self.assertIsNone(vm.graphical_result(echo + 'SESSION_RESULT=pending\r\n'))
        self.assertEqual(vm.graphical_result(echo + 'SESSION_RESULT=0\r\n'), 0)
        self.assertEqual(vm.graphical_result('SESSION_RESULT=42\n'), 42)
        for output in (echo, 'SESSION_RESULT=0\nSESSION_RESULT=1\n'):
            with self.assertRaises(RuntimeError):
                vm.graphical_result(output)

    def test_vm_graphical_probe_preserves_qualifier_failure(self):
        home = self.root / 'home'
        (home / '.local/bin').mkdir(parents=True)
        (home / 'current-vm-stage').write_text('source')
        mock = home / 'mock-bin'
        mock.mkdir()
        for name in ('loginctl', 'systemctl', 'ps'):
            tool = mock / name
            tool.write_text('#!/bin/sh\nexit 0\n')
            tool.chmod(0o755)
        (home / '.local/bin/current-vm-qualify-workstation').write_text('exit 42\n')
        result = subprocess.run(['bash'], input=vm.session_probe(), text=True,
                                env=dict(os.environ, PATH=str(mock) + ':' + os.environ['PATH'], HOME=str(home), XDG_SESSION_TYPE='wayland',
                                         WAYLAND_DISPLAY='fixture', XDG_CURRENT_DESKTOP='fixture'))
        self.assertEqual(result.returncode, 42)
        self.assertEqual((home / 'current-vm-session-source.rc').read_text().strip(), '42')
        self.assertIn('DESKTOP=fixture', (home / 'current-vm-session-source.log').read_text())

    def test_journal_verifier_defers_only_unsupported_archives(self):
        root = '/var/log/journal/' + 'a' * 32 + '/'
        archive = root + 'system@000123-abcdef.journal~'
        good = 'PASS: ' + root + 'system.journal\r\n'
        unsupported = 'FAIL: ' + archive + ' (Operation not supported)\r\n'
        result = vm.journal_verification(good + unsupported + 'VERIFY_RC=1\r\n', True)
        self.assertEqual(result['deferred'], [archive])
        rotated = unsupported.replace('.journal~', '.journal')
        self.assertEqual(vm.journal_verification(good + rotated + 'VERIFY_RC=1\n', True)['deferred'], [archive[:-1]])
        with self.assertRaises(RuntimeError):
            vm.journal_verification(good + unsupported + 'VERIFY_RC=1\n')
        for bad in (unsupported.replace('Operation not supported', 'Bad message'),
                    rotated.replace('Operation not supported', 'Bad message'),
                    unsupported.replace('@000123-abcdef.journal~', '.journal'),
                    unsupported.replace('/var/log/journal/', '/tmp/')):
            with self.assertRaises(RuntimeError):
                vm.journal_verification(good + bad + 'VERIFY_RC=1\n', True)
        rollback = vm.journal_verification(good + 'PASS: ' + archive + '\nVERIFY_RC=0\n')
        self.assertTrue(set(result['deferred']).issubset(rollback['passed']))
        missing = vm.journal_verification(good + 'VERIFY_RC=0\n')
        self.assertFalse(set(result['deferred']).issubset(missing['passed']))
        for incomplete in (good, 'VERIFY_RC=0\n', good + 'VERIFY_RC=1\n',
                           good + unsupported + 'VERIFY_RC=0\n'):
            with self.assertRaises(RuntimeError):
                vm.journal_verification(incomplete, True)

    def test_vm_shutdown_acceptance_requires_pivots_and_no_final_failure(self):
        # A busy device on an initial unmount pass is allowed when the shutdown
        # initramfs subsequently takes over. Giving up before reboot is not.
        clean = 'systemd-shutdown[1]: Could not detach DM /dev/dm-0: Device or resource busy\nSuccessfully changed into root pivot.\nReturning to initrd...\ndracut: Unmounted /oldroot.\n'
        self.assertTrue(vm.shutdown_summary(clean * 2, 2)['passed'])
        self.assertTrue(vm.shutdown_summary(clean + clean.replace('Returning to initrd', 'Entering exitrd'), 2)['passed'])
        self.assertFalse(vm.shutdown_summary(clean, 2)['passed'])
        missing = clean.replace('dracut: Unmounted /oldroot.\n', '')
        self.assertFalse(vm.shutdown_summary(missing + clean, 2)['passed'])
        duplicate = clean.replace('dracut: Unmounted /oldroot.', 'dracut Warning: Unmounted /oldroot.\ndracut Warning: Unmounted /oldroot.')
        self.assertEqual(vm.shutdown_summary(duplicate, 1)['oldroot_unmounts'], 1)
        self.assertFalse(vm.shutdown_summary(missing + duplicate, 2)['passed'])
        self.assertFalse(vm.shutdown_summary(clean + 'systemd-shutdown[1]: Failed to execute shutdown binary: Permission denied\n', 1)['passed'])
        for failure in ('dracut Warning: Cannot umount /oldroot',
                        'dracut Warning: Unmounting /oldroot/sysroot timed out.',
                        'dracut Warning: reboot failed!',
                        'device-mapper: remove ioctl on current-root failed: Device or resource busy'):
            self.assertFalse(vm.shutdown_summary(clean + failure + '\n', 1)['passed'])
        for verb in ('Failed', 'Unable'):
            bad = clean * 2 + 'systemd-shutdown[1]: ' + verb + ' to finalize loop devices, DM devices, ignoring.\n'
            result = vm.shutdown_summary(bad, 2)
            self.assertFalse(result['passed'])
            self.assertEqual(len(result['finalization_failures']), 1)

    def test_vm_marker_comparison_ignores_terminal_framing(self):
        # Captured Fedora shell framing preceded a real journal entry and made
        # the first diagnostic run misreport a lost bootstrap marker.
        for terminator in ('\x07', '\x1b\\'):
            output = '\x1b]3008;start=fixture;type=command' + terminator + 'bootstrap\r\n'
            output += '\x1b[32mdestination\x1b[0m\r\n'
            self.assertEqual(vm.terminal_text(output).splitlines(), ['bootstrap', 'destination'])
        self.assertNotIn('bootstrap', vm.terminal_text('\x1b]0;bootstrap\x07destination\n').splitlines())

    def test_xfs_formatter_applies_profile_without_changing_other_formats(self):
        source = self.root / 'fsmkfs.py'
        original = '''from types import SimpleNamespace
availability = SimpleNamespace(BLOCKDEV_XFS_MKFS=True)
class FSBlockDevMkfs:
    def do_task(self, **kwargs): return kwargs
class XFSMkfs(FSBlockDevMkfs):
    ext = availability.BLOCKDEV_XFS_MKFS
    fstype = "xfs"
    can_nodiscard = True
    can_set_uuid = True
    can_label = True
    force = True
'''
        source.write_text(original)
        policy.install_xfs(source)
        namespace = {}
        exec(compile(source.read_text(), str(source), 'exec'), namespace)
        formatter = namespace['XFSMkfs']()
        options = ['-mreflink=1']
        self.assertEqual(formatter.do_task(options=options, label=True, set_uuid=True, nodiscard=True),
                         dict(options=['-mreflink=1', '-nparent=0', '-iexchange=0'], label=True, set_uuid=True, nodiscard=True))
        self.assertEqual(options, ['-mreflink=1'])
        self.assertEqual(formatter.do_task()['options'], ['-nparent=0', '-iexchange=0'])
        self.assertEqual(namespace['FSBlockDevMkfs']().do_task(), {})
        subclass = type('Subclass', (namespace['XFSMkfs'],), {})
        self.assertEqual(subclass().do_task()['options'], ['-nparent=0', '-iexchange=0'])
        for changed in (source.read_text(), original + '    def do_task(self): pass\n',
                        original.replace('force = True', 'force = False')):
            source.write_text(changed)
            with self.assertRaisesRegex(ValueError, 'contract changed'):
                policy.install_xfs(source)

    def test_vm_qmp_named_device_arguments(self):
        writes = []
        qmp = vm.QMP.__new__(vm.QMP)
        qmp.stream = SimpleNamespace(write=writes.append, readline=lambda: b'{"return": {}}\n')
        for up in (False, True):
            qmp.call('set_link', name='nic0', up=up)
            self.assertEqual(json.loads(writes[-1]), {'execute': 'set_link', 'arguments': {'name': 'nic0', 'up': up}})

    def test_installer_rejects_btrfs_mounts_and_new_formats(self):
        def device(fstype, mountpoint, exists=True, formatted=True):
            return SimpleNamespace(name='fixture', exists=exists,
                                   format=SimpleNamespace(type=fstype, mountpoint=mountpoint, exists=formatted))
        for mountpoint in ('/', '/home', '/var', '/boot', '/srv'):
            errors = []
            policy.verify_current_filesystems(SimpleNamespace(devices=[device('btrfs', mountpoint)]), {}, errors.append, None)
            self.assertEqual(len(errors), 1)
            self.assertIn('AlmaLinux', errors[0])
        for exists, formatted in ((False, False), (True, False)):
            errors = []
            policy.verify_current_filesystems(SimpleNamespace(devices=[device('btrfs', None, exists, formatted)]), {}, errors.append, None)
            self.assertEqual(len(errors), 1)
        errors = []
        policy.verify_current_filesystems(SimpleNamespace(devices=[device('xfs', '/'), device('efi', '/boot/efi'),
                                          device('btrfs', None)]), {}, errors.append, None)
        self.assertEqual(errors, [])

    def test_installer_storage_check_registration_and_upstream_drift(self):
        source = self.root / 'checker.py'
        source.write_text('def verify_root(*args): pass\nclass StorageChecker:\n'
                          '    def __init__(self):\n        self.checks = []\n'
                          '    def add_check(self, check): self.checks.append(check)\n'
                          '    def set_default_checks(self):\n        self.add_check(verify_root)\n')
        policy.install(source)
        namespace = {}
        exec(compile(source.read_text(), str(source), 'exec'), namespace)
        checker = namespace['StorageChecker']()
        checker.set_default_checks()
        self.assertEqual([check.__name__ for check in checker.checks], ['verify_root', 'verify_current_filesystems'])
        with self.assertRaisesRegex(ValueError, 'contract changed'):
            policy.install(source)
        source.write_text('class DifferentChecker: pass\n')
        with self.assertRaisesRegex(ValueError, 'contract changed'):
            policy.install(source)

    def test_vm_receipt_binding_and_checksum(self):
        iso = self.root / 'current-installer-x86_64.iso'
        iso.write_bytes(b'fixture ISO')
        digest = hashlib.sha256(iso.read_bytes()).hexdigest()
        iso.with_suffix('.iso.sha256').write_text(digest + '  ' + iso.name + '\n')
        receipt = self.root / 'build-inputs.txt'
        receipt.write_text('revision=' + 'a' * 40 + '\narchitecture=x86_64\npayload=' +
                           self.env['CURRENT_INSTALLER_PAYLOAD_REF'] + '\nembedded_source=' +
                           'localhost/current-bootstrap-payload:sha256-' + 'a' * 64 + '\n')
        self.assertEqual(vm.inputs(self.root, 'a' * 40)[1], digest)
        with self.assertRaisesRegex(ValueError, 'revision'):
            vm.inputs(self.root, 'b' * 40)
        iso.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
            vm.inputs(self.root, 'a' * 40)

    def test_vm_kickstart_only_targets_new_virtual_disk(self):
        ks = vm.kickstart({'payload': 'pinned', 'embedded_source': 'bound'}, 'ephemeral', 8080)
        self.assertIn('ignoredisk --only-use=vda', ks)
        self.assertIn('clearpart --all --initlabel --drives=vda', ks)
        self.assertIn('rootpw --lock', ks)
        self.assertIn('autopart\n', ks)
        self.assertNotIn('--fstype=', ks)
        self.assertNotIn('--nohome', ks)  # Exercise the shipping Anaconda layout.
        self.assertNotIn('NOPASSWD', ks)
        self.assertNotIn('autologin', ks)
        rejected = vm.kickstart({'payload': 'pinned', 'embedded_source': 'bound'}, 'ephemeral', 8080, 'reject-btrfs')
        self.assertIn('autopart --type=btrfs\n', rejected)
        self.assertNotIn('--fstype=xfs', rejected)

    def test_vm_negative_observer_collects_actual_validation_without_storage_commands(self):
        ks = vm.kickstart({'payload': 'pinned', 'embedded_source': 'bound'}, 'ephemeral', 8080, 'reject-btrfs')
        observer = ks.split('%pre\n', 1)[1].split('%end', 1)[0]
        # Run the real shell observer synchronously against isolated log fixtures.
        observer = observer.replace('/tmp/', str(self.root) + '/').replace('nohup sh -c', 'sh -c').replace('2>&1 &', '2>&1')
        (self.root / 'storage.log').write_text('DEBUG:anaconda.modules.storage.partitioning.validate:Found sanity error: Current cannot install using Btrfs: fixture\n')
        (self.root / 'anaconda.log').write_text('fixture summary\n')
        capture = self.root / 'uploads'
        curl = self.bin / 'curl'
        curl.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$CAPTURE"\n')
        curl.chmod(0o755)
        subprocess.run(['sh', '-c', observer], check=True, timeout=5,
                       env={**os.environ, 'PATH': str(self.bin) + ':' + os.environ['PATH'], 'CAPTURE': str(capture)})
        uploads = capture.read_text().splitlines()
        self.assertEqual(len(uploads), 3)
        self.assertIn('/storage.log', uploads[1])
        self.assertIn('validation-rejected http://10.0.2.2:8080/storage-rejected.log', uploads[2])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.output = self.root / 'output'
        self.log = self.root / 'commands'
        self.env = dict(os.environ, PATH=str(self.bin) + ':' + os.environ['PATH'],
                        CURRENT_INSTALLER_PAYLOAD_REF='ghcr.io/pelagians/current-bootstrap-x86_64@sha256:' + 'a' * 64,
                        CURRENT_INSTALLER_ARCH='x86_64', CURRENT_INSTALLER_OUTPUT_DIR=str(self.output),
                        MOCK_LOG=str(self.log))
        for name, script in {
            'uname': 'echo "${MOCK_ARCH:-x86_64}"',
            'sudo': 'if [[ "$1" != chown ]]; then exec "$@"; fi',
            'cosign': 'echo "$*" >> "$MOCK_LOG"; [[ "${MOCK_VERIFY_FAIL:-0}" = 0 ]]',
            'podman': '''printf '%s\\n' "$*" >> "$MOCK_LOG"
if [[ "$1 $2" == 'image inspect' ]]; then
  case "$4" in
    *Architecture*) echo "${MOCK_OCI_ARCH:-amd64}" ;;
    *Labels*) echo 1 ;;
    *) echo sha256:runtime ;;
  esac
elif [[ "$1" == run ]]; then
  [[ "${MOCK_BUILD_FAIL:-0}" = 0 ]] || exit 1
  mkdir -p "$CURRENT_INSTALLER_OUTPUT_DIR/bootiso"
  printf 'fixture ISO' > "$CURRENT_INSTALLER_OUTPUT_DIR/bootiso/install.iso"
fi''',
        }.items():
            path = self.bin / name
            path.write_text('#!/bin/bash\nset -eu\n' + script + '\n')
            path.chmod(0o755)

    def run_build(self):
        return subprocess.run(['bash', str(ROOT / 'scripts/build-unified-installer-iso.sh')],
                              env=self.env, capture_output=True, text=True)

    def test_native_both_architectures_output_and_checksum(self):
        for arch, oci in [('x86_64', 'amd64'), ('aarch64', 'arm64')]:
            with self.subTest(arch=arch):
                output = self.root / arch
                self.env.update(CURRENT_INSTALLER_ARCH=arch, MOCK_ARCH=arch, MOCK_OCI_ARCH=oci,
                                CURRENT_INSTALLER_OUTPUT_DIR=str(output))
                result = self.run_build()
                self.assertEqual(result.returncode, 0, result.stderr)
                iso = output / f'current-installer-{arch}.iso'
                self.assertTrue(iso.exists())
                check = subprocess.run(['sha256sum', '-c', iso.name + '.sha256'], cwd=output,
                                       capture_output=True, text=True)
                self.assertEqual(check.returncode, 0, check.stderr)
                commands = self.log.read_text()
                self.assertIn('--bootc-default-fs xfs', commands)
                self.assertIn('bootc-generic-iso', commands)
                local_source = 'localhost/current-bootstrap-payload:sha256-' + 'a' * 64
                self.assertIn('--bootc-installer-payload-ref ' + local_source, commands)
                self.assertIn('tag ' + self.env['CURRENT_INSTALLER_PAYLOAD_REF'] + ' ' + local_source, commands)
                self.assertIn('--build-arg CURRENT_PAYLOAD_REF=' + self.env['CURRENT_INSTALLER_PAYLOAD_REF'], commands)
                self.assertIn('--build-arg CURRENT_PAYLOAD_SOURCE=' + local_source, commands)
                self.assertIn('--seed 42', commands)
                self.assertLess(commands.index('verify --key'), commands.index('pull --arch'))
                again = self.run_build()
                self.assertNotEqual(again.returncode, 0)
                self.assertIn('empty output directory', again.stderr)

    def test_wrong_architecture_or_unpinned_payload_fails_before_commands(self):
        for overrides in ({'CURRENT_INSTALLER_ARCH': 'aarch64'},
                          {'CURRENT_INSTALLER_PAYLOAD_REF': 'ghcr.io/pelagians/current-bootstrap:latest'},
                          {'CURRENT_IMAGE_BUILDER': 'ghcr.io/osbuild/image-builder-cli:latest'}):
            with self.subTest(overrides=overrides), patch.dict(self.env, overrides):
                self.assertNotEqual(self.run_build().returncode, 0)
                self.assertFalse(self.log.exists())

    def test_verification_and_build_errors_do_not_publish_iso(self):
        for key in ('MOCK_VERIFY_FAIL', 'MOCK_BUILD_FAIL'):
            self.env.update({key: '1', 'CURRENT_INSTALLER_OUTPUT_DIR': str(self.root / key)})
            self.assertNotEqual(self.run_build().returncode, 0)
            self.assertFalse(list((self.root / key).glob('*.iso.sha256')))
            self.env.pop(key)

    def test_bootstrap_recipe_identity(self):
        with patch.object(build, 'ROOT', self.root), patch.dict(os.environ,
                GITHUB_SHA='a' * 40, GITHUB_RUN_ID='123', GITHUB_RUN_ATTEMPT='1'):
            (self.root / 'recipes').mkdir()
            (self.root / 'recipes/bootstrap.yml').write_text((ROOT / 'recipes/bootstrap.yml').read_text())
            for arch in build.ARCHES:
                relative = build.prepare(arch)
                text = (self.root / 'recipes' / relative.lstrip('/')).read_text()
                self.assertIn('name: current-bootstrap-' + arch, text)
                self.assertIn('org.opencontainers.image.revision: "' + 'a' * 40 + '"', text)
                self.assertIn('io.current.build: "run-123-1-', text)

    def test_bootstrap_resolution_rejects_wrong_commit(self):
        raw = json.dumps({'schemaVersion': 2})
        config = {'architecture': 'amd64', 'os': 'linux', 'config': {'Labels': {
            'containers.bootc': '1', 'org.opencontainers.image.revision': 'b' * 40,
            'io.current.build': 'run-123-1-amd64'}}}
        def run(*args):
            if args[1] == 'list-tags':
                return json.dumps({'Tags': ['run-123-1-amd64-44']})
            return json.dumps(config) if '--config' in args else raw
        with patch.dict(os.environ, GITHUB_SHA='a' * 40, GITHUB_RUN_ID='123', GITHUB_RUN_ATTEMPT='1'), patch.object(build, 'run', run):
            with self.assertRaises(ValueError):
                build.resolve('x86_64')
            config['config']['Labels']['org.opencontainers.image.revision'] = 'a' * 40
            self.assertIn('@sha256:', build.resolve('x86_64'))

    def test_payload_is_not_the_installer_runtime(self):
        recipe = (ROOT / 'recipes/bootstrap.yml').read_text()
        for unwanted in ('layers/shared/core-base.yml', 'layers/shared/core.yml', 'anaconda', 'cosmic', 'gnome', 'k3s', 'ceph'):
            self.assertNotIn(unwanted, recipe)
        containerfile = (ROOT / 'installer/unified/Containerfile').read_text()
        self.assertIn('FROM ${CURRENT_INSTALLER_BASE}', containerfile)
        self.assertIn('grub2-efi-aa64-cdboot shim-aa64', containerfile)
        kickstart = (ROOT / 'installer/unified/interactive-defaults.ks').read_text()
        for forbidden in ('clearpart', 'autopart', 'zerombr', 'user --', 'rootpw --plaintext'):
            self.assertNotIn(forbidden, kickstart)
        self.assertIn('rootpw --lock', kickstart)
        self.assertIn('selinux --enforcing', kickstart)
        runtime = (ROOT / 'installer/unified/prepare-runtime.sh').read_text()
        self.assertIn('file_system_type = xfs', runtime)
        self.assertIn('default_scheme = LVM', runtime)
        self.assertIn('root_device_types = LVM MD PARTITION DISK LVM_THINP', runtime)
        self.assertIn('python3 /tmp/storage-policy.py', runtime)
        self.assertIn('default_partitioning =\n    / (min 10 GiB)', runtime)
        self.assertNotIn('/home (', runtime)
        iso_config = (ROOT / 'installer/unified/iso.yaml').read_text()
        self.assertIn('selinux=1 enforcing=0', iso_config)
        self.assertNotIn('selinux=0', iso_config)


class NativeEFI(unittest.TestCase):
    def test_fedora_assets_for_each_architecture_and_missing_asset(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            font = root / 'usr/share/grub/unicode.pf2'
            font.parent.mkdir(parents=True)
            font.write_text('font')
            for arch, suffix in [('x86_64', 'x64'), ('aarch64', 'aa64')]:
                destination = root / 'boot/efi/EFI/fedora'
                updates = root / 'usr/lib/bootupd/updates/EFI/fedora'
                package = root / 'usr/lib/efi/shim/test/EFI/fedora'
                updates.mkdir(parents=True, exist_ok=True)
                package.mkdir(parents=True, exist_ok=True)
                names = [f'shim{suffix}.efi', f'mm{suffix}.efi', f'gcd{suffix}.efi']
                for name in names:
                    ((package if name.startswith('shim') else updates) / name).write_text(name)
                args = ['bash', str(ROOT / 'installer/alma10-server/prepare-efi.sh'), str(root), 'fedora', arch]
                result = subprocess.run(args, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                for name in names:
                    self.assertEqual((destination / name).read_text(), name)
                (destination / names[2]).unlink()
                (updates / names[2]).unlink()
                (updates / f'grub{suffix}.efi').write_text('not CD boot')
                result = subprocess.run(args, capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)


if __name__ == '__main__':
    unittest.main()
