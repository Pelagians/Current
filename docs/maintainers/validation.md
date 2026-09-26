# Validation

Use the repo validation scripts as the source of truth for the supported image matrix.

Primary checks:

- scripts/validate-runtime-artifacts.sh
- scripts/validate-image-matrix.sh

The runtime validator checks shared payloads, image support files, workstation helpers, k3s wiring, Ceph wiring, NVIDIA wiring, and update/rebase commands.

The image-matrix validator checks that recipes, CI, and the shipped matrix describe the same supported image set.

Flatpak behavior checks are included in the runtime validator and can also run alone:

```bash
python3 scripts/test-flatpak-maintenance.py
```

They require Python 3, Bash, Node.js, and util-linux (`flock`/`setsid`). They use temporary mocks, never host Flatpak installations. Run as an ordinary user to exercise the real root-rejection gate; root containers that cannot change UID report that case as skipped. See the Flatpak section of `runtime-contracts.md` for remaining image integration checks.
