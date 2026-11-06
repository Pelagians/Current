#!/usr/bin/env python3
"""Prepare isolated native bootstrap recipes and resolve their CI build identity."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
ARCHES = {'x86_64': 'amd64', 'aarch64': 'arm64'}


def run(*args):
    return subprocess.check_output(args, text=True)


def identity(arch):
    revision = os.environ['GITHUB_SHA']
    run_id, attempt = os.environ['GITHUB_RUN_ID'], os.environ['GITHUB_RUN_ATTEMPT']
    if not re.fullmatch('[0-9a-f]{40}', revision) or not run_id.isdecimal() or not attempt.isdecimal():
        raise ValueError('Invalid CI identity')
    return revision, f'run-{run_id}-{attempt}-{ARCHES[arch]}'


def prepare(arch):
    revision, marker = identity(arch)
    text = (ROOT / 'recipes/bootstrap.yml').read_text().replace(
        'name: current-bootstrap\n', f'name: current-bootstrap-{arch}\n')
    text += f'\nalt-tags:\n  - {marker}\nlabels:\n'
    text += f'  org.opencontainers.image.revision: "{revision}"\n  io.current.build: "{marker}"\n'
    path = ROOT / f'recipes/.generated/bootstrap-{arch}.yml'
    path.parent.mkdir(exist_ok=True)
    path.write_text(text)
    return '/.generated/' + path.name


def resolve(arch):
    revision, marker = identity(arch)
    repository = 'ghcr.io/pelagians/current-bootstrap-' + arch
    tags = json.loads(run('skopeo', 'list-tags', 'docker://' + repository))['Tags']
    matches = sorted(tag for tag in tags if re.search(r'(?:^|-)' + re.escape(marker) + r'(?:-44)?$', tag))
    if not matches:
        raise ValueError('No bootstrap artifact from this run')
    raw = run('skopeo', 'inspect', '--raw', 'docker://' + repository + ':' + matches[0])
    data = json.loads(raw)
    digest = 'sha256:' + hashlib.sha256(raw.encode()).hexdigest()
    if 'manifests' in data:
        children = [entry for entry in data['manifests'] if entry.get('platform', {}).get('os') != 'unknown']
        if len(children) != 1 or children[0].get('platform', {}).get('architecture') != ARCHES[arch]:
            raise ValueError('Wrong native bootstrap index')
        digest = children[0]['digest']
    if not re.fullmatch('sha256:[a-f0-9]{64}', digest):
        raise ValueError('Invalid bootstrap digest')
    target = repository + '@' + digest
    config = json.loads(run('skopeo', 'inspect', '--config', 'docker://' + target))
    labels = config.get('config', {}).get('Labels', {})
    if (config.get('architecture') != ARCHES[arch] or config.get('os') != 'linux'
            or labels.get('org.opencontainers.image.revision') != revision
            or labels.get('io.current.build') != marker or labels.get('containers.bootc') != '1'):
        raise ValueError('Bootstrap platform/build identity mismatch')
    return target


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'resolve'))
    parser.add_argument('architecture', choices=ARCHES)
    args = parser.parse_args()
    print(prepare(args.architecture) if args.command == 'prepare' else resolve(args.architecture))
