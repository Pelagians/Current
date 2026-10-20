"""Run image-time compatibility linking only inside a temporary filesystem."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class DistroboxLinks(unittest.TestCase):
    def test_creates_usable_relative_links_and_preserves_existing_executables(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'bin').mkdir(); (root / 'sbin').mkdir()
            for name in ('distrobox-export', 'distrobox-host-exec', 'distrobox-init'):
                path = root / 'bin' / name
                path.write_text('#!/bin/sh\nexit 0\n'); path.chmod(0o755)
            existing = root / 'sbin/distrobox-init'
            existing.write_text('#!/bin/sh\n# packaged compatibility helper\n'); existing.chmod(0o755)
            body = (ROOT / 'files/scripts/distrobox-helper-links.sh').read_text()
            body = body.replace('/usr/bin/', str(root / 'bin') + '/').replace('/usr/sbin/', str(root / 'sbin') + '/')
            for _ in range(2):
                result = subprocess.run(['bash'], input=body, text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((root / 'sbin/distrobox-export').readlink(), Path('../bin/distrobox-export'))
            self.assertTrue((root / 'sbin/distrobox-host-exec').resolve().is_file())
            self.assertFalse(existing.is_symlink())

    def test_missing_packaged_helper_fails_build(self):
        with tempfile.TemporaryDirectory() as directory:
            body = (ROOT / 'files/scripts/distrobox-helper-links.sh').read_text().replace('/usr/', directory + '/')
            self.assertNotEqual(subprocess.run(['bash'], input=body, text=True, capture_output=True).returncode, 0)
