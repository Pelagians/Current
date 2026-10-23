"""Reject source drift and corrupt repair artifacts before building a candidate."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


def module(name, script):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / script)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


build = module('cosmic_repair_build', 'build-cosmic-repairs.py')
candidate = module('cosmic_repair_candidate', 'prepare-cosmic-repair-candidate.py')


class NativeRepairs(unittest.TestCase):
    def test_spec_preserves_native_tests_dependencies_and_install(self):
        native = ('Name: cosmic-panel\nRelease: %autorelease\nSource2: vendor.toml\n'
                  'BuildRequires: cargo\n%prep\n%autosetup -n cosmic-panel -p1 -a1\n'
                  '%build\njust build-release\n%install\njust install\n%check\n%cargo_test\n')
        result = build.patch_spec(native, '1.el10')
        self.assertIn('Release: 1.el10.current1\n', result)
        self.assertIn('Patch900: current-repair.patch\n', result)
        self.assertTrue(result.endswith(native[native.index('BuildRequires:'):]))
        for invalid in (native.replace('Source2:', 'Source3:'),
                        native.replace('%autosetup ', '%setup '),
                        native + 'Release: another\n', result):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    build.patch_spec(invalid, '1.el10')

    def artifacts(self, directory):
        configuration = json.loads((build.INPUTS / 'sources.json').read_text())['alma10']
        for package, source in configuration['packages'].items():
            rpm = directory / (package + '-1.11.0-1.el10.current1.x86_64.rpm')
            rpm.write_bytes(b'synthetic native package')
            receipt = dict(distribution='alma10', package=package, source=source,
                           native_version=source['version'], base=configuration['base'],
                           base_revision=configuration['base_revision'], rpm=rpm.name,
                           rpm_sha256=hashlib.sha256(rpm.read_bytes()).hexdigest(),
                           patch_sha256=hashlib.sha256(
                               (build.INPUTS / 'patches' / source['patch']).read_bytes()).hexdigest())
            (directory / (package + '.json')).write_text(json.dumps(receipt))

    def test_context_contains_only_verified_runtime_rpms_and_receipts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.artifacts(root)
            (root / 'vendor.src.rpm').write_bytes(b'large source and build dependencies')
            candidate.prepare('alma10', root, root / 'context')
            self.assertEqual(len(list((root / 'context/rpms').iterdir())), 2)
            self.assertFalse(list((root / 'context').rglob('*.src.rpm')))
            text = (root / 'context/Containerfile').read_text()
            self.assertIn("--disablerepo='*'", text)
            self.assertIn('bootc container lint', text)

    def test_corruption_source_drift_missing_metadata_and_path_escape_fail_before_writing(self):
        for mutation in ('bytes', 'base', 'source', 'patch_sha256', 'missing', 'escape'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                self.artifacts(root)
                metadata = root / 'cosmic-panel.json'
                receipt = json.loads(metadata.read_text())
                if mutation == 'bytes':
                    (root / receipt['rpm']).write_bytes(b'corrupt')
                elif mutation == 'missing':
                    metadata.unlink()
                elif mutation == 'escape':
                    receipt['rpm'] = '../outside.x86_64.rpm'
                else:
                    receipt[mutation] = 'different inputs'
                if mutation != 'missing':
                    metadata.write_text(json.dumps(receipt))
                with self.assertRaises(ValueError):
                    candidate.prepare('alma10', root, root / 'context')
                self.assertFalse((root / 'context').exists())
