<p align="center">
  <a href="https://github.com/Pelagians/Current">
    <img src="docs/brand/assets/current-wordmark.svg" alt="Current" width="420" />
  </a>
</p>

# Current &nbsp; [![Build](https://github.com/Pelagians/Current/actions/workflows/build.yml/badge.svg)](https://github.com/Pelagians/Current/actions/workflows/build.yml)

Current is an image-based Linux distribution for developer workstations,
lab machines, and small servers. It builds on Fedora and AlmaLinux and
uses bootc to install, update, and roll back the operating system as a
single image. The defaults are designed for running apps and services
in containers.

## Choose an image

Start with the [image guide](docs/user/choose-an-image.md). Current publishes
GNOME and COSMIC workstation images and headless server images. The guide
lists supported combinations of distribution, CPU architecture, and NVIDIA
drivers.

## Get started

- **Install on a new machine.** Follow the [installation guide](docs/user/install.md).
  It covers the AlmaLinux 10 Server installer ISO for bare metal and how to
  build a virtual machine image.
- **Switch an existing bootc system.** Choose an image and follow the
  [switch instructions](docs/user/install.md#switch-an-installed-system).
  If you already run Current, use `current rebase` to choose another image
  that supports your hardware.

## Update and roll back

Use `current update-system` to stage an operating system image update and
update managed system Flatpaks. Current applies the staged image when you
reboot. You can return to the previous deployment if needed. See
[updates and rollbacks](docs/user/updates-and-rollbacks.md).

## Documentation

- [Apps and Flatpak](docs/user/apps-and-flatpak.md)
- [AI and GPU support on the host](docs/user/ai-ready.md)
- [Documentation index](docs/README.md)
- [Maintainer guide](docs/maintainers/README.md)

## Maintained by Pelagian

Current runs independently of the Pelagian platform. Its images are built
with [BlueBuild](https://blue-build.org/) and stay close to Fedora and AlmaLinux.
