"""Exercise installer EFI preparation without touching host boot files."""
from pathlib import Path
import subprocess
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "installer/alma10-server/prepare-efi.sh"
DEST = Path("boot/efi/EFI/almalinux")
UPDATES = Path("usr/lib/bootupd/updates/EFI/almalinux")
FONT = Path("usr/share/grub/unicode.pf2")


class InstallerEFI(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.put(FONT, b"font")
        self.put(DEST / "gcdx64.efi", b"cdboot-grub")
        self.put(UPDATES / "shimx64.efi", b"signed-shim")
        self.put(UPDATES / "mmx64.efi", b"signed-mokmanager")

    def put(self, relative, content):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def run_prepare(self):
        return subprocess.run(["bash", str(SCRIPT), str(self.root)],
                              capture_output=True, text=True)

    def test_bootupd_layout_and_repeated_execution(self):
        for _ in range(2):
            result = self.run_prepare()
            self.assertEqual(result.returncode, 0, result.stderr)
            for name in ("shimx64.efi", "mmx64.efi"):
                self.assertEqual((self.root / DEST / name).read_bytes(),
                                 (self.root / UPDATES / name).read_bytes())
            self.assertEqual((self.root / DEST / "gcdx64.efi").read_bytes(),
                             b"cdboot-grub")

    def test_existing_package_files_take_precedence(self):
        self.put(DEST / "shimx64.efi", b"newer-signed-shim")
        self.put(DEST / "mmx64.efi", b"newer-mokmanager")
        result = self.run_prepare()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / DEST / "shimx64.efi").read_bytes(),
                         b"newer-signed-shim")
        self.assertEqual((self.root / DEST / "mmx64.efi").read_bytes(),
                         b"newer-mokmanager")

    def test_missing_or_empty_assets_fail_before_copying(self):
        for relative in (UPDATES / "shimx64.efi", UPDATES / "mmx64.efi",
                         DEST / "gcdx64.efi", FONT):
            for empty in (False, True):
                with self.subTest(asset=str(relative), empty=empty):
                    path = self.root / relative
                    original = path.read_bytes()
                    if empty:
                        path.write_bytes(b"")
                    else:
                        path.unlink()
                    result = self.run_prepare()
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(relative.name, result.stderr)
                    self.assertFalse((self.root / DEST / "shimx64.efi").exists())
                    self.assertFalse((self.root / DEST / "mmx64.efi").exists())
                    path.write_bytes(original)

    def test_installed_system_grub_is_not_cdboot_grub(self):
        (self.root / DEST / "gcdx64.efi").unlink()
        self.put(UPDATES / "grubx64.efi", b"system-grub")
        result = self.run_prepare()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("gcdx64.efi", result.stderr)

    def test_build_wiring_and_interactive_configuration(self):
        containerfile = (ROOT / "installer/alma10-server/Containerfile").read_text()
        self.assertIn("COPY installer/alma10-server/prepare-efi.sh", containerfile)
        self.assertIn("RUN bash /tmp/current-installer-prepare-efi.sh", containerfile)
        self.assertLess(containerfile.index("grub2-efi-x64-cdboot"),
                        containerfile.index("RUN bash"))
        self.assertNotIn("|| true", containerfile)
        config = tomllib.loads((ROOT / "installer/alma10-server/iso.toml").read_text())
        self.assertEqual(set(config["customizations"]), {"installer"})
        kickstart = config["customizations"]["installer"]["kickstart"]["contents"]
        self.assertIn("\ngraphical\n", kickstart)
        self.assertNotIn("clearpart", kickstart)
        self.assertNotIn("autopart", kickstart)


if __name__ == "__main__":
    unittest.main()
