#!/usr/bin/env python3
"""Disposable x86 UEFI qualification. Never accepts an existing disk or block device.

The original ISO first boots without overrides for graphical evidence. A second
boot uses its own GRUB/kernel/initrd with a test-only Kickstart over slirp HTTP.
Only storage/user answers are automated; installed setup and bootc stay real.
No credentials, virtual disks, or EFI variable stores are uploaded as evidence.
"""
import argparse
import base64
import hashlib
import http.server
import json
import os
from pathlib import Path
import platform
import re
import secrets
import shlex
import shutil
import socket
import subprocess
import threading
import time
import uuid


# Kernel audit records can split printf's marker between any two characters.
# Accept only complete timestamped audit lines there; unrelated text or a
# truncated record must still fail. The leading newline excludes command echo.
_AUDIT_INSERTION = r'(?:\[\s*[0-9]+\.[0-9]+\] audit: [^\r\n]*\r?\n)*'
COMMAND_RC = r'\r?\n' + _AUDIT_INSERTION.join(map(re.escape, 'VM_RC=')) + _AUDIT_INSERTION + r'([0-9]+)'


def workstation_target(distribution, desktop, target_distribution=None, target_desktop=None):
    # Keep desktop identity for cross-distro tests, and preserve the existing
    # default GNOME <-> COSMIC test within one distro. Explicit choice is allowed.
    if target_desktop:
        return target_desktop
    if target_distribution and target_distribution != distribution:
        return desktop
    return 'cosmic' if desktop == 'gnome' else 'gnome'


def allowed_evidence_path(path):
    fixed = {'/anaconda.log', '/storage.log', '/program.log', '/packaging.log',
             '/users.log', '/install-marker.log', '/install-error.log',
             '/storage-rejected.log', '/bootstrap-account-labels.log',
             '/installer-account-diagnostics.log'}
    return path in fixed or re.fullmatch(
        r'/(?:bootstrap|source|bootstrap-reboot|destination|destination-reboot|rollback|rebase-target|rebase-target-reboot|rebase-rollback|recovery-bootstrap|journal-final)-(?:markers|archive-verification|workstation-health|avahi-startup)\.log',
        path) is not None or re.fullmatch(
        r'/(?:source|rebase-target|rebase-target-reboot|rebase-rollback)-(?:before|after)-portal\.png', path) is not None or re.fullmatch(
        r'/(?:source|rebase-target|rebase-target-reboot|rebase-rollback)-(?:before-workstation-health|cosmic-shutdown)\.log', path) is not None


def accent_footer_regions(width, height, pixel):
    """OCR regions for stock COSMIC cyan controls; a region never authorizes a click."""
    points = set()
    for y in range(height // 2, height):
        for x in range(width):
            red, green, blue = pixel(x, y)
            if green > 130 and blue > 130 and green > red * 1.25 and blue > red * 1.25:
                points.add((x, y))
    regions = []
    while points:
        seed = points.pop()
        pending = [seed]
        left = right = seed[0]
        top = bottom = seed[1]
        while pending:
            x, y = pending.pop()
            left, right, top, bottom = min(left, x), max(right, x), min(top, y), max(bottom, y)
            for neighbour in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if neighbour in points:
                    points.remove(neighbour)
                    pending.append(neighbour)
        if (0 < left < right < width - 1 and bottom < height - 1
                and 45 <= right - left + 1 <= 240 and 20 <= bottom - top + 1 <= 70):
            regions.append((left + 6, top + 6, right - 5, bottom - 5))
    return sorted(regions)


def visible_control(tsv, width, height, labels=('next', 'finish'), required_phrase=None, minimum_y=None):
    """Only act on a unique visible control in the expected UI, never guess."""
    if required_phrase:
        fields = [line.split('\t') for line in tsv.splitlines()[1:]]
        words = ' '.join(' '.join(row[11] for row in fields if len(row) == 12
                                 and row[0] == '5' and float(row[10]) >= 60).split())
        phrases = (required_phrase,) if isinstance(required_phrase, str) else required_phrase
        if not any(phrase.lower() in words.lower() for phrase in phrases):
            return None
    buttons = []
    minimum_y = height / 2 if minimum_y is None else minimum_y
    for line in tsv.splitlines()[1:]:
        fields = line.split('\t')
        if len(fields) != 12 or fields[11].lower() not in labels:
            continue
        x, y, w, h = map(int, fields[6:10])
        if (float(fields[10]) >= 60 and 0 <= x < x + w <= width
                and minimum_y < y < y + h <= height):
            buttons.append((fields[11], x + w // 2, y + h // 2))
    return buttons[0] if len(buttons) == 1 else None


def terminal_text(output):
    """Remove terminal framing, retaining the actual guest output for assertions."""
    output = re.sub(r'\x1b\].*?(?:\x07|\x1b\\)', '', output, flags=re.DOTALL)
    return re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', output)


def journal_verification(output, allow_older_reader=False):
    """Defer only unsupported archives; rollback must verify those exact files."""
    output = '\n'.join(terminal_text(output).splitlines())
    status = re.search(r'^VERIFY_RC=([0-9]+)$', output, re.MULTILINE)
    passed = re.findall(r'^PASS: (.+)$', output, re.MULTILINE)
    failed = re.findall(r'^FAIL: (.+)$', output, re.MULTILINE)
    deferred = []
    for failure in failed:
        match = re.fullmatch(r'(/var/log/journal/[0-9a-f]{32}/(?:system|user-[0-9]+)@[^/ ]+\.journal~?) \(Operation not supported\)', failure)
        if not allow_older_reader or not match:
            raise RuntimeError('Journal verification failed: ' + failure)
        deferred.append(match[1])
    if not status or not passed or (status[1] != '0' and not deferred) or (status[1] == '0' and failed):
        raise RuntimeError('Incomplete or inconsistent journal verification result')
    return {'passed': passed, 'deferred': deferred}


def shutdown_summary(output, expected_reboots):
    output = terminal_text(output)
    failures = re.findall(r'systemd-shutdown\[1\]: (?:(?:Failed|Unable) to finalize|Failed to execute shutdown binary|Failed to switch root to)[^\r\n]*', output)
    # 252 says "Returning to initrd"; 259 says "Entering exitrd". Both report
    # this stable preceding sentence after successfully changing the root.
    # The pivot hands teardown to dracut; failures there must also fail the run.
    failures += re.findall(r'(?:dracut(?: Warning)?: (?:Cannot umount /oldroot|Unmounting [^\r\n]* (?:timed out|failed)|(?:reboot|poweroff|halt) failed!)|device-mapper: remove ioctl on [^\r\n]* failed:)[^\r\n]*', output)
    shutdowns = output.split('Successfully changed into root pivot.')[1:]
    pivots = len(shutdowns)
    # EL9 logs successful unmounts with a Warning prefix, sometimes twice.
    # Require one confirmation per pivot, rather than counting duplicate lines.
    unmounted = sum(bool(re.search(r'dracut(?: Warning)?: Unmounted /oldroot\.', part)) for part in shutdowns)
    return {'expected_reboots': expected_reboots, 'initrd_pivots': pivots,
            'oldroot_unmounts': unmounted, 'finalization_failures': failures,
            'passed': not failures and pivots >= expected_reboots and unmounted == pivots}


def cosmic_boot_id(output):
    """Kernel UUIDs use hyphens; journalctl boot descriptors require 32 hex digits."""
    matches = re.findall(r'^COSMIC_BOOT_ID=([0-9a-fA-F-]+)\r?$', terminal_text(output), re.MULTILINE)
    if len(matches) != 1:
        raise RuntimeError('Missing or ambiguous native COSMIC boot identity')
    value = uuid.UUID(matches[0])
    if not value.int:
        raise RuntimeError('Invalid nil COSMIC boot identity')
    return value.hex


def cosmic_shutdown_summary(text):
    """Read native, non-replayed journal JSON from one completed session boot."""
    events = [json.loads(line) for line in text.splitlines() if line.strip()]
    if not events or any(not isinstance(event, dict) for event in events):
        raise RuntimeError('Missing or malformed native COSMIC shutdown journal')
    boots = {event.get('_BOOT_ID') for event in events}
    if len(boots) != 1 or not re.fullmatch(r'[0-9a-f]{32}', next(iter(boots)) or ''):
        raise RuntimeError('COSMIC shutdown journal spans missing or inconsistent boots')
    panics, cores, disconnects = [], [], 0
    for event in events:
        message = event.get('MESSAGE', '')
        if isinstance(message, list):
            message = bytes(message).decode('utf-8', errors='replace')
        if not isinstance(message, str):
            raise RuntimeError('Malformed native journal message')
        identity = str(event.get('SYSLOG_IDENTIFIER', '')) + ' ' + str(event.get('_EXE', ''))
        if 'cosmic' in identity.lower():
            if 'panicked at' in message:
                panics.append(dict(timestamp=event.get('__REALTIME_TIMESTAMP'), message=message))
            if 'wayland dispatch:' in message:
                disconnects += 1
        if event.get('COREDUMP_EXE') and 'cosmic' in str(event['COREDUMP_EXE']).lower():
            cores.append(dict(executable=event['COREDUMP_EXE'], signal=event.get('COREDUMP_SIGNAL'),
                              timestamp=event.get('__REALTIME_TIMESTAMP')))
    return dict(boot_id=next(iter(boots)), records=len(events), panics=panics, coredumps=cores,
                wayland_dispatch_errors=disconnects, passed=not panics and not cores)


def bootc_document(output):
    """Ignore serial framing before bootc's machine-readable response."""
    output = terminal_text(output)
    match = re.search(r'\{\s*"apiVersion"\s*:\s*"org.containers.bootc/v1"', output)
    if not match:
        raise RuntimeError('No bootc JSON response captured')
    document, _ = json.JSONDecoder().raw_decode(output[match.start():])
    if not document.get('status', {}).get('booted', {}).get('image', {}).get('imageDigest'):
        raise RuntimeError('No booted native digest in bootc response')
    return document


def staged_rebase(output):
    lines = re.findall(r'^REBASE_STAGED=(\{[^\r\n]+\})\r?$', terminal_text(output), re.MULTILINE)
    if len(lines) != 1:
        raise RuntimeError('No unique completed rebase receipt captured')
    return json.loads(lines[0])


def console_password(serial):
    # A late getty restart can discard the first username at boot. Retry only
    # after a fresh login prompt, before sending any password.
    for _ in range(3):
        serial.sendline('currenttest')
        if serial.expect(['Password:', 'current-vm login:'], timeout=60) == 0:
            return
    raise RuntimeError('Serial login repeatedly reset before requesting a password')


def graphical_result(output):
    """Ignore echoed commands while waiting for an actual autostart receipt."""
    results = re.findall(r'^SESSION_RESULT=([0-9]+|pending)\r?$', terminal_text(output), re.MULTILINE)
    if len(results) != 1:
        raise RuntimeError('No unique graphical session status receipt')
    return None if results[0] == 'pending' else int(results[0])


def rebase_program(distribution, environment, channel, revision):
    # Resolve the standard VM lane through the installed authoritative inventory
    # and reuse Current's metadata and trust validation, without resetting the
    # completed first-boot transaction to masquerade as another initial setup.
    return f"""import json
from pathlib import Path
from current_setup.matrix import load_rows
from current_setup.execution import resolve, check_policy, command, status, image
rows = load_rows(Path('/usr/share/current/image-matrix.tsv'))
rows = [r for r in rows if r['architecture']=='x86_64' and r['platform']=={distribution!r} and r['environment']=={environment!r} and r['driver']=='standard']
assert len(rows)==1, 'No unique standard VM destination'
candidate = {{'architecture':'x86_64', 'reference':'ghcr.io/pelagians/'+rows[0]['image']+':'+{channel!r}}}
current=status()
assert not current.get('staged') and not current.get('rollbackQueued') and current.get('bootOrder')!='rollback', 'Pending deployment exists'
target,digest,revision=resolve(candidate)
assert revision=={revision!r}, 'Destination source changed during qualification'
check_policy(target)
print('REBASE_RESOLVED='+json.dumps({{'target':target,'digest':digest,'revision':revision}}), flush=True)
print(command(['bootc','switch','--enforce-container-sigpolicy','--retain',target],timeout=7200), flush=True)
assert image(status().get('staged'))==(target,digest), 'Expected destination was not staged'
print('REBASE_STAGED='+json.dumps({{'target':target,'digest':digest,'revision':revision}}), flush=True)
"""


def session_probe():
    # This runs only through the real desktop's XDG autostart after greeter
    # password authentication. Never manufacture DISPLAY or desktop variables.
    return r'''#!/bin/bash
stage=$(cat "$HOME/current-vm-stage")
case "$stage" in *[!a-z0-9-]*|'') exit 2 ;; esac
exec >"$HOME/current-vm-session-$stage.log" 2>&1
(
  set -eu
  printf 'BOOT_ID=%s\n' "$(cat /proc/sys/kernel/random/boot_id)"
  printf 'SESSION_ID=%s\nDESKTOP=%s\nSESSION_TYPE=%s\nWAYLAND_DISPLAY=%s\nDISPLAY=%s\n' "${XDG_SESSION_ID:-}" "${XDG_CURRENT_DESKTOP:-}" "${XDG_SESSION_TYPE:-}" "${WAYLAND_DISPLAY:-}" "${DISPLAY:-}"
  printf 'LANG=%s\nLC_ALL=%s\nLANGUAGE=%s\n' "${LANG:-}" "${LC_ALL:-}" "${LANGUAGE:-}"
  test "${XDG_SESSION_TYPE:-}" = wayland || test "${XDG_SESSION_TYPE:-}" = x11
  test -n "${WAYLAND_DISPLAY:-}${DISPLAY:-}"
  loginctl show-user "$(id -u)" -p Display -p Sessions
  loginctl list-sessions --no-pager
  systemctl --user --failed --no-pager
  ps -u "$(id -u)" -o pid,comm,args
  bash "$HOME/.local/bin/current-vm-qualify-workstation"
)
rc=$?
printf '%s\n' "$rc" >"$HOME/current-vm-session-$stage.rc"
exit "$rc"
'''


def inputs(artifact, revision):
    if not re.fullmatch(r'[0-9a-f]{40}', revision):
        raise ValueError('Expected a full source revision')
    iso = artifact / 'current-installer-x86_64.iso'
    if not iso.is_file() or iso.is_symlink():
        raise ValueError('Expected a regular original ISO')
    checksum = (artifact / (iso.name + '.sha256')).read_text().split()
    if len(checksum) != 2 or checksum[1] != iso.name:
        raise ValueError('Invalid checksum receipt')
    with iso.open('rb') as handle:
        digest = hashlib.file_digest(handle, 'sha256').hexdigest()
    if checksum[0] != digest:
        raise ValueError('ISO checksum mismatch')
    receipt = dict(line.split('=', 1) for line in (artifact / 'build-inputs.txt').read_text().splitlines() if '=' in line)
    if receipt.get('revision') != revision or receipt.get('architecture') != 'x86_64':
        raise ValueError('ISO source revision or architecture mismatch')
    payload = receipt.get('payload', '')
    if not re.fullmatch(r'ghcr.io/pelagians/current-bootstrap-x86_64@sha256:[a-f0-9]{64}', payload):
        raise ValueError('Unexpected bootstrap payload')
    source = 'localhost/current-bootstrap-payload:sha256-' + payload.split('@sha256:')[1]
    if receipt.get('embedded_source') != source:
        raise ValueError('Embedded source is not bound to the bootstrap digest')
    return iso.resolve(), digest, receipt


def kickstart(receipt, password, port, scenario='server-flow'):
    partitioning = ' --type=btrfs' if scenario == 'reject-btrfs' else ''
    # Graphical Anaconda keeps correctable storage errors in its summary screen;
    # %onerror is reserved for fatal errors. Observe its real validation log
    # without modifying the storage model or invoking the checker ourselves.
    observer = f'''%pre
nohup sh -c '
for attempt in $(seq 1 300); do
  if grep -q "^DEBUG:anaconda[.]modules[.]storage[.]partitioning[.]validate:Found sanity error: Current cannot install using Btrfs" /tmp/storage.log 2>/dev/null; then
    for f in /tmp/anaconda.log /tmp/storage.log /tmp/program.log; do
      test ! -f "$f" || curl -fsS --max-time 10 --data-binary @"$f" http://10.0.2.2:{port}/$(basename "$f")
    done
    curl -fsS --max-time 10 --data-binary validation-rejected http://10.0.2.2:{port}/storage-rejected.log
    exit
  fi
  sleep 2
done
' </dev/null >/tmp/current-validation-observer.log 2>&1 &
%end
''' if scenario == 'reject-btrfs' else ''
    return f'''# TEST ONLY: vda is a newly created QEMU disk. Never install this on hardware.
graphical
lang en_US.UTF-8
keyboard us
timezone UTC --utc
network --bootproto=dhcp --device=link --activate --onboot=on --hostname=current-vm
rootpw --lock
selinux --enforcing
user --name=currenttest --groups=wheel --password={password} --plaintext
ignoredisk --only-use=vda
zerombr
clearpart --all --initlabel --drives=vda
autopart{partitioning}
bootloader --append="console=tty0 console=ttyS0,115200n8"
bootc --source-imgref containers-storage:{receipt['embedded_source']} --target-imgref {receipt['payload']}
reboot --eject
{observer}
%post --nochroot
for f in /tmp/anaconda.log /tmp/storage.log /tmp/program.log /tmp/packaging.log /tmp/users.log; do
  test ! -f "$f" || curl -sS --max-time 10 --data-binary @"$f" http://10.0.2.2:{port}/$(basename "$f")
done
curl -sS --max-time 10 --data-binary 'post-install-reached' http://10.0.2.2:{port}/install-marker.log
%end
%onerror
for f in /tmp/anaconda.log /tmp/storage.log /tmp/program.log /tmp/packaging.log /tmp/users.log; do
  test ! -f "$f" || curl -sS --max-time 10 --data-binary @"$f" http://10.0.2.2:{port}/$(basename "$f")
done
curl -sS --max-time 10 --data-binary 'anaconda-error' http://10.0.2.2:{port}/install-error.log
%end
'''


class QMP:
    def __init__(self, path):
        self.socket = socket.socket(socket.AF_UNIX)
        self.socket.settimeout(20)
        for _ in range(100):
            try:
                self.socket.connect(str(path))
                break
            except (FileNotFoundError, ConnectionRefusedError):
                time.sleep(.1)
        self.stream = self.socket.makefile('rwb', buffering=0)
        json.loads(self.stream.readline())
        self.call('qmp_capabilities')

    def call(self, execute, **arguments):
        self.stream.write((json.dumps({'execute': execute, 'arguments': arguments}) + '\n').encode())
        while True:
            answer = json.loads(self.stream.readline())
            if 'error' in answer:
                raise RuntimeError(answer['error'])
            if 'return' in answer:
                return answer['return']

    def keys(self, text, delay=.025):
        punctuation = {' ': 'spc', '/': 'slash', ':': 'shift-semicolon', '=': 'equal',
                       '-': 'minus', '.': 'dot', ',': 'comma', '_': 'shift-minus',
                       '(': 'shift-9', ')': 'shift-0', '\n': 'ret'}
        for char in text:
            key = punctuation.get(char, 'shift-' + char.lower() if char.isupper() else char)
            self.call('human-monitor-command', **{'command-line': 'sendkey ' + key + ' 10'})
            time.sleep(delay)

    def click(self, x, y, width, height):
        if not (0 <= x < width and 0 <= y < height):
            raise ValueError('Pointer coordinate is outside the VM screenshot')
        self.call('input-send-event', events=[
            {'type': 'abs', 'data': {'axis': 'x', 'value': round(x * 32767 / width)}},
            {'type': 'abs', 'data': {'axis': 'y', 'value': round(y * 32767 / height)}},
            {'type': 'btn', 'data': {'down': True, 'button': 'left'}}])
        time.sleep(.1)
        self.call('input-send-event', events=[{'type': 'btn', 'data': {'down': False, 'button': 'left'}}])
        # A hovering hand cursor can cover the next page's small button label.
        self.call('input-send-event', events=[
            {'type': 'abs', 'data': {'axis': 'x', 'value': 16384}},
            {'type': 'abs', 'data': {'axis': 'y', 'value': 3277}}])


class VM:
    def __init__(self, root, evidence, iso, accel):
        self.root, self.evidence, self.iso, self.accel = root, evidence, iso, accel
        self.process = None
        self.serial = None
        self.qmp = None
        self.disk = root / 'disposable.qcow2'
        subprocess.run(['qemu-img', 'create', '-f', 'qcow2', str(self.disk), '64G'], check=True)
        shutil.copyfile('/usr/share/OVMF/OVMF_VARS_4M.fd', root / 'vars.fd')

    def start(self, label, cd=True):
        import pexpect.fdpexpect
        for name in ('qmp', 'serial'):
            (self.root / name).unlink(missing_ok=True)
        args = ['qemu-system-x86_64', '-machine', 'q35,accel=' + self.accel,
                '-cpu', 'host' if self.accel == 'kvm' else 'max', '-smp', '4', '-m', '8192',
                '-drive', 'if=pflash,format=raw,readonly=on,file=/usr/share/OVMF/OVMF_CODE_4M.fd',
                '-drive', 'if=pflash,format=raw,file=' + str(self.root / 'vars.fd'),
                '-drive', 'if=virtio,format=qcow2,file=' + str(self.disk),
                '-device', 'virtio-vga', '-display', 'none',
                '-device', 'qemu-xhci', '-device', 'usb-tablet',
                '-netdev', 'user,id=net', '-device', 'virtio-net-pci,netdev=net,id=nic0',
                '-qmp', 'unix:' + str(self.root / 'qmp') + ',server=on,wait=off',
                '-chardev', 'socket,id=serial,path=' + str(self.root / 'serial') + ',server=on,wait=off',
                '-serial', 'chardev:serial']
        if cd:
            args += ['-cdrom', str(self.iso), '-boot', 'order=d']
        else:
            args += ['-boot', 'order=c']
        self.process = subprocess.Popen(args, stdout=(self.evidence / (label + '-qemu.log')).open('w'), stderr=subprocess.STDOUT)
        self.qmp = QMP(self.root / 'qmp')
        serial_socket = socket.socket(socket.AF_UNIX)
        serial_socket.connect(str(self.root / 'serial'))
        # fdspawn closes its descriptor directly. Transfer ownership so a later
        # socket destructor cannot close a descriptor reused by the next QMP.
        self.serial = pexpect.fdpexpect.fdspawn(serial_socket.detach(), encoding='utf-8', codec_errors='replace', timeout=120)
        self.serial.logfile_read = (self.evidence / (label + '-serial.log')).open('w')

    def screenshot(self, name):
        from PIL import Image
        ppm = self.evidence / (name + '.ppm')
        self.qmp.call('screendump', filename=str(ppm))
        Image.open(ppm).save(ppm.with_suffix('.png'))
        ppm.unlink()

    def stop(self):
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        if self.serial:
            self.serial.logfile_read.close()
            self.serial.close()
            self.serial = None
        if self.qmp:
            self.qmp.stream.close()
            self.qmp.socket.close()
            self.qmp = None


def run(args):
    import pexpect
    if platform.machine() != 'x86_64':
        raise RuntimeError('Use a native x86_64 VM host for this qualification harness')
    iso, digest, receipt = inputs(args.artifact, args.revision)
    root = args.output.resolve()
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    evidence = root / 'evidence'
    evidence.mkdir()
    report = {'iso_sha256': digest, 'inputs': receipt, 'harness_revision': subprocess.check_output(
        ['git', 'rev-parse', 'HEAD'], text=True).strip(), 'distribution': args.distribution,
        'channel': args.channel, 'scenario': args.scenario, 'require_mdns': args.require_mdns, 'expect_locale': args.expect_locale, 'require_clean_avahi': args.require_clean_avahi,
              'desktop': args.desktop if args.scenario == 'workstation-flow' else None,
              'target_distribution': args.target_distribution, 'target_desktop': args.target_desktop,
              'target_channel': args.target_channel, 'image_revision': args.image_revision, 'milestones': [], 'status': 'running'}
    def record(message):
        report['milestones'].append(message)
        (evidence / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
        print(message, flush=True)
    accel = 'kvm' if os.access('/dev/kvm', os.R_OK | os.W_OK) else 'tcg'
    report['acceleration'] = accel
    record('Using ' + accel + '; firmware Secure Boot disabled for this test')
    if shutil.disk_usage(root).free < 18 * 1024**3:
        raise RuntimeError('Need at least 18 GiB free for disposable installation/staging')
    password = secrets.token_hex(16)
    ks = b''
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != '/test.ks':
                self.send_error(404)
                return
            self.send_response(200)
            self.end_headers()
            self.wfile.write(ks)

        def do_POST(self):
            if not allowed_evidence_path(self.path):
                self.send_error(404)
                return
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 <= length <= 32 * 1024**2:
                self.send_error(413)
                return
            data = self.rfile.read(length)
            if self.path.endswith('.png'):
                if not data.startswith(b'\x89PNG\r\n\x1a\n'):
                    self.send_error(400)
                    return
            else:
                data = data.replace(password.encode(), b'[REDACTED]')
            (evidence / self.path[1:]).write_bytes(data)
            self.send_response(200)
            self.end_headers()

        def log_message(self, *unused):
            pass
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    ks = kickstart(receipt, password, server.server_port, args.scenario).encode()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    vm = VM(root, evidence, iso, accel)
    graphical_password_pending = False
    cosmic_stages = []
    try:
        vm.start('original-iso')
        for seconds in range(1, 5):
            time.sleep(45)
            vm.screenshot('original-iso-' + str(seconds * 45))
            record('Original ISO UEFI screenshot captured at ' + str(seconds * 45) + ' seconds (requires visual review)')
        vm.stop()
        # Fresh firmware variables prevent the preceding boot changing selection.
        shutil.copyfile('/usr/share/OVMF/OVMF_VARS_4M.fd', root / 'vars.fd')
        vm.start('installation')
        # Firmware/GRUB timing varies across runners. Wait for the rendered menu
        # rather than sending keys while OVMF is still selecting the boot device.
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            vm.screenshot('grub-wait')
            try:
                screen = subprocess.check_output(
                    ['tesseract', str(evidence / 'grub-wait.png'), 'stdout'],
                    text=True, stderr=subprocess.DEVNULL, timeout=30,
                    env={**os.environ, 'OMP_THREAD_LIMIT': '1'})
            except subprocess.TimeoutExpired:
                # A busy runner can delay OCR. Keep the overall boot deadline;
                # do not mistake one slow screenshot for a firmware failure.
                continue
            (evidence / 'grub-text.log').write_text(screen)
            if 'install current' in screen.lower():
                break
            time.sleep(2)
        else:
            raise RuntimeError('UEFI did not reach the Current GRUB menu within 120 seconds')
        vm.qmp.keys('c')
        # This ISO's GRUB already exposes the firmware serial console. Do not
        # mix queued emulated keystrokes with serial commands or consume a stale
        # prompt while an earlier command is still being entered.
        vm.serial.expect('grub>', timeout=30)
        vm.screenshot('grub-command-line')
        def grub(command, timeout=60):
            vm.serial.send(command + '\r')
            vm.serial.expect('grub>', timeout=timeout)
            output = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', vm.serial.before)
            if 'error:' in output.lower():
                raise RuntimeError('GRUB rejected command: ' + output)
        grub('linux (cd0)/images/pxeboot/vmlinuz inst.stage2=hd:LABEL=Current-Installer '
                           f'inst.ks=http://10.0.2.2:{server.server_port}/test.ks inst.graphical '
                           'ip=dhcp console=tty0 console=ttyS0,115200n8 selinux=1 enforcing=0')
        grub('initrd (cd0)/images/pxeboot/initrd.img')
        vm.serial.send('boot\r')
        if vm.serial.expect(['Linux version', 'error:'], timeout=120):
            raise RuntimeError('GRUB could not start the installation kernel')
        record('Installation kernel started through original ISO UEFI GRUB with test-only Kickstart answers')
        # Keep reading serial output and preserve screenshots even on installer failure.
        deadline = time.monotonic() + (600 if args.scenario == 'reject-btrfs' else 1800)
        while time.monotonic() < deadline:
            result = vm.serial.expect(['current-vm login:', pexpect.TIMEOUT, pexpect.EOF], timeout=45)
            vm.screenshot('installation-latest')
            if (evidence / 'install-error.log').exists() or (evidence / 'storage-rejected.log').exists():
                if args.scenario == 'reject-btrfs':
                    logs = '\n'.join(path.read_text(errors='replace') for path in evidence.glob('*.log'))
                    if not re.search(r'^DEBUG:anaconda\.modules\.storage\.partitioning\.validate:Found sanity error: Current cannot install using Btrfs', logs, re.MULTILINE) or (evidence / 'install-marker.log').exists():
                        raise RuntimeError('Installer failed without proving the Btrfs policy rejection')
                    vm.stop()
                    extents = json.loads(subprocess.check_output(['qemu-img', 'map', '--output=json', str(vm.disk)], text=True))
                    (evidence / 'disk-map.json').write_text(json.dumps(extents, indent=2) + '\n')
                    if any(extent['data'] for extent in extents):
                        raise RuntimeError('Btrfs was rejected but the disposable installation disk has allocated data')
                    record('Anaconda rejected Btrfs through Current storage validation with the virtual disk entirely unallocated')
                    report['status'] = 'passed-btrfs-rejection'
                    return
                raise RuntimeError('Anaconda reported an installation error; inspect uploaded logs')
            if result == 0:
                if args.scenario == 'reject-btrfs':
                    raise RuntimeError('Btrfs rejection test unexpectedly reached installed login')
                break
            if result == 2:
                raise RuntimeError('VM serial disconnected during installation')
            print('Waiting for installed authenticated login...', flush=True)
        else:
            raise RuntimeError('Installation/login deadline exceeded; inspect Anaconda logs and screenshot')
        if not (evidence / 'install-marker.log').exists():
            raise RuntimeError('Login seen without successful Anaconda post-install evidence')
        record('Anaconda reached post-install and rebooted into an authenticated login')

        def login(bootstrap):
            console_password(vm.serial)
            vm.serial.sendline(password)
            shell_prompt = r'\[currenttest@current-vm [^\r\n]*\]\$ '
            started_setup = vm.serial.expect(['Current initial setup', shell_prompt]) == 0
            if bootstrap and not started_setup:
                raise RuntimeError('Bootstrap login did not automatically launch setup')
            if started_setup:
                vm.serial.expect(r'\[sudo\] password for currenttest:')
                vm.serial.sendline(password)
                step = vm.serial.expect(['Choose a distribution', 'Resume the previous selection?',
                                         'Destination staged:', 'Current setup is complete.'])
                if step == 1:
                    vm.serial.sendline('n')
                    vm.serial.expect('Choose a distribution')
                if step < 2:
                    vm.serial.sendline('q')
                    vm.serial.expect('Setup paused')
                vm.serial.expect(shell_prompt)
            # sudo can flush queued TTY input while returning to the shell. Wait
            # for bash, not the wizard's final message, before issuing commands.
            # Disable echo and prompt hooks; encode the first prompt character so
            # command echo cannot be mistaken for the subsequent real prompt.
            vm.serial.sendline("unset PROMPT_COMMAND; bind 'set enable-bracketed-paste off'; stty -echo; export TERM=dumb; PS1=$(printf '\\103URRENT_VM> ')")
            vm.serial.expect_exact('CURRENT_VM> ')
            vm.serial.sendline("printf 'READY\\n'")
            vm.serial.expect(r'READY\r?\n')
            vm.serial.expect_exact('CURRENT_VM> ')
            return started_setup

        def command(text, timeout=120):
            with (evidence / 'guest-commands.log').open('a') as commands:
                commands.write(text + '\n')
            vm.serial.sendline(text + "; printf '\\nVM_RC=%s\\n' \"$?\"")
            # A long pull can outlive sudo's credential cache. Reauthenticate
            # normally instead of adding a passwordless rule to the test image.
            result = vm.serial.expect([COMMAND_RC, r'\[sudo\] password for currenttest:'], timeout=timeout)
            if result:
                vm.serial.sendline(password)
                vm.serial.expect(COMMAND_RC, timeout=timeout)
            output = vm.serial.before
            if vm.serial.match.group(1) != '0':
                raise RuntimeError('Guest command failed: ' + text + '\n' + output)
            vm.serial.expect('CURRENT_VM> ')
            return output

        def request_reboot():
            # Large image pulls can expire sudo's timestamp. Authenticate through
            # the normal prompt before waiting for a reboot that never started.
            command('sudo -v')
            vm.serial.sendline('sudo systemctl reboot')

        checkpoints = []
        deferred_journals = set()
        report['journal_verification'] = {}

        def diagnostics(stage, distribution=None, verify_deferred=False):
            # Keep optional/version-dependent probes nonfatal, but retain each
            # status. Session execution and cross-boot marker retention below
            # are assertions, not an interpretation of warning text.
            probes = [
                'rpm -q systemd systemd-pam pam dracut ostree bootc; uname -r',
                'rpm -q glibc-minimal-langpack glibc-langpack-en glibc-all-langpacks; cat /etc/locale.conf; localectl status; locale -a | head -15',
                'systemctl --failed --no-pager; systemctl --user --failed --no-pager',
                'loginctl session-status --no-pager; systemctl show user@$(id -u).service -p ActiveState -p SubState -p Result -p ExecMainStatus',
                'sudo cat /etc/pam.d/systemd-user /usr/lib/pam.d/systemd-user; authselect current',
                'findmnt -R /; sudo losetup -l; sudo dmsetup info -c; lsblk -o NAME,TYPE,FSTYPE,MOUNTPOINTS',
                'sudo ls -la /run/initramfs; sudo test -x /run/initramfs/shutdown',
                'systemctl cat dracut-shutdown.service; sudo cat /usr/lib/dracut/dracut-initramfs-restore',
                # Include prior boots: restore runs in ExecStop, after the
                # preceding checkpoint, and its errors may not reach serial.
                # Bound observational history: a desktop exiting at shutdown
                # can produce thousands of repeated Wayland errors. Closed
                # archive verification and shutdown acceptance below stay full.
                'sudo journalctl -n 1000 -u dracut-shutdown.service -u systemd-journald.service -u user@$(id -u).service --no-pager',
                'sudo journalctl --header --no-pager',
                'sudo journalctl -b -p warning -n 1000 --no-pager',
                # Online verification is diagnostic only: concurrent journald
                # writes can yield false corruption (systemd issue #27532).
                'sudo journalctl --verify',
                'sudo cat /etc/containers/policy.json /etc/containers/registries.d/current-setup.yaml; sha256sum /usr/share/current/cosign.pub',
            ]
            if args.scenario == 'workstation-flow':
                probes += [
                    'rpm -q gdm gnome-shell gnome-session cosmic-greeter cosmic-session cosmic-comp greetd',
                    'cat /usr/share/current/workstation/desktop.env /usr/share/wayland-sessions/*.desktop',
                    'systemctl show current-workstation-dm-apply.service display-manager.service gdm.service cosmic-greeter.service greetd.service graphical.target -p Wants -p Requires -p After -p Before -p Conflicts -p FragmentPath -p DropInPaths',
                    'sudo ls -lR /run/systemd/generator.early; readlink -f /etc/systemd/system/display-manager.service',
                    'sudo journalctl -b -u current-workstation-dm-apply.service -u gdm.service -u cosmic-greeter.service -u cosmic-greeter-daemon.service --no-pager',
                ]
            with (evidence / (stage + '-diagnostics.log')).open('w') as output:
                for probe in probes:
                    output.write('$ ' + probe + '\n')
                    output.write(command('(' + probe + "); rc=$?; printf '\\nPROBE_RC=%s\\n' \"$rc\"; true", timeout=180))
                if args.expect_locale:
                    program = ('import locale, shlex\nfrom pathlib import Path\n'
                               'values=dict(item.split("=",1) for item in shlex.split(Path("/etc/locale.conf").read_text(), comments=True) if "=" in item)\n'
                               f'assert values.get("LANG")=={args.expect_locale!r}, values\n'
                               f'locale.setlocale(locale.LC_ALL, {args.expect_locale!r})\n'
                               f'print("LOCALE_QUALIFIED="+{args.expect_locale!r})\n')
                    output.write(command('python3 -c ' + shlex.quote(program)))
                if args.require_clean_avahi:
                    name = stage + '-avahi-startup.log'
                    command('sudo python3 ~/.local/bin/current-vm-workstation-health --avahi-only > ~/current-vm-avahi.json && curl -fsS --max-time 30 --data-binary @"$HOME/current-vm-avahi.json" http://10.0.2.2:' + str(server.server_port) + '/' + name)
                    report.setdefault('avahi_startup', {})[stage] = name
                command('systemctl is-active user@$(id -u).service && systemctl --user is-active default.target && systemd-run --user --wait --pipe /usr/bin/true')
                command('logger -t current-vm-checkpoint ' + stage)
                checkpoints.append(stage)
                # Rotate, never vacuum or rewrite. All records up to this
                # checkpoint are now in closed persistent archives. Exclude
                # newly opened active files from structural verification.
                command('sudo journalctl --sync')
                command('sudo journalctl --rotate')
                archives = "--file='/var/log/journal/*/*@*.journal*'"
                output.write('$ sudo journalctl --header ' + archives + '\n')
                output.write(command('sudo journalctl --header --no-pager ' + archives))
                output.write('$ sudo journalctl --verify ' + archives + '\n')
                # Kernel audit messages can split serial output mid-word. Send
                # closed-file verification through the existing evidence HTTP
                # collector so machine assertions see the unchanged bytes.
                verification_path = evidence / (stage + '-archive-verification.log')
                command('(sudo journalctl --verify ' + archives + '; rc=$?; printf \'\\nVERIFY_RC=%s\\n\' "$rc") > ~/current-vm-archive-verification.log 2>&1; curl -fsS --max-time 30 --data-binary @"$HOME/current-vm-archive-verification.log" http://10.0.2.2:' + str(server.server_port) + '/' + verification_path.name, timeout=180)
                verification = verification_path.read_text()
                output.write(verification)
                result = journal_verification(verification, (distribution or args.distribution) == 'alma9' and stage != 'bootstrap')
                report['journal_verification'][stage] = result
                deferred_journals.update(result['deferred'])
                if (verify_deferred or (stage == 'rollback' and args.scenario not in ('workstation-flow', 'rebase-flow'))) and not deferred_journals.issubset(result['passed']):
                    raise RuntimeError('Rollback did not verify every deferred journal archive')
            marker_path = evidence / (stage + '-markers.log')
            command('sudo journalctl -q -t current-vm-checkpoint -o cat --no-pager ' + archives + ' > ~/current-vm-markers.log && curl -fsS --max-time 30 --data-binary @"$HOME/current-vm-markers.log" http://10.0.2.2:' + str(server.server_port) + '/' + marker_path.name)
            markers = marker_path.read_text()
            if not set(checkpoints).issubset(set(terminal_text(markers).splitlines())):
                raise RuntimeError('Persistent journal lost checkpoint markers at ' + stage)
            record(stage + ': user manager, transient user service and persistent journal markers passed; diagnostics captured')

        def put_guest(path, content, executable=False):
            encoded = base64.b64encode(content.encode()).decode()
            command('printf %s ' + shlex.quote(encoded) + ' | base64 -d > ' + path)
            if executable:
                command('chmod 700 ' + path)

        def graphical_diagnostics(stage):
            output = command("loginctl list-sessions --no-pager; sudo journalctl -b --no-pager -u gdm.service -u cosmic-greeter.service -u cosmic-greeter-daemon.service; sudo journalctl -b --no-pager -g 'gdm-password|authentication|avc:|session opened'; sudo ausearch -m AVC,USER_AVC -ts boot -i; sudo ls -ldZ /etc/passwd /etc/shadow /etc/.pwd.lock /var/lib/AccountsService/users /var/home/currenttest; true")
            (evidence / (stage + '-authentication.log')).write_text(output)
            labels = command("getent passwd currenttest avahi linuxbrew; getent group avahi linuxbrew; grep -E '^(passwd|group):' /etc/nsswitch.conf; sudo matchpathcon /var/home/currenttest /var/home/currenttest/.local/share/icc /etc/.pwd.lock; systemctl cat brew-setup.service avahi-daemon.service; sudo journalctl -b --no-pager -u brew-setup.service -u avahi-daemon.service; sudo restorecon -nv /var/home/currenttest; if test -d /var/home/currenttest/.local/share/icc; then sudo restorecon -nRv /var/home/currenttest/.local/share/icc; fi; true", timeout=180)
            (evidence / (stage + '-label-account-audit.log')).write_text(labels)
            resolver = command("rpm -q avahi avahi-tools nss-mdns NetworkManager systemd-resolved; grep -E '^(hosts|passwd|group):' /etc/nsswitch.conf; ls -l /etc/resolv.conf; readlink -f /etc/resolv.conf; cat /etc/resolv.conf; nmcli general status; nmcli -g IP4.DNS,IP6.DNS device show; systemctl is-enabled NetworkManager-wait-online.service; systemctl show avahi-daemon.service NetworkManager.service NetworkManager-wait-online.service network-online.target -p After -p Wants -p ActiveEnterTimestampMonotonic -p ExecMainStartTimestampMonotonic; sudo journalctl -b -u avahi-daemon.service -u NetworkManager.service -u NetworkManager-wait-online.service --no-pager -n 500; true")
            (evidence / (stage + '-resolver-diagnostics.log')).write_text(resolver)

        def control_ocr(name):
            # Full-frame OCR reads white prompt titles. Cropped control interiors
            # keep rounded cyan borders from hiding their small black labels.
            # Both readings come from the same unchanged QMP screenshot.
            from PIL import Image
            path = evidence / (name + '.png')
            def read(image, psm):
                return subprocess.check_output(['tesseract', str(image), 'stdout', '--psm', str(psm), 'tsv'], text=True, stderr=subprocess.DEVNULL, timeout=30, env={**os.environ, 'OMP_THREAD_LIMIT': '1'})
            rows = [line.split('\t') for line in read(path, 11).splitlines()]
            image = Image.open(path).convert('RGB')
            pixels = image.load()
            for index, box in enumerate(accent_footer_regions(image.width, image.height, lambda x, y: pixels[x, y])):
                crop = image.crop(box).convert('L')
                crop = crop.resize((crop.width * 3, crop.height * 3))
                derived = evidence / (name + '-ocr-button-' + str(index) + '.png')
                crop.save(derived)
                for line in read(derived, 7).splitlines()[1:]:
                    fields = line.split('\t')
                    if len(fields) != 12 or fields[0] != '5':
                        continue
                    x, y, w, h = map(int, fields[6:10])
                    fields[6:10] = map(str, (box[0] + x // 3, box[1] + y // 3, (w + 2) // 3, (h + 2) // 3))
                    duplicate = next((row for row in rows if len(row) == 12 and row[0] == '5'
                                      and row[11].lower() == fields[11].lower()
                                      and abs(int(row[6]) - int(fields[6])) <= 8
                                      and abs(int(row[7]) - int(fields[7])) <= 8), None)
                    if duplicate is None:
                        rows.append(fields)
                    elif float(fields[10]) > float(duplicate[10]):
                        duplicate[:] = fields
            text = '\n'.join('\t'.join(row) for row in rows) + '\n'
            (evidence / (name + '.tsv')).write_text(text)
            return text

        def cosmic_onboarding(stage):
            nonlocal graphical_password_pending
            # Exercise the actual first-run UI, including its own completion
            # marker. Never create that marker, mask autostart, or delete user
            # preferences to make shutdown quieter.
            from PIL import Image
            actions = []
            entry = {'stage': stage, 'actions': actions, 'completed': False}
            report.setdefault('cosmic_onboarding', []).append(entry)
            timezone_searched = False
            timezone_authenticated = False
            for attempt in range(24):
                state = command("printf '\\nONBOARDING_DONE=%s\\n' \"$(if test -f ~/.config/cosmic-initial-setup-done; then printf 1; else printf 0; fi)\"")
                if re.search(r'^ONBOARDING_DONE=1\r?$', terminal_text(state), re.MULTILINE):
                    command("(for attempt in $(seq 1 20); do if ! pgrep -u $(id -u) -f '^(/usr/bin/)?cosmic-initial-setup($| )' >/dev/null; then exit 0; fi; sleep 1; done; exit 1)")
                    if timezone_searched:
                        command('test "$(timedatectl show -p Timezone --value)" = Africa/Dakar')
                    entry['completed'] = True
                    (evidence / (stage + '-first-run-journal.log')).write_text(command('sudo journalctl -b _UID=$(id -u) --no-pager -n 1000; timedatectl status'))
                    record(stage + ': COSMIC first-run completion marker and process exit passed after real UI interaction')
                    return
                name = stage + '-first-run-' + str(attempt)
                vm.screenshot(name)
                tsv = control_ocr(name)
                width, height = Image.open(evidence / (name + '.png')).size
                # A real polkit dialog can cover this page while its Next
                # button remains clickable behind it. Complete authentication
                # before advancing; never count that obscured UI as a pass.
                screen_text = ' '.join(line.split('\t')[-1] for line in tsv.splitlines()[1:])
                if re.search(r'authentication\s+required', screen_text, re.IGNORECASE):
                    field = visible_control(tsv, width, height, labels=('password',),
                                            required_phrase='Authentication is required to set system timezone', minimum_y=0)
                    if not timezone_searched or timezone_authenticated or not field:
                        raise RuntimeError('Unexpected authentication dialog during COSMIC onboarding; no password entered')
                    _, x, y = field
                    vm.qmp.click(x, y, width, height)
                    graphical_password_pending = True
                    vm.qmp.keys(password + '\n', delay=.1)
                    command('(for attempt in $(seq 1 20); do if test "$(timedatectl show -p Timezone --value)" = Africa/Dakar; then exit 0; fi; sleep 1; done; exit 1)')
                    graphical_password_pending = False
                    timezone_authenticated = True
                    actions.append({'screenshot': name + '.png', 'authentication': 'native timezone polkit dialog', 'timezone_verified': 'Africa/Dakar'})
                    time.sleep(3)
                    continue
                search = visible_control(tsv, width, height, labels=('closest',), required_phrase='Timezone and location', minimum_y=0)
                if search and not timezone_searched:
                    _, x, y = search
                    vm.qmp.click(x, y, width, height)
                    # A real native city choice; Dakar observes UTC year-round,
                    # matching this disposable install's UTC time preference.
                    vm.qmp.keys('Dakar\n')
                    actions.append({'screenshot': name + '.png', 'field': 'timezone', 'search': 'Dakar', 'selection': 'native first search result via Enter'})
                    timezone_searched = True
                    time.sleep(3)
                    continue
                # The guest has verified wired networking and no virtual Wi-Fi.
                # Use the native optional page's explicit Skip control when it
                # reports no networks; do not manufacture connectivity or state.
                button = visible_control(tsv, width, height, labels=('skip',), required_phrase='No networks have been found')
                if not button:
                    button = visible_control(tsv, width, height)
                if button:
                    label, x, y = button
                    vm.qmp.click(x, y, width, height)
                    actions.append({'screenshot': name + '.png', 'button': label, 'x': x, 'y': y})
                time.sleep(3)
            (evidence / (stage + '-first-run-journal.log')).write_text(command('sudo journalctl -b _UID=$(id -u) --no-pager -n 1000'))
            raise RuntimeError('COSMIC first-run UI did not complete; inspect retained pages/controls and native journal; no marker was manufactured')

        def cosmic_rendering(stage, phase):
            # Keep the original software GPU and resolution. Capture more than
            # one QMP frame, plus a native portal image as a second capture path.
            # Consent uses the real GUI; no display variables are manufactured.
            stage = stage + '-' + phase
            # A repaired parser must keep the native keyboard alive, not merely
            # replace its startup panic with a silent unsuccessful exit.
            command('if test -f /usr/share/current/cosmic-repairs/cosmic-osk.json; then test "$(pgrep -u $(id -u) -x cosmic-osk | wc -l)" = 1; fi')
            diagnostics = command("rpm -q iso-codes cosmic-initial-setup cosmic-comp cosmic-panel cosmic-session cosmic-osk cosmic-screenshot xdg-desktop-portal-cosmic libxkbcommon mesa-dri-drivers mesa-libEGL mesa-vulkan-drivers; if test -d /usr/share/current/cosmic-repairs; then cat /usr/share/current/cosmic-repairs/*.json; fi; locale; localectl status; lspci -nnk; ls -l /dev/dri /sys/class/drm; systemctl --user show-environment | grep -E '^(LANG|LANGUAGE|LC_ALL|DISPLAY|WAYLAND_DISPLAY|XDG_CURRENT_DESKTOP|XDG_SESSION_TYPE|XDG_DATA_DIRS)='; systemd-run --user --wait --pipe cosmic-randr list; systemctl --user list-units --all --no-pager '*CosmicInitialSetup*'; systemctl --user show org.freedesktop.impl.portal.desktop.cosmic.service -p ActiveState -p Result -p ExecMainCode -p ExecMainStatus -p NRestarts; cosmic-screenshot --help; true")
            (evidence / (stage + '-rendering-diagnostics.log')).write_text(diagnostics)
            for index in range(3):
                time.sleep(3)
                vm.screenshot(stage + '-render-' + str(index))
            directory = '/var/home/currenttest/current-vm-portal-' + stage
            prefix = directory
            program = 'cosmic-screenshot --interactive=false --modal=false --notify=false --save-dir ' + directory + ' > ' + prefix + '.log 2>&1; rc=$?; printf "%s\\n" "$rc" > ' + prefix + '.rc; exit "$rc"'
            command('mkdir -p ' + directory + '; systemd-run --user --no-block --collect --property=RuntimeMaxSec=60s /bin/bash -c ' + shlex.quote(program))
            consent = []
            for attempt in range(20):
                state = graphical_result(command("printf 'SESSION_RESULT=%s\\n' \"$(if test -f " + prefix + ".rc; then cat " + prefix + ".rc; else printf pending; fi)\""))
                if state is not None:
                    break
                name = stage + '-portal-consent-' + str(attempt)
                vm.screenshot(name)
                tsv = control_ocr(name)
                from PIL import Image
                width, height = Image.open(evidence / (name + '.png')).size
                button = visible_control(tsv, width, height, labels=('allow',), required_phrase=('Allow Apps to Take Screenshots', 'Allow Applications to Take Screenshots'))
                if button:
                    label, x, y = button
                    vm.qmp.click(x, y, width, height)
                    consent.append({'screenshot': name + '.png', 'button': label, 'x': x, 'y': y})
                time.sleep(3)
            else:
                raise RuntimeError('Native screenshot request did not finish; inspect portal consent; onboarding was not tested past this obstacle')
            capture = command('cat ' + prefix + '.log; printf "\\nPORTAL_RC=%s\\n" "$(cat ' + prefix + '.rc)"; if test "$(cat ' + prefix + '.rc)" = 0; then image=$(find ' + directory + ' -maxdepth 1 -type f -name "*.png" -print -quit); if test -n "$image"; then curl -fsS --max-time 30 --data-binary @"$image" http://10.0.2.2:' + str(server.server_port) + '/' + stage + '-portal.png; fi; fi; true', timeout=120)
            (evidence / (stage + '-portal-capture.log')).write_text(capture)
            report.setdefault('rendering_captures', []).append({'stage': stage, 'qmp_frames': [stage + '-render-' + str(i) + '.png' for i in range(3)], 'native_portal': (evidence / (stage + '-portal.png')).is_file(), 'portal_returncode': state, 'consent': consent})
            if state != 0 or not (evidence / (stage + '-portal.png')).is_file():
                raise RuntimeError('Native screenshot failed; rendering remains unqualified and onboarding was not tested past this capture obstacle')

        def workstation_health(stage, desktop, before=False):
            options = (' --require-mdns' if args.require_mdns else '') + (' --require-icc' if desktop == 'gnome' else '')
            name = stage + ('-before' if before else '') + '-workstation-health.log'
            command('sudo python3 ~/.local/bin/current-vm-workstation-health' + options + ' > ~/current-vm-workstation-health.json && curl -fsS --max-time 30 --data-binary @"$HOME/current-vm-workstation-health.json" http://10.0.2.2:' + str(server.server_port) + '/' + name)

        def graphical_login(stage, desktop):
            nonlocal graphical_password_pending
            if desktop == 'cosmic':
                identity = command('printf "\\nCOSMIC_BOOT_ID=%s\\n" "$(cat /proc/sys/kernel/random/boot_id)"')
                report.setdefault('cosmic_boot_ids', {})[stage] = cosmic_boot_id(identity)
                cosmic_stages.append(stage)
            from PIL import Image
            command('printf %s ' + shlex.quote(stage) + ' > ~/current-vm-stage')
            ownership = command('bash ~/.local/bin/current-vm-qualify-workstation --system-only')
            (evidence / (stage + '-ownership.log')).write_text(ownership)
            command('loginctl seat-status seat0 --no-pager; sudo journalctl -b -u display-manager.service --no-pager')
            deadline = time.monotonic() + 180
            words = []
            while time.monotonic() < deadline:
                vm.screenshot(stage + '-greeter')
                screen = subprocess.check_output(['tesseract', str(evidence / (stage + '-greeter.png')), 'stdout', 'tsv'], text=True, stderr=subprocess.DEVNULL, timeout=30, env={**os.environ, 'OMP_THREAD_LIMIT': '1'})
                (evidence / (stage + '-greeter-ocr.log')).write_text(screen)
                words = [line.split('\t') for line in screen.splitlines()[1:] if len(line.split('\t')) == 12]
                if any(w[11].lower().strip(':') in ('currenttest', 'password') for w in words):
                    break
                time.sleep(5)
            else:
                raise RuntimeError('No recognizable ' + desktop + ' greeter; inspect screenshot and manager journal')
            if desktop == 'gnome':
                user = next((w for w in words if w[11].lower() == 'currenttest'), None)
                if user:
                    width, height = Image.open(evidence / (stage + '-greeter.png')).size
                    vm.qmp.click(int(user[6]) + int(user[8]) // 2, int(user[7]) + int(user[9]) // 2, width, height)
                else:
                    vm.qmp.keys('\n')
                # Confirm the password screen before typing a secret. A first
                # pointer event can focus the user tile without activating it.
                time.sleep(3)
                for attempt in range(12):
                    vm.screenshot(stage + '-password-prompt')
                    prompt = subprocess.check_output(['tesseract', str(evidence / (stage + '-password-prompt.png')), 'stdout', 'tsv'], text=True, stderr=subprocess.DEVNULL, timeout=30, env={**os.environ, 'OMP_THREAD_LIMIT': '1'})
                    fields = [line.split('\t') for line in prompt.splitlines()[1:] if len(line.split('\t')) == 12]
                    field = next((w for w in fields if w[11].lower().strip(':') == 'password'), None)
                    if field:
                        # The prompt can appear while GDM still initializes PAM.
                        # Focus the actual entry and allow that initialization
                        # to settle before sending a deliberately paced password.
                        time.sleep(5)
                        width, height = Image.open(evidence / (stage + '-password-prompt.png')).size
                        vm.qmp.click(int(field[6]) + int(field[8]) // 2, int(field[7]) + int(field[9]) // 2, width, height)
                        time.sleep(1)
                        break
                    if attempt == 0:
                        vm.qmp.keys('\n')
                    time.sleep(2)
                else:
                    raise RuntimeError('GNOME password field did not appear; no password entered')
            graphical_password_pending = True
            vm.qmp.keys(password + '\n', delay=.1)
            deadline = time.monotonic() + 240
            while time.monotonic() < deadline:
                output = graphical_result(command("printf 'SESSION_RESULT=%s\\n' \"$(if test -f ~/current-vm-session-" + stage + ".rc; then cat ~/current-vm-session-" + stage + ".rc; else printf pending; fi)\""))
                if output is not None:
                    proof = command('cat ~/current-vm-session-' + stage + '.log')
                    (evidence / (stage + '-graphical-session.log')).write_text(proof)
                    graphical_password_pending = False
                    graphical_diagnostics(stage)
                    time.sleep(10)
                    vm.screenshot(stage + '-session')
                    if output != 0:
                        raise RuntimeError('Graphical session qualification failed: ' + proof)
                    if ('DESKTOP=' + desktop.upper()) not in proof.upper():
                        raise RuntimeError('Autostart reported the wrong desktop')
                    if args.expect_locale and not re.search(r'^LANG=' + re.escape(args.expect_locale) + r'\r?$', terminal_text(proof), re.MULTILINE):
                        raise RuntimeError('Graphical session did not retain the installer locale')
                    command('sudo systemctl start avahi-daemon.service')
                    if desktop == 'cosmic':
                        (evidence / (stage + '-session.png')).rename(evidence / (stage + '-session-initial.png'))
                        workstation_health(stage, desktop, before=True)
                        cosmic_rendering(stage, 'before')
                        cosmic_onboarding(stage)
                        cosmic_rendering(stage, 'after')
                        vm.screenshot(stage + '-session')
                    workstation_health(stage, desktop)
                    brew = command('/var/home/linuxbrew/.linuxbrew/bin/brew --version')
                    (evidence / (stage + '-brew-version.log')).write_text(brew)
                    if stage == 'source':
                        command('printf retained-brew-data > /var/home/linuxbrew/.linuxbrew/current-vm-sentinel')
                    else:
                        command('test "$(cat /var/home/linuxbrew/.linuxbrew/current-vm-sentinel)" = retained-brew-data')
                    report.setdefault('graphical_logins', []).append({'stage': stage, 'desktop': desktop, 'proof': stage + '-graphical-session.log', 'health_proof': stage + '-workstation-health.log'})
                    record(stage + ': real greeter password login and desktop-session ownership checks passed')
                    if stage == 'source' and os.environ.get('GITHUB_ACTIONS') == 'true':
                        print('::notice title=Current workstation source health::Source health passed: '
                              + args.distribution + ' ' + desktop
                              + '; destination reboot and rollback remain pending', flush=True)
                    return
                time.sleep(5)
            graphical_diagnostics(stage)
            raise RuntimeError('No graphical autostart proof after password login; inspect greeter/session evidence')

        def booted(stage):
            document = bootc_document(command('sudo bootc status --json'))
            slot = document['status']['booted']['image']
            if stage not in ('bootstrap', 'recovery-bootstrap') and slot['image'].get('signature') != 'containerPolicy':
                raise RuntimeError('Booted destination lacks enforced signature policy')
            report.setdefault('booted_images', {})[stage] = slot
            return slot

        def retained():
            command('test "$(getenforce)" = Enforcing && test "$(findmnt -n -o FSTYPE /sysroot)" = xfs && test "$(cat ~/current-sentinel)" = retained-user-data && test "$(id -u)" = "$(cat ~/current-original-uid)" && sudo sha256sum -c ~/current-network-hashes && systemctl is-active NetworkManager')
            command('code=$(curl -sS --max-time 30 -o /dev/null -w "%{http_code}" https://ghcr.io/v2/) && { test "$code" = 401 || test "$code" = 200; }')

        def reboot_to(stage, distribution, expected, desktop=None):
            request_reboot()
            vm.serial.expect('current-vm login:', timeout=600)
            login(False)
            command('sudo -v')
            (evidence / (stage + '-finalization.log')).write_text(command('sudo journalctl -b -1 -u ostree-finalize-staged.service --no-pager'))
            slot = booted(stage)
            if slot['imageDigest'] != expected['imageDigest']:
                raise RuntimeError('Unexpected booted image at ' + stage + ': ' + json.dumps(slot))
            retained()
            diagnostics(stage, distribution)
            if desktop:
                graphical_login(stage, desktop)

        login(True)
        vm.serial.logfile_read.flush()
        # Exclude the installer environment's own shutdown from installed-OS
        # qualification. Retain the complete original log as evidence.
        shutdown_start = (evidence / 'installation-serial.log').stat().st_size
        record('Authenticated wheel login automatically launched setup; q safely paused it')
        command('findmnt; getent passwd currenttest; cat /etc/fstab; ls -ld /home /var/home "$HOME"; test -d "$HOME" && test -w "$HOME"')
        command('systemctl show systemd-remount-fs.service -p Result; cat /proc/cmdline; getenforce')
        command('test "$(getenforce)" = Enforcing')
        command('test "$(findmnt -n -o FSTYPE /sysroot)" = xfs')
        command('sudo python3 -c \'import subprocess; reports = [subprocess.check_output(["xfs_info", mount], text=True) for mount in ("/sysroot", "/boot")]; print("".join(reports)); assert all("parent=0" in r and "exchange=0" in r for r in reports)\'')
        # Check older destination repair tools against the bootstrap formatter's
        # feature profile, on an unmounted disposable regular file only.
        command('sudo truncate -s 512M /var/tmp/current-xfs-repair.img && sudo mkfs.xfs -f -nparent=0 -iexchange=0 /var/tmp/current-xfs-repair.img')
        command('test -d /sys/firmware/efi && id && nmcli -t -f STATE general && systemctl is-active NetworkManager')
        command("printf 'retained-user-data\\n' > ~/current-sentinel; sha256sum ~/current-sentinel")
        command('mkdir -p ~/.local/bin')
        put_guest('~/.local/bin/current-vm-workstation-health', Path('scripts/qualify-workstation-health.py').read_text())
        command('sudo python3 ~/.local/bin/current-vm-workstation-health --installer-diagnostics > ~/current-vm-installer-accounts.log && curl -fsS --max-time 30 --data-binary @"$HOME/current-vm-installer-accounts.log" http://10.0.2.2:' + str(server.server_port) + '/installer-account-diagnostics.log')
        command('sudo python3 ~/.local/bin/current-vm-workstation-health --labels-only > ~/current-vm-bootstrap-labels.json && curl -fsS --max-time 30 --data-binary @"$HOME/current-vm-bootstrap-labels.json" http://10.0.2.2:' + str(server.server_port) + '/bootstrap-account-labels.log')
        command('id -u > ~/current-original-uid; sudo sh -c \'sha256sum /etc/NetworkManager/system-connections/*\' > ~/current-network-hashes')
        # Test-only persistent journal retains shutdown-time finalization errors.
        command('sudo mkdir -p /var/log/journal && sudo systemd-tmpfiles --create --prefix /var/log/journal && sudo journalctl --flush')
        diagnostics('bootstrap')
        if args.scenario == 'bootstrap-reboot':
            request_reboot()
            vm.serial.expect('current-vm login:', timeout=600)
            login(True)
            diagnostics('bootstrap-reboot')
            command('test -e /usr/share/current/bootstrap && test "$(getenforce)" = Enforcing && test "$(cat ~/current-sentinel)" = retained-user-data && sudo sha256sum -c ~/current-network-hashes')
            vm.serial.logfile_read.flush()
            serial = (evidence / 'installation-serial.log').read_bytes()[shutdown_start:].decode('utf-8', errors='replace')
            report['shutdown'] = shutdown_summary(serial, 1)
            if not report['shutdown']['passed']:
                raise RuntimeError('Bootstrap shutdown teardown failed qualification')
            record('Bootstrap reboot passed shutdown, journal, authenticated setup resume and retained network checks; no destination was staged')
            report['status'] = 'passed-bootstrap-reboot'
            return
        bootstrap_image = booted('bootstrap')
        if args.scenario == 'workstation-flow':
            command('mkdir -p ~/.local/bin ~/.config/autostart')
            put_guest('~/.local/bin/current-vm-qualify-workstation', Path('scripts/qualify-workstation-boot.sh').read_text(), True)
            put_guest('~/.local/bin/current-vm-session', session_probe(), True)
            put_guest('~/.config/autostart/current-vm-session.desktop', '[Desktop Entry]\nType=Application\nName=Current VM qualification\nExec=/home/currenttest/.local/bin/current-vm-session\n')
        command('rpm -q ostree bootc selinux-policy-targeted policycoreutils libsemanage; sudo semodule -lfull; sudo ls -ldZ /etc/selinux /var/lib/selinux; sudo bootc status --json')
        command('systemctl cat ostree-finalize-staged.service; systemctl show ostree-finalize-staged.service -p Environment')
        vm.serial.sendline('sudo current setup --channel ' + args.channel)
        vm.serial.expect('Choose a distribution')
        vm.serial.sendline({'alma10': '1', 'fedora': '2', 'alma9': '3'}[args.distribution])
        vm.serial.expect('Choose a system type')
        vm.serial.sendline('2' if args.scenario == 'workstation-flow' else '1')
        if args.scenario == 'workstation-flow':
            vm.serial.expect('Choose a desktop')
            vm.serial.sendline('1' if args.desktop == 'gnome' else '2')
        vm.serial.expect('Choose a different compatible image?')
        vm.serial.sendline('n')
        vm.serial.expect('Accept these experimental limitations and stage this image?')
        vm.qmp.call('set_link', name='nic0', up=False)
        vm.serial.sendline('y')
        vm.serial.expect('Setup failed:', timeout=120)
        vm.serial.expect('Retry this selection without repeating the questionnaire?', timeout=60)
        record('Disconnected virtual NIC caused a recoverable registry failure and offered retry')
        vm.qmp.call('set_link', name='nic0', up=True)
        time.sleep(10)
        vm.serial.sendline('y')
        outcome = vm.serial.expect(['Validated destination staged:', 'Setup failed:'], timeout=2400)
        if outcome:
            vm.serial.expect('Retry this selection without repeating the questionnaire?', timeout=60)
            vm.serial.sendline('n')
            vm.serial.expect('CURRENT_VM> ')
            command('sudo current setup status; sudo bootc status --json')
            raise RuntimeError('Real destination validation/staging failed; recovery receipt captured')
        vm.serial.expect('CURRENT_VM> ')
        command('sudo current setup status; sudo bootc status --json')
        record('Real wizard staged a signature-enforced destination; completion still pending')
        request_reboot()
        vm.serial.expect('current-vm login:', timeout=600)
        returned_to_bootstrap = login(False)
        if returned_to_bootstrap:
            command('sudo bootc status --json; sudo current setup reconcile; sudo systemctl --failed --no-pager; sudo journalctl -b -1 -u ostree-finalize-staged.service --no-pager; sudo journalctl -b -u ostree-boot-complete.service --no-pager; sudo sh -c \'cat /boot/loader/entries/*.conf\'; true')
            raise RuntimeError('Staged destination did not boot; bootstrap remains accessible and finalization diagnostics were captured')
        # Refresh sudo through normal password authentication; never install a bypass.
        vm.serial.sendline('sudo -v')
        vm.serial.expect(r'\[sudo\] password for currenttest:')
        vm.serial.sendline(password)
        vm.serial.expect('CURRENT_VM> ')
        command('test ! -e /usr/share/current/bootstrap && cat /usr/lib/os-release && sudo bootc status --json')
        command('sudo journalctl -b -1 -u ostree-finalize-staged.service --no-pager')
        diagnostics('destination')
        command('test -e /usr/lib/systemd/system/ostree-finalize-staged.service.d/10-current-target-path.conf && test ! -e /etc/systemd/system/ostree-finalize-staged.service.d/10-current-target-path.conf')
        command('getenforce; test "$(getenforce)" = Enforcing')
        command('rpm -q xfsprogs; sudo xfs_info /sysroot; sudo xfs_info /boot')
        command('sudo xfs_repair -n -f /var/tmp/current-xfs-repair.img && sudo rm /var/tmp/current-xfs-repair.img')
        command('test "$(cat ~/current-sentinel)" = retained-user-data && test "$(id -u)" = "$(cat ~/current-original-uid)" && sudo sha256sum -c ~/current-network-hashes && systemctl is-active NetworkManager')
        command('code=$(curl -sS -o /dev/null -w "%{http_code}" https://ghcr.io/v2/) && { test "$code" = 401 || test "$code" = 200; }')
        command("command -v current; ls -ld /usr/local /usr/local/bin /usr/local/bin/current /usr/bin/current; sudo sh -c 'printf \"sudo PATH=%s\\n\" \"$PATH\"; command -v current'; true")
        command('sudo python3 -c ' + shlex.quote("import json; s=json.load(open('/var/lib/current/setup/state.json')); assert s['revision']==" + repr(args.image_revision)))
        source_image = booted('source')
        if args.scenario == 'workstation-flow':
            graphical_login('source', args.desktop)
        command('sudo current setup status')
        vm.serial.sendline('sudo current setup')
        vm.serial.expect('The selected image is booted.')
        vm.serial.expect('Have networking and your intended login/session worked?')
        vm.serial.sendline('y')
        vm.serial.expect('Current setup is complete.')
        vm.serial.expect('CURRENT_VM> ')
        command('sudo current setup status; sudo current setup')
        record('Destination boot, retained login/user data/network, explicit completion and completed resume passed')
        if args.scenario in ('workstation-flow', 'rebase-flow'):
            target_distribution = args.target_distribution or args.distribution
            target_desktop = workstation_target(args.distribution, args.desktop, args.target_distribution,
                                                args.target_desktop) if args.scenario == 'workstation-flow' else None
            program = rebase_program(target_distribution, target_desktop or 'server', args.target_channel or args.channel, args.image_revision)
            (evidence / 'rebase-program.py').write_text(program)
            put_guest('~/current-vm-rebase.py', program)
            staged = command('sudo env PYTHONPATH=/usr/lib python3 ~/current-vm-rebase.py', timeout=3600)
            (evidence / 'rebase-staging.log').write_text(staged)
            target = staged_rebase(staged)
            report['rebase_target'] = target
            expected = {'imageDigest': target['digest']}
            reboot_to('rebase-target', target_distribution, expected, target_desktop)
            reboot_to('rebase-target-reboot', target_distribution, expected, target_desktop)
            command('sudo bootc rollback')
            reboot_to('rebase-rollback', args.distribution, source_image, args.desktop if args.scenario == 'workstation-flow' else None)
            record('Rebase, ordinary target reboot and exact source rollback retained account/data/network and enforcing SELinux')
            # A final Fedora reader verifies archives produced across older/newer
            # systemd versions, after source rollback was already qualified.
            command('sudo bootc switch --enforce-container-sigpolicy --retain ' + shlex.quote(receipt['payload']), timeout=1800)
            reboot_to('recovery-bootstrap', 'fedora', bootstrap_image)
            diagnostics('journal-final', 'fedora', verify_deferred=True)
            # Read with the original bootstrap's newer systemd. An EL9 reader
            # cannot reliably read every Fedora journal format. Exact native
            # boot IDs select complete sessions including shutdown, without
            # replayed diagnostic history or a bounded tail hiding failures.
            for completed_stage in cosmic_stages:
                name = completed_stage + '-cosmic-shutdown.log'
                # Preserve long native messages; journalctl otherwise replaces
                # large JSON values with null. Keep core metadata, not memory
                # blobs or process environments, in the bounded evidence upload.
                boot_id = report['cosmic_boot_ids'][completed_stage]
                command('sudo journalctl --boot=' + boot_id + ' --all --no-pager -o json --output-fields=MESSAGE,_BOOT_ID,__REALTIME_TIMESTAMP,SYSLOG_IDENTIFIER,_EXE,_PID,_UID,_COMM,PRIORITY,_SYSTEMD_USER_UNIT,COREDUMP_EXE,COREDUMP_UID,COREDUMP_SIGNAL,COREDUMP_FILENAME _UID=$(id -u) + COREDUMP_UID=$(id -u) > ~/current-vm-cosmic-shutdown.json && curl -fsS --max-time 30 --data-binary @"$HOME/current-vm-cosmic-shutdown.json" http://10.0.2.2:' + str(server.server_port) + '/' + name)
                summary = cosmic_shutdown_summary((evidence / name).read_text())
                if summary['boot_id'] != boot_id:
                    raise RuntimeError('Collected COSMIC journal differs from the authenticated boot identity')
                report.setdefault('cosmic_shutdown', {})[completed_stage] = dict(summary, journal=name)
            if any(not summary['passed'] for summary in report.get('cosmic_shutdown', {}).values()):
                raise RuntimeError('Native COSMIC panic or coredump in a completed session boot; inspect cosmic-shutdown journals')
            vm.serial.logfile_read.flush()
            serial = (evidence / 'installation-serial.log').read_bytes()[shutdown_start:].decode('utf-8', errors='replace')
            report['shutdown'] = shutdown_summary(serial, 5)
            if not report['shutdown']['passed']:
                raise RuntimeError('Rebase flow failed shutdown teardown qualification')
            report['status'] = 'passed-' + args.scenario
            record('All rebase shutdowns passed; original bootstrap verified every deferred journal archive after rollback')
            return
        if args.distribution == 'alma9':
            # Separate ordinary Alma 9 shutdown from a cross-version rebase.
            request_reboot()
            vm.serial.expect('current-vm login:', timeout=600)
            if login(False):
                raise RuntimeError('Ordinary destination reboot unexpectedly returned to bootstrap')
            command('sudo -v')
            diagnostics('destination-reboot')
            command('sudo current setup; test ! -e /usr/share/current/bootstrap && test "$(getenforce)" = Enforcing')
        command('sudo bootc rollback')
        request_reboot()
        vm.serial.expect('current-vm login:', timeout=600)
        login(True)
        diagnostics('rollback')
        command('sudo bootc status --json; sudo current setup status')
        vm.screenshot('rollback')
        record('Bootc rollback returned to bootstrap and preserved authenticated login; inspect completed-state semantics')
        vm.serial.logfile_read.flush()
        serial = (evidence / 'installation-serial.log').read_bytes()[shutdown_start:].decode('utf-8', errors='replace')
        report['shutdown'] = shutdown_summary(serial, 3 if args.distribution == 'alma9' else 2)
        if not report['shutdown']['passed']:
            raise RuntimeError('Server flow completed, but installed-OS shutdown teardown failed qualification; inspect serial and dracut history')
        record('Every installed-OS reboot returned to the shutdown initramfs without final device teardown failure')
        report['status'] = 'passed-server-flow'
    except BaseException as error:
        report['status'] = 'interrupted' if isinstance(error, KeyboardInterrupt) else 'failed'
        report['error'] = str(error).replace(password, '[REDACTED]')
        if os.environ.get('GITHUB_ACTIONS') == 'true':
            # Keep a redacted failure reason readable when artifact delivery fails.
            message = report['error'].replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')
            print('::error title=Current UEFI qualification::' + message, flush=True)
        try:
            # A misfocused greeter could echo the ephemeral password. Keep the
            # pre-password screenshot and logs instead of uploading that frame.
            if not graphical_password_pending:
                vm.screenshot('failure')
        except Exception:
            pass
        raise
    finally:
        (evidence / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
        vm.stop()
        server.shutdown()
        for path in evidence.iterdir():
            if path.suffix in ('.log', '.json'):
                path.write_bytes(path.read_bytes().replace(password.encode(), b'[REDACTED]'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifact', type=Path, required=True)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--output', type=Path, required=True, help='New directory; existing paths refused')
    parser.add_argument('--distribution', choices=('fedora', 'alma10', 'alma9'), default='fedora')
    parser.add_argument('--channel', default='br-codex_unified-installer')
    parser.add_argument('--desktop', choices=('gnome', 'cosmic'), default='gnome')
    parser.add_argument('--target-channel', help='Optional independently published destination channel for rebase qualification')
    parser.add_argument('--target-distribution', choices=('fedora', 'alma10', 'alma9'))
    parser.add_argument('--target-desktop', choices=('gnome', 'cosmic'))
    parser.add_argument('--image-revision', default='782560bfcb1a853ac9a6a3d3eeb694438794f7e6')
    parser.add_argument('--scenario', choices=('server-flow', 'reject-btrfs', 'bootstrap-reboot', 'workstation-flow', 'rebase-flow'), default='server-flow')
    parser.add_argument('--require-mdns', action='store_true', help='Require native provider/default mDNS lookups and no Avahi startup warnings')
    parser.add_argument('--require-clean-avahi', action='store_true', help='Reject original Avahi NSS/resolver warnings at every bootstrap and destination checkpoint')
    parser.add_argument('--expect-locale', help='Require this selected locale in native configuration, libc and graphical sessions')
    args = parser.parse_args()
    if not re.fullmatch(r'pr-[0-9]+|br-[A-Za-z0-9_.-]+|latest', args.channel):
        parser.error('Invalid destination channel')
    if args.target_channel and not re.fullmatch(r'pr-[0-9]+|br-[A-Za-z0-9_.-]+|latest', args.target_channel):
        parser.error('Invalid destination channel')
    if not re.fullmatch(r'[0-9a-f]{40}', args.image_revision):
        parser.error('Expected a full destination image revision')
    if args.scenario == 'rebase-flow' and (not args.target_distribution or args.target_distribution == args.distribution):
        parser.error('Rebase flow requires a different target distribution')
    run(args)
