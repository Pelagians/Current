"""Check signed sibling-image trust in every native recipe without host writes."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('trust_image_matrix', ROOT / 'scripts/image_matrix.py')
matrix = importlib.util.module_from_spec(spec)
spec.loader.exec_module(matrix)


class SetupTrust(unittest.TestCase):
    def test_every_native_lane_applies_namespace_trust_after_signing(self):
        recipes = {ROOT / row['recipe'] for row in matrix.load_rows()} | {ROOT / 'recipes/bootstrap.yml'}
        signing = ROOT / 'recipes/layers/shared/signing.yml'
        for recipe in recipes:
            with self.subTest(recipe=recipe):
                graph = matrix.recipe_graph(recipe)
                self.assertEqual(graph.count(signing), 1)
                self.assertEqual(graph[-1], signing)
        source = signing.read_text()
        self.assertLess(source.index('type: signing'), source.index('setup-trust-policy.sh'))

    def test_namespace_policy_preserves_other_rules_and_registry_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            containers = root / 'etc/containers'
            (containers / 'registries.d').mkdir(parents=True)
            other = containers / 'registries.d/administrator.yaml'
            other.write_text('docker:\n  example.invalid:\n    use-sigstore-attachments: true\n')
            original = {'default': [{'type': 'reject'}], 'transports': {'docker': {
                'ghcr.io/pelagians/fedora-server': [{'type': 'sigstoreSigned', 'keyPath': '/vendor/key'}],
                'ghcr.io/pelagians/blocked': [{'type': 'reject'}],
                'example.invalid': [{'type': 'reject'}]}}}
            policy_path = containers / 'policy.json'
            policy_path.write_text(json.dumps(original))
            mock = root / 'bin'
            mock.mkdir()
            lint = mock / 'bootc'
            lint.write_text('#!/bin/sh\ntest "$*" = "container lint"\n')
            lint.chmod(0o755)
            env = dict(os.environ, PATH=str(mock) + ':' + os.environ['PATH'])
            result = subprocess.run(['bash', str(ROOT / 'files/scripts/setup-trust-policy.sh'), str(root)],
                                    env=env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            policy = json.loads(policy_path.read_text())
            rule = policy['transports']['docker'].pop('ghcr.io/pelagians')
            self.assertEqual(rule, [{'type': 'sigstoreSigned', 'keyPath': '/usr/share/current/cosign.pub',
                                     'signedIdentity': {'type': 'matchRepository'}}])
            self.assertEqual(policy, original)
            self.assertIn('use-sigstore-attachments: true', (containers / 'registries.d/current-setup.yaml').read_text())
            self.assertEqual(other.read_text(), 'docker:\n  example.invalid:\n    use-sigstore-attachments: true\n')
            policy_path.write_text('invalid policy')
            result = subprocess.run(['bash', str(ROOT / 'files/scripts/setup-trust-policy.sh'), str(root)],
                                    env=env, text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(policy_path.read_text(), 'invalid policy')


if __name__ == '__main__':
    unittest.main()
