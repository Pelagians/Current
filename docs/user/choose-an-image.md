# Choose An Image

Current is an image ecosystem. Choose the image that best matches the machine's hardware and workflow.

Public image names follow this technical grammar:

- `<platform>-<environment>`
- `<platform>-<environment>-<driver>`

Choose in this order.

## 1. Pick the CPU architecture

Existing image names are x86_64. Initial ARM64 candidate names add `-arm64`.
The rebase picker filters to your running machine's architecture. ARM candidates
cover standard Alma 10/Fedora server, GNOME and COSMIC recipes; image builds and
boot qualification are still required before publication/support claims.

## 2. Pick a lane

- `alma9`: NVIDIA 580 compatibility lane
- `alma10`: stable lane
- `fedora`: edge lane, including akmod-built NVIDIA 580 images

## 3. Pick an environment

- `gnome`: the default documented workstation experience
- `cosmic`: a parallel supported workstation experience
- `server`: the headless admin/operator lane

## 4. Pick a driver lane if the distro lane supports one

- images without a driver suffix are the standard lane
- `nvidia-open`: newer supported NVIDIA GPUs on supported Alma 10 and Fedora images
- `nvidia-580`: supported proprietary R580 lane; Alma 9 uses prebuilt module-stream kmods and Fedora builds modules during image build with akmods

## Supported images

The exact supported image list comes from `files/base/runtime/usr/share/current/image-matrix.tsv`; `current rebase` downloads that matrix from GitHub when it builds the picker.

Current lanes:

- `alma9`: `alma9-gnome-nvidia-580`, `alma9-cosmic-nvidia-580`, `alma9-server-nvidia-580`
- `alma10`: `alma10-gnome`, `alma10-gnome-nvidia-open`, `alma10-cosmic`, `alma10-cosmic-nvidia-open`, `alma10-server`, `alma10-server-nvidia-open`
- `fedora`: `fedora-gnome`, `fedora-gnome-nvidia-open`, `fedora-gnome-nvidia-580`, `fedora-cosmic`, `fedora-cosmic-nvidia-open`, `fedora-cosmic-nvidia-580`, `fedora-server`, `fedora-server-nvidia-580`

Unsupported combinations are intentional.

- no Alma 9 standard or `nvidia-open` images
- no `fedora-server-nvidia-open`

## Published tag examples

- Current AlmaLinux 10 GNOME workstation: `alma10-gnome`
- Current AlmaLinux 10 COSMIC workstation with the open NVIDIA lane: `alma10-cosmic-nvidia-open`
- Current Fedora GNOME workstation: `fedora-gnome`
- Current Fedora NVIDIA 580 GNOME workstation: `fedora-gnome-nvidia-580`
- Current AlmaLinux 9 NVIDIA 580 GNOME workstation: `alma9-gnome-nvidia-580`
- Current AlmaLinux 10 Server: `alma10-server`
- Current Fedora Server: `fedora-server`

`current rebase` shows matching images by architecture, role, environment,
platform and driver. ARM candidate tags are `alma10-server-arm64`,
`alma10-gnome-arm64`, `alma10-cosmic-arm64`, `fedora-server-arm64`,
`fedora-gnome-arm64` and `fedora-cosmic-arm64`. See the
[ARM maintainer status](../maintainers/arm-image-lanes.md) for qualification limits.
