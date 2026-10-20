"""Synthetic hardware and isolated setup transactions; never mutate the host."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'files/setup/usr/lib'))
from current_setup import hardware as hw
from current_setup import execution as ex
from current_setup import cli
from current_setup.matrix import load_rows

MATRIX = ROOT / 'files/base/runtime/usr/share/current/image-matrix.tsv'
COMPAT = ROOT / 'files/setup/usr/share/current/setup-compatibility.json'
FIXTURE = ROOT / 'scripts/tests/fixtures/setup/intel-uefi.json'
DIGEST = 'sha256:' + 'a' * 64
TARGET = 'ghcr.io/pelagians/fedora-server@' + DIGEST


def slot(target, digest):
    return {'image': {'image': {'image': target, 'transport': 'registry', 'signature': 'containerPolicy'},
                      'imageDigest': digest}}


class Selection(unittest.TestCase):
    def setUp(self):
        self.rows, self.compat = hw.catalogue(MATRIX, COMPAT)
        self.hardware = json.loads(FIXTURE.read_text())

    def select(self, **kwargs):
        return hw.recommend(self.hardware, self.rows, self.compat, **kwargs)

    def gpu(self, vendor, device):
        self.hardware['gpus'] = [{'vendor': vendor, 'device': device, 'slot': '0000:01:00.0'}]

    def test_cpu_architecture_and_shared_references(self):
        for arch in ('x86_64', 'aarch64'):
            self.hardware['architecture'] = arch
            result = self.select()
            self.assertTrue(result['candidates'])
            for row in result['candidates']:
                self.assertEqual(row['architecture'], arch)
                self.assertNotIn('-arm64:', row['reference'])
                self.assertFalse(row['boot_qualified'])
                self.assertFalse(row['driver_qualified'])
        self.hardware['architecture'] = 'riscv64'
        self.assertFalse(self.select()['candidates'])

    def test_amd_intel_and_headless_use_standard(self):
        for vendor in ('1002', '8086', '1af4'):
            self.gpu(vendor, 'abcd')
            self.assertEqual(self.select()['recommended']['driver'], 'standard')
        self.hardware['gpus'] = []
        self.assertEqual(self.select()['recommended']['driver'], 'standard')

    def test_modern_and_legacy_nvidia(self):
        for device, driver in [('13c2', 'nvidia-580'), ('1b80', 'nvidia-580'),
                               ('2182', 'nvidia-open'), ('2684', 'nvidia-open')]:
            self.gpu('10de', device)
            result = self.select(role='workstation', desktop='cosmic')
            self.assertEqual(result['recommended']['driver'], driver)
            self.assertEqual(result['recommended']['environment'], 'cosmic')
        self.gpu('10de', '1b80')
        self.assertEqual(self.select(distribution='alma10')['recommended']['driver'], 'standard')

    def test_unknown_nvidia_requires_manual_standard_fallback(self):
        self.gpu('10de', 'ffff')
        result = self.select()
        self.assertIsNone(result['recommended'])
        self.assertTrue(result['manual_selection_required'])
        self.assertEqual({row['driver'] for row in result['candidates']}, {'standard'})
        self.gpu('abcd', '1234')
        self.assertIsNone(self.select()['recommended'])

    def test_multiple_gpus_intersect_compatible_drivers(self):
        self.gpu('10de', '1b80')
        self.hardware['gpus'] += [{'vendor': '10de', 'device': '2684'}, {'vendor': '8086', 'device': '1234'}]
        result = self.select()
        self.assertEqual(result['recommended']['driver'], 'nvidia-580')
        self.assertTrue(any('Multiple GPUs' in warning for warning in result['warnings']))
        self.hardware['gpus'][1]['device'] = 'ffff'
        self.assertIsNone(self.select()['recommended'])

    def test_secure_boot_never_assumes_module_enrollment(self):
        self.gpu('10de', '2684')
        for value in ('enabled', 'unknown'):
            self.hardware['secure_boot'] = value
            self.assertIsNone(self.select()['recommended'])
            self.assertEqual({row['driver'] for row in self.select()['candidates']}, {'standard'})

    def test_arm_platform_constraints(self):
        self.hardware['architecture'] = 'aarch64'
        for model in ('Apple M2', 'apple,t8103', 'Asahi Linux'):
            self.hardware['platform'] = model
            self.assertFalse(self.select()['candidates'])
        self.hardware['platform'] = 'Generic SBSA'
        self.assertTrue(self.select()['candidates'])
        self.hardware['uefi'] = False
        self.assertFalse(self.select()['candidates'])

    def test_cpu_levels_filter_alma_lanes(self):
        for level in (None, 1, 2, 3):
            self.hardware['cpu_level'] = level
            for distro, minimum in [('alma9', 2), ('alma10', 3)]:
                self.assertEqual(bool(self.select(distribution=distro)['candidates']),
                                 level is not None and level >= minimum)

    def test_inventory_metadata_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'matrix.tsv'
            for content in ('', MATRIX.read_text().splitlines()[0] + '\n',
                            MATRIX.read_text().replace('fedora-server\t', 'oops\t', 1),
                            MATRIX.read_text() + MATRIX.read_text().splitlines()[1] + '\n',
                            MATRIX.read_text().replace('server-images\t', 'bad\t', 1),
                            MATRIX.read_text().replace('\n', '\textra\n', 2)):
                path.write_text(content)
                with self.assertRaises(ValueError):
                    load_rows(path)
            path.write_text('{}')
            with self.assertRaises(ValueError):
                hw.catalogue(MATRIX, path)
            with self.assertRaises(OSError):
                hw.catalogue(MATRIX, Path(directory) / 'missing')

    def test_discovery_from_sysfs_and_cpu_intersection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def put(name, data):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data if isinstance(data, bytes) else data.encode())
            put('proc/cpuinfo', 'flags\t: ' + ' '.join(hw.V3) + '\nflags\t: ' + ' '.join(hw.V2))
            put('sys/firmware/efi/efivars/SecureBoot-test', b'\x07\0\0\0\x01')
            for number, vendor in enumerate(('8086', '1002', '10de')):
                base = f'sys/bus/pci/devices/0000:0{number}:00.0/'
                put(base + 'class', '0x030000')
                put(base + 'vendor', '0x' + vendor)
                put(base + 'device', '0x2182')
            put('sys/bus/pci/devices/0000:03:00.0/class', '0x020000')
            result = hw.discover(root, 'amd64')
            self.assertEqual(result['architecture'], 'x86_64')
            self.assertEqual(result['cpu_level'], 2)
            self.assertEqual(result['secure_boot'], 'enabled')
            self.assertEqual([gpu['vendor'] for gpu in result['gpus']], ['8086', '1002', '10de'])
            self.assertEqual(hw.discover(Path(directory) / 'absent', 'arm64')['secure_boot'], 'unknown')


class FakeCommands:
    def __init__(self):
        self.calls = []
        self.current = {'booted': slot('ghcr.io/pelagians/current-bootstrap@sha256:' + 'b' * 64,
                                        'sha256:' + 'b' * 64), 'staged': None}
        self.fail = None
        self.bad = None
        self.stage_output = True

    def __call__(self, args, timeout=60):
        self.calls.append(args)
        if self.fail and self.fail in args:
            raise ex.SetupError('mock network/verification/staging failure')
        if args[:2] == ['bootc', 'status']:
            return json.dumps({'status': self.current})
        if args[:2] == ['bootc', 'switch']:
            if self.stage_output:
                self.current['staged'] = slot(args[-1], args[-1].split('@')[1])
            return ''
        if args[0] == 'skopeo':
            if '--raw' in args:
                entries = [{'platform': {'os': 'linux', 'architecture': 'amd64'}, 'digest': DIGEST}]
                if self.bad == 'missing':
                    entries = []
                if self.bad == 'duplicate':
                    entries *= 2
                return json.dumps({'manifests': entries})
            metadata = {'Architecture': 'amd64', 'Os': 'linux', 'Digest': DIGEST,
                        'Labels': {'containers.bootc': '1', 'io.current.setup-api': '1', 'org.opencontainers.image.revision': 'c' * 40}}
            if self.bad in metadata:
                metadata[self.bad] = None
            if self.bad == 'Labels':
                metadata['Labels'] = {}
            return json.dumps(metadata)
        raise AssertionError(args)


class Transactions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = ex.Store(Path(self.temp.name))
        self.run = FakeCommands()
        self.hardware = json.loads(FIXTURE.read_text())
        rows, compat = hw.catalogue(MATRIX, COMPAT)
        self.candidate = hw.recommend(self.hardware, rows, compat)['recommended']

    def stage(self, **kwargs):
        return ex.stage(self.store, self.candidate, self.hardware, self.run,
                        policy_check=kwargs.pop('policy_check', lambda _: None), boot_id='boot-one', **kwargs)

    def test_staged_is_not_complete_and_destination_requires_user_acceptance(self):
        state = self.stage()
        self.assertEqual(state['phase'], 'image-staged')
        switch = next(call for call in self.run.calls if call[:2] == ['bootc', 'switch'])
        self.assertEqual(switch, ['bootc', 'switch', '--enforce-container-sigpolicy', '--retain', TARGET])
        self.assertNotIn('--apply', switch)
        with self.assertRaises(ex.SetupError):
            ex.complete(self.store, self.run)
        self.run.current['booted'] = self.run.current.pop('staged')
        state = ex.reconcile(self.store, self.run, 'boot-two')
        self.assertEqual(state['phase'], 'destination-booted')
        self.assertEqual(ex.complete(self.store, self.run)['phase'], 'complete')
        calls = len(self.run.calls)
        self.assertEqual(ex.reconcile(self.store, self.run)['phase'], 'complete')
        self.assertEqual(len(self.run.calls), calls)
        with self.assertRaises(ex.SetupError):
            self.stage()

    def test_network_failure_and_retry_preserve_questionnaire(self):
        self.run.fail = 'skopeo'
        with self.assertRaises(ex.SetupError):
            self.stage()
        state = self.store.load()
        self.assertEqual(state['phase'], 'recovery-required')
        self.assertEqual(state['candidate']['image'], 'fedora-server')
        self.assertFalse(any(call[:2] == ['bootc', 'switch'] for call in self.run.calls))
        self.run.fail = None
        self.assertEqual(self.stage()['phase'], 'image-staged')

    def test_signature_policy_rejection_and_bootc_staging_failure(self):
        def reject(_):
            raise ex.SetupError('signature policy missing')
        with self.assertRaises(ex.SetupError):
            self.stage(policy_check=reject)
        self.assertFalse(any(call[:2] == ['bootc', 'switch'] for call in self.run.calls))
        self.run.fail = 'switch'
        with self.assertRaises(ex.SetupError):
            self.stage()
        self.assertEqual(self.store.load()['phase'], 'recovery-required')
        self.assertIsNotNone(self.store.load()['source'])

    def test_metadata_failures_never_switch(self):
        for bad in ('missing', 'duplicate', 'Architecture', 'Os', 'Digest', 'Labels'):
            with self.subTest(bad=bad):
                self.run.bad = bad
                with self.assertRaises(ex.SetupError):
                    self.stage()
                self.assertFalse(any(call[:2] == ['bootc', 'switch'] for call in self.run.calls))

    def test_success_return_without_staged_image_requires_recovery(self):
        self.run.stage_output = False
        with self.assertRaises(ex.SetupError):
            self.stage()
        self.assertEqual(self.store.load()['phase'], 'recovery-required')

    def test_crash_after_switch_recovers_from_selected_receipt(self):
        state = self.stage()
        self.store.save(state, 'image-selected')
        self.assertEqual(ex.reconcile(self.store, self.run, 'boot-one')['phase'], 'image-staged')
        self.run.current['staged'] = None
        self.assertEqual(ex.reconcile(self.store, self.run, 'boot-two')['phase'], 'recovery-required')

    def test_wrong_digest_or_same_boot_is_not_success(self):
        self.stage()
        self.run.current['staged'] = None
        self.run.current['booted'] = slot(TARGET, 'sha256:' + 'd' * 64)
        self.assertEqual(ex.reconcile(self.store, self.run, 'boot-two')['phase'], 'recovery-required')
        with self.assertRaises(ex.SetupError):
            ex.complete(self.store, self.run)

    def test_existing_staged_deployment_and_non_bootc_host_rejected(self):
        self.run.current['staged'] = slot('other', DIGEST)
        with self.assertRaises(ex.SetupError):
            self.stage()
        self.assertEqual(self.store.load()['phase'], 'not-configured')
        self.run.current = {}
        with self.assertRaises(ex.SetupError):
            self.stage()

    def test_pending_rollback_readonly_and_changed_deployment_fail_closed(self):
        for flag in ('rollbackQueued', 'readOnly'):
            self.run.current[flag] = True
            with self.assertRaises(ex.SetupError):
                self.stage()
            self.run.current.pop(flag)
        original = self.run
        def changed(args, timeout=60):
            result = original(args, timeout)
            if args[0] == 'skopeo' and '--raw' not in args:
                original.current['staged'] = slot('another-update', DIGEST)
            return result
        self.run = changed
        with self.assertRaisesRegex(ex.SetupError, 'changed during validation'):
            self.stage()
        self.assertFalse(any(call[:2] == ['bootc', 'switch'] for call in original.calls))

    def test_interrupted_switch_can_resume(self):
        original = self.run
        def interrupt(args, timeout=60):
            output = original(args, timeout)
            if args[:2] == ['bootc', 'switch']:
                raise KeyboardInterrupt
            return output
        self.run = interrupt
        with self.assertRaises(KeyboardInterrupt):
            self.stage()
        self.assertEqual(self.store.load()['phase'], 'recovery-required')
        self.assertEqual(ex.reconcile(self.store, original, 'boot-one')['phase'], 'image-staged')

    def test_store_lock_corruption_and_private_atomic_state(self):
        with self.store.locked():
            with self.assertRaises(ex.SetupError), ex.Store(self.store.directory).locked():
                pass
        self.stage()
        self.assertEqual(self.store.path.stat().st_mode & 0o777, 0o600)
        self.assertFalse(list(self.store.directory.glob('.state-*')))
        for content in ('{broken', json.dumps({'schema': 1, 'phase': 'complete', 'history': []})):
            self.store.path.write_text(content)
            with self.assertRaises(ex.SetupError):
                self.store.load()

    def test_effective_policy_rejects_permissive_more_specific_scope(self):
        key = self.store.directory / 'key.pub'
        key.write_text('fixture-key')
        policy = self.store.directory / 'policy.json'
        rule = {'type': 'sigstoreSigned', 'keyPath': str(key), 'signedIdentity': {'type': 'matchRepository'}}
        data = {'default': [{'type': 'reject'}], 'transports': {'docker': {'ghcr.io/pelagians': [rule]}}}
        policy.write_text(json.dumps(data))
        ex.check_policy(TARGET, policy, key)
        data['transports']['docker']['ghcr.io/pelagians/fedora-server'] = [{'type': 'insecureAcceptAnything'}]
        policy.write_text(json.dumps(data))
        with self.assertRaises(ex.SetupError):
            ex.check_policy(TARGET, policy, key)


class Frontend(unittest.TestCase):
    def test_machine_output_and_interactive_dry_run(self):
        base = [sys.executable, '-m', 'current_setup.cli']
        options = ['--fixture', str(FIXTURE), '--matrix', str(MATRIX), '--compatibility', str(COMPAT)]
        env = dict(os.environ, PYTHONPATH=str(ROOT / 'files/setup/usr/lib'), PYTHONDONTWRITEBYTECODE='1')
        result = subprocess.run(base + ['plan'] + options, env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['recommended']['image'], 'fedora-server')
        result = subprocess.run(base + ['--dry-run'] + options, input='4\n1\nn\n',
                                env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Dry run: no registry access', result.stdout)
        result = subprocess.run(base + options, env=env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('restricted to plan and dry-run', result.stderr)
        result = subprocess.run(base + ['complete', '--dry-run'], env=env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('--dry-run applies only to wizard', result.stderr)

    def test_first_boot_guard_and_destination_vendor_service(self):
        profile = (ROOT / 'files/bootstrap/etc/profile.d/current-setup.sh').read_text()
        self.assertIn('/usr/share/current/bootstrap', profile)
        self.assertIn('SSH_CONNECTION', profile)
        self.assertIn('sudo /usr/libexec/current-setup', profile)
        self.assertNotIn('autologin', profile)
        service = ROOT / 'files/setup/usr/lib/systemd/system/current-setup-reconcile.service'
        self.assertIn('ConditionPathExists=/var/lib/current/setup/state.json', service.read_text())
        self.assertTrue((service.parent / 'multi-user.target.wants' / service.name).is_symlink())
        self.assertFalse((ROOT / 'files/bootstrap/etc/systemd/system/default.target').exists())


class ConsoleIntegration(unittest.TestCase):
    def test_profile_authenticates_local_admin_and_preserves_ssh(self):
        import pty
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / 'bootstrap'
            marker.touch()
            log = root / 'log'
            binary = root / 'bin'
            binary.mkdir()
            for name, body in {
                'tty': 'echo "${MOCK_TTY:-/dev/tty1}"',
                'id': 'if [ "$1" = -u ]; then echo 1000; else echo "user wheel"; fi',
                'sudo': 'echo authenticated >> "$MOCK_LOG"',
            }.items():
                tool = binary / name
                tool.write_text('#!/bin/sh\n' + body + '\n')
                tool.chmod(0o755)
            source = (ROOT / 'files/bootstrap/etc/profile.d/current-setup.sh').read_text()
            profile = root / 'profile.sh'
            profile.write_text(source.replace('/usr/share/current/bootstrap', str(marker)))
            env = dict(os.environ, PATH=str(binary) + ':' + os.environ['PATH'], MOCK_LOG=str(log))
            master, slave = pty.openpty()
            try:
                for ssh, tty, expected in [('', '/dev/tty1', True), ('host', '/dev/tty1', False),
                                           ('', '/dev/pts/1', False), ('', '/dev/ttyAMA0', True)]:
                    log.unlink(missing_ok=True)
                    result = subprocess.run(['bash', '--noprofile', '--norc', '-ic', 'source "$1"', 'bash', str(profile)],
                                            stdin=slave, capture_output=True, text=True,
                                            env=dict(env, SSH_CONNECTION=ssh, MOCK_TTY=tty))
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(log.exists(), expected)
                marker.unlink()
                log.unlink(missing_ok=True)
                subprocess.run(['bash', '--noprofile', '--norc', '-ic', 'source "$1"', 'bash', str(profile)],
                               stdin=slave, capture_output=True, env=env)
                self.assertFalse(log.exists())
            finally:
                os.close(master)
                os.close(slave)

    def test_native_systemd_unit_has_no_dependency_cycle(self):
        with tempfile.TemporaryDirectory() as directory:
            source = ROOT / 'files/setup/usr/lib/systemd/system/current-setup-reconcile.service'
            unit = Path(directory) / source.name
            unit.write_text(source.read_text().replace('/usr/libexec/current-setup reconcile', '/usr/bin/true'))
            result = subprocess.run(['systemd-analyze', 'verify', str(unit)], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
