#!/usr/bin/env python3
"""Build-time installation from the pinned, read-only COSMIC runtime bundle."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys


def rpm(*args):
    return subprocess.check_output(['rpm', *args], text=True).strip()


def distribution(release):
    values = dict(line.split('=', 1) for line in release.splitlines()
                  if '=' in line and not line.startswith('#'))
    identity = values.get('ID', '').strip('"')
    version = values.get('VERSION_ID', '').strip('"').split('.')[0]
    if identity == 'fedora':
        return 'fedora'
    if identity == 'almalinux' and version in ('9', '10'):
        return 'alma' + version
    raise ValueError('No COSMIC repair set for this distribution')


def install(bundle, distro, receipts):
    architecture = rpm('--eval', '%{_arch}')
    if architecture == 'aarch64':
        print('Current COSMIC native repairs: ARM packages remain upstream; unqualified')
        return
    if architecture != 'x86_64':
        raise ValueError('Unsupported native RPM architecture')
    root = bundle / distro
    metadata = sorted((root / 'receipts').glob('*.json'))
    if not metadata:
        raise ValueError('Missing COSMIC repair receipts')
    packages = []
    for path in metadata:
        receipt = json.loads(path.read_text())
        package = receipt['package']
        native = receipt['native_version']
        name = receipt['rpm']
        if (receipt['distribution'] != distro or path.stem != package
                or Path(name).name != name or name != package + '-' + native + '.current1.x86_64.rpm'):
            raise ValueError('Invalid native COSMIC repair receipt')
        artifact = root / 'rpms' / name
        if hashlib.sha256(artifact.read_bytes()).hexdigest() != receipt['rpm_sha256']:
            raise ValueError('COSMIC repair RPM checksum mismatch')
        identity = rpm('-qp', '--qf', '%{NAME} %{VERSION}-%{RELEASE} %{ARCH}', str(artifact))
        if identity != package + ' ' + native + '.current1 x86_64':
            raise ValueError('COSMIC repair RPM metadata mismatch')
        installed = rpm('-q', '--qf', '%{VERSION}-%{RELEASE}', package)
        if installed not in (native, native + '.current1'):
            raise ValueError('Native COSMIC package changed; review repair before updating: ' + package + ' ' + installed)
        packages.append((package, native, artifact))
    # All versions and bytes are checked before any mutation. The bundle is
    # trusted by its reviewed digest and Current signature, not an RPM repo.
    subprocess.run(['dnf', '-y', '--disablerepo=*', 'install',
                    *[str(artifact) for _, _, artifact in packages]], check=True)
    for package, native, _ in packages:
        if rpm('-q', '--qf', '%{VERSION}-%{RELEASE}', package) != native + '.current1':
            raise ValueError('Repaired COSMIC package was not installed: ' + package)
    receipts.mkdir(parents=True, exist_ok=True)
    for path in metadata:
        shutil.copyfile(path, receipts / path.name)


if __name__ == '__main__':
    if not Path('/run/.containerenv').exists() and not Path('/.dockerenv').exists():
        raise SystemExit('COSMIC repair installation must run in an image build container')
    if len(sys.argv) != 2:
        raise SystemExit('usage: install-cosmic-repairs.py BUNDLE')
    install(Path(sys.argv[1]), distribution(Path('/usr/lib/os-release').read_text()),
            Path('/usr/share/current/cosmic-repairs'))
