"""Alma 9 preflight parsing and retry policy without containers or network access."""
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import verify_alma9_nvidia_580 as verify

GOOD = '''kernel-core-5.14.0-611.el9.x86_64
 nvidia-driver x86_64 3:580.119.02-1.el9 almalinux-nvidia 82 M
 kmod-nvidia-580.119.02-5.14.0-611.el9.x86_64 x86_64 3:580.119.02-1.el9 almalinux-nvidia 52 M
'''


class Alma9Nvidia(unittest.TestCase):
    def test_lane_and_prebuilt_transaction(self):
        self.assertEqual(len(verify.validate_lane()), 3)
        result = verify.parse_result(GOOD)
        self.assertEqual(result['KERNEL_CORE'], '5.14.0-611.el9.x86_64')
        self.assertEqual(result['PREBUILT_KMODS'], 'yes')
        self.assertEqual(result['DKMS'], 'no')

    def test_missing_kernel_query_uses_prebuilt_package_identity(self):
        self.assertEqual(verify.parse_result(GOOD.split('\n', 1)[1])['KERNEL_CORE'], '5.14.0-611.el9.x86_64')

    def test_dnf_failure_empty_result_missing_prebuilt_and_dkms_fail(self):
        for output in ('Error: resolution failed\n' + GOOD, '- package a conflicts with b\n' + GOOD,
                       '', GOOD.split(' kmod-', 1)[0], GOOD + ' kmod-nvidia-dkms x86_64 580.1 almalinux-nvidia 1 M\n'):
            with self.subTest(output=output), self.assertRaises(ValueError):
                verify.parse_result(output)

    @patch.object(verify.time, 'sleep')
    @patch.object(verify.subprocess, 'run')
    def test_transient_failure_retries_then_succeeds(self, run, sleep):
        run.side_effect = [subprocess.CompletedProcess([], 1, 'TLS handshake timeout'),
                           subprocess.CompletedProcess([], 0, GOOD)]
        self.assertEqual(verify.transaction('podman', verify.PACKAGES['server']), GOOD)
        sleep.assert_called_once_with(5)
        command = run.call_args.args[0]
        self.assertEqual(command[:4], ['podman', 'run', '--rm', verify.IMAGE])
        self.assertIn('dnf -y --assumeno install nvidia-driver nvidia-driver-cuda', command[-1])
        self.assertIn('module enable nvidia-driver:580', command[-1])

    @patch.object(verify.time, 'sleep')
    @patch.object(verify.subprocess, 'run')
    def test_retries_are_bounded_and_nontransient_failure_is_immediate(self, run, sleep):
        run.return_value = subprocess.CompletedProcess([], 1, 'unexpected EOF')
        with self.assertRaisesRegex(ValueError, 'attempt 3/3'):
            verify.transaction('docker', verify.PACKAGES['workstation'])
        self.assertEqual(run.call_count, 3)
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [5, 10])
        run.reset_mock(); sleep.reset_mock()
        run.return_value = subprocess.CompletedProcess([], 125, 'permission denied')
        with self.assertRaisesRegex(ValueError, 'permission denied'):
            verify.transaction('docker', verify.PACKAGES['server'])
        run.assert_called_once(); sleep.assert_not_called()

    @patch.object(verify.shutil, 'which', return_value=None)
    def test_missing_runtime_is_an_error(self, which):
        with self.assertRaisesRegex(ValueError, 'Need podman or docker'):
            verify.main()
