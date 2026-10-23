"""Installer account labeling and persistent-image package provisioning."""
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('account_policy', ROOT / 'installer/unified/account-policy.py')
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)
health_spec = importlib.util.spec_from_file_location('workstation_health', ROOT / 'scripts/qualify-workstation-health.py')
health = importlib.util.module_from_spec(health_spec)
health_spec.loader.exec_module(health)


class Accounts(unittest.TestCase):
    def test_bootc_exposes_only_needed_selinux_submount_and_tracks_teardown(self):
        original = '''class PrepareBootcMountTargetsTask:
    def _handle_api_mount_points(self):
        for path in ("/proc", "/sys"):
            sysroot_path = self._sysroot + path
            safe_exec_program("mount", ["--bind", path, sysroot_path])
            self._internal_mounts.append(sysroot_path)
'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'installation.py'; path.write_text(original)
            policy.install_mounts(path)
            mount = Mock(); scope = dict(safe_exec_program=mount)
            exec(compile(path.read_text(), str(path), 'exec'), scope)
            task = scope['PrepareBootcMountTargetsTask']()
            task._sysroot = '/target'; task._internal_mounts = []
            task._handle_api_mount_points()
            self.assertEqual(task._internal_mounts, ['/target/proc', '/target/sys', '/target/sys/fs/selinux'])
            self.assertEqual(mount.call_args_list[-1].args,
                             ('mount', ['--bind', '/sys/fs/selinux', '/target/sys/fs/selinux']))
            self.assertNotIn('--rbind', path.read_text())
            with self.assertRaisesRegex(ValueError, 'contract changed'):
                policy.install_mounts(path)
            path.write_text(original.replace('"/sys"', '"/dev"'))
            with self.assertRaisesRegex(ValueError, 'contract changed'):
                policy.install_mounts(path)

    def test_health_rejects_colord_denials_separately_from_bootc_probe(self):
        probe = 'type=AVC avc: denied { mac_admin } scontext=system_u:system_r:unconfined_service_t:s0 tcontext=system_u:object_r:invalid_bootcinstall_testlabel_t:s0'
        health.check_avcs(probe)
        with self.assertRaisesRegex(RuntimeError, 'Color daemon'):
            health.check_avcs(probe + '\ntype=AVC avc:  denied { read } scontext=system_u:system_r:colord_t:s0 tcontext=unconfined_u:object_r:var_t:s0')

    def test_health_detects_incorrect_types_without_forcing_context_user(self):
        expected = lambda path: b'unconfined_u:object_r:user_home_dir_t:s0\n'
        labels = health.check_labels([Path('/fixture')],
                                    get_context=lambda path: b'system_u:object_r:user_home_dir_t:s0\0',
                                    expected_context=expected)
        self.assertEqual(len(labels), 1)
        with self.assertRaisesRegex(RuntimeError, 'Incorrect native-policy type'):
            health.check_labels([Path('/fixture')],
                                get_context=lambda path: b'system_u:object_r:var_t:s0\0',
                                expected_context=expected)

    def test_installer_labels_only_successfully_created_new_homes(self):
        original = '''def create_user(root, homedir):
    mk_homedir = not os.path.exists(root + homedir)
    status = util.execWithRedirect("useradd", args)
    if status:
        raise ValueError('user creation failed')
'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'users.py'
            path.write_text(original)
            policy.install(path)
            util = SimpleNamespace(execWithCapture=Mock(return_value='/var/home/alice\n'),
                                   execWithRedirect=Mock(return_value=0))
            exists = Mock(return_value=False)
            scope = dict(util=util, os=SimpleNamespace(path=SimpleNamespace(exists=exists)), args=['fixture'])
            exec(compile(path.read_text(), str(path), 'exec'), scope)
            scope['create_user']('/target', '/home/alice')
            self.assertEqual(util.execWithRedirect.call_args_list[1].args[0], 'selinuxenabled')
            self.assertEqual(util.execWithRedirect.call_args_list[2].args,
                             ('restorecon', ['-R', '-v', '--', '/var/home/alice']))
            self.assertTrue(all(call.kwargs.get('root') == '/target'
                                for call in util.execWithRedirect.call_args_list[1:]))
            self.assertIn('/etc/.pwd.lock', util.execWithRedirect.call_args_list[3].args[1])
            util.execWithRedirect.reset_mock()
            exists.return_value = True
            scope['create_user']('/target', '/home/alice')
            self.assertEqual(util.execWithRedirect.call_count, 1)  # reused data untouched
            util.execWithRedirect.side_effect = [1]
            with self.assertRaises(ValueError):
                scope['create_user']('/target', '/home/alice')
            with self.assertRaisesRegex(ValueError, 'contract changed'):
                policy.install(path)
            path.write_text(original.replace('mk_homedir =', 'new_home ='))
            with self.assertRaisesRegex(ValueError, 'contract changed'):
                policy.install(path)

    def test_native_policy_labeling_errors_are_not_hidden(self):
        function = policy._current_label_new_home
        scope = function.__globals__
        from unittest.mock import patch
        for home, statuses in [('/', []), ('', []), ('/var/home/alice', [1]),
                               ('/var/home/alice', [0, 1]), ('/var/home/alice', [0, 0, 1])]:
            util = SimpleNamespace(execWithCapture=Mock(return_value=home),
                                   execWithRedirect=Mock(side_effect=statuses))
            with self.subTest(home=home, statuses=statuses), patch.dict(scope, util=util):
                with self.assertRaises(RuntimeError):
                    function('/target', '/home/alice')

    def test_sysusers_uses_packaged_ids_and_rejects_invalid_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tools = root / 'tools'; tools.mkdir()
            getent = tools / 'getent'
            getent.write_text('#!/bin/sh\ncase "$1" in\npasswd) echo "$PACKAGED_USER";;\ngroup) echo "avahi:x:70:";;\nesac\n')
            getent.chmod(0o755)
            env = dict(os.environ, PATH=str(tools) + ':' + os.environ['PATH'],
                       PACKAGED_USER='avahi:x:70:70:Avahi daemon:/run/avahi-daemon:/sbin/nologin')
            script = ROOT / 'files/scripts/setup-avahi-account.sh'
            result = subprocess.run(['bash', str(script), str(root)], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            contents = (root / 'usr/lib/sysusers.d/90-current-avahi.conf').read_text()
            self.assertIn('g avahi 70\nu avahi 70:avahi "Avahi daemon"', contents)
            self.assertFalse((root / 'etc/passwd').exists())
            env['PACKAGED_USER'] = 'avahi:x:1000:70:User:/home/user:/bin/bash'
            result = subprocess.run(['bash', str(script), str(root)], env=env, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((root / 'usr/lib/sysusers.d/90-current-avahi.conf').read_text(), contents)

    def test_el9_copy_retains_existing_files_and_symlinks(self):
        unit = (ROOT / 'files/workstation/alma9/usr/lib/systemd/system/brew-setup.service.d/10-current-el9-copy.conf').read_text()
        copy = next(line.removeprefix('ExecStart=') for line in unit.splitlines()
                    if line.startswith('ExecStart=/usr/bin/cp ')).split()
        self.assertEqual(copy[:4], ['/usr/bin/cp', '-R', '-n', '/usr/share/homebrew/home/linuxbrew/.linuxbrew'])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source/.linuxbrew'; source.mkdir(parents=True)
            destination = root / 'linuxbrew'; destination.mkdir()
            (source / 'existing').write_text('image default')
            (source / 'new').write_text('new file')
            (source / 'link').symlink_to('new')
            subprocess.run(copy[:3] + [str(source), str(destination)], check=True)
            installed = destination / '.linuxbrew'
            self.assertTrue((installed / 'link').is_symlink())
            (installed / 'existing').write_text('user data')
            # Some modern cp versions use a nonzero status for a skipped file;
            # EL9 returns zero. The upstream unit conditions skip existing prefixes.
            subprocess.run(copy[:3] + [str(source), str(destination)], capture_output=True)
            self.assertEqual((installed / 'existing').read_text(), 'user data')
            self.assertEqual((installed / 'new').read_text(), 'new file')


if __name__ == '__main__':
    unittest.main()
