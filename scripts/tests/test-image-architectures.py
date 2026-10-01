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
        self.assertEqual(sum(r['architecture'] == 'x86_64' for r in rows), 17)
        self.assertEqual(sum(r['architecture'] == 'aarch64' for r in rows), 6)
        for row in rows:
            self.assertTrue((ROOT / row['recipe']).is_file())
            self.assertEqual(row['image'], matrix.expected_image(row))
            self.assertEqual(row['recipe'], matrix.expected_recipe(row))
            if row['architecture'] == 'aarch64':
                self.assertEqual(row['driver'], 'standard')
                self.assertTrue(row['image'].endswith('-arm64'))

    def test_ci_rendering_requires_architecture_and_filters_roles(self):
        import json
        for arch, job, count in [('aarch64', 'server-images', 2), ('aarch64', 'workstation-images', 4),
                                 ('x86_64', 'server-images', 5), ('x86_64', 'workstation-images', 12)]:
            result = subprocess.run(['python3', str(ROOT / 'scripts/render-image-matrix.py'),
                                     'gha', '--architecture', arch, job], capture_output=True, text=True, check=True)
            rows = json.loads(result.stdout)
            self.assertEqual(len(rows), count)
            self.assertTrue(all(r['name'].endswith('-arm64') == (arch == 'aarch64') for r in rows))
        result = subprocess.run(['python3', str(ROOT / 'scripts/render-image-matrix.py'),
                                 'gha', 'server-images'], capture_output=True)
        self.assertNotEqual(result.returncode, 0)

    def test_rejects_unknown_architecture_and_unqualified_arm_driver(self):
        for changes in ({'architecture': 'riscv64'}, {'architecture': 'aarch64', 'driver': 'nvidia-open'}):
            with tempfile.TemporaryDirectory() as directory:
                file = Path(directory) / 'matrix.tsv'
                row = dict(matrix.load_rows()[3], **changes)
                with file.open('w') as handle:
                    writer = csv.DictWriter(handle, fieldnames=matrix.FIELDS, delimiter='\t')
                    writer.writeheader(); writer.writerow(row)
                with patch.object(matrix, 'MATRIX_FILE', file), self.assertRaises(SystemExit):
                    matrix.load_rows()

    def run_picker(self, architecture, legacy=False, expected_success=True):
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            fields = [f for f in matrix.FIELDS if f != 'architecture'] if legacy else matrix.FIELDS
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
head -n 1 "$TEST_DIR/choices"
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
                       PATH=str(tmp) + ':' + os.environ['PATH'])
            result = subprocess.run(['bash', str(recipe)], env=env, text=True, capture_output=True)
            if expected_success:
                self.assertEqual(result.returncode, 0, result.stderr)
                choices = (tmp / 'choices').read_text().splitlines()
                native = 'aarch64' if architecture in ('aarch64', 'arm64') else 'x86_64'
                self.assertTrue(all(line.startswith(native + ' | ') for line in choices))
                sudo_call = (tmp / 'sudo-call').read_text()
                self.assertIn('bootc switch ghcr.io/pelagians/', sudo_call)
                self.assertEqual('-arm64:latest' in sudo_call, native == 'aarch64')
            else:
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((tmp / 'sudo-call').exists())

    def test_picker_filters_x64_and_arm64_and_architecture_aliases(self):
        for arch in ('x86_64', 'aarch64', 'amd64', 'arm64'):
            with self.subTest(arch=arch): self.run_picker(arch)

    def test_picker_accepts_legacy_matrix_only_on_x64(self):
        self.run_picker('x86_64', legacy=True)
        self.run_picker('aarch64', legacy=True, expected_success=False)

    def test_picker_rejects_unsupported_machine_architecture(self):
        self.run_picker('riscv64', expected_success=False)


if __name__ == '__main__':
    unittest.main(verbosity=2)
