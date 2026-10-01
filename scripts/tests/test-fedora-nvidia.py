#!/usr/bin/env python3
"""Exercise Fedora's real header selection and module checks with isolated stubs."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
LAYER = ROOT / 'recipes/layers/fedora/nvidia-akmod.yml'
lines = LAYER.read_text().splitlines()
BODY = ' '.join(line.strip() for line in lines[lines.index('      - >-') + 1:])
HEADER = BODY[BODY.index('kernel_version='):BODY.index('cp /usr/sbin/akmodsbuild')]
VERIFY = BODY[BODY.index('verify_modules()'):BODY.index('depmod "${kernel_version}"')]


class FedoraNvidia(unittest.TestCase):
    def headers(self, arch='aarch64', available=False, signer='dbfcf71c6d9f90a6',
                bad_payload=False, bad_signature=False):
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            scripts = {
                'rpm': '''#!/bin/bash
case "$*" in
  *-qp*)
    package=kernel-devel
    [[ "$2" == *kernel-devel-matched* ]] && package=kernel-devel-matched
    if [[ "$TEST_BAD_PAYLOAD" == 1 ]]; then printf 'kernel-core wrong';
    else printf '%s 7.2.7-200.fc44.%s' "$package" "$TEST_ARCH"; fi ;;
  *RSAHEADER*) printf 'RSA/SHA256, Key ID %s' "$TEST_SIGNER" ;;
  *'%{VERSION}-%{RELEASE}.%{ARCH}'*) printf '7.2.7-200.fc44.%s' "$TEST_ARCH" ;;
  *'%{VERSION}'*) printf 7.2.7 ;;
  *'%{RELEASE}'*) printf 200.fc44 ;;
  *'%{ARCH}'*) printf '%s' "$TEST_ARCH" ;;
  *) exit 2 ;;
esac
''',
                'dnf': '''#!/bin/bash
printf 'dnf %s\n' "$*" >> "$TEST_DIR/calls"
if [[ "$*" == *repoquery* ]]; then
  [[ "$TEST_AVAILABLE" == 1 ]] && printf 'kernel-devel-matched\n'
  exit 0
fi
if [[ "$*" == *localpkg_gpgcheck=True* && "$TEST_BAD_SIGNATURE" == 1 ]]; then
  printf 'Invalid package signature\n' >&2; exit 1
fi
mkdir -p "$TEST_DIR/kernels/7.2.7-200.fc44.$TEST_ARCH"
''',
                'curl': '''#!/bin/bash
printf 'curl %s\n' "$*" >> "$TEST_DIR/calls"
while (($#)); do
  if [[ "$1" == -o ]]; then touch "$2"; fi
  shift
done
''',
            }
            for name, content in scripts.items():
                file = tmp / name; file.write_text(content); file.chmod(0o755)
            body = HEADER.replace('/usr/src/kernels/', str(tmp / 'kernels') + '/')
            body = body.replace('/tmp/${package}-', str(tmp) + '/${package}-')
            env = dict(os.environ, PATH=str(tmp) + ':' + os.environ['PATH'],
                       TEST_DIR=str(tmp), TEST_ARCH=arch, TEST_SIGNER=signer,
                       TEST_AVAILABLE=str(int(available)), TEST_BAD_PAYLOAD=str(int(bad_payload)),
                       TEST_BAD_SIGNATURE=str(int(bad_signature)))
            result = subprocess.run(['bash', '-euxo', 'pipefail', '-c', body],
                                    env=env, capture_output=True, text=True)
            calls = (tmp / 'calls').read_text()
            return result, calls

    def test_available_exact_header_pair_uses_repositories(self):
        result, calls = self.headers(available=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('kernel-devel-7.2.7-200.fc44.aarch64 kernel-devel-matched-7.2.7-200.fc44.aarch64', calls)
        self.assertNotIn('curl ', calls)
        self.assertIn('--exclude=kernel,kernel-core,kernel-modules*,kernel-devel,kernel-devel-matched install akmods', calls)

    def test_missing_headers_fetches_signed_matching_pair_on_both_cpus(self):
        for arch in ('x86_64', 'aarch64'):
            with self.subTest(arch=arch):
                result, calls = self.headers(arch=arch)
                self.assertEqual(result.returncode, 0, result.stderr)
                for package in ('kernel-devel', 'kernel-devel-matched'):
                    self.assertIn(f'/kernel/7.2.7/200.fc44/data/signed/6d9f90a6/{arch}/{package}-7.2.7-200.fc44.{arch}.rpm', calls)
                self.assertIn('--setopt=localpkg_gpgcheck=True install', calls)
                self.assertIn('Matching kernel-devel absent', result.stderr)

    def test_invalid_signer_prevents_download_or_install(self):
        result, calls = self.headers(signer='unsigned')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('curl ', calls)
        self.assertNotIn(' install ', calls)

    def test_unsupported_kernel_architecture_fails_before_download(self):
        result, calls = self.headers(arch='riscv64')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('curl ', calls)

    def test_wrong_downloaded_package_fails_before_install(self):
        result, calls = self.headers(bad_payload=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(' install ', calls)

    def test_signature_failure_stops_before_akmods(self):
        result, calls = self.headers(bad_signature=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Invalid package signature', result.stderr)
        self.assertNotIn('install akmods', calls)

    def modules(self, missing=False, wrong_kernel=False, core_license='NVIDIA'):
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            for module in ('nvidia', 'nvidia-drm', 'nvidia-modeset', 'nvidia-peermem', 'nvidia-uvm'):
                if missing and module == 'nvidia-uvm': continue
                (tmp / (module + '.ko.zst')).touch()
            modinfo = tmp / 'modinfo'
            modinfo.write_text('''#!/bin/bash
if [[ "$2" == license ]]; then
  if [[ "${3##*/}" == nvidia.ko.zst ]]; then printf '%s' "$TEST_LICENSE";
  else printf 'MIT'; fi
else printf '%s SMP preempt mod_unload aarch64' "$TEST_KERNEL"; fi
''')
            modinfo.chmod(0o755)
            body = VERIFY.replace('/usr/lib/modules/${kernel_version}/extra/nvidia', str(tmp))
            env = dict(os.environ, PATH=str(tmp) + ':' + os.environ['PATH'],
                       TEST_LICENSE=core_license, TEST_KERNEL='wrong' if wrong_kernel else '7.2.7-200.fc44.aarch64')
            return subprocess.run(['bash', '-euo', 'pipefail', '-c',
                                   'kernel_version=7.2.7-200.fc44.aarch64; expected_license="' + core_license + '"; ' + body],
                                  env=env, capture_output=True, text=True)

    def test_compressed_modules_and_mixed_submodule_licenses_are_valid(self):
        for license in ('NVIDIA', 'Dual MIT/GPL'):
            result = self.modules(core_license=license)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_module_or_wrong_kernel_fails(self):
        self.assertNotEqual(self.modules(missing=True).returncode, 0)
        self.assertNotEqual(self.modules(wrong_kernel=True).returncode, 0)


if __name__ == '__main__':
    unittest.main()
