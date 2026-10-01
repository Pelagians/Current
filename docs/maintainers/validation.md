# Validation

Use the repo validation scripts as the source of truth for the supported image matrix.

Primary checks:

- scripts/validate-runtime-artifacts.sh
- scripts/validate-image-matrix.sh

The runtime validator checks shared payloads, image support files, workstation helpers, k3s wiring, Ceph wiring, NVIDIA wiring, and update/rebase commands.

The image-matrix validator checks that recipes, CI, and the shipped matrix describe the same supported image set.

Workstation regression checks run automatically through the runtime validator:

```bash
python3 scripts/tests/test-workstation-dm.py
```

They use temporary roots, real offline `systemctl`, and native systemd dependency
verification. They never start/stop the runner's display manager. Workstation
image layers also call the installed helper's `--check gnome|cosmic` mode to
validate native service/config/session and helper/generator/service contracts.
Booted tests remain required by [workstation rebase qualification](workstation-rebase-qualification.md).
