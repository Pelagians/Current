#!/usr/bin/env python3
"""Resolve the Alma 9 R580 server/workstation transactions in a disposable container."""
import re
import shlex
import shutil
import subprocess
import sys
import time

from image_matrix import ROOT, load_rows, recipe_graph

IMAGE = 'quay.io/almalinuxorg/almalinux-bootc:9'
REPO = 'https://git.almalinux.org/rpms/almalinux-release-nvidia-driver/raw/branch/a9/almalinux-nvidia.repo'
STREAM = '580'
PACKAGES = {
    'server': ['nvidia-driver', 'nvidia-driver-cuda'],
    'workstation': ['nvidia-driver', 'nvidia-driver-cuda', 'libnvidia-fbc',
                    'libnvidia-cfg', 'nvidia-settings', 'nvidia-libXNVCtrl'],
}
TRANSIENT = re.compile(
    r'unexpected EOF|happened during read|while reconnecting|TLS handshake timeout|'
    r'connection reset|connection refused|i/o timeout|net/http|timeout awaiting response headers|'
    r'temporary failure|temporarily unavailable|service unavailable|blob to file|cdn.*EOF|quay\.io.*EOF',
    re.I)


def validate_lane():
    rows = [r for r in load_rows() if r['platform'] == 'alma9' and r['driver'] == 'nvidia-580']
    if len(rows) != 3 or sum(r['role'] == 'server' for r in rows) != 1 or sum(r['role'] == 'workstation' for r in rows) != 2:
        raise ValueError('Expected three Alma 9 R580 rows: one server and two workstations')
    lane = (ROOT / 'recipes/layers/alma9/nvidia-580.yml').read_text()
    for snippet in ('RUN dnf -y module reset nvidia-driver',
                    'RUN dnf -y module enable nvidia-driver:580',
                    'nvidia-driver nvidia-driver-cuda',
                    *(f"--exclude='{p}*'" for p in ('kernel-debug', 'kernel-debug-core',
                                                   'kernel-debug-modules', 'kernel-debug-modules-extra'))):
        if snippet not in lane:
            raise ValueError(f'Alma 9 R580 layer missing required contract: {snippet}')
    if 'libva-nvidia-driver' in lane or 'nvidia-driver:latest' in lane:
        raise ValueError('Alma 9 R580 must remain server-safe and use a pinned module stream')
    workstation = ROOT / 'recipes/layers/alma9/nvidia-workstation.yml'
    if 'libva-nvidia-driver' not in workstation.read_text():
        raise ValueError('Alma 9 NVIDIA workstation layer must install the VAAPI backend')
    for row in rows:
        count = recipe_graph(ROOT / row['recipe']).count(workstation)
        if count != int(row['role'] == 'workstation'):
            raise ValueError(f"{row['image']}: incorrect workstation VAAPI layer")
    return rows


def transaction(runtime, packages):
    script = f'''set -euo pipefail
curl -fsSL {shlex.quote(REPO)} -o /etc/yum.repos.d/almalinux-nvidia.repo
rpm -q kernel-core
dnf -y module reset nvidia-driver >/dev/null
dnf -y module enable nvidia-driver:{STREAM} >/dev/null
dnf -y --assumeno install {shlex.join(packages)} 2>&1 || true
'''
    for attempt in range(1, 4):
        result = subprocess.run([runtime, 'run', '--rm', IMAGE, 'bash', '-lc', script],
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if result.returncode == 0:
            return result.stdout
        if TRANSIENT.search(result.stdout) and attempt < 3:
            print(f'Transient container failure (attempt {attempt}/3); retrying', file=sys.stderr)
            time.sleep(5 * attempt)
            continue
        raise ValueError(f'Container verification failed (attempt {attempt}/3):\n{result.stdout}')
    raise AssertionError('unreachable')


def parse_result(output):
    if re.search(r'^Error:|^\s*- package .* conflicts with ', output, re.M):
        raise ValueError(f'DNF resolution failed:\n{output}')
    resolved = sorted(set(f'{m[1]}-{m[3]}' for m in re.finditer(
        r'^\s*(\S+)\s+(\S+)\s+(\S+)\s+almalinux-nvidia\s+', output, re.M)))
    if not resolved:
        raise ValueError(f'No resolved AlmaLinux NVIDIA packages:\n{output}')
    prebuilt = [p for p in resolved if re.match(r'^kmod-nvidia-\d+\.\d+\.\d+-', p) and 'dkms' not in p.lower()]
    dkms = any('dkms' in p.lower() for p in resolved)
    if not prebuilt or dkms:
        raise ValueError(f'Expected prebuilt proprietary kmods without DKMS; resolved: {resolved}')
    kernel = re.search(r'^kernel-core-(\S+)$', output, re.M)
    fallback = re.match(r'^kmod-nvidia-\d+\.\d+\.\d+-(.+)-3:', prebuilt[0])
    return {'KERNEL_CORE': kernel[1] if kernel else fallback[1] if fallback else 'unknown',
            'PREBUILT_KMODS': 'yes', 'DKMS': 'no',
            'RESOLVED_PACKAGES': ', '.join(resolved), 'AMBIGUITY': 'none'}


def main():
    rows = validate_lane()
    runtime = shutil.which('podman') or shutil.which('docker')
    if not runtime:
        raise ValueError('Need podman or docker for the live Alma 9 NVIDIA transaction preflight')
    for role, packages in PACKAGES.items():
        result = parse_result(transaction(runtime, packages))
        for row in rows:
            if row['role'] != role:
                continue
            for key in ('image', 'platform', 'role', 'environment', 'driver'):
                print(f'{key.upper()}={row[key]}')
            print(f'DRIVER_STREAM={STREAM}')
            for key, value in result.items():
                print(f'{key}={value}')
            print()


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError) as error:
        raise SystemExit(str(error))
