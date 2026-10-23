#!/usr/bin/env bash
# Build-time compatibility for locales-rs with older distro iso-codes data.
set -euo pipefail
python3 - <<'PY'
import json
import os
from pathlib import Path
import re

path = Path(os.environ.get('CURRENT_COSMIC_ISO3166_JSON', '/usr/share/iso-codes/json/iso_3166-1.json'))
document = json.loads(path.read_text(encoding='utf-8'))
territories = document.get('3166-1')
if not isinstance(territories, list) or not territories:
    raise ValueError('Missing or invalid native ISO 3166 territory list')
changed = 0
for territory in territories:
    if not isinstance(territory, dict):
        raise ValueError('Invalid native ISO 3166 territory')
    code = territory.get('alpha_2')
    if not isinstance(code, str) or not re.fullmatch('[A-Z]{2}', code):
        raise ValueError('Invalid native ISO 3166 alpha_2 code')
    if 'flag' in territory:
        if not isinstance(territory['flag'], str):
            raise ValueError('Invalid existing native ISO 3166 flag')
        continue
    # Unicode regional-indicator pairs derive from the package's own alpha_2.
    # Do not add territories, rename them, or replace an existing flag value.
    territory['flag'] = ''.join(chr(0x1F1E6 + ord(char) - ord('A')) for char in code)
    changed += 1
if changed:
    # A build failure discards the layer. In-place writing preserves the native
    # file's ownership, mode and labels; already-compatible files stay identical.
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print('Current COSMIC ISO 3166 compatibility: added flags to {} native entries'.format(changed))
PY
