"""Regression tests for the validators' negative assertions, using isolated files."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class NegativeAssertions(unittest.TestCase):
    def check(self, *args):
        return subprocess.run(['bash', '-euc',
                               'source "$1"; shift; reject_matches "$@"; echo continued',
                               'validation-test', str(ROOT / 'scripts/validation.sh'), *map(str, args)],
                              text=True, capture_output=True)

    def test_matches_fail_instead_of_continuing_under_errexit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'source'
            path.write_text('forbidden content\n')
            result = self.check('-q', 'forbidden', path)
            self.assertEqual(result.returncode, 1)
            self.assertIn('Forbidden content matched', result.stderr)
            self.assertNotIn('continued', result.stdout)

    def test_no_matches_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'source'
            path.write_text('allowed content\n')
            result = self.check('-q', 'forbidden', path)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), 'continued')

    def test_missing_files_and_invalid_patterns_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'source'
            path.write_text('content\n')
            for pattern, target in (('forbidden', path.with_name('absent')), ('[', path)):
                with self.subTest(pattern=pattern):
                    result = self.check('-q', pattern, target)
                    self.assertEqual(result.returncode, 2)
                    self.assertNotIn('continued', result.stdout)

    def test_recursive_exclusions_are_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'source').write_text('allowed\n')
            (root / 'history').mkdir()
            (root / 'history/record').write_text('forbidden\n')
            self.assertEqual(self.check('-RInE', '--exclude-dir=history', 'forbidden', root).returncode, 0)
            self.assertEqual(self.check('-RInE', 'forbidden', root).returncode, 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
