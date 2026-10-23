"""Reject source drift and corrupt repair artifacts before building a candidate."""
import hashlib
import base64
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
installer = module('cosmic_repair_installer', '../files/scripts/install-cosmic-repairs.py')


class NativeRepairs(unittest.TestCase):
    def test_normal_cosmic_layer_uses_the_reviewed_immutable_bundle(self):
        bundle = json.loads((build.INPUTS / 'bundle.json').read_text())
        for name in ('runtime', 'sources'):
            self.assertRegex(bundle[name], r'^ghcr\.io/pelagians/current-cosmic-repairs@sha256:[0-9a-f]{64}$')
        self.assertEqual(bundle['catalogue_sha256'], hashlib.sha256((build.INPUTS / 'sources.json').read_bytes()).hexdigest())
        self.assertEqual(bundle['patches'], {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                           for p in (build.INPUTS / 'patches').glob('*.patch')})
        layer = (ROOT / 'recipes/layers/shared/workstation-cosmic.yml').read_text()
        self.assertIn('from=' + bundle['runtime'] + ',src=/,dst=/tmp/current-cosmic-repairs,ro', layer)
        self.assertIn('install-cosmic-repairs.py /tmp/current-cosmic-repairs', layer)
        self.assertNotIn(bundle['sources'], layer)

    def test_native_installation_checks_all_inputs_before_dnf_and_preserves_arm(self):
        with patch.object(installer, 'rpm', return_value='aarch64'), patch.object(installer.subprocess, 'run') as command:
            installer.install(Path('/absent'), 'alma9', Path('/unused'))
            command.assert_not_called()
        for mutation in ('none', 'bytes', 'native-version', 'rpm-metadata', 'install-failure'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                artifacts = root / 'artifacts'
                artifacts.mkdir()
                self.artifacts(artifacts)
                candidate.prepare('alma10', artifacts, root / 'alma10')
                installed = False
                def rpm(*args):
                    if args[0] == '--eval':
                        return 'x86_64'
                    if args[0] == '-qp':
                        if mutation == 'rpm-metadata':
                            return 'wrong architecture aarch64'
                        name = Path(args[-1]).name.split('-1.11.0-')[0]
                        return name + ' 1.11.0-1.el10.current1 x86_64'
                    if mutation == 'native-version':
                        return '1.12.0-1.el10'
                    return '1.11.0-1.el10' + ('.current1' if installed else '')
                def run(*args, **kwargs):
                    nonlocal installed
                    if mutation == 'install-failure':
                        raise installer.subprocess.CalledProcessError(1, args[0])
                    installed = True
                if mutation == 'bytes':
                    next((root / 'alma10/rpms').iterdir()).write_bytes(b'bad')
                with patch.object(installer, 'rpm', side_effect=rpm), patch.object(installer.subprocess, 'run', side_effect=run) as command:
                    if mutation == 'none':
                        installer.install(root, 'alma10', root / 'installed-receipts')
                        self.assertEqual(len(list((root / 'installed-receipts').iterdir())), 2)
                        self.assertIn('--disablerepo=*', command.call_args.args[0])
                    else:
                        with self.assertRaises((ValueError, installer.subprocess.CalledProcessError)):
                            installer.install(root, 'alma10', root / 'installed-receipts')
                        self.assertFalse((root / 'installed-receipts').exists())
                        if mutation != 'install-failure':
                            command.assert_not_called()

    def test_installer_distribution_identity(self):
        self.assertEqual(installer.distribution('ID=fedora\nVERSION_ID=44'), 'fedora')
        self.assertEqual(installer.distribution('ID="almalinux"\nVERSION_ID="9.8"'), 'alma9')
        self.assertEqual(installer.distribution('ID=almalinux\nVERSION_ID="10.2"'), 'alma10')
        for release in ('ID=unknown', 'ID=almalinux\nVERSION_ID=8'):
            with self.assertRaises(ValueError):
                installer.distribution(release)

    def test_seed_reuses_only_present_unexpired_artifacts_from_same_branch_builder(self):
        previous = dict(status='completed', head_branch='codex/unified-installer',
                        head_sha='a' * 40,
                        head_repository=dict(full_name='Pelagians/Current'),
                        path='.github/workflows/build.yml', event='workflow_dispatch')
        artifacts = dict(total_count=2, artifacts=[
            dict(name='cosmic-repair-alma10-cosmic-panel', expired=False),
            dict(name='cosmic-repair-alma9-cosmic-initial-setup', expired=True)])
        def blob(data):
            return json.dumps(dict(encoding='base64', size=len(data), content=base64.b64encode(data).decode()))
        catalogue = (build.INPUTS / 'sources.json').read_bytes()
        native_patch = (build.INPUTS / 'patches/panel-transparent-repaint.patch').read_bytes()
        with patch.dict(os.environ, GITHUB_REPOSITORY='Pelagians/Current', GITHUB_REF_NAME='codex/unified-installer'):
            with patch.object(build.subprocess, 'check_output', side_effect=[json.dumps(previous), json.dumps(artifacts), blob(catalogue), blob(native_patch)]):
                rows = build.matrix('123')['include']
                self.assertEqual([(row['distribution'], row['package']) for row in rows if row['seed_run']], [('alma10', 'cosmic-panel')])
            for old_patch in (b'different repair', native_patch):
                old_catalogue = json.loads(catalogue)
                if old_patch == native_patch:
                    old_catalogue['alma10']['packages']['cosmic-panel']['sha256'] = 'b' * 64
                responses = [json.dumps(previous), json.dumps(artifacts), blob(json.dumps(old_catalogue).encode()), blob(old_patch)]
                with patch.object(build.subprocess, 'check_output', side_effect=responses):
                    self.assertFalse(any(row['seed_run'] for row in build.matrix('123')['include']))
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

    def test_bundle_separates_corresponding_sources_and_rejects_corrupt_runtime(self):
        for corrupt in (False, True):
            with self.subTest(corrupt=corrupt), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                inputs = root / 'inputs'
                inputs.mkdir()
                config = json.loads((build.INPUTS / 'sources.json').read_text())
                (inputs / 'sources.json').write_text(json.dumps({'alma10': config['alma10']}))
                import shutil
                shutil.copytree(build.INPUTS / 'patches', inputs / 'patches')
                fixture = root / 'fixture'
                fixture.mkdir()
                self.artifacts(fixture)
                artifacts = root / 'artifacts'
                for package, source in config['alma10']['packages'].items():
                    directory = artifacts / ('cosmic-repair-alma10-' + package)
                    directory.mkdir(parents=True)
                    shutil.copyfile(fixture / (package + '.json'), directory / (package + '.json'))
                    receipt = json.loads((fixture / (package + '.json')).read_text())
                    shutil.copyfile(fixture / receipt['rpm'], directory / receipt['rpm'])
                    (directory / (package + '-' + source['version'] + '.current1.src.rpm')).write_bytes(b'patched native source')
                    if corrupt:
                        (directory / receipt['rpm']).write_bytes(b'corrupt')
                with patch.object(candidate, 'INPUTS', inputs):
                    if corrupt:
                        with self.assertRaises(ValueError):
                            candidate.prepare_bundle(artifacts, root / 'bundle')
                        continue
                    candidate.prepare_bundle(artifacts, root / 'bundle')
                self.assertEqual(len(list((root / 'bundle/runtime').rglob('*.x86_64.rpm'))), 2)
                self.assertFalse(list((root / 'bundle/runtime').rglob('*.src.rpm')))
                hashes = json.loads((root / 'bundle/sources/sha256.json').read_text())
                self.assertEqual(len(hashes), 2)
                for name, digest in hashes.items():
                    self.assertEqual(hashlib.sha256((root / 'bundle/sources' / name).read_bytes()).hexdigest(), digest)
