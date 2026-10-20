#!/usr/bin/env bash
set -euo pipefail
# Extend the normal BlueBuild signing policy to Current destinations using the
# same repository public key. No insecure transport or alternate trust root.
python3 - <<'PY'
import json
from pathlib import Path
path = Path('/etc/containers/policy.json')
policy = json.loads(path.read_text())
policy['transports'].setdefault('docker', {})['ghcr.io/pelagians'] = [{
    'type': 'sigstoreSigned', 'keyPath': '/usr/share/current/cosign.pub',
    'signedIdentity': {'type': 'matchRepository'}}]
path.write_text(json.dumps(policy, indent=2) + '\n')
Path('/etc/containers/registries.d/current-setup.yaml').write_text(
    'docker:\n  ghcr.io/pelagians:\n    use-sigstore-attachments: true\n')
PY
bootc container lint
