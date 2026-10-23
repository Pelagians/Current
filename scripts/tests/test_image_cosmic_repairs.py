"""Reject source drift and corrupt repair artifacts before building a candidate."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def module(name, script):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / script)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


build = module('cosmic_repair_build', 'build-cosmic-repairs.py')
candidate = module('cosmic_repair_candidate', 'prepare-cosmic-repair-candidate.py')


class NativeRepairs(unittest.TestCase):
    def test_seed_reuses_only_present_unexpired_artifacts_from_same_branch_builder(self):
        previous = dict(status='completed', head_branch='codex/unified-installer',
                        head_repository=dict(full_name='Pelagians/Current'),
                        path='.github/workflows/build.yml', event='workflow_dispatch')
        artifacts = dict(total_count=2, artifacts=[
            dict(name='cosmic-repair-alma10-cosmic-panel', expired=False),
            dict(name='cosmic-repair-alma9-cosmic-initial-setup', expired=True)])
        with patch.dict(os.environ, GITHUB_REPOSITORY='Pelagians/Current', GITHUB_REF_NAME='codex/unified-installer'):
            with patch.object(build.subprocess, 'check_output', side_effect=[json.dumps(previous), json.dumps(artifacts)]):
                rows = build.matrix('123')['include']
                self.assertEqual([(row['distribution'], row['package']) for row in rows if row['seed_run']], [('alma10', 'cosmic-panel')])
            for changed in (dict(previous, status='in_progress'), dict(previous, head_branch='other'),
                            dict(previous, path='unrelated.yml'), dict(previous, event='pull_request'),
                            dict(previous, head_repository=dict(full_name='Other/Repository'))):
                with self.subTest(changed=changed), patch.object(build.subprocess, 'check_output', return_value=json.dumps(changed)):
                    with self.assertRaises(ValueError):
                        build.matrix('123')
        with patch.object(build.subprocess, 'check_output') as command:
            with self.assertRaises(ValueError):
                build.matrix('../123')
            command.assert_not_called()

    def test_spec_preserves_native_tests_dependencies_and_install(self):
        native = ('Name: cosmic-panel\nRelease: %autorelease\nSource2: vendor.toml\n'
                  'BuildRequires: cargo\n%prep\n%autosetup -n cosmic-panel -p1 -a1\n'
                  '%build\njust build-release\n%install\njust install\n%check\n%cargo_test\n'
                  '%changelog\n%autochangelog\n')
        result = build.patch_spec(native, '1.el10')
        self.assertIn('Release: 1.el10.current1\n', result)
        self.assertIn('Patch900: current-repair.patch\n', result)
        self.assertIn(native[native.index('BuildRequires:'):native.index('%changelog')], result)
        self.assertNotIn('%autochangelog', result)
        static = native.replace('%autochangelog', '* Thu Oct 22 2026 Vendor\n- Native history.')
        self.assertIn('* Thu Oct 22 2026 Vendor\n- Native history.', build.patch_spec(static, '1.el10'))
        for invalid in (native.replace('Source2:', 'Source3:'),
                        native.replace('%autosetup ', '%setup '),
                        native + 'Release: another\n', native + '%autochangelog\n', result):
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
