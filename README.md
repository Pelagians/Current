<p align="center">
  <a href="https://github.com/Pelagians/Current">
    <img src="docs/brand/assets/current-wordmark.svg" alt="Current" width="420" />
  </a>
</p>

# Current &nbsp; [![Build](https://github.com/Pelagians/Current/actions/workflows/build.yml/badge.svg)](https://github.com/Pelagians/Current/actions/workflows/build.yml)

Current is a practical, image-native Linux distribution for developer workstations, lab machines, and small infrastructure hosts.

It builds bootc images close to upstream Fedora and AlmaLinux, with a small set of supported lanes, explicit hardware policy, and container-first defaults. Current is developer-first, with AI-ready host capability where the platform supports it, but it does not ship preloaded models or hosted services.

## Why Current

- **Image-native:** bootc images are the unit of install, update, rollback, and rebase.
- **Container-first:** applications and services belong in containers whenever practical.
- **Close to upstream:** Current adds a focused image layer instead of pretending to replace Fedora or AlmaLinux.
- **Explicit lanes:** supported platform, desktop, server, and GPU combinations are declared in one matrix.
- **AI-ready, not AI-bloated:** Current includes practical host/runtime support without bundling models, agents, or cloud services.

## Supported images

Current publishes workstation and server images across three platform lanes:

- `fedora`: edge lane for newer userspace and hardware enablement, including akmod-built NVIDIA 580 images
- `alma10`: stable AlmaLinux lane
- `alma9`: standard and NVIDIA open lanes on both CPUs, plus x64 NVIDIA 580 compatibility

Workstation environments:

- `gnome`
- `cosmic`

Driver lanes:

- standard images, with no driver suffix
- `nvidia-open` where supported
- `nvidia-580` on Alma 9 and Fedora

The supported image matrix is generated from:

```text
files/base/runtime/usr/share/current/image-matrix.tsv
```

User image-selection docs live in [docs/user/choose-an-image.md](docs/user/choose-an-image.md).

## Install and update

Switch an installed bootc system interactively:

```bash
current rebase
```

Switch directly:

```bash
sudo bootc switch ghcr.io/pelagians/alma10-gnome:latest
```

Stage image and managed system Flatpak updates:

```bash
current update-system
```

Current disables unattended `bootc` auto-apply. Rebase when you choose; reboot when you are ready.

Install docs:

- [docs/user/install.md](docs/user/install.md)
- [docs/user/installer-iso.md](docs/user/installer-iso.md)
- [docs/user/updates-and-rollbacks.md](docs/user/updates-and-rollbacks.md)

## Documentation

Start with [docs/README.md](docs/README.md).

Common entry points:

- [Choose an image](docs/user/choose-an-image.md)
- [Install](docs/user/install.md)
- [Updates and rollbacks](docs/user/updates-and-rollbacks.md)
- [Apps and Flatpak](docs/user/apps-and-flatpak.md)
- [AI-ready host support](docs/user/ai-ready.md)
- [Maintainer docs](docs/maintainers/README.md)

## Project boundary

Current is a focused base operating system. It is not a hosted application platform, an AI appliance, or a replacement for upstream Linux distributions.

Higher-level services should run above Current, usually in containers or k3s.

## Maintained by Pelagian

Current is maintained by Pelagian and used internally by Pelagian, but it stands alone as an open-source project.

## Upstream and BlueBuild

Current depends on excellent upstream distributions and the BlueBuild image build framework. The project should keep its product opinions small, explicit, and reviewable.
