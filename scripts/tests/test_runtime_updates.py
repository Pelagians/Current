"""Installed update helpers with temporary tools, homes, markers and credentials."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
HELPERS = ROOT / 'files/justfiles/usr/libexec'


def executable(path, body):
    path.write_text('#!/bin/bash\n' + body + '\n')
    path.chmod(0o755)


class Updates(unittest.TestCase):
    def test_system_server_skip_and_workstation_missing_helper(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / 'calls'
            marker = root / 'desktop.env'
            helper = root / 'managed-flatpak'
            executable(root / 'sudo', '''printf '%s\\n' "$*" >> "$CALL_LOG"
if [[ "$1" == bootc ]]; then exit "$BOOTC_RESULT"; fi
[[ -x "$1" ]] || exit 127
exit "$FP_RESULT"''')
            body = (HELPERS / 'current-update-system').read_text().replace(
                '/usr/share/current/workstation/desktop.env', str(marker)).replace(
                '/usr/libexec/current-flatpak-system-maintenance', str(helper))
            env = dict(os.environ, PATH=str(root), CALL_LOG=str(log), BOOTC_RESULT='0', FP_RESULT='0')
            for workstation, installed, bootc, fp, expected_calls, expected_result in (
                (False, False, 0, 0, 1, 0), (False, False, 8, 0, 1, 1),
                (True, False, 0, 0, 2, 1), (False, True, 0, 7, 2, 1)):
                with self.subTest(workstation=workstation, installed=installed, bootc=bootc):
                    if workstation: marker.touch()
                    else: marker.unlink(missing_ok=True)
                    if installed: executable(helper, 'exit 0')
                    else: helper.unlink(missing_ok=True)
                    log.write_text('')
                    result = subprocess.run(['/bin/bash'], input=body, text=True, capture_output=True,
                                            env=dict(env, BOOTC_RESULT=str(bootc), FP_RESULT=str(fp)))
                    self.assertEqual(result.returncode, expected_result, result.stderr)
                    self.assertEqual(len(log.read_text().splitlines()), expected_calls)
                    self.assertIn('bootc upgrade', log.read_text())
                    self.assertEqual('skipped' in result.stdout, not workstation and not installed)

    def test_server_user_update_skips_absent_flatpak_but_workstation_requires_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable(root / 'distrobox-upgrade', 'echo distrobox')
            marker = root / 'desktop.env'
            body = (HELPERS / 'current-update-user').read_text().replace('/usr/share/current/workstation/desktop.env', str(marker))
            env = dict(os.environ, PATH=str(root), HOME=str(root), XDG_DATA_HOME=str(root / 'data'))
            result = subprocess.run(['/bin/bash'], input=body, text=True, capture_output=True, env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('distrobox', result.stdout)
            marker.touch()
            result = subprocess.run(['/bin/bash'], input=body, text=True, capture_output=True, env=env)
            self.assertEqual(result.returncode, 127)
            self.assertNotIn('distrobox', result.stdout)

    def test_retained_distrobox_repair_preserves_backup_and_usable_old_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / 'data/containers/storage/overlay-containers/box/userdata/config.json'
            config.parent.mkdir(parents=True)
            for name in ('flatpak', 'distrobox-upgrade'):
                executable(root / name, 'exit 0')
            (root / 'bin').mkdir(); (root / 'sbin').mkdir()
            new = root / 'bin/distrobox-export'
            old = root / 'sbin/distrobox-export'
            executable(new, 'exit 0')
            original = '{"mounts":[{"source":"' + str(old) + '","destination":"/helper"}],"unrelated":true}'
            config.write_text(original)
            body = (HELPERS / 'current-update-user').read_text().replace('/usr/share/current/workstation/desktop.env', str(root / 'desktop.env'))
            body = body.replace('/usr/bin/', str(root / 'bin') + '/').replace('/usr/sbin/', str(root / 'sbin') + '/')
            env = dict(os.environ, PATH=str(root) + ':' + os.environ['PATH'], HOME=str(root), XDG_DATA_HOME=str(root / 'data'))
            executable(old, 'exit 0')
            result = subprocess.run(['/bin/bash'], input=body, text=True, capture_output=True, env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(config.read_text(), original)
            backup = Path(str(config) + '.current-distrobox-helper-paths.bak')
            self.assertFalse(backup.exists())
            old.unlink()
            for _ in range(2):
                result = subprocess.run(['/bin/bash'], input=body, text=True, capture_output=True, env=env)
                self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(config.read_text(), original.replace(str(old), str(new)))
            self.assertEqual(backup.read_text(), original)

    def test_podman_auth_precedence_and_no_auth_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = [root / 'explicit', root / 'runtime/containers/auth.json',
                     root / '.config/containers/auth.json', root / '.docker/config.json']
            for path in paths:
                path.parent.mkdir(parents=True, exist_ok=True); path.write_text('{}')
            executable(root / 'podman', 'printf "%s\\n" "$*" >> "$CALL_LOG"')
            body = (HELPERS / 'current-update-podman').read_text()
            env = dict(os.environ, PATH=str(root), HOME=str(root), XDG_RUNTIME_DIR=str(root / 'runtime'),
                       REGISTRY_AUTH_FILE=str(paths[0]), CALL_LOG=str(root / 'calls'))
            for path in [*paths, None]:
                (root / 'calls').write_text('')
                result = subprocess.run(['/bin/bash'], input=body, text=True, capture_output=True, env=env)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual((root / 'calls').read_text().splitlines(),
                                 ['image prune -f', 'auto-update' + (f' --authfile {path}' if path else '')])
                if path: path.unlink()

    def test_public_just_targets_delegate_to_installed_executable_helpers(self):
        for name in ('rebase', 'update-system', 'update-user', 'update-podman', 'update-all'):
            with self.subTest(name=name):
                helper = HELPERS / ('current-' + name)
                self.assertTrue(os.access(helper, os.X_OK))
                just = ROOT / 'files/justfiles/usr/share/current/just' / ('rebase.just' if name == 'rebase' else 'update.just')
                self.assertIn(name + ':\n  /usr/libexec/current-' + name + '\n', just.read_text())
