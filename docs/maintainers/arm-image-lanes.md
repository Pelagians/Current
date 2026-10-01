# ARM64 image candidates

The architecture split happens before the server/workstation split in CI.
`build.yml` calls `build-architecture.yml` once for x86_64 and once for aarch64.
The reusable workflow expands each architecture's server and workstation rows
from the single shipped TSV manifest. x64 uses `ubuntu-latest`; ARM64 uses
`ubuntu-24.04-arm`. Builds run natively, with an explicit `platforms` entry in
every recipe. ARM images have distinct `-arm64` names, avoiding concurrent writes
to the existing x64 image tags.

The manifest includes 15 ARM candidates. Each row below provides server, GNOME
and COSMIC recipes, reusing the existing role, desktop and bootc layers:

| Distro | ARM driver lanes | Candidate count |
| --- | --- | --- |
| Alma 9 | standard | 3 |
| Alma 10 | standard, NVIDIA open | 6 |
| Fedora | standard, NVIDIA 580 | 6 |

Driver support requires package builds and hardware qualification. These are generic aarch64
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

The first 32-image CI run built 19 images successfully. It exposed three missing
Alma ARM packages in the normal runtime repositories: Alma 9
`mesa-vulkan-drivers`, and Alma 10 `loupe` and `fprintd-pam` (required by the
native COSMIC greeter). Signed native builds exist in Alma's devel repository.
The experimental ARM recipes use small distro/role-specific layers to install
these packages before their normal shared transactions. Each transaction
restricts devel to the required package names and direct missing subpackages
(`glycin-loaders` or `fprintd`), verifies signatures with the base image's Alma
key and leaves no repository configuration installed. No x64 recipe uses these
layers; Alma 10 servers acquire neither desktop dependency.

Alma [describes devel as a build dependency repository](https://wiki.almalinux.org/repos/AlmaLinux)
and explicitly discourages runtime use. These ARM Alma lanes remain experimental
pending an appropriate runtime package source and boot qualification. Successful
candidate builds do not remove that limitation. Their package layers are
`alma9/arm-core.yml`, `alma10/arm-gnome.yml` and `alma10/arm-cosmic.yml`.

Source inspection on 2026-09-30 confirmed:

- `quay.io/fedora/fedora-bootc:latest` and
  `quay.io/almalinuxorg/almalinux-bootc:10` publish arm64 OCI manifests.
- `ghcr.io/blue-build/cli:latest-installer` publishes arm64, and its native
  BlueBuild 0.9.37 binary can generate recipes on the development host.
- Fedora provides aarch64 GDM, COSMIC greeter and COSMIC session packages.
- Enterprise COSMIC publishes an Alma 10 `rhel+epel-10-aarch64` repository with
  its COSMIC stack and applets, plus `epel-9-aarch64` for Alma 9. The existing
  Alma source layer already computes that target from `uname -m`.
- Brave's ARM repository provides `brave-origin`; existing workstation app
  policy remains the same.

Alma 10's native NVIDIA repository provides `nvidia-open-kmod` and the driver,
CUDA and workstation userspace packages for aarch64. NVIDIA's CUDA repository
uses `sbsa`, rather than `aarch64`, in its RHEL ARM paths and repository IDs;
the shared bootstrap explicitly maps those names. Fedora's Negativo17 R580
repository provides native aarch64 akmod source and userspace packages, so ARM
recipes reuse the same image-time module build and verification as x64.
The first CI run also exposed an incomplete Fedora kernel-devel selector on both
architectures. R580 now requests the installed kernel's full version, release
and architecture, avoiding both unmatched version-only queries and a header
upgrade to a different kernel.

Two x64 driver contracts have no exact ARM counterpart in the inspected sources:

- Alma 9 ARM lacks the prebuilt proprietary R580 module-stream contract used
  by x64. Its module metadata offers DKMS variants instead; ARM Alma 9 therefore
  exposes standard images, rather than claiming proprietary legacy GPU parity.
- Fedora 44's NVIDIA `sbsa` CUDA repository has six packages and lacks the
  required `kmod-nvidia-open-dkms`, `nvidia-open` and driver package set. There
  are no Fedora ARM open-driver candidates. An ARM URL existing is insufficient.

This establishes candidate source availability, not a complete dependency solve
or boot qualification. The native package commands, session contracts and PAM
checks in the workstation layers still fail the image build if an expected
contract is missing.

References: [BlueBuild platform selection](https://blue-build.org/reference/recipe/#platforms),
[GitHub ARM runners](https://docs.github.com/en/actions/reference/runners/github-hosted-runners),
[Enterprise COSMIC ARM repository](https://download.copr.fedorainfracloud.org/results/ligenix/enterprise-cosmic/rhel+epel-10-aarch64/),
[Brave ARM repository](https://brave-browser-rpm-release.s3.brave.com/aarch64/).
Driver metadata: [Alma 9 ARM](https://nvidia.repo.almalinux.org/cuda/9/aarch64/),
[Alma 10 ARM](https://nvidia.repo.almalinux.org/cuda/10/aarch64/),
[NVIDIA RHEL 10 SBSA](https://developer.download.nvidia.com/compute/cuda/repos/rhel10/sbsa/),
[Fedora R580 ARM](https://negativo17.org/repos/nvidia-580/fedora-44/aarch64/),
[Fedora 44 CUDA SBSA](https://developer.download.nvidia.com/compute/cuda/repos/fedora44/sbsa/).

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

The seven architecture tests exercise the actual rebase shell with isolated curl,
fzf, uname and sudo stubs, plus matrix validation, role/architecture filtering and
the CUDA repository bootstrap with isolated curl/dnf/uname stubs.
The workstation helper's separate tests are architecture independent.

Local results on 2026-09-30, using native BlueBuild 0.9.37 and Podman:

- All six ARM recipes passed schema validation and Containerfile generation.
- After integrating the current `stable` fixes, all 15 expanded ARM candidates
  passed schema validation and Containerfile generation. Current full builds
  remain subject to CI; the two full build results below predate that integration.
- Fedora ARM server and COSMIC workstation full builds passed at `bd9c1978`.
  Their local image IDs are `f3994c0df506` and `3c2ad54c1bd1`, respectively;
  both report OCI architecture `arm64`. They were not pushed.
- Both images passed `bootc container lint` with 13 checks passed, one skipped,
  and one warning about runtime-directory content in `/run` and `/tmp`.
- In a disposable container from the COSMIC image, the real generator/helper
  repaired a stale GDM alias, enabled generic greetd link and selected-unit
  mask. A second run was idempotent. Native unit graph verification passed.
  The image installs only `cosmic.desktop` in its Wayland session directory.
- The three restricted supplemental Alma ARM package transactions passed in
  disposable native Alma 9/10 containers with RPM signature checks enabled.
  Alma 9 installed its matching Vulkan subpackage; Alma 10 installed Loupe and
  its loaders, plus the COSMIC greeter's fingerprint PAM dependency.
- Alma 10 ARM `cosmic-greeter-1.9.1-1.el10.aarch64` units, native configuration
  and PAM payload were compared with x64 and are byte-for-byte identical.

Before release, build all 15 candidates on the ARM runner, install on a
disposable generic ARM64 bootc machine, and perform fresh server/desktop boots.
Then perform the [persistent workstation rebase qualification](workstation-rebase-qualification.md)
on each ARM desktop pair. Record architecture, image digests, bootloader/kernel,
greeter appearance, successful login, session identity and retained preferences.
The remaining ARM full builds, remote CI and all booted qualification remain
pending. Container validation does not establish greeter or login behavior.
