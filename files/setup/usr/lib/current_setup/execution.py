"""Privileged staging and durable receipts. No terminal or questionnaire logic."""
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from contextlib import contextmanager

DIGEST = re.compile(r'sha256:[0-9a-f]{64}')
PHASES = {'not-configured', 'image-selected', 'image-staged', 'destination-booted',
          'complete', 'recovery-required'}


class SetupError(RuntimeError):
    pass


def command(args, timeout=60):
    try:
        result = subprocess.run(args, text=True, capture_output=True, timeout=timeout,
                                env=dict(os.environ, LC_ALL='C'))
    except (OSError, subprocess.TimeoutExpired) as error:
        raise SetupError(f'{args[0]} failed: {error}') from error
    if result.returncode:
        raise SetupError(f'{args[0]} failed ({result.returncode}): {result.stderr.strip()}')
    return result.stdout


def status(run=command):
    value = json.loads(run(['bootc', 'status', '--json']))
    if not isinstance(value.get('status'), dict) or not value['status'].get('booted'):
        raise SetupError('No booted bootc deployment found; refusing to stage')
    if value['status'].get('readOnly'):
        raise SetupError('Read-only bootc host cannot be configured')
    if value['status']['booted'].get('incompatible'):
        raise SetupError('Booted deployment has incompatible local changes')
    return dict(value['status'], bootOrder=value.get('spec', {}).get('bootOrder', 'default'))


def image(slot):
    item = (slot or {}).get('image') or {}
    return (item.get('image') or {}).get('image'), item.get('imageDigest')


class Store:
    def __init__(self, directory=Path('/var/lib/current/setup')):
        self.directory = directory
        self.path = directory / 'state.json'

    @contextmanager
    def locked(self):
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (self.directory / 'lock').open('a') as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise SetupError('Setup is already running in another session') from error
            yield

    def load(self):
        if not self.path.exists():
            return {'schema': 1, 'phase': 'not-configured', 'history': []}
        try:
            state = json.loads(self.path.read_text())
            if state.get('schema') != 1 or state['phase'] not in PHASES or not isinstance(state['history'], list):
                raise ValueError('invalid state')
            return state
        except (ValueError, KeyError, TypeError) as error:
            raise SetupError('Setup state is damaged; preserve state.json and inspect recovery documentation') from error

    def save(self, state, phase, **values):
        state = dict(state, **values, phase=phase)
        state['history'] = state.get('history', []) + [phase]
        fd, name = tempfile.mkstemp(dir=self.directory, prefix='.state-')
        try:
            with os.fdopen(fd, 'w') as handle:
                json.dump(state, handle, indent=2)
                handle.write('\n')
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(name, self.path)
            directory_fd = os.open(self.directory, os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if os.path.exists(name):
                os.unlink(name)
        return state


def matches(slot, state):
    ref, digest = image(slot)
    return bool(state.get('target') and ref == state['target'] and digest == state.get('digest'))


def reconcile(store, run=command, boot_id=None):
    state = store.load()
    if state['phase'] in ('not-configured', 'complete'):
        return state
    current = status(run)
    if matches(current.get('booted'), state):
        if state['phase'] != 'destination-booted':
            state = store.save(state, 'destination-booted', error=None)
        return state
    if matches(current.get('staged'), state):
        if state['phase'] != 'image-staged':
            state = store.save(state, 'image-staged', error=None)
        return state
    boot_id = boot_id or Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    if state['phase'] in ('image-staged', 'destination-booted') or (
            state.get('stage_boot_id') and state['stage_boot_id'] != boot_id):
        state = store.save(state, 'recovery-required', error='Expected destination is neither booted nor staged; '
                           'rollback or interrupted staging requires review')
    return state


def resolve(candidate, run=command):
    reference = candidate['reference']
    arch = {'x86_64': 'amd64', 'aarch64': 'arm64'}[candidate['architecture']]
    # Registry access is the network preflight. Do not confuse "NM connected"
    # with reachability, and do not reject a working manually configured network.
    raw = json.loads(run(['skopeo', 'inspect', '--raw', 'docker://' + reference]))
    if 'manifests' not in raw:
        raise SetupError('Destination must be a published shared multi-architecture index')
    children = [entry for entry in raw['manifests']
                if entry.get('platform', {}).get('architecture') == arch
                and entry.get('platform', {}).get('os') == 'linux'
                and entry.get('platform', {}).get('variant', '') in ('', 'v8')]
    if len(children) != 1 or not DIGEST.fullmatch(children[0].get('digest', '')):
        raise SetupError('Missing, duplicate or invalid native image metadata')
    digest = children[0]['digest']
    target = reference.rsplit(':', 1)[0] + '@' + digest
    metadata = json.loads(run(['skopeo', 'inspect', '--override-arch', arch, 'docker://' + target]))
    labels = metadata.get('Labels') or {}
    if (metadata.get('Architecture') != arch or metadata.get('Os') != 'linux'
            or metadata.get('Digest') != digest or labels.get('containers.bootc') != '1'
            or labels.get('io.current.setup-api') != '1'
            or not re.fullmatch(r'[0-9a-f]{40}', labels.get('org.opencontainers.image.revision', ''))):
        raise SetupError('Destination architecture, digest, bootc, setup-api or revision metadata is invalid; use images built with the setup reconciler')
    return target, digest, labels['org.opencontainers.image.revision']


def check_policy(target, policy_path=Path('/etc/containers/policy.json'),
                 key_path=Path('/usr/share/current/cosign.pub')):
    policy = json.loads(policy_path.read_text())
    repository = target.split('@', 1)[0]
    scopes = policy.get('transports', {}).get('docker', {})
    applicable = [key for key in scopes if repository == key or repository.startswith(key + '/') or key == '']
    rules = scopes[max(applicable, key=len)] if applicable else policy.get('default', [])
    # Require the repository key and identity binding; never trust permissive
    # fallback policy. More restrictive extra rules remain in force in bootc.
    for rule in rules:
        if (rule.get('type') == 'sigstoreSigned'
                and rule.get('signedIdentity', {}).get('type') == 'matchRepository'
                and rule.get('keyPath') and Path(rule['keyPath']).read_bytes() == key_path.read_bytes()):
            return
    raise SetupError('Effective container policy does not require the Current repository signing key')


def stage(store, candidate, hardware, run=command, policy_check=check_policy, boot_id=None):
    """Caller supplies a candidate freshly recomputed from native hardware."""
    state = store.load()
    if state['phase'] in ('complete', 'destination-booted', 'image-staged'):
        raise SetupError('Reconcile/resume the existing transaction before staging another image')
    current = status(run)
    if current.get('staged'):
        raise SetupError('An existing bootc deployment is staged; inspect bootc status before proceeding')
    if current.get('rollbackQueued') or current.get('bootOrder') == 'rollback':
        raise SetupError('A rollback is pending')
    state = store.save(state, 'image-selected', candidate=candidate, hardware=hardware,
                       target=None, digest=None, error=None, source=current['booted'])
    try:
        target, digest, revision = resolve(candidate, run)
        policy_check(target)
        boot_id = boot_id or Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        state = store.save(state, 'image-selected', target=target, digest=digest, revision=revision,
                           stage_boot_id=boot_id)
        latest = status(run)
        if (latest.get('staged') or latest.get('rollbackQueued') or latest.get('bootOrder') == 'rollback'
                or latest['booted'] != state['source']):
            raise SetupError('Deployment changed during validation; inspect bootc status before retry')
        run(['bootc', 'switch', '--enforce-container-sigpolicy', '--retain', target], timeout=7200)
        if not matches(status(run).get('staged'), state):
            raise SetupError('bootc returned success without the expected staged deployment')
        return store.save(state, 'image-staged')
    except (SetupError, OSError, ValueError, KeyboardInterrupt) as error:
        store.save(state, 'recovery-required', error=str(error) or 'Interrupted; reconcile before retry')
        raise


def complete(store, run=command):
    state = reconcile(store, run)
    if state['phase'] == 'complete':
        return state
    if state['phase'] != 'destination-booted' or not matches(status(run).get('booted'), state):
        raise SetupError('Completion requires the exact destination to be booted')
    # Explicit user acceptance of networking/login is separate from digest observation.
    return store.save(state, 'complete', accepted_by_user=True)
