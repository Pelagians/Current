#!/usr/bin/env python3
"""Verify architecture filtering and the actual rebase shell with safe stubs."""
import csv
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("image_matrix", ROOT / "scripts/render-image-matrix.py")
matrix = importlib.util.module_from_spec(spec)
spec.loader.exec_module(matrix)


class Architectures(unittest.TestCase):
    def test_manifest_counts_names_and_recipes(self):
        rows = matrix.load_rows()
        self.assertEqual(sum(r['architecture'] == 'x86_64' for r in rows), 24)
        self.assertEqual(sum(r['architecture'] == 'aarch64' for r in rows), 21)
        for row in rows:
            self.assertTrue((ROOT / row['recipe']).is_file())
            self.assertEqual(row['image'], matrix.expected_image(row))
            self.assertEqual(row['recipe'], matrix.expected_recipe(row))
            if row['architecture'] == 'aarch64':
                self.assertIn(row['driver'], matrix.ARM_DRIVERS[row['platform']])
                self.assertTrue(row['image'].endswith('-arm64'))

    def test_ci_rendering_requires_architecture_and_filters_roles(self):
        import json
        for arch, job, count in [('aarch64', 'server-images', 7), ('aarch64', 'workstation-images', 14),
                                 ('x86_64', 'server-images', 8), ('x86_64', 'workstation-images', 16)]:
            result = subprocess.run(['python3', str(ROOT / 'scripts/render-image-matrix.py'),
                                     'gha', '--architecture', arch, job], capture_output=True, text=True, check=True)
            rows = json.loads(result.stdout)
            self.assertEqual(len(rows), count)
            self.assertTrue(all(r['name'].endswith('-arm64') == (arch == 'aarch64') for r in rows))
        result = subprocess.run(['python3', str(ROOT / 'scripts/render-image-matrix.py'),
                                 'gha', 'server-images'], capture_output=True)
        self.assertNotEqual(result.returncode, 0)

    def test_rejects_unknown_architecture_and_unqualified_arm_driver(self):
        for changes in ({'architecture': 'riscv64'},
                        {'architecture': 'aarch64', 'platform': 'alma10', 'driver': 'nvidia-580'},
                        {'architecture': 'aarch64', 'platform': 'alma9', 'driver': 'nvidia-580'}):
            with tempfile.TemporaryDirectory() as directory:
                file = Path(directory) / 'matrix.tsv'
                row = dict(matrix.load_rows()[3], **changes)
                row['image'] = matrix.expected_image(row)
                row['recipe'] = matrix.expected_recipe(row)
                with file.open('w') as handle:
                    writer = csv.DictWriter(handle, fieldnames=matrix.FIELDS, delimiter='\t')
                    writer.writeheader(); writer.writerow(row)
                with patch.object(matrix, 'MATRIX_FILE', file), self.assertRaises(SystemExit):
                    matrix.load_rows()

    def run_picker(self, architecture, legacy=False, expected_success=True,
                   rows=None, selected_image=None):
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            fields = [f for f in matrix.FIELDS if f != 'architecture'] if legacy else matrix.FIELDS
            if rows is None:
                rows = matrix.load_rows()
            if legacy:
                rows = [r for r in rows if r['architecture'] == 'x86_64']
            file = tmp / 'matrix.tsv'
            with file.open('w') as handle:
                writer = csv.DictWriter(handle, fieldnames=fields, delimiter='\t', extrasaction='ignore')
                writer.writeheader(); writer.writerows(rows)
            scripts = {
                'curl': '''#!/bin/bash
set -e
while (($#)); do
  if [[ "$1" == --output ]]; then output="$2"; shift; fi
  shift
done
cp "$TEST_MATRIX" "$output"
printf 200
''',
                'fzf': '''#!/bin/bash
cat > "$TEST_DIR/choices"
if [[ -n "$TEST_SELECTION" ]]; then
  awk -F'|' -v image="$TEST_SELECTION:latest" '$6 == " " image { print; exit }' "$TEST_DIR/choices"
else
  head -n 1 "$TEST_DIR/choices"
fi
''',
                'uname': '#!/bin/bash\nprintf "%s\\n" "$TEST_ARCH"\n',
                'sudo': '#!/bin/bash\nprintf "%s\\n" "$*" > "$TEST_DIR/sudo-call"\n',
            }
            for name, content in scripts.items():
                script = tmp / name; script.write_text(content); script.chmod(0o755)
            # Execute the real recipe body; all external effects are stubbed.
            body = (ROOT / 'files/justfiles/usr/share/current/just/rebase.just').read_text().splitlines()[1:]
            recipe = tmp / 'picker.sh'
            recipe.write_text('\n'.join(line.removeprefix('    ') for line in body) + '\n')
            env = dict(os.environ, TEST_ARCH=architecture, TEST_DIR=str(tmp), TEST_MATRIX=str(file),
                       TEST_SELECTION=selected_image or '',
                       PATH=str(tmp) + ':' + os.environ['PATH'])
            result = subprocess.run(['bash', str(recipe)], env=env, text=True, capture_output=True)
            if expected_success:
                self.assertEqual(result.returncode, 0, result.stderr)
                choices = (tmp / 'choices').read_text().splitlines()
                native = 'aarch64' if architecture in ('aarch64', 'arm64') else 'x86_64'
                self.assertTrue(all(line.startswith(native + ' | ') for line in choices))
                expected_images = [r['image'] for r in rows if r['architecture'] == native]
                self.assertEqual([line.split('|')[5].strip().removesuffix(':latest')
                                  for line in choices], expected_images)
                self.assertIn('Detected architecture: ' + native, result.stdout)
                sudo_call = (tmp / 'sudo-call').read_text()
                self.assertEqual(sudo_call, 'bootc switch ghcr.io/pelagians/' +
                                 (selected_image or expected_images[0]) + ':latest\n')
            else:
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((tmp / 'sudo-call').exists())
            return result

    def test_picker_filters_x64_and_arm64_and_architecture_aliases(self):
        for arch in ('x86_64', 'aarch64', 'amd64', 'arm64'):
            with self.subTest(arch=arch): self.run_picker(arch)

    def test_picker_accepts_legacy_matrix_only_on_x64(self):
        self.run_picker('x86_64', legacy=True)
        self.run_picker('aarch64', legacy=True, expected_success=False)

    def test_picker_rejects_unsupported_machine_architecture(self):
        result = self.run_picker('riscv64', expected_success=False)
        self.assertIn('Unsupported machine architecture: riscv64', result.stderr)

    def test_picker_rejects_image_names_mislabeled_with_another_architecture(self):
        for arch in ('x86_64', 'aarch64'):
            with self.subTest(arch=arch):
                rows = matrix.load_rows()
                row = next(r for r in rows if r['architecture'] == arch)
                row['image'] = (row['image'] + '-arm64' if arch == 'x86_64'
                                else row['image'].removesuffix('-arm64'))
                result = self.run_picker(arch, rows=rows, expected_success=False)
                self.assertIn('image name does not match architecture', result.stderr)

    def test_picker_selects_each_fedora_arm_r580_image(self):
        for environment in ('server', 'gnome', 'cosmic'):
            with self.subTest(environment=environment):
                self.run_picker('aarch64', selected_image=f'fedora-{environment}-nvidia-580-arm64')

    def test_cuda_repo_maps_native_arm_to_sbsa(self):
        layer = (ROOT / 'recipes/layers/shared/nvidia-cuda.yml').read_text()
        snippet = layer.split('RUN ', 1)[1]
        for arch in ('x86_64', 'aarch64', 'riscv64'):
            for major in ('9', '10'):
                with self.subTest(arch=arch, major=major), tempfile.TemporaryDirectory() as directory:
                    tmp = Path(directory)
                    marker = tmp / 'os-release-meta.env'
                    marker.write_text('EL_MAJOR=' + major + '\n')
                    for name, content in {
                        'uname': 'printf "%s\\n" "$TEST_ARCH"\n',
                        'curl': 'printf "%s\\n" "$*" >> "$TEST_DIR/calls"\n',
                        'dnf': 'printf "%s\\n" "$*" >> "$TEST_DIR/calls"\n'
                               'if [[ "$*" == "config-manager --help" && "$TEST_MAJOR" == 9 ]]; then printf "%s\\n" --set-disabled; fi\n',
                    }.items():
                        script = tmp / name
                        script.write_text('#!/bin/bash\n' + content)
                        script.chmod(0o755)
                    env = dict(os.environ, TEST_ARCH=arch, TEST_MAJOR=major, TEST_DIR=str(tmp),
                               PATH=str(tmp) + ':' + os.environ['PATH'])
                    command = snippet.replace('/usr/share/current/os-release-meta.env', str(marker))
                    result = subprocess.run(['bash', '-euc', command], env=env, text=True, capture_output=True)
                    if arch == 'riscv64':
                        self.assertNotEqual(result.returncode, 0)
                        self.assertFalse((tmp / 'calls').exists())
                    else:
                        self.assertEqual(result.returncode, 0, result.stderr)
                        cuda_arch = 'sbsa' if arch == 'aarch64' else 'x86_64'
                        calls = (tmp / 'calls').read_text()
                        self.assertIn(f'/rhel{major}/{cuda_arch}/cuda-rhel{major}.repo', calls)
                        expected = f'--set-disabled cuda-rhel{major}-{cuda_arch}' if major == '9' else f'cuda-rhel{major}-{cuda_arch}.enabled=0'
                        self.assertIn(expected, calls)


if __name__ == '__main__':
    unittest.main(verbosity=2)
