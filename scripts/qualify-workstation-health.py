#!/usr/bin/env python3
"""Read-only native-policy/account assertions for fresh disposable VM installs."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess


def check_labels(paths, get_context=lambda path: os.getxattr(path, 'security.selinux'),
                 expected_context=lambda path: subprocess.check_output(['matchpathcon', '-n', str(path)])):
    results = []
    for path in paths:
        actual = get_context(path).decode().rstrip('\0\n')
        expected = expected_context(path).decode().strip()
        # restorecon normally preserves SELinux user/range. Compare policy types,
        # without forcing an administrator's context user or MLS range.
        if actual.split(':')[2] != expected.split(':')[2]:
            raise RuntimeError(f'Incorrect native-policy type: {path}: {actual}, expected {expected}')
        results.append(dict(path=str(path), actual=actual, expected=expected))
    return results


def check_avcs(output):
    # Keep bootc's known install-domain capability probe distinct from a real
    # color-daemon denial; do not suppress either from the captured journal.
    for line in output.splitlines():
        if ':colord_t:' in line and re.search(r'avc:\s+denied', line):
            raise RuntimeError('Color daemon still has an SELinux denial: ' + line)


def installer_diagnostics():
    # Read the logs saved by Anaconda after all tasks, not only the earlier
    # live-runtime %post snapshot. Never collect credential/shadow contents.
    pattern = re.compile(r'restorecon|genhomedircon|_current_label_new_home|relabel|SELinux is disabled', re.I)
    for path in sorted(Path('/var/log/anaconda').glob('*.log')):
        print('LOG', path)
        for line in path.read_text(errors='replace')[-4 * 1024**2:].splitlines():
            if pattern.search(line) and not re.search(r'password|rootpw|chpasswd', line, re.I):
                print(line)
    path = Path('/etc/selinux/targeted/contexts/files/file_contexts.homedirs')
    print('HOMEDIR_CONTEXTS', path.exists())
    if path.exists():
        for line in path.read_text().splitlines():
            if re.search(r'currenttest|HOME_|/var/home|/home', line):
                print(line)


def main(labels_only=False, require_icc=False):
    home = Path('/var/home/currenttest')
    paths = [home, home / 'current-sentinel', Path('/etc/passwd'), Path('/etc/shadow'),
             Path('/etc/group'), Path('/etc/gshadow'), Path('/etc/.pwd.lock')]
    icc = home / '.local/share/icc'
    if icc.exists():
        paths.extend([icc, *sorted(path for path in icc.rglob('*') if not path.is_symlink())])
    if require_icc and not any(path.suffix == '.icc' and path.is_file() for path in paths):
        raise RuntimeError('GNOME did not produce a readable ICC profile for this VM display')
    result = {'labels': check_labels(paths)}
    if labels_only:
        print(json.dumps(result, indent=2))
        return
    result['avahi_user'] = subprocess.check_output(['getent', 'passwd', 'avahi'], text=True).strip()
    result['avahi_group'] = subprocess.check_output(['getent', 'group', 'avahi'], text=True).strip()
    if result['avahi_user'].split(':')[3] != result['avahi_group'].split(':')[2]:
        raise RuntimeError('Avahi primary group does not resolve consistently')
    subprocess.run(['systemctl', 'is-active', '--quiet', 'avahi-daemon.service'], check=True)
    brew_result = subprocess.check_output(['systemctl', 'show', 'brew-setup.service', '-p', 'Result', '--value'], text=True).strip()
    if brew_result != 'success':
        raise RuntimeError('Homebrew setup unit failed: ' + brew_result)
    brew = Path('/var/home/linuxbrew/.linuxbrew')
    if not (brew / 'bin/brew').is_file() or not Path('/etc/.linuxbrew').exists():
        raise RuntimeError('Homebrew initial setup did not complete')
    result['brew_uid'] = brew.stat().st_uid
    if result['brew_uid'] != 1000:
        raise RuntimeError('Homebrew prefix lost its user ownership')
    avcs = subprocess.check_output(['journalctl', '-k', '-b', '--no-pager', '-o', 'cat'], text=True)
    check_avcs(avcs)
    result['colord_denials'] = 0
    result['colord_denials_source'] = 'current-boot kernel journal'
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--labels-only', action='store_true')
    parser.add_argument('--require-icc', action='store_true')
    parser.add_argument('--installer-diagnostics', action='store_true')
    args = parser.parse_args()
    if args.installer_diagnostics:
        installer_diagnostics()
    else:
        main(args.labels_only, args.require_icc)
