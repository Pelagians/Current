"""Execute build download scripts with local payloads and real checksum checks."""
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class Downloads(unittest.TestCase):
    def run_install(self, name, architecture, bad_checksum=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tools = root / 'tools'; tools.mkdir()
            destination = root / 'installed'
            checksum = '0' * 64 if bad_checksum else hashlib.sha256(b'fixture').hexdigest()
            stubs = {
                'uname': 'echo "$TEST_ARCH"',
                'curl': '''printf '%s\\n' "$*" >> "$CALL_LOG"
url=''; output=''
while (($#)); do
  case "$1" in
    -o) output="$2"; shift ;;
    https:*) url="$1" ;;
  esac
  shift
done
[[ -n "$output" ]] || output="${url##*/}"
case "$url" in
  *sha256sum-amd64.txt) printf '%s  k3s\\n' "$CHECKSUM" > "$output" ;;
  *sha256sum-arm64.txt) printf '%s  k3s-arm64\\n' "$CHECKSUM" > "$output" ;;
  *.sha256sum) printf '%s  %s\\n' "$CHECKSUM" "${output%.sha256sum}" > "$output" ;;
  *) printf fixture > "$output" ;;
esac''',
                'tar': '''echo tar >> "$CALL_LOG"
case "$TEST_ARCH" in x86_64) arch=amd64 ;; aarch64) arch=arm64 ;; esac
mkdir -p "linux-$arch"
printf '#!/bin/sh\\nexit 0\\n' > "linux-$arch/helm"''',
                'helm': 'echo helm-version >> "$CALL_LOG"',
            }
            for tool, body in stubs.items():
                path = tools / tool
                path.write_text('#!/bin/bash\n' + body + '\n'); path.chmod(0o755)
            body = (ROOT / 'files/scripts' / ('install-' + name + '.sh')).read_text()
            body = body.replace('/tmp/', str(root) + '/').replace('cd /tmp ', 'cd ' + str(root) + ' ')
            body = body.replace('/usr/local/bin/k3s', str(destination)).replace('/usr/bin/helm', str(destination))
            result = subprocess.run(['/bin/bash'], input=body, cwd=root, text=True, capture_output=True,
                                    env=dict(os.environ, PATH=str(tools) + ':' + os.environ['PATH'],
                                             TEST_ARCH=architecture, CHECKSUM=checksum, CALL_LOG=str(root / 'calls')))
            calls = (root / 'calls').read_text() if (root / 'calls').exists() else ''
            return result, calls, destination.exists()

    def test_native_assets_and_checksums_on_both_architectures(self):
        for name in ('helm', 'k3s'):
            for arch, asset in (('x86_64', 'amd64'), ('aarch64', 'arm64')):
                with self.subTest(name=name, arch=arch):
                    result, calls, installed = self.run_install(name, arch)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertTrue(installed)
                    if name == 'k3s':
                        self.assertIn('v1.36.1+k3s1/', calls)
                        self.assertIn(f'sha256sum-{asset}.txt', calls)
                    else:
                        self.assertIn(f'helm-v4.2.0-linux-{asset}.tar.gz.sha256sum', calls)
                        self.assertIn('helm-version', calls)

    def test_bad_checksums_and_unknown_architectures_never_install(self):
        for name in ('helm', 'k3s'):
            with self.subTest(name=name):
                result, calls, installed = self.run_install(name, 'aarch64', bad_checksum=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(installed)
                self.assertNotIn('helm-version', calls)
                result, calls, installed = self.run_install(name, 'riscv64')
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(installed)
                self.assertFalse(calls)

    def test_recipes_mount_the_actual_build_scripts(self):
        for layer, script in (
            ('features/k3s', 'install-k3s'), ('alma/core', 'install-helm'),
            ('alma9/cosmic-assets', 'alma9-cosmic-assets'),
            ('fedora/nvidia-akmod', 'fedora-nvidia-build'),
            ('fedora/nvidia-workstation', 'fedora-nvidia-workstation')):
            with self.subTest(layer=layer):
                text = (ROOT / 'recipes/layers' / (layer + '.yml')).read_text()
                self.assertIn('RUN --mount=type=bind,from=stage-files,src=/files,dst=/tmp/files,ro '
                              '/usr/bin/bash /tmp/files/scripts/' + script + '.sh', text)
                self.assertTrue((ROOT / 'files/scripts' / (script + '.sh')).is_file())
