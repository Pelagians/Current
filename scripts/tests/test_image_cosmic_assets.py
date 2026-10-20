"""The EL9 noarch workaround stays restricted and fails on signature errors."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class CosmicAssets(unittest.TestCase):
    def run_install(self, arch='aarch64', major='9', installed_arch='noarch', dnf_result=0,
                    version_ok=True, bad_payload=False, scriptlet=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metadata = root / 'os-release-meta.env'
            metadata.write_text(f'DISTRO_ID=almalinux\nEL_MAJOR={major}\n')
            for name, text in {
                'uname': 'echo "$TEST_ARCH"',
                'dnf': '''printf 'dnf %s\\n' "$*" >> "$CALL_LOG"
if [[ "$*" == *repoquery* && "$VERSION_OK" == 1 ]]; then printf 'cosmic-icon-theme.noarch\\n'; fi
exit "$DNF_RESULT"''',
                'rpm': '''printf 'rpm %s\\n' "$*" >> "$CALL_LOG"
case "$*" in
  *--queryformat*) printf '%s' "$INSTALLED_ARCH" ;;
  *--scripts*) [[ "$SCRIPTLET" == 1 ]] && printf scriptlet ;;
  *-ql*)
    if [[ "$BAD_PAYLOAD" == 1 ]]; then printf '/usr/bin/unexpected\\n'
    else printf '/usr/share/icons/Cosmic/index.theme\\n'; fi ;;
esac
exit 0''',
            }.items():
                path = root / name; path.write_text('#!/bin/bash\n' + text + '\n'); path.chmod(0o755)
            body = (ROOT / 'files/scripts/alma9-cosmic-assets.sh').read_text().replace('/usr/share/current/os-release-meta.env', str(metadata))
            result = subprocess.run(['/bin/bash'], input=body, text=True, capture_output=True,
                                    env=dict(os.environ, PATH=str(root) + ':' + os.environ['PATH'], TEST_ARCH=arch, VERSION_OK=str(int(version_ok)),
                                             INSTALLED_ARCH=installed_arch, DNF_RESULT=str(dnf_result),
                                             BAD_PAYLOAD=str(int(bad_payload)), SCRIPTLET=str(int(scriptlet)), CALL_LOG=str(root / 'calls')))
            calls = (root / 'calls').read_text() if (root / 'calls').exists() else ''
            return result, calls

    def test_scoped_signed_noarch_source_on_both_cpus(self):
        for arch in ('aarch64', 'x86_64'):
            with self.subTest(arch=arch):
                result, calls = self.run_install(arch=arch)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(f'/rhel+epel-10-{arch}/', calls)
                self.assertIn('--setopt=current-el9-cosmic-assets.includepkgs=cosmic-icon-theme,cosmic-wallpapers', calls)
                self.assertIn('--setopt=current-el9-cosmic-assets.gpgcheck=1', calls)
                self.assertIn('--setopt=current-el9-cosmic-assets.gpgkey=https://download.copr.fedorainfracloud.org/results/ligenix/enterprise-cosmic/pubkey.gpg', calls)
                self.assertIn('install cosmic-icon-theme.noarch cosmic-wallpapers.noarch', calls)
                self.assertIn("repoquery --installed --whatprovides cosmic-icon-theme >= 1.9.0", calls)

    def test_incorrect_lane_or_cpu_fails_before_transaction(self):
        for changes in ({'major': '10'}, {'arch': 'riscv64'}):
            with self.subTest(changes=changes):
                result, calls = self.run_install(**changes)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(calls)

    def test_signature_failure_stops_and_native_package_cannot_pass(self):
        result, calls = self.run_install(dnf_result=71)
        self.assertEqual(result.returncode, 71)
        self.assertNotIn('rpm ', calls)
        result, calls = self.run_install(installed_arch='aarch64')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('--whatprovides', calls)

    def test_old_installed_version_does_not_pass_validation(self):
        result, calls = self.run_install(version_ok=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('--whatprovides cosmic-icon-theme >= 1.9.0', calls)

    def test_future_executable_payload_or_scriptlets_fail_the_build(self):
        for changes in ({'bad_payload': True}, {'scriptlet': True}):
            with self.subTest(changes=changes):
                result, calls = self.run_install(**changes)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn('--whatprovides', calls)
