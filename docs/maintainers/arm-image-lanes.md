# ARM64 image candidates

The architecture split happens before the server/workstation split in CI.
`build.yml` calls `build-architecture.yml` once for x86_64 and once for aarch64.
The reusable workflow expands each architecture's server and workstation rows
from the single shipped TSV manifest. x64 uses `ubuntu-latest`; ARM64 uses
`ubuntu-24.04-arm`. Builds run natively, with an explicit `platforms` entry in
every recipe. ARM images have distinct `-arm64` names, avoiding concurrent writes
to the existing x64 image tags.

Initial ARM candidates are the standard server, GNOME and COSMIC images on
Alma 10 and Fedora. They reuse the existing role, desktop and bootc layers.
There are no ARM NVIDIA or Alma 9 candidates in this first set. Driver support
requires its own packaging/hardware qualification. These are generic aarch64
bootc/UEFI candidates; they do not provide an Apple Silicon/Asahi hardware port
or an ARM installer ISO.

## Package differences

ROCm installation is extracted into `layers/alma10/rocm.yml` and
`layers/fedora/rocm.yml`, included by the existing x64 recipes. ARM recipes omit
these layers: Fedora ARM metadata includes rocm-smi but does not include the
required rocminfo/rocm-hip-devel/rocm-opencl-devel set. The x64 package intent is
preserved. Intel microcode and thermald installation is conditional on x86_64
in the shared workstation substrate. Required ARM packages are not silently
skipped by a broad package fallback.

Source inspection on 2026-09-30 confirmed:

- `quay.io/fedora/fedora-bootc:latest` and
  `quay.io/almalinuxorg/almalinux-bootc:10` publish arm64 OCI manifests.
- `ghcr.io/blue-build/cli:latest-installer` publishes arm64, and its native
  BlueBuild 0.9.37 binary can generate recipes on the development host.
- Fedora provides aarch64 GDM, COSMIC greeter and COSMIC session packages.
- Enterprise COSMIC publishes an Alma 10 `rhel+epel-10-aarch64` repository with
  its COSMIC stack and applets. The existing Alma source layer already computes
  that target from `uname -m`.
- Brave's ARM repository provides `brave-origin`; existing workstation app
  policy remains the same.

This establishes candidate source availability, not a complete dependency solve
or boot qualification. The native package commands, session contracts and PAM
checks in the workstation layers still fail the image build if an expected
contract is missing.

References: [BlueBuild platform selection](https://blue-build.org/reference/recipe/#platforms),
[GitHub ARM runners](https://docs.github.com/en/actions/reference/runners/github-hosted-runners),
[Enterprise COSMIC ARM repository](https://download.copr.fedorainfracloud.org/results/ligenix/enterprise-cosmic/rhel+epel-10-aarch64/),
[Brave ARM repository](https://brave-browser-rpm-release.s3.brave.com/aarch64/).

## Matrix and rebase compatibility

The TSV adds `architecture` immediately after `job`. Allowed values are
`x86_64` and `aarch64`. CI rendering requires an explicit architecture filter.
The updated `current rebase` filters to the running machine's architecture before
showing choices. It also accepts the previous seven-column matrix as x86_64-only,
so updated clients can read the existing stable manifest during rollout.

Older clients reject the new header safely. Upgrade their current image with
`bootc upgrade` to install the updated picker before using the new matrix, or
use an explicit architecture-correct `bootc switch` reference. CPU architecture
cannot be changed through a desktop rebase. ARM candidates must pass builds and
boot qualification before being described as supported published deployments.

## Validation and qualification

```bash
bash scripts/validate-runtime-artifacts.sh
bash scripts/validate-image-matrix.sh
python3 scripts/render-image-matrix.py gha --architecture aarch64 server-images
python3 scripts/render-image-matrix.py gha --architecture aarch64 workstation-images
bluebuild generate --platform linux/arm64 recipes/images/arm64/server/fedora/server.yml
bluebuild build --platform linux/arm64 --no-sign recipes/images/arm64/server/fedora/server.yml
```

The six architecture tests exercise the actual rebase shell with isolated curl,
fzf, uname and sudo stubs, plus matrix validation and role/architecture filtering.
The workstation helper's separate tests are architecture independent.

Before release, build all six candidates on the ARM runner, install on a
disposable generic ARM64 bootc machine, and perform fresh server/desktop boots.
Then perform the [persistent workstation rebase qualification](workstation-rebase-qualification.md)
on each ARM desktop pair. Record architecture, image digests, bootloader/kernel,
greeter appearance, successful login, session identity and retained preferences.
Full image builds and booted qualification remain pending until those results
are recorded; recipe generation and source availability alone are insufficient.
