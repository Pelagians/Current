# Release Policy

Current publishes a small image matrix with explicit contracts.

## Stability policy

- `alma10` is the stable baseline lane.
- `fedora` is the edge lane for newer userspace and hardware enablement, including akmod-built NVIDIA 580 images.
- `alma9` provides standard and NVIDIA open images on both CPUs, plus the x64 prebuilt NVIDIA 580 compatibility lane.
- Role, environment, platform, and driver lanes are all explicit supported contracts.

## Update policy

- Published images are meant to be updated intentionally.
- Rebases between supported images are part of the normal workflow.
- Workstation-environment rebases are expected to preserve the correct display-manager ownership on boot.
- The supported image matrix is the source of truth for published tags and `current rebase`.

## Support boundaries

- Developers and AI developers are the primary audience.
- Server and lab infrastructure remain first-class targets.
- Workstation is the developer/operator desktop and laptop lane for the same image-based system model.
- GNOME and COSMIC are workstation environments, not separate product lines.
- Images outside the published matrix are unsupported unless they are added to the manifest and validation flow.

Repository-wide support expectations are documented in [SUPPORT.md](../../SUPPORT.md).
