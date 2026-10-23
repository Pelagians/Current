#!/usr/bin/env python3
"""Rebuild pinned native COSMIC RPMs in disposable containers, never on the host."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
INPUTS = ROOT / 'packages/cosmic-repairs'


def run(*command):
    subprocess.run(command, check=True)


def file_hash(path):
    # EL9's native Python is 3.9, before hashlib.file_digest was introduced.
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def patch_spec(text, release):
    # Native autosetup already applies all declared patches with -p1. Keep the
    # vendor's build, install, test, dependency and license handling intact.
    text, count = re.subn(r'^Release:.*$', 'Release: ' + release + '.current1', text, flags=re.M)
    if count != 1 or text.count('%autosetup ') != 1 or 'Patch900:' in text:
        raise ValueError('Unexpected native spec structure')
    text, count = re.subn(r'^(Source2:.*)$', r'\1\nPatch900: current-repair.patch', text, flags=re.M)
    if count != 1:
        raise ValueError('Missing native vendored source declaration')
    # SRPMs have no packaging Git history. Fedora 44 also no longer publishes
    # the old standalone rpmautospec macro package. Record this local rebuild
    # explicitly rather than requiring the source packager's Git automation.
    if text.count('%autochangelog') > 1:
        raise ValueError('Unexpected native changelog structure')
    text = text.replace('%autochangelog', '* Fri Oct 23 2026 Current Project\n'
                        '- Apply the pinned Current COSMIC repair.')
    return text


def build(distribution, package, output):
    if not Path('/run/.containerenv').exists() and not Path('/.dockerenv').exists():
        raise ValueError('Native RPM rebuild must run inside a disposable container')
    configuration = json.loads((INPUTS / 'sources.json').read_text())[distribution]
    source = configuration['packages'][package]
    native = subprocess.check_output(['rpm', '-q', '--qf', '%{VERSION}-%{RELEASE}', package], text=True)
    if native != source['version']:
        raise ValueError(f'Pinned source does not match installed {package}: {native}')
    output.mkdir(parents=True, exist_ok=True)
    # bootc /opt points into /var; installed-OS tmpfiles have not run in this
    # disposable build container. Native EL9 GCC toolsets install below /opt/rh.
    Path('/var/opt').mkdir(parents=True, exist_ok=True)
    Path('/var/roothome').mkdir(parents=True, exist_ok=True)
    dnf = shutil.which('dnf4') or shutil.which('dnf')
    run(dnf, '-y', 'install', 'dnf-plugins-core', 'rpm-build', 'rpmdevtools')
    with tempfile.TemporaryDirectory(prefix='cosmic-rpm-') as directory:
        top = Path(directory)
        archive = top / 'source.src.rpm'
        with urllib.request.urlopen(source['url'], timeout=120) as response, archive.open('wb') as handle:
            shutil.copyfileobj(response, handle)
        digest = file_hash(archive)
        if digest != source['sha256']:
            raise ValueError('Source RPM checksum mismatch')
        run('rpm', '-i', '--define', f'_topdir {top}', str(archive))
        spec = top / 'SPECS' / (package + '.spec')
        spec.write_text(patch_spec(spec.read_text(), native.split('-', 1)[1]))
        patch = INPUTS / 'patches' / source['patch']
        shutil.copyfile(patch, top / 'SOURCES/current-repair.patch')
        run(dnf, '-y', 'builddep', str(spec))
        # The SRPM contains vendored Cargo inputs. Refuse registry/Git updates.
        os.environ['CARGO_NET_OFFLINE'] = 'true'
        os.environ['CARGO_BUILD_JOBS'] = '2'
        os.environ['CARGO_HOME'] = str(top / 'cargo-home')
        run('rpmbuild', '-ba', '--define', f'_topdir {top}',
            '--define', 'debug_package %{nil}', str(spec))
        rpms = list((top / 'RPMS').glob('*/' + package + '-[0-9]*.rpm'))
        if len(rpms) != 1:
            raise ValueError('Expected exactly one repaired native package')
        rpm = rpms[0]
        shutil.copyfile(rpm, output / rpm.name)
        source_rpms = list((top / 'SRPMS').glob('*.src.rpm'))
        if len(source_rpms) != 1:
            raise ValueError('Missing patched source RPM')
        shutil.copyfile(source_rpms[0], output / source_rpms[0].name)
        receipt = dict(distribution=distribution, package=package, native_version=native,
                       source=source, base=configuration['base'], base_revision=configuration['base_revision'],
                       builder_script_sha256=file_hash(Path(__file__)),
                       patch_sha256=hashlib.sha256(patch.read_bytes()).hexdigest(),
                       rpm=rpm.name, rpm_sha256=file_hash(rpm))
        (output / (package + '.json')).write_text(json.dumps(receipt, indent=2) + '\n')


def matrix(seed_run):
    available = set()
    if seed_run:
        if not re.fullmatch(r'[0-9]+', seed_run):
            raise ValueError('Invalid seed run identity')
        repository = os.environ['GITHUB_REPOSITORY']
        endpoint = f'repos/{repository}/actions/runs/{seed_run}'
        previous = json.loads(subprocess.check_output(['gh', 'api', endpoint], text=True))
        if (previous.get('status') != 'completed' or previous.get('head_branch') != os.environ['GITHUB_REF_NAME']
                or previous.get('head_repository', {}).get('full_name') != repository
                or previous.get('path') != '.github/workflows/build.yml'
                or previous.get('event') != 'workflow_dispatch'):
            raise ValueError('Seed must be a completed builder run from this repository and branch')
        artifacts = json.loads(subprocess.check_output(['gh', 'api', endpoint + '/artifacts?per_page=100'], text=True))
        if artifacts['total_count'] > 100:
            raise ValueError('Unexpected repair artifact count')
        available = {item['name'] for item in artifacts['artifacts'] if not item['expired']}
    config = json.loads((INPUTS / 'sources.json').read_text())
    # The assembler validates every reused source/base/patch/binary hash before
    # building or signing a candidate. A seed never reuses assembled images.
    return {'include': [dict(distribution=distro, package=package, base=row['base'],
                             seed_run=seed_run if 'cosmic-repair-' + distro + '-' + package in available else '')
                        for distro, row in config.items() for package in row['packages']]}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['matrix', 'build'])
    parser.add_argument('--distribution', choices=['fedora', 'alma9', 'alma10'])
    parser.add_argument('--package')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--seed-run', default='')
    args = parser.parse_args()
    if args.mode == 'matrix':
        print(json.dumps(matrix(args.seed_run)))
    else:
        if not all((args.distribution, args.package, args.output)):
            parser.error('build requires distribution, package and output')
        build(args.distribution, args.package, args.output)
