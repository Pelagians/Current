# Validation

Use the repo validation scripts as the source of truth for the supported image matrix.

Run from the repository root. Bash and Python 3 run the validators; runtime
fixtures also require Node.js, util-linux (`flock`/`setsid`) and systemd tools.
Tests use temporary roots and mocks, never the host display manager or Flatpak
installation. Negative source assertions fail on matches **and** grep errors.

Primary checks:

- scripts/validate-runtime-artifacts.sh
- scripts/validate-image-matrix.sh

The runtime validator checks shared payloads, image support files, workstation helpers, k3s wiring, Ceph wiring, NVIDIA wiring, and update/rebase commands.

The image-matrix validator checks that recipes, CI, and the shipped matrix describe the same supported image set.

Workstation regression checks run automatically through the runtime validator:

```bash
python3 scripts/tests/test_runtime_workstation_dm.py
```

The reconciliation cases use temporary roots, real offline `systemctl`, and native systemd dependency
verification. They never start/stop the runner's display manager. Workstation
image layers also call the installed helper's `--check gnome|cosmic` mode to
validate native service/config/session and helper/generator/service contracts.
Booted tests remain required by [workstation rebase qualification](workstation-rebase-qualification.md).

The image-matrix validator runs architecture, publication/CPU-transaction and isolated Fedora NVIDIA regressions, plus recipe-graph, download, Distrobox link and Alma preflight fixtures. They check the native
rebase picker, legacy matrix compatibility, explicit platforms, and architecture
before role in CI. NVIDIA tests execute the actual header selection and module checks with temporary package/network stubs, including signed fallback, wrong package identity, signature rejection matching kernel modules, and retaining CUDA compiler headers during cleanup. Native ARM build/boot qualification is tracked in
[ARM candidate status](arm-image-lanes.md). Publication fixtures cover missing,
duplicate and stale native artifacts, source/platform validation, invalid indexes,
signing failures, channel isolation and signing all indexes/aliases before any
public channel advances. They never contact a registry. Real publication must
pass [the gated CI publisher](image-publishing.md).

Flatpak behavior checks are included in the runtime validator and can also run alone:

```bash
python3 scripts/tests/test_runtime_flatpak.py
```

The Flatpak tests require Python 3, Bash, Node.js, and util-linux (`flock`/`setsid`). They use temporary mocks, never host Flatpak installations. Run as an ordinary user to exercise the real root-rejection gate; root containers that cannot change UID report that case as skipped. See the Flatpak section of `runtime-contracts.md` for remaining image integration checks.

## Test entrypoints

All Python regressions are discoverable without a maintained list of filenames:

```bash
python3 -m unittest discover -s scripts/tests -p 'test_*.py' -v
```

The runtime validator runs `test_runtime_*.py`; the matrix validator runs
`test_image_*.py`. The JavaScript policy fixture is called by the Flatpak tests.
Historical decision records and test fixtures are excluded from the active-source
namespace check; active implementation and maintainer/user documentation remain
checked. A historical spelling in a fixture must not make validation pass or fail.

CI intentionally runs both branch-head and PR-merge candidates. Branch tags remain
published; PR tags identify merge candidates. See [image publishing](image-publishing.md).

## Build-side contracts

`scripts/image_matrix.py` owns TSV validation and recursive recipe includes.
The renderer CLI, index publisher, composition validator and Alma 9 NVIDIA
preflight use it. `validate_image_recipes.py` checks composition; the shell
entrypoint also checks CI wiring and invokes image regression discovery.

CI runs the live Alma 9 R580 package preflight separately:

```bash
python3 scripts/verify_alma9_nvidia_580.py
```

It requires Podman or Docker and network access, explicitly selects the x64 Alma 9 bootc container (a native x64 runner or configured emulation is required),
and resolves server and workstation transactions with DNF `--assumeno`. It
rejects resolver errors and DKMS providers, requires prebuilt kmods, and retries
only transient container failures, at most three attempts. Unit fixtures cover
the parser and retry policy without contacting package repositories.

Update-helper fixtures cover server/workstation capability handling, independent
stage failures, credential-file precedence, executable wrapper wiring, and
retained Distrobox mount repair with an unchanged backup. These are isolated
fixtures; real retained-container upgrade qualification remains pending.
Build download fixtures execute both CPU paths with real checksum verification
and reject invalid checksums/unknown CPUs before installation.
