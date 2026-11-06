"""Check graphical identity resolution without contacting host logind."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts/qualify-workstation-boot.sh'


class GraphicalQualification(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        loginctl = self.root / 'loginctl'
        loginctl.write_text('''#!/bin/bash
set -eu
if [[ "$1" == show-user ]]; then printf '%s\\n' "${TEST_DISPLAY_SESSION:-}"; exit 0; fi
[[ "$1" == show-session && "$2" == g1 ]] || exit 1
case "${3:-}" in
  --property=User) printf '%s\\n' "$TEST_SESSION_UID" ;;
  --property=Type) printf '%s\\n' "$TEST_SESSION_TYPE" ;;
  --property=State) printf '%s\\n' "$TEST_SESSION_STATE" ;;
  -p) printf 'User=%s\\nType=%s\\nState=%s\\n' "$TEST_SESSION_UID" "$TEST_SESSION_TYPE" "$TEST_SESSION_STATE" ;;
  *) exit 2 ;;
esac
''')
        loginctl.chmod(0o755)
        self.env = {key: value for key, value in os.environ.items()
                    if key not in ('XDG_SESSION_ID', 'XDG_CURRENT_DESKTOP', 'XDG_SESSION_TYPE', 'WAYLAND_DISPLAY', 'DISPLAY')}
        self.env.update(PATH=str(self.root) + ':' + os.environ['PATH'], TEST_DISPLAY_SESSION='g1',
                        TEST_SESSION_UID=str(os.getuid()), TEST_SESSION_TYPE='wayland', TEST_SESSION_STATE='active',
                        XDG_CURRENT_DESKTOP='COSMIC', XDG_SESSION_TYPE='wayland', WAYLAND_DISPLAY='fixture')

    def qualify(self, desktop='COSMIC'):
        return subprocess.run(['bash', '-c', 'source "$1"; qualify_session "$2"', 'test', str(SCRIPT), desktop],
                              env=self.env, text=True, capture_output=True)

    def test_systemd_autostart_and_direct_session_identity(self):
        for session in ('', 'g1'):
            self.env['XDG_SESSION_ID'] = session
            result = self.qualify()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('Type=wayland', result.stdout)
        self.env['XDG_CURRENT_DESKTOP'] = 'GNOME:GNOME'
        self.assertEqual(self.qualify('GNOME').returncode, 0)

    def test_wrong_or_missing_graphical_identity_fails(self):
        for key, value in (('TEST_DISPLAY_SESSION', ''), ('TEST_SESSION_UID', str(os.getuid() + 99)),
                           ('TEST_SESSION_TYPE', 'tty'), ('TEST_SESSION_STATE', 'closing'),
                           ('XDG_CURRENT_DESKTOP', 'GNOME'), ('XDG_SESSION_TYPE', 'tty'),
                           ('WAYLAND_DISPLAY', '')):
            with self.subTest(key=key, value=value):
                original = self.env[key]
                self.env[key] = value
                self.assertNotEqual(self.qualify().returncode, 0)
                self.env[key] = original


if __name__ == '__main__':
    unittest.main()
