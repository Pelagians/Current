#!/usr/bin/env python3
"""Stage native BlueBuild images, then publish verified, signed OCI indexes."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('image_matrix', ROOT / 'scripts/render-image-matrix.py')
matrix = importlib.util.module_from_spec(spec)
spec.loader.exec_module(matrix)
OCI_ARCH = {'x86_64': 'amd64', 'aarch64': 'arm64'}


def run(*args):
    result = subprocess.run(args, text=True, capture_output=True)
    if result.returncode:
        raise ValueError(f"{' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def build_context():
    revision = os.environ['GITHUB_SHA']
    run_id, attempt = os.environ['GITHUB_RUN_ID'], os.environ['GITHUB_RUN_ATTEMPT']
    if not re.fullmatch(r'[0-9a-f]{40}', revision) or not run_id.isdecimal() or not attempt.isdecimal():
        raise ValueError('Invalid CI build identity')
    namespace = os.environ.get('CURRENT_REGISTRY_NAMESPACE', 'ghcr.io/pelagians').lower()
    if not re.fullmatch(r'ghcr\.io/[a-z0-9][a-z0-9_-]*', namespace):
        raise ValueError('Invalid Current registry namespace')
    return revision, run_id, attempt, namespace


def marker(architecture, attempt=None):
    _, run_id, current_attempt, _ = build_context()
    return f'run-{run_id}-{attempt or current_attempt}-{OCI_ARCH[architecture]}'


def native_row(image, architecture):
    return next(r for r in matrix.load_rows() if r['image'] == image and r['architecture'] == architecture)


def prepare(image, architecture):
    row = native_row(image, architecture)
    text = (ROOT / row['recipe']).read_text()
    if re.search(r'^(alt-tags|labels):', text, re.M):
        raise ValueError('Native staging requires recipes without custom tags/labels')
    revision, _, _, _ = build_context()
    text += '\nalt-tags:\n  - ' + marker(architecture) + '\nlabels:\n'
    for key, value in {'org.opencontainers.image.revision': revision,
                       'io.current.build': marker(architecture)}.items():
        text += '  ' + key + ': ' + json.dumps(value) + '\n'
    path = ROOT / 'recipes/.generated' / f'{image}-{OCI_ARCH[architecture]}.yml'
    path.parent.mkdir(exist_ok=True)
    path.write_text(text)
    return '/.generated/' + path.name


def inspect_raw(ref):
    raw = run('skopeo', 'inspect', '--raw', 'docker://' + ref)
    return json.loads(raw), 'sha256:' + hashlib.sha256(raw.encode()).hexdigest()


def check_config(ref, architecture, attempt=None):
    config = json.loads(run('skopeo', 'inspect', '--config', 'docker://' + ref))
    revision, _, _, _ = build_context()
    labels = config.get('config', {}).get('Labels', {})
    if (config.get('os'), config.get('architecture')) != ('linux', OCI_ARCH[architecture]):
        raise ValueError(f'{ref}: wrong native image platform')
    if labels.get('org.opencontainers.image.revision') != revision or labels.get('io.current.build') != marker(architecture, attempt):
        raise ValueError(f'{ref}: image is from another commit or CI build')


def record(image, architecture, directory):
    native_row(image, architecture)
    revision, run_id, attempt, namespace = build_context()
    repo = namespace + '/' + image
    tags = json.loads(run('skopeo', 'list-tags', 'docker://' + repo))['Tags']
    pattern = re.compile(r'(?:^|-)' + re.escape(marker(architecture)) + r'(?:-[0-9]+)?$')
    tags = sorted(t for t in tags if pattern.search(t))
    if not tags:
        raise ValueError(f'{repo}: missing native staging tag')
    versions = {match[1] for tag in tags if (match := re.search(r'-([0-9]+)$', tag))}
    if len(versions) != 1:
        raise ValueError(f'{repo}: missing or inconsistent native distro version tags')
    raw, digest = inspect_raw(repo + ':' + tags[0])
    if 'manifests' in raw:
        # Buildx may also attach provenance descriptors with unknown/unknown platform.
        images = [d for d in raw['manifests'] if d.get('platform', {}).get('os') != 'unknown']
        if len(images) != 1 or (images[0].get('platform', {}).get('architecture'), images[0].get('platform', {}).get('os')) != (OCI_ARCH[architecture], 'linux'):
            raise ValueError(f'{repo}: staging index is not the requested native platform')
        digest = images[0]['digest']
    ref = repo + '@' + digest
    check_config(ref, architecture)
    artifact = dict(image=image, architecture=architecture, digest=digest,
                    revision=revision, run_id=run_id, attempt=attempt, namespace=namespace,
                    version=versions.pop())
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f'{image}-{OCI_ARCH[architecture]}.json').write_text(json.dumps(artifact) + '\n')
    print('Recorded ' + ref)


def load_records(directory):
    revision, run_id, attempt, namespace = build_context()
    expected = {(r['image'], r['architecture']) for r in matrix.load_rows()}
    records = {}
    for path in directory.rglob('*.json'):
        value = json.loads(path.read_text())
        key = (value['image'], value['architecture'])
        if key not in expected or key in records:
            raise ValueError(f'{path}: unexpected or duplicate native build')
        if (value['revision'], value['run_id'], value['namespace']) != (revision, run_id, namespace):
            raise ValueError(f'{path}: native build is from another commit/run/registry')
        native_attempt = value['attempt']
        if not isinstance(native_attempt, str) or not native_attempt.isdecimal() or not 1 <= int(native_attempt) <= int(attempt):
            raise ValueError(f'{path}: invalid or future native build attempt')
        if not re.fullmatch(r'sha256:[0-9a-f]{64}', value['digest']):
            raise ValueError(f'{path}: invalid native digest')
        if not re.fullmatch(r'[0-9]+', value['version']):
            raise ValueError(f'{path}: invalid native distro version')
        records[key] = value
    missing = expected - records.keys()
    if missing:
        raise ValueError(f'Missing native builds: {sorted(missing)}')
    for image in {r['image'] for r in records.values()}:
        if len({r['version'] for r in records.values() if r['image'] == image}) != 1:
            raise ValueError(f'{image}: architectures have different distro versions')
    return records


def channel():
    event = os.environ['GITHUB_EVENT_NAME']
    ref = os.environ['GITHUB_REF_NAME']
    if event == 'pull_request':
        number = os.environ['CURRENT_PR_NUMBER']
        if not number.isdecimal():
            raise ValueError('Invalid pull request number')
        return 'pr-' + number
    if os.environ.get('GITHUB_REF_TYPE') == 'branch':
        if ref == os.environ['CURRENT_DEFAULT_BRANCH']:
            return 'latest'
        tag = 'br-' + ref.replace('/', '_')
    else:
        tag = 'sha-' + build_context()[0][:12]
    if not re.fullmatch(r'[a-zA-Z0-9_][a-zA-Z0-9_.-]{0,127}', tag):
        raise ValueError('Invalid publication channel')
    return tag


def check_index(raw, children, revision):
    expected = {('linux', OCI_ARCH[arch], digest) for arch, digest in children.items()}
    actual = [(d.get('platform', {}).get('os'), d.get('platform', {}).get('architecture'), d['digest'])
              for d in raw.get('manifests', [])]
    if len(actual) != len(expected) or set(actual) != expected:
        raise ValueError('Merged index has missing, duplicate, wrong-platform or wrong-digest children')
    if raw.get('annotations', {}).get('org.opencontainers.image.revision') != revision:
        raise ValueError('Merged index has incorrect source revision')


def sign_and_verify(ref):
    # Match BlueBuild's Cosign v3 contract and containers/image's .sig attachments.
    run('cosign', 'sign', '--yes', '--key', 'env://COSIGN_PRIVATE_KEY',
        '--new-bundle-format=false', '--use-signing-config=false', ref)
    run('cosign', 'verify', '--key', str(ROOT / 'cosign.pub'), ref)


def publish(directory):
    records = load_records(directory)
    revision, run_id, attempt, namespace = build_context()
    target = channel()
    if not os.environ.get('COSIGN_PRIVATE_KEY'):
        raise ValueError('Missing index signing key')
    # Validate every artifact and its actual registry payload before any publication.
    grouped = {}
    for (image, arch), record in sorted(records.items()):
        repo = namespace + '/' + image
        ref = repo + '@' + record['digest']
        check_config(ref, arch, record['attempt'])
        grouped.setdefault(image, {})[arch] = record['digest']
    staged = {}
    for image, children in grouped.items():
        repo = namespace + '/' + image
        for digest in children.values():
            ref = repo + '@' + digest
            sign_and_verify(ref)
        staged_ref = f'{repo}:run-{run_id}-{attempt}'
        run('docker', 'buildx', 'imagetools', 'create', '--prefer-index=true',
            '--annotation', 'index:org.opencontainers.image.revision=' + revision,
            '--tag', staged_ref, *[repo + '@' + d for d in children.values()])
        raw, digest = inspect_raw(staged_ref)
        check_index(raw, children, revision)
        ref = repo + '@' + digest
        sign_and_verify(ref)
        staged[image] = ref
        if 'aarch64' in children:
            digest = children['aarch64']
            alias_repo = f'{namespace}/{image}-arm64'
            run('skopeo', 'copy', '--preserve-digests', 'docker://' + repo + '@' + digest,
                f'docker://{alias_repo}:run-{run_id}-{attempt}')
            alias_ref = alias_repo + '@' + digest
            sign_and_verify(alias_ref)
    # Only complete, validated and signed indexes can advance user-facing channels.
    # Each tag update is atomic; registries do not offer transactions across repositories.
    for image, ref in staged.items():
        version = next(r['version'] for r in records.values() if r['image'] == image)
        # Preserve stock BlueBuild version streams, including older installed ARM refs.
        targets = [target, version if target == 'latest' else target + '-' + version]
        for tag in targets:
            run('docker', 'buildx', 'imagetools', 'create', '--tag', f'{namespace}/{image}:{tag}', ref)
            for arch, digest in grouped[image].items():
                native = namespace + '/' + image + '@' + digest
                run('docker', 'buildx', 'imagetools', 'create', '--prefer-index=false',
                    '--tag', f'{namespace}/{image}:{tag}-{OCI_ARCH[arch]}', native)
                if arch == 'aarch64':
                    # Compatibility signatures were staged in their own repository above.
                    run('docker', 'buildx', 'imagetools', 'create', '--prefer-index=false',
                        '--tag', f'{namespace}/{image}-arm64:{tag}',
                        f'{namespace}/{image}-arm64@{digest}')
        print(f'Published {namespace}/{image}:{target}: ' + ', '.join(grouped[image]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'record', 'publish'))
    parser.add_argument('--image')
    parser.add_argument('--architecture', choices=OCI_ARCH)
    parser.add_argument('--directory', type=Path, default=Path('native-digests'))
    args = parser.parse_args()
    if args.command == 'publish':
        publish(args.directory)
    else:
        if not args.image or not args.architecture:
            parser.error('prepare/record require --image and --architecture')
        if args.command == 'prepare':
            print(prepare(args.image, args.architecture))
        else:
            record(args.image, args.architecture, args.directory)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, StopIteration, OSError) as error:
        sys.exit('Image publication failed: ' + str(error))
