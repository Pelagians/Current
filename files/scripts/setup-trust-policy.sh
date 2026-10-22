#!/usr/bin/env bash
set -euo pipefail
# Extend the normal BlueBuild signing policy to Current destinations using the
# same repository public key. No insecure transport or alternate trust root.
python3 - "${1:-/}" <<'PY'
import json
import sys
from pathlib import Path
root = Path(sys.argv[1])
path = root / 'etc/containers/policy.json'
policy = json.loads(path.read_text())
policy['transports'].setdefault('docker', {})['ghcr.io/pelagians'] = [{
    'type': 'sigstoreSigned', 'keyPath': '/usr/share/current/cosign.pub',
    'signedIdentity': {'type': 'matchRepository'}}]
path.write_text(json.dumps(policy, indent=2) + '\n')
(root / 'etc/containers/registries.d/current-setup.yaml').write_text(
    'docker:\n  ghcr.io/pelagians:\n    use-sigstore-attachments: true\n')
PY
bootc container lint
