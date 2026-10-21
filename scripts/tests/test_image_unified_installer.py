"""Exercise the ISO build wrapper with isolated container, signing and sudo mocks."""
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('bootstrap_build', ROOT / 'scripts/bootstrap-build.py')
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)
vm_spec = importlib.util.spec_from_file_location('installer_vm', ROOT / 'scripts/test-unified-installer-vm.py')
vm = importlib.util.module_from_spec(vm_spec)
vm_spec.loader.exec_module(vm)


class UnifiedISO(unittest.TestCase):
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
        self.assertIn('--fstype=xfs', ks)
        self.assertNotIn('NOPASSWD', ks)
        self.assertNotIn('autologin', ks)

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
        runtime = (ROOT / 'installer/unified/prepare-runtime.sh').read_text()
        self.assertIn('file_system_type = xfs', runtime)
        self.assertIn('default_scheme = LVM', runtime)


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
