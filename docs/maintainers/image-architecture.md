# Image Architecture

The matrix selects CPU architecture before server/workstation role. The image
set is rendered directly from the single matrix manifest. Desktop and capability
layer ownership remains shared across architectures.

## Authoritative image tree

```text
recipes/images/
  workstation/
    gnome/
      alma9/
      alma10/
      fedora/
    cosmic/
      alma9/
      alma10/
      fedora/
  server/
    alma9/
    alma10/
    fedora/
```

This is the authoritative image tree.

Internal filenames like `core.yml` and `nvidia-580.yml` are maintenance details. The public product model comes from the manifest and the recipe `name:` fields.

## Product model

Public names follow this grammar:

- `<platform>-<environment>`
- `<platform>-<environment>-<driver>`

The exact supported set lives in `files/base/runtime/usr/share/current/image-matrix.tsv`.

The renderer and CI treat that TSV as the canonical support contract for:

- published image names
- supported recipe paths
- workflow matrix expansion
- `current rebase` output

## Machine-readable matrix

`files/base/runtime/usr/share/current/image-matrix.tsv` is shipped into images at `/usr/share/current/image-matrix.tsv`. `current rebase` downloads the same source path from the Current GitHub repo at runtime so the picker can reflect the online support matrix.

It is consumed by:

- `scripts/render-image-matrix.py`
- `scripts/validate-image-matrix.sh`
- `.github/workflows/build.yml`
- `current rebase` through the raw GitHub copy

The TSV schema is intentionally small:

- `job`
- `architecture` (`x86_64` or `aarch64`)
- `platform`
- `role`
- `environment`
- `driver`
- `image`
- `recipe`

## Layer ownership

### Cross-distro core baseline

`recipes/layers/shared/core-base.yml` owns the low-level baseline shared by Alma and Fedora builds.

It owns:

- common core packages
- base runtime payloads and branding
- shared Justfile command surface
- distrobox helper symlinks
- inclusion of shared feature and policy layers

The core base intentionally delegates feature areas that were getting too large:

- `recipes/layers/features/k3s.yml` owns k3s binary and disabled service units
- `recipes/layers/features/pcp.yml` owns PCP local metrics collection and history
- `recipes/layers/features/tailscale.yml` owns Tailscale package and daemon baseline
- `recipes/layers/shared/system-policy.yml` owns shared groups, kernel args, and masked update/counting services

`recipes/layers/shared/core.yml` owns the small distro-neutral host/operator package baseline layered after `shared/core-base.yml` and any required distro-family repository setup.

### Distro core delta

- `recipes/layers/alma/core.yml` adds Alma-family repository and package-manager setup.
- `recipes/layers/fedora/core.yml` adds the Fedora edge-lane delta.
- `recipes/layers/alma10/core.yml` and `recipes/layers/alma9/core.yml` keep the remaining Alma-version drift after the Alma-family layer.

### Feature overlays and shared remainder

`recipes/layers/features/cockpit.yml` owns Cockpit.

`recipes/layers/features/ceph.yml` owns shared Ceph host prerequisites.

`recipes/layers/features/k3s.yml` owns shared k3s runtime capability.

`recipes/layers/features/pcp.yml` owns shared PCP runtime capability.

`recipes/layers/features/tailscale.yml` owns shared Tailscale runtime capability.

`recipes/layers/shared/system-policy.yml` owns shared system policy.

`recipes/layers/shared/core.yml` owns the remaining host/operator package baseline:

- fastfetch, fzf, zstd, gcc, distrobox, and podman-compose
- inclusion of Cockpit and Ceph feature overlays

### Workstation layers

`recipes/layers/shared/flatpak-base.yml` owns the workstation Flatpak baseline, remotes, managed shared apps, policy payloads, session environment import hook, and cleanup helper inclusion.

`recipes/layers/shared/workstation-common.yml` is the DE-agnostic workstation orchestrator.

It delegates visible ownership to:

- `workstation-substrate.yml`: shared desktop and hardware package substrate
- `workstation-admin-tools.yml`: workstation diagnostics, storage, network, and admin utilities
- `workstation-policy.yml`: graphical target, display-manager reconciliation, and workstation sleep policy
- `workstation-user-tools.yml`: Homebrew and Brave Origin Beta

`recipes/layers/shared/workstation-modern.yml` carries the shared workstation delta reused by the Alma 10 and Fedora lanes.

`recipes/layers/shared/workstation-gnome.yml` and `recipes/layers/shared/workstation-cosmic.yml` own environment identity and session behavior. Their nested Flatpak layers own portal backend selection and environment-specific Flatpak app/remote drift.

`recipes/layers/shared/workstation-gnome-modern.yml` carries the shared GNOME app delta reused by the Alma 10 and Fedora lanes.

Remaining distro workstation layers only add real drift:

- `alma9/workstation.yml` and `alma9/gnome.yml` for the Alma 9 compatibility lane
- `alma10/workstation.yml` and `alma10/gnome.yml` for the Alma 10 stable lane
- `alma/cosmic.yml` for Alma-family COSMIC COPR source setup shared by Alma 9 and Alma 10
- `fedora/workstation.yml` and `fedora/cosmic.yml` for Fedora edge-lane drift

### NVIDIA layers

NVIDIA ownership is split three ways:

- `shared/nvidia-base.yml`: common repo bootstrap, NVIDIA container toolkit setup, NVIDIA PCP PMDA package, copied NVIDIA support payloads, and kernel args
- `shared/nvidia-common.yml` / `shared/nvidia-open.yml`: Alma-family NVIDIA lane wiring
- `fedora/nvidia-open.yml`: architecture-specific Fedora open-driver dispatcher on top of the shared NVIDIA base
- `fedora/nvidia-580.yml` and `fedora/nvidia-open.yml`: explicit driver contracts sharing the image-time build in `fedora/nvidia-akmod.yml`, with exact signed headers and module verification

That keeps common repo bootstrap, container-toolkit wiring, copied support files, and driver-lane-specific package/build behavior separated instead of repeated across image recipes.

## Naming

The public tags are uniform and short.

- no `workstation-*` prefix
- no `default` suffix in published names
- no `nvidia-legacy` naming in the supported recipe tree or manifest

## Registry namespace

Current image references use `ghcr.io/pelagians/<image>:<tag>`.

## Architecture-first builds

CI first selects x64 or ARM64, then reuses the server/workstation workflow for
that architecture. The 24 shared recipes declare supported OCI platforms; each
CI build overrides that list with its single native platform. A gated publisher
combines the 45 builds into signed public indexes and preserves existing ARM
references as compatibility aliases. See [publishing](image-publishing.md). See [ARM candidates](arm-image-lanes.md) for package
differences, rebase-picker compatibility and pending qualification.
