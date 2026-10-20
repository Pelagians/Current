# Choose An Image

Current is an image ecosystem. Choose the image that best matches the machine's hardware and workflow.

Public image names follow this technical grammar:

- `<platform>-<environment>`
- `<platform>-<environment>-<driver>`

Choose in this order.

## 1. Pick the CPU architecture

Public image names are shared by x64 and ARM64. Each `:latest` OCI index contains
only its supported architectures; bootc selects the matching native image.
The rebase picker filters unsupported combinations before showing choices.
Explicit `:latest-amd64` and `:latest-arm64` tags are available for diagnosis.
Existing `-arm64:latest` image references remain updated as compatibility aliases.
Boot/GPU qualification remains separate from a successful image build.

## 2. Pick a lane

- `alma9`: EL9 lane, including the NVIDIA 580 compatibility option
- `alma10`: stable lane
- `fedora`: edge lane, including akmod-built NVIDIA 580 images

## 3. Pick an environment

- `gnome`: the default documented workstation experience
- `cosmic`: a parallel supported workstation experience
- `server`: the headless admin/operator lane

## 4. Pick a driver lane if the distro lane supports one

- images without a driver suffix are the standard lane
- `nvidia-open`: newer supported NVIDIA GPUs on Alma 9, Alma 10 and Fedora candidates
- `nvidia-580`: supported proprietary R580 lane; Alma 9 uses prebuilt module-stream kmods and Fedora builds modules during image build with akmods

## Supported images

The exact supported image list comes from `files/base/runtime/usr/share/current/image-matrix.tsv`; `current rebase` downloads that matrix from GitHub when it builds the picker.

The matrix has 24 public image families backed by 24 x64 and 21 ARM builds.
The names below apply to both CPUs wherever the ARM column lists support. Build success and boot/GPU qualification are separate gates.

| Distro / driver | Server | GNOME | COSMIC | ARM equivalents |
| --- | --- | --- | --- | --- |
| Alma 9 standard | `alma9-server` | `alma9-gnome` | `alma9-cosmic` | All three |
| Alma 9 open | `alma9-server-nvidia-open` | `alma9-gnome-nvidia-open` | `alma9-cosmic-nvidia-open` | All three |
| Alma 9 R580 | `alma9-server-nvidia-580` | `alma9-gnome-nvidia-580` | `alma9-cosmic-nvidia-580` | None |
| Alma 10 standard | `alma10-server` | `alma10-gnome` | `alma10-cosmic` | All three |
| Alma 10 open | `alma10-server-nvidia-open` | `alma10-gnome-nvidia-open` | `alma10-cosmic-nvidia-open` | All three |
| Fedora standard | `fedora-server` | `fedora-gnome` | `fedora-cosmic` | All three |
| Fedora open | `fedora-server-nvidia-open` | `fedora-gnome-nvidia-open` | `fedora-cosmic-nvidia-open` | All three |
| Fedora R580 | `fedora-server-nvidia-580` | `fedora-gnome-nvidia-580` | `fedora-cosmic-nvidia-580` | All three |

ARM Alma 9 lacks the prebuilt proprietary R580 module-stream contract used by
x64. Alma 10 has no R580 lane on either architecture. ARM Alma candidates use
restricted supplemental devel packages and remain experimental; see the
[package sources and qualification limits](../maintainers/arm-image-lanes.md).

## Published tag examples

- Current AlmaLinux 10 GNOME workstation: `alma10-gnome`
- Current AlmaLinux 10 COSMIC workstation with the open NVIDIA lane: `alma10-cosmic-nvidia-open`
- Current Fedora GNOME workstation: `fedora-gnome`
- Current Fedora NVIDIA 580 GNOME workstation: `fedora-gnome-nvidia-580`
- Current AlmaLinux 9 NVIDIA 580 GNOME workstation: `alma9-gnome-nvidia-580`
- Current AlmaLinux 10 Server: `alma10-server`
- Current Fedora Server: `fedora-server`

`current rebase` shows matching images by architecture, role, environment,
platform and driver, then switches to the shared reference, for example
`ghcr.io/pelagians/fedora-cosmic-nvidia-580:latest` on either CPU. See the
[ARM maintainer status](../maintainers/arm-image-lanes.md) for qualification limits.
