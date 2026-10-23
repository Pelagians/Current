#!/usr/bin/env python3
"""Validate native repair receipts before assembling a disposable bootc image."""
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
INPUTS = ROOT / 'packages/cosmic-repairs'


def prepare(distribution, artifacts, destination):
    config = json.loads((INPUTS / 'sources.json').read_text())[distribution]
    expected = config['packages']
    if {p.stem for p in artifacts.glob('*.json')} != set(expected):
        raise ValueError('Missing or unexpected native repair receipts')
    verified = []
    for package, source in expected.items():
        receipt = json.loads((artifacts / (package + '.json')).read_text())
        if (receipt.get('distribution') != distribution or receipt.get('package') != package
                or receipt.get('source') != source or receipt.get('base') != config['base']
                or receipt.get('base_revision') != config['base_revision']
                or receipt.get('native_version') != source['version']
                or receipt.get('patch_sha256') != hashlib.sha256(
                    (INPUTS / 'patches' / source['patch']).read_bytes()).hexdigest()):
            raise ValueError('Repair receipt differs from pinned inputs')
        name = receipt['rpm']
        # Do not let an artifact select a host path or substitute an SRPM.
        if Path(name).name != name or '/' in name or not name.startswith(package + '-') or not name.endswith('.x86_64.rpm'):
            raise ValueError('Invalid native repair RPM filename')
        rpm = artifacts / name
        if hashlib.sha256(rpm.read_bytes()).hexdigest() != receipt['rpm_sha256']:
            raise ValueError('Native repair RPM checksum mismatch')
        verified.append((rpm, package + '.json'))
    # Validate every artifact before creating the build context.
    destination.mkdir()
    (destination / 'rpms').mkdir()
    (destination / 'receipts').mkdir()
    for rpm, receipt in verified:
        shutil.copyfile(rpm, destination / 'rpms' / rpm.name)
        shutil.copyfile(artifacts / receipt, destination / 'receipts' / receipt)
    (destination / 'Containerfile').write_text('''ARG BASE
FROM ${BASE}
COPY rpms/ /tmp/current-cosmic-rpms/
RUN dnf -y --disablerepo='*' install /tmp/current-cosmic-rpms/*.rpm && rm -rf /tmp/current-cosmic-rpms && bootc container lint
COPY receipts/ /usr/share/current/cosmic-repairs/
''')


if __name__ == '__main__':
    if len(sys.argv) != 4:
        raise SystemExit('usage: prepare-cosmic-repair-candidate.py DISTRIBUTION ARTIFACTS DESTINATION')
    prepare(sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3]))
