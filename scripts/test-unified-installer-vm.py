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
  test "${XDG_SESSION_TYPE:-}" = wayland || test "${XDG_SESSION_TYPE:-}" = x11
  test -n "${WAYLAND_DISPLAY:-}${DISPLAY:-}"
  bash "$HOME/.local/bin/current-vm-qualify-workstation"
  loginctl list-sessions --no-pager
  systemctl --user --failed --no-pager
  ps -u "$(id -u)" -o pid,comm,args
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

    def keys(self, text):
        punctuation = {' ': 'spc', '/': 'slash', ':': 'shift-semicolon', '=': 'equal',
                       '-': 'minus', '.': 'dot', ',': 'comma', '_': 'shift-minus',
                       '(': 'shift-9', ')': 'shift-0', '\n': 'ret'}
        for char in text:
            key = punctuation.get(char, 'shift-' + char.lower() if char.isupper() else char)
            self.call('human-monitor-command', **{'command-line': 'sendkey ' + key + ' 10'})
            time.sleep(.025)

    def click(self, x, y, width, height):
        if not (0 <= x < width and 0 <= y < height):
            raise ValueError('Pointer coordinate is outside the VM screenshot')
        self.call('input-send-event', events=[
            {'type': 'abs', 'data': {'axis': 'x', 'value': round(x * 32767 / width)}},
            {'type': 'abs', 'data': {'axis': 'y', 'value': round(y * 32767 / height)}},
            {'type': 'btn', 'data': {'down': True, 'button': 'left'}},
            {'type': 'btn', 'data': {'down': False, 'button': 'left'}}])


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
        'channel': args.channel, 'scenario': args.scenario,
              'desktop': args.desktop if args.scenario == 'workstation-flow' else None,
              'target_distribution': args.target_distribution, 'image_revision': args.image_revision, 'milestones': [], 'status': 'running'}
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
            if self.path not in ('/anaconda.log', '/storage.log', '/program.log', '/packaging.log', '/users.log', '/install-marker.log', '/install-error.log', '/storage-rejected.log'):
                self.send_error(404)
                return
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 <= length <= 32 * 1024**2:
                self.send_error(413)
                return
            (evidence / self.path[1:]).write_bytes(self.rfile.read(length).replace(password.encode(), b'[REDACTED]'))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *unused):
            pass
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    ks = kickstart(receipt, password, server.server_port, args.scenario).encode()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    vm = VM(root, evidence, iso, accel)
    graphical_password_pending = False
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
            vm.serial.sendline('currenttest')
            vm.serial.expect('Password:')
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
            result = vm.serial.expect([r'\r?\nVM_RC=([0-9]+)\r?\n', r'\[sudo\] password for currenttest:'], timeout=timeout)
            if result:
                vm.serial.sendline(password)
                vm.serial.expect(r'\r?\nVM_RC=([0-9]+)\r?\n', timeout=timeout)
            output = vm.serial.before
            if vm.serial.match.group(1) != '0':
                raise RuntimeError('Guest command failed: ' + text + '\n' + output)
            vm.serial.expect('CURRENT_VM> ')
            return output

        checkpoints = []
        deferred_journals = set()
        report['journal_verification'] = {}

        def diagnostics(stage, distribution=None, verify_deferred=False):
            # Keep optional/version-dependent probes nonfatal, but retain each
            # status. Session execution and cross-boot marker retention below
            # are assertions, not an interpretation of warning text.
            probes = [
                'rpm -q systemd systemd-pam pam dracut ostree bootc; uname -r',
                'systemctl --failed --no-pager; systemctl --user --failed --no-pager',
                'loginctl session-status --no-pager; systemctl show user@$(id -u).service -p ActiveState -p SubState -p Result -p ExecMainStatus',
                'sudo cat /etc/pam.d/systemd-user /usr/lib/pam.d/systemd-user; authselect current',
                'findmnt -R /; sudo losetup -l; sudo dmsetup info -c; lsblk -o NAME,TYPE,FSTYPE,MOUNTPOINTS',
                'sudo ls -la /run/initramfs; sudo test -x /run/initramfs/shutdown',
                'systemctl cat dracut-shutdown.service; sudo cat /usr/lib/dracut/dracut-initramfs-restore',
                # Include prior boots: restore runs in ExecStop, after the
                # preceding checkpoint, and its errors may not reach serial.
                'sudo journalctl -u dracut-shutdown.service -u systemd-journald.service -u user@$(id -u).service --no-pager',
                'sudo journalctl --header --no-pager',
                'sudo journalctl -b -p warning --no-pager',
                # Online verification is diagnostic only: concurrent journald
                # writes can yield false corruption (systemd issue #27532).
                'sudo journalctl --verify',
            ]
            with (evidence / (stage + '-diagnostics.log')).open('w') as output:
                for probe in probes:
                    output.write('$ ' + probe + '\n')
                    output.write(command('(' + probe + "); rc=$?; printf '\\nPROBE_RC=%s\\n' \"$rc\"; true", timeout=180))
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
                verification = command('sudo journalctl --verify ' + archives + '; rc=$?; printf \'\\nVERIFY_RC=%s\\n\' "$rc"; true', timeout=180)
                output.write(verification)
                result = journal_verification(verification, (distribution or args.distribution) == 'alma9' and stage != 'bootstrap')
                report['journal_verification'][stage] = result
                deferred_journals.update(result['deferred'])
                if (verify_deferred or (stage == 'rollback' and args.scenario not in ('workstation-flow', 'rebase-flow'))) and not deferred_journals.issubset(result['passed']):
                    raise RuntimeError('Rollback did not verify every deferred journal archive')
            markers = command('sudo journalctl -q -t current-vm-checkpoint -o cat --no-pager ' + archives)
            (evidence / (stage + '-markers.log')).write_text(markers)
            if not set(checkpoints).issubset(set(terminal_text(markers).splitlines())):
                raise RuntimeError('Persistent journal lost checkpoint markers at ' + stage)
            record(stage + ': user manager, transient user service and persistent journal markers passed; diagnostics captured')

        def put_guest(path, content, executable=False):
            encoded = base64.b64encode(content.encode()).decode()
            command('printf %s ' + shlex.quote(encoded) + ' | base64 -d > ' + path)
            if executable:
                command('chmod 700 ' + path)

        def graphical_login(stage, desktop):
            nonlocal graphical_password_pending
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
                time.sleep(3)
                vm.screenshot(stage + '-password-prompt')
            graphical_password_pending = True
            vm.qmp.keys(password + '\n')
            deadline = time.monotonic() + 240
            while time.monotonic() < deadline:
                output = terminal_text(command('if test -f ~/current-vm-session-' + stage + '.rc; then cat ~/current-vm-session-' + stage + '.rc; fi')).strip()
                if output:
                    proof = command('cat ~/current-vm-session-' + stage + '.log')
                    (evidence / (stage + '-graphical-session.log')).write_text(proof)
                    graphical_password_pending = False
                    time.sleep(10)
                    vm.screenshot(stage + '-session')
                    if output != '0':
                        raise RuntimeError('Graphical session qualification failed: ' + proof)
                    if ('DESKTOP=' + desktop.upper()) not in proof.upper():
                        raise RuntimeError('Autostart reported the wrong desktop')
                    report.setdefault('graphical_logins', []).append({'stage': stage, 'desktop': desktop, 'proof': stage + '-graphical-session.log'})
                    record(stage + ': real greeter password login and desktop-session ownership checks passed')
                    return
                time.sleep(5)
            command('loginctl list-sessions --no-pager; sudo journalctl -b -u display-manager.service --no-pager; true')
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
            vm.serial.sendline('sudo systemctl reboot')
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
        command('id -u > ~/current-original-uid; sudo sh -c \'sha256sum /etc/NetworkManager/system-connections/*\' > ~/current-network-hashes')
        # Test-only persistent journal retains shutdown-time finalization errors.
        command('sudo mkdir -p /var/log/journal && sudo systemd-tmpfiles --create --prefix /var/log/journal && sudo journalctl --flush')
        diagnostics('bootstrap')
        if args.scenario == 'bootstrap-reboot':
            vm.serial.sendline('sudo systemctl reboot')
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
        vm.serial.sendline('sudo systemctl reboot')
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
            target_distribution = args.target_distribution if args.scenario == 'rebase-flow' else args.distribution
            target_desktop = ('cosmic' if args.desktop == 'gnome' else 'gnome') if args.scenario == 'workstation-flow' else None
            program = rebase_program(target_distribution, target_desktop or 'server', args.channel, args.image_revision)
            staged = command('sudo env PYTHONPATH=/usr/lib python3 -c ' + shlex.quote(program), timeout=3600)
            (evidence / 'rebase-staging.log').write_text(staged)
            target = json.loads(re.search(r'REBASE_STAGED=(.+)', terminal_text(staged))[1])
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
            vm.serial.sendline('sudo systemctl reboot')
            vm.serial.expect('current-vm login:', timeout=600)
            if login(False):
                raise RuntimeError('Ordinary destination reboot unexpectedly returned to bootstrap')
            command('sudo -v')
            diagnostics('destination-reboot')
            command('sudo current setup; test ! -e /usr/share/current/bootstrap && test "$(getenforce)" = Enforcing')
        command('sudo bootc rollback')
        vm.serial.sendline('sudo systemctl reboot')
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
    parser.add_argument('--channel', default='pr-29')
    parser.add_argument('--desktop', choices=('gnome', 'cosmic'), default='gnome')
    parser.add_argument('--target-distribution', choices=('fedora', 'alma10', 'alma9'))
    parser.add_argument('--image-revision', default='01abb3d85a097c8357de4625f10fbb01e9239445')
    parser.add_argument('--scenario', choices=('server-flow', 'reject-btrfs', 'bootstrap-reboot', 'workstation-flow', 'rebase-flow'), default='server-flow')
    args = parser.parse_args()
    if not re.fullmatch(r'pr-[0-9]+|br-[A-Za-z0-9_.-]+|latest', args.channel):
        parser.error('Invalid destination channel')
    if not re.fullmatch(r'[0-9a-f]{40}', args.image_revision):
        parser.error('Expected a full destination image revision')
    if args.scenario == 'rebase-flow' and (not args.target_distribution or args.target_distribution == args.distribution):
        parser.error('Rebase flow requires a different target distribution')
    run(args)
