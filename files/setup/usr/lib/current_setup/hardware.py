"""Read-only discovery and deterministic recommendations, independent of UI."""
import json
import platform
from pathlib import Path

from .matrix import load_rows

V2 = set('cx16 lahf_lm popcnt pni ssse3 sse4_1 sse4_2'.split())
# Linux exposes usable AVX only when OSXSAVE is active; /proc omits osxsave itself.
V3 = V2 | set('avx avx2 bmi1 bmi2 f16c fma abm movbe xsave'.split())


def read(path):
    try:
        return path.read_text().strip().replace('\0', ' ')
    except (OSError, UnicodeError):
        return ''


def discover(root=Path('/'), architecture=None):
    arch = architecture or platform.machine()
    arch = {'amd64': 'x86_64', 'arm64': 'aarch64'}.get(arch, arch)
    cpu = read(root / 'proc/cpuinfo')
    flag_sets = [set(line.split(':', 1)[1].split()) for line in cpu.splitlines()
                 if line.startswith(('flags\t', 'flags ', 'Features\t', 'Features '))]
    flags = set.intersection(*flag_sets) if flag_sets else set()
    gpus = []
    for device in sorted((root / 'sys/bus/pci/devices').glob('*')):
        if not read(device / 'class').startswith('0x03'):
            continue
        gpus.append({'slot': device.name, 'vendor': read(device / 'vendor').removeprefix('0x'),
                     'device': read(device / 'device').removeprefix('0x'),
                     'subsystem_vendor': read(device / 'subsystem_vendor').removeprefix('0x'),
                     'subsystem_device': read(device / 'subsystem_device').removeprefix('0x')})
    uefi = (root / 'sys/firmware/efi').is_dir()
    secure = 'unknown'
    for efivar in (root / 'sys/firmware/efi/efivars').glob('SecureBoot-*'):
        try:
            data = efivar.read_bytes()
            if len(data) == 5 and data[4] in (0, 1):
                secure = 'enabled' if data[4] else 'disabled'
        except OSError:
            pass
    model = ' '.join(filter(None, [read(root / 'sys/firmware/devicetree/base/compatible'),
                                   read(root / 'sys/firmware/devicetree/base/model'),
                                   read(root / 'sys/class/dmi/id/sys_vendor'),
                                   read(root / 'sys/class/dmi/id/product_name')]))
    return {'architecture': arch, 'cpu_flags': sorted(flags), 'gpus': gpus,
            'uefi': uefi, 'secure_boot': secure, 'platform': model,
            'cpu_level': (3 if V3 <= flags else 2 if V2 <= flags else 1) if flag_sets else None}


def catalogue(matrix_path, compatibility_path):
    rows = load_rows(matrix_path)
    data = json.loads(compatibility_path.read_text())
    if (data.get('schema') != 1 or data.get('qualification') != 'experimental'
            or data.get('cpu_levels') != {'fedora': 1, 'alma9': 2, 'alma10': 3}
            or not isinstance(data.get('nvidia'), dict)):
        raise ValueError('Unsupported or missing compatibility metadata')
    for device, info in data['nvidia'].items():
        if (len(device) != 4 or any(c not in '0123456789abcdef' for c in device)
                or not info.get('name') or not info.get('drivers')
                or not set(info['drivers']) <= {'nvidia-open', 'nvidia-580'}):
            raise ValueError('Invalid NVIDIA compatibility entry')
    return rows, data


def recommend(hardware, rows, compatibility, distribution='auto', role='server', desktop='gnome'):
    if distribution not in ('auto', 'fedora', 'alma10', 'alma9'):
        raise ValueError('Unknown distribution')
    if role not in ('server', 'workstation') or desktop not in ('gnome', 'cosmic'):
        raise ValueError('Unknown role or desktop')
    arch = hardware['architecture']
    blocked = []
    warnings = ['No bootstrap-to-destination transition is boot-qualified yet.']
    if arch not in ('x86_64', 'aarch64'):
        blocked.append('Unsupported CPU architecture')
    if not hardware['uefi']:
        blocked.append('This installer requires UEFI; legacy BIOS and non-UEFI ARM are unqualified')
    if arch == 'aarch64':
        if any(word in hardware['platform'].lower() for word in ('apple', 'asahi')):
            blocked.append('Apple Silicon/Asahi is not supported by this generic ARM UEFI installer')
        warnings.append('Generic ARM64 UEFI candidate only; board firmware and boot support are unqualified.')
    if hardware['secure_boot'] == 'unknown':
        warnings.append('Secure Boot status could not be read.')
    nvidia = [gpu for gpu in hardware['gpus'] if gpu['vendor'] == '10de']
    known = [compatibility['nvidia'].get(gpu['device']) for gpu in nvidia]
    drivers = {'standard'}
    manual = False
    if nvidia:
        if all(known):
            drivers |= set.intersection(*(set(item['drivers']) for item in known))
        else:
            manual = True
            warnings.append('Unknown NVIDIA PCI ID: no proprietary/open driver compatibility asserted. '
                            'Only the standard image fallback is offered; display/acceleration may not work.')
        if hardware['secure_boot'] != 'disabled':
            drivers = {'standard'}
            manual = True
            warnings.append('NVIDIA module signing/key enrollment is unqualified with Secure Boot enabled or unknown. '
                            'Only the standard fallback is offered.')
    if any(gpu['vendor'] not in ('10de', '1002', '8086', '1af4', '1234') for gpu in hardware['gpus']):
        manual = True
        warnings.append('Unknown graphics vendor: standard driver support is unqualified.')
    if len(hardware['gpus']) > 1:
        warnings.append('Multiple GPUs detected; hybrid graphics and display routing need hardware qualification.')
    environment = 'server' if role == 'server' else desktop
    candidates = []
    rejected = []
    for row in rows:
        if row['role'] != role or row['environment'] != environment:
            continue
        reasons = list(blocked)
        if row['architecture'] != arch:
            reasons.append('Architecture mismatch')
        if distribution != 'auto' and row['platform'] != distribution:
            continue
        if row['driver'] not in drivers:
            reasons.append('Driver not compatible with all detected GPUs or Secure Boot state')
        if arch == 'x86_64' and compatibility['cpu_levels'][row['platform']] > 1:
            level = hardware['cpu_level']
            if level is None or level < compatibility['cpu_levels'][row['platform']]:
                reasons.append('Required x86-64 CPU feature level unavailable')
        if reasons:
            rejected.append({'image': row['image'], 'architecture': row['architecture'], 'reasons': reasons})
            continue
        notes = list(warnings)
        if row['platform'] != 'fedora':
            notes.append('Cross-distribution switch: bootloader, SELinux, network and retained /etc need VM qualification.')
        if arch == 'aarch64' and row['platform'].startswith('alma'):
            notes.append('Alma ARM uses supplemental package sources; see arm-image-lanes.md.')
        if row['driver'] == 'standard' and nvidia:
            notes.append('Standard fallback does not promise NVIDIA acceleration or a working graphical login.')
        candidates.append(dict(row, reference=f"ghcr.io/pelagians/{row['image']}:latest",
                               compatibility='experimental', boot_qualified=False, driver_qualified=False,
                               warnings=notes, reasons=['Matches native architecture and requested role/desktop',
                               'CPU and known GPU constraints passed; this is not a boot or rendering test']))
    # Prefer staying on Fedora during initial qualification, then open, R580, standard.
    candidates.sort(key=lambda row: (('fedora', 'alma10', 'alma9').index(row['platform']),
                                    ('nvidia-open', 'nvidia-580', 'standard').index(row['driver'])))
    return {'schema': 1, 'hardware': hardware, 'preferences': {'distribution': distribution,
            'role': role, 'desktop': desktop}, 'recommended': None if manual or not candidates else candidates[0],
            'candidates': candidates, 'rejected': rejected, 'warnings': warnings, 'blocked': blocked,
            'manual_selection_required': manual}
