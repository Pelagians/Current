#!/usr/bin/env bash
set -euo pipefail
# Build only: preserve the distribution package's actual account allocation.
# A runtime sysusers declaration survives bootc's persistent /etc/passwd merge.
python3 - "${1:-/}" <<'PY'
import json
from pathlib import Path
import subprocess
import sys

user = subprocess.check_output(['getent', 'passwd', 'avahi'], text=True).strip().split(':')
group = subprocess.check_output(['getent', 'group', 'avahi'], text=True).strip().split(':')
if (len(user) != 7 or len(group) != 4 or user[0] != 'avahi' or group[0] != 'avahi'
        or not user[2].isdigit() or not user[3].isdigit()
        or not 0 < int(user[2]) < 1000 or user[3] != group[2]
        or user[6] not in ('/sbin/nologin', '/usr/sbin/nologin', '/bin/false', '/usr/bin/false')):
    raise ValueError('Unexpected packaged Avahi identity; review before provisioning')
directory = Path(sys.argv[1]) / 'usr/lib/sysusers.d'
directory.mkdir(parents=True, exist_ok=True)
text = '# Derived from the installed Avahi package; existing local accounts are preserved.\n'
text += f'g avahi {group[2]}\n'
text += f'u avahi {user[2]}:avahi {json.dumps(user[4])} {json.dumps(user[5])} {json.dumps(user[6])}\n'
(directory / '90-current-avahi.conf').write_text(text)
print(text, end='')
PY
