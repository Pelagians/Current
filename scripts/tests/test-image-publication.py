#!/usr/bin/env python3
"""Exercise real publication logic without modifying any registry or display manager."""
import importlib.util
import io
from contextlib import redirect_stdout
import json
import os
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('publication', ROOT / 'scripts/publish-image-index.py')
pub = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pub)
ENV = dict(GITHUB_SHA='a' * 40, GITHUB_RUN_ID='123', GITHUB_RUN_ATTEMPT='2',
           GITHUB_EVENT_NAME='push', GITHUB_REF_NAME='stable', GITHUB_REF_TYPE='branch',
           CURRENT_DEFAULT_BRANCH='stable', COSIGN_PRIVATE_KEY='fixture', CURRENT_PR_NUMBER='28')


class Publication(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, ENV)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.rows = pub.matrix.load_rows()
        for index, row in enumerate(self.rows, 1):
            value = dict(image=row['image'], architecture=row['architecture'],
                         digest='sha256:' + f'{index:064x}', revision=ENV['GITHUB_SHA'],
                         run_id='123', attempt='2', namespace='ghcr.io/pelagians',
                         version={'alma9':'9','alma10':'10','fedora':'44'}[row['platform']])
            (self.directory / f'{index}.json').write_text(json.dumps(value))

    def fake_registry(self, wrong_config=False, signing_failure=False, wrong_index=False):
        self.calls, indexes = [], {}
        digests = {json.loads(p.read_text())['digest']: json.loads(p.read_text())['architecture']
                   for p in self.directory.glob('*.json')}

        def command(*args):
            self.calls.append(args)
            if args[:3] == ('skopeo', 'inspect', '--config'):
                arch = digests[args[-1].split('@')[1]]
                return json.dumps(dict(os='linux', architecture='amd64' if wrong_config else pub.OCI_ARCH[arch],
                                       config=dict(Labels={'org.opencontainers.image.revision': ENV['GITHUB_SHA'],
                                                           'io.current.build': pub.marker(arch)})))
            if args[:4] == ('docker', 'buildx', 'imagetools', 'create'):
                target = args[args.index('--tag') + 1]
                if '--annotation' in args:
                    descriptors = [{'platform': {'os': 'linux', 'architecture': pub.OCI_ARCH[digests[a.split('@')[1]]]},
                                    'digest': a.split('@')[1]} for a in args if '@' in a]
                    indexes[target] = dict(manifests=descriptors,
                                           annotations={'org.opencontainers.image.revision': ENV['GITHUB_SHA']})
                    if wrong_index: indexes[target]['manifests'].append(descriptors[0])
            if args[:3] == ('skopeo', 'inspect', '--raw'):
                return json.dumps(indexes[args[-1].removeprefix('docker://')])
            if args[:2] == ('cosign', 'sign') and signing_failure:
                raise ValueError('fixture signature failure')
            return ''
        return command

    def mutable_updates(self):
        return [c for c in self.calls if '--tag' in c and ':run-123-2' not in c[c.index('--tag') + 1]]

    def test_all_platforms_merge_and_sign_before_any_channel_advances(self):
        with patch.object(pub, 'run', self.fake_registry()), redirect_stdout(io.StringIO()):
            pub.publish(self.directory)
        updates = self.mutable_updates()
        canonical = [c for c in updates if c[c.index('--tag') + 1].endswith(':latest')
                     and '-arm64:' not in c[c.index('--tag') + 1]]
        self.assertEqual(len(canonical), 24)
        self.assertTrue(any(c[c.index('--tag') + 1] == 'ghcr.io/pelagians/fedora-gnome:44' for c in updates))
        self.assertEqual(sum(c[c.index('--tag') + 1].endswith(':latest-arm64') for c in updates), 21)
        self.assertEqual(sum('-arm64:latest' in c[c.index('--tag') + 1] for c in updates), 21)
        first = self.calls.index(updates[0])
        self.assertEqual(sum(c[:2] == ('cosign', 'verify') for c in self.calls[:first]), 90)
        self.assertFalse(any(c[:2] == ('cosign', 'sign') for c in self.calls[first:]))

    def test_missing_wrong_attempt_duplicate_and_invalid_digest_stop_before_registry_calls(self):
        for change in ('missing', 'attempt', 'duplicate', 'digest', 'version'):
            with self.subTest(change=change):
                path = self.directory / ('4.json' if change == 'version' else '1.json'); original = path.read_text()
                value = json.loads(original)
                if change == 'missing': path.unlink()
                elif change == 'duplicate': (self.directory / 'duplicate.json').write_text(original)
                else:
                    value['version' if change == 'version' else 'attempt' if change == 'attempt' else 'digest'] = '99' if change == 'version' else 'wrong'
                    path.write_text(json.dumps(value))
                with patch.object(pub, 'run') as run, self.assertRaises(ValueError):
                    pub.publish(self.directory)
                run.assert_not_called()
                path.write_text(original)
                (self.directory / 'duplicate.json').unlink(missing_ok=True)

    def test_wrong_registry_platform_stops_before_publication(self):
        with patch.object(pub, 'run', self.fake_registry(wrong_config=True)), self.assertRaisesRegex(ValueError, 'wrong native image platform'):
            pub.publish(self.directory)
        self.assertFalse(any(c[0] in ('docker', 'cosign') for c in self.calls))

    def test_failed_signature_or_invalid_index_does_not_advance_channels(self):
        for changes in ({'signing_failure': True}, {'wrong_index': True}):
            with self.subTest(changes=changes), patch.object(pub, 'run', self.fake_registry(**changes)), self.assertRaises(ValueError):
                pub.publish(self.directory)
            self.assertFalse(self.mutable_updates())

    def test_index_contract_rejects_wrong_missing_and_duplicate_children(self):
        digest = 'sha256:' + '1' * 64
        base = dict(manifests=[dict(platform=dict(os='linux', architecture='amd64'), digest=digest)],
                    annotations={'org.opencontainers.image.revision': ENV['GITHUB_SHA']})
        pub.check_index(base, {'x86_64': digest}, ENV['GITHUB_SHA'])
        for kind in ('missing', 'duplicate', 'architecture', 'digest', 'revision'):
            value = json.loads(json.dumps(base))
            if kind == 'missing': value['manifests'] = []
            elif kind == 'duplicate': value['manifests'] *= 2
            elif kind == 'revision': value['annotations']['org.opencontainers.image.revision'] = 'b' * 40
            else: value['manifests'][0]['platform' if kind == 'architecture' else 'digest'] = {} if kind == 'architecture' else 'sha256:' + '2' * 64
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                pub.check_index(value, {'x86_64': digest}, ENV['GITHUB_SHA'])

    def test_pr_and_other_branches_cannot_publish_latest(self):
        for changes, expected in (({'GITHUB_EVENT_NAME': 'pull_request'}, 'pr-28'),
                                  ({'GITHUB_REF_NAME': 'codex/feature'}, 'br-codex_feature'),
                                  ({'GITHUB_REF_TYPE': 'tag'}, 'sha-' + 'a' * 12)):
            with patch.dict(os.environ, changes): self.assertEqual(pub.channel(), expected)
        with patch.dict(os.environ, GITHUB_EVENT_NAME='pull_request'), patch.object(pub, 'run', self.fake_registry()), redirect_stdout(io.StringIO()):
            pub.publish(self.directory)
        targets = [c[c.index('--tag') + 1] for c in self.mutable_updates()]
        self.assertIn('ghcr.io/pelagians/fedora-gnome-arm64:pr-28-44', targets)
        self.assertFalse(any(':latest' in tag for tag in targets))

    def test_native_recipe_uses_unique_staging_tag_and_source_labels(self):
        generated = ROOT / 'recipes/.generated/fedora-gnome-arm64.yml'
        self.addCleanup(lambda: generated.unlink(missing_ok=True))
        pub.prepare('fedora-gnome', 'aarch64')
        text = generated.read_text()
        self.assertIn('alt-tags:\n  - run-123-2-arm64', text)
        self.assertIn('io.current.build: "run-123-2-arm64"', text)
        self.assertIn('org.opencontainers.image.revision: "' + 'a' * 40 + '"', text)
        with self.assertRaises(StopIteration): pub.prepare('alma9-server-nvidia-580', 'aarch64')

    def test_record_resolves_native_child_and_rejects_other_builds(self):
        digest = 'sha256:' + 'b' * 64
        for wrong_revision in (False, True):
            def registry(*args):
                if args[1] == 'list-tags': return json.dumps({'Tags': ['old', 'pr-28-run-123-2-arm64-44']})
                if '--raw' in args:
                    return json.dumps({'manifests': [
                        {'platform': {'os': 'linux', 'architecture': 'arm64', 'variant': 'v8'}, 'digest': digest},
                        {'platform': {'os': 'unknown', 'architecture': 'unknown'}, 'digest': 'sha256:' + 'c' * 64}]})
                return json.dumps({'os': 'linux', 'architecture': 'arm64', 'config': {'Labels': {
                    'org.opencontainers.image.revision': 'c' * 40 if wrong_revision else ENV['GITHUB_SHA'],
                    'io.current.build': 'run-123-2-arm64'}}})
            with self.subTest(wrong_revision=wrong_revision), patch.object(pub, 'run', registry), redirect_stdout(io.StringIO()):
                if wrong_revision:
                    with self.assertRaisesRegex(ValueError, 'another commit'):
                        pub.record('fedora-gnome', 'aarch64', self.directory)
                else:
                    pub.record('fedora-gnome', 'aarch64', self.directory)
                    artifact = json.loads((self.directory / 'fedora-gnome-arm64.json').read_text())
                    self.assertEqual(artifact['digest'], digest)
                    self.assertEqual(artifact['architecture'], 'aarch64')
            (self.directory / 'fedora-gnome-arm64.json').unlink(missing_ok=True)

    def test_package_transactions_run_only_on_the_intended_cpu(self):
        import subprocess
        layers = ['alma9/arm-core', 'alma9/arm-cosmic', 'alma10/arm-gnome',
                  'alma10/arm-cosmic', 'alma10/rocm', 'fedora/rocm']
        for layer in layers:
            for arch in ('x86_64', 'aarch64', 'riscv64'):
                with self.subTest(layer=layer, arch=arch), tempfile.TemporaryDirectory() as directory:
                    tmp = Path(directory)
                    os_release = tmp / 'os-release'
                    os_release.write_text('ID=almalinux\nVERSION_ID=' + ('9' if layer.startswith('alma9') else '10') + '\n')
                    command = (ROOT / ('recipes/layers/' + layer + '.yml')).read_text().split('RUN ', 1)[1]
                    if command.startswith('--mount='): command = command.split(' ', 1)[1]
                    command = ' '.join(command.splitlines()).replace('/etc/os-release', str(os_release))
                    for name, body in {'uname': 'printf "%s\\n" "$TEST_ARCH"',
                                       'dnf': 'printf "%s\\n" "$*" >> "$TEST_CALLS"',
                                       'rpm': ':', 'cp': ':'}.items():
                        path = tmp / name; path.write_text('#!/bin/bash\n' + body + '\n'); path.chmod(0o755)
                    env = dict(os.environ, PATH=str(tmp) + ':' + os.environ['PATH'], TEST_ARCH=arch, TEST_CALLS=str(tmp / 'calls'))
                    result = subprocess.run(['bash', '-euc', command], env=env, text=True, capture_output=True)
                    self.assertEqual(result.returncode == 0, arch != 'riscv64', result.stderr)
                    intended = 'x86_64' if layer.endswith('/rocm') else 'aarch64'
                    self.assertEqual((tmp / 'calls').exists(), arch == intended)

    def test_workflow_native_override_and_publication_gate(self):
        native = (ROOT / '.github/workflows/build-architecture.yml').read_text()
        self.assertEqual(native.count('build_opts: --platform ${{ matrix.platform }}'), 3)
        self.assertEqual(native.count('skip_checkout: true'), 3)
        workflow = (ROOT / '.github/workflows/build.yml').read_text()
        self.assertIn('needs: [x64-images, arm64-images]', workflow)
        self.assertIn('pattern: native-*', workflow)
        self.assertIn('publish-image-index.py publish', workflow)


if __name__ == '__main__':
    unittest.main(verbosity=2)
