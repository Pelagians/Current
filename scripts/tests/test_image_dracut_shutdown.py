"""Check build-time initrd lookup compatibility without touching host boot files."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class DracutShutdown(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def image(self, version='7.2.11.x86_64'):
        image = self.root / 'usr/lib/modules' / version / 'initramfs.img'
        image.parent.mkdir(parents=True)
        image.write_bytes(b'generated fixture')
        return image

    def run_link(self):
        return subprocess.run(['bash', str(ROOT / 'files/scripts/dracut-initrd-link.sh'), str(self.root)],
                              capture_output=True, text=True)

    def test_all_kernels_relative_links_and_regeneration(self):
        images = [self.image(), self.image('6.12.0.aarch64')]
        for _ in range(2):
            result = self.run_link()
            self.assertEqual(result.returncode, 0, result.stderr)
            for image in images:
                link = image.with_name('initrd')
                self.assertEqual(str(link.readlink()), 'initramfs.img')
                self.assertEqual(link.read_bytes(), image.read_bytes())
                image.write_bytes(b'regenerated fixture')

    def test_existing_vendor_initrd_is_preserved(self):
        image = self.image()
        initrd = image.with_name('initrd')
        initrd.write_bytes(b'vendor shutdown image')
        self.assertEqual(self.run_link().returncode, 0)
        self.assertFalse(initrd.is_symlink())
        self.assertEqual(initrd.read_bytes(), b'vendor shutdown image')

    def test_missing_or_empty_generated_image_fails(self):
        self.assertNotEqual(self.run_link().returncode, 0)
        image = self.image()
        image.write_bytes(b'')
        self.assertNotEqual(self.run_link().returncode, 0)
        self.assertFalse(image.with_name('initrd').exists())

    def test_broken_or_empty_vendor_initrd_is_not_replaced(self):
        image = self.image()
        initrd = image.with_name('initrd')
        initrd.symlink_to('missing-vendor-image')
        self.assertNotEqual(self.run_link().returncode, 0)
        self.assertEqual(str(initrd.readlink()), 'missing-vendor-image')
        initrd.unlink()
        initrd.touch()
        self.assertNotEqual(self.run_link().returncode, 0)
        self.assertFalse(initrd.is_symlink())


if __name__ == '__main__':
    unittest.main()
