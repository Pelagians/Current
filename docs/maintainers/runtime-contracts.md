# Runtime Contracts

The purpose of the refactor is to keep layer ownership explicit while simplifying the public image model.

## Cross-distro core contract

`recipes/layers/shared/core-base.yml` owns the low-level baseline shared by every supported image.

That includes:

- common core packages and runtime defaults
- branding and `os-release` metadata
- host Vulkan userland/tooling where supported by the platform lane
- base runtime files and shared Justfile command surface
- inclusion of cross-image feature and policy layers

`recipes/layers/shared/core-base.yml` should not grow into a catch-all layer. Shared features with their own policy surface should live in explicit feature or policy layers.

Current delegated layers:

- `recipes/layers/features/k3s.yml`: k3s binary and disabled server/agent unit baseline
- `recipes/layers/features/pcp.yml`: PCP local metrics collection and history
- `recipes/layers/features/tailscale.yml`: Tailscale package and daemon baseline
- `recipes/layers/shared/system-policy.yml`: shared groups, kernel args, and masked update/counting services

`recipes/layers/shared/core.yml` owns the small distro-neutral host/operator package baseline shared by every supported image. It runs after `shared/core-base.yml` and any distro-family repository setup needed to make the shared package set available.

ROCm userspace is not a universal cross-image promise. It belongs to the platform lanes that can support the package set cleanly, currently Alma 10 and Fedora. Alma 9 should remain focused on the NVIDIA 580 compatibility lane.

## Distro core deltas

- `recipes/layers/alma/core.yml` owns Alma-family repository setup such as EPEL/CRB enablement and subscription-manager cleanup.
- `recipes/layers/fedora/core.yml` owns the Fedora edge-lane delta such as `dnf5-plugins`, Fedora-native ROCm packages, and Fedora-specific package drift.
- `recipes/layers/alma9/core.yml` and `recipes/layers/alma10/core.yml` own only the remaining Alma-version drift that does not belong in the shared Alma-family layer.
- `recipes/layers/alma10/core.yml` may carry ROCm-related Alma 10 enablement when that support belongs to the Alma 10 lane rather than the cross-distro contract.

## Feature overlays and shared remainder

`recipes/layers/features/cockpit.yml` owns the Cockpit admin surface.

`recipes/layers/features/ceph.yml` owns the shared Ceph host prerequisites.

`recipes/layers/features/k3s.yml` owns shared k3s runtime capability.

`recipes/layers/features/pcp.yml` owns shared PCP runtime capability.

`recipes/layers/features/tailscale.yml` owns shared Tailscale runtime capability.

`recipes/layers/shared/system-policy.yml` owns shared system policy that is not tied to one distro or role.

`recipes/layers/shared/core.yml` owns the remaining host/operator package baseline:

- fastfetch, fzf, zstd, gcc, distrobox, and podman-compose
- inclusion of Cockpit and Ceph feature overlays

## Flatpak contract

`recipes/layers/shared/flatpak-base.yml` is for workstation Flatpak runtime and app governance.

It owns:

- Flatpak and `xdg-desktop-portal` package baseline
- user `flathub` remote for personal installs
- hidden-at-rest admin-managed `org-system` remote, temporarily enumerable for dependency resolution
- shared managed system app set
- Flatpak policy payloads under `files/flatpak/base/`
- graphical session environment import for D-Bus activation and `systemd --user`

`recipes/layers/shared/flatpak-cleanup.yml` owns the system-scope maintenance helper used by startup hooks and Justfile targets.

Managed system Flatpak transactions require root and use a fixed executable path and root-owned `/run/current-flatpak-maintenance.lock` with `flock`. Sequence: acquire lock, inspect the existing managed remote, enable enumeration and dependency use, run the operation, clean unused refs after a successful update, restore `--no-enumerate --use-for-deps`, release lock. An absent remote is allowed; an existing remote with an unexpected URL, disabled state, or disabled GPG verification is rejected for update/repair/setup. No remote trust keys or URLs are rewritten.

The EXIT trap reports restoration failures without erasing an earlier operation failure. HUP/INT/TERM stop the child before restoring. SIGKILL and power loss cannot be trapped. The next managed operation restores policy; the startup unit also has a locked `ExecStopPost=... ensure` recovery path. Root can still bypass these advisory lifecycle controls.

The BlueBuild v2 `ExecStart` is wrapped as one `setup` transaction, including first-run remote creation. Separate pre/post invocations cannot hold a lock across BlueBuild setup. The expected upstream executable is `/usr/libexec/bluebuild/default-flatpaks/system-flatpak-setup`; a missing or changed executable fails visibly. BlueBuild retains ownership of app reconciliation. Current does not reinterpret errors swallowed internally by upstream setup.

There is no explicit GL/VAAPI extension warmup: Flatpak transaction metadata selects related extensions and hardware-specific branches. Explicit runtime installs auto-pin; historical pins cannot safely be attributed to Current and are left intact. Cleanup only calls `flatpak --system uninstall --unused -y --noninteractive`.

`00-current-flatpak.rules` runs before upstream `org.freedesktop.Flatpak.rules` (which grants some wheel operations silently) and normal distro `50-default.rules`. Current's `25-gnome.rules` does not handle Flatpak. The Flatpak rule permits only `appstream-update` and `metadata-update` without authentication for active local sessions. All other Flatpak actions, including unknown future IDs, require wheel membership and `AUTH_ADMIN`, not `AUTH_ADMIN_KEEP`. A scoped admin-identity rule enforces wheel across distro lanes without changing other services. Per-user operations normally do not invoke the system helper/polkit. Sudo/root authorization remains governed by the host sudo policy, including its credential-cache behavior.

Audit sources: [Flatpak policy and helper](https://github.com/flatpak/flatpak/tree/ddcd5c4ebb545a7a1e7225a96bd44256c61ac5cb/system-helper), [Flatpak transaction dependency and pin handling](https://github.com/flatpak/flatpak/blob/ddcd5c4ebb545a7a1e7225a96bd44256c61ac5cb/common/flatpak-transaction.c), [BlueBuild default-flatpaks v2](https://github.com/blue-build/modules/tree/7d51cca7502a41ef4fd05ad75ff9702f2ef8d147/modules/default-flatpaks/v2/post-boot), and [polkit rule ordering](https://polkit.pages.freedesktop.org/polkit/polkit.8.html). The upstream action set includes `update-remote` and both parental-control overrides; `DeployAppstream` is a D-Bus method, not an allowed polkit action ID.

Behavior tests run through `scripts/validate-runtime-artifacts.sh` using Python 3, Bash, flock, and Node.js. They model runtime branch migration and pin/dependency retention, exercise signal restoration and lock contention, and execute rule decisions and extracted Justfile shell bodies. These are deterministic mocks, not proof of real Flatpak dependency resolution or a running polkit daemon. Image smoke tests must check the installed Flatpak version/action policy, complete distro/local rule ordering, authentication prompts, BlueBuild/systemd stop behavior, GNOME/KDE branch transitions, and actual graphics extensions. Administrators can override image policy with earlier local rules; inspect both `/etc/polkit-1/rules.d` and `/usr/share/polkit-1/rules.d` in basename order.

`recipes/layers/shared/flatpak-gnome.yml` and `recipes/layers/shared/flatpak-cosmic.yml` own desktop portal backend selection and environment-specific Flatpak remotes/apps.

Server recipes do not consume these layers and should not receive desktop portal backend logic.

The system Flatpak model is intentionally opinionated. It reduces drift on multi-user workstations by keeping curated shared apps separate from each user's personal `flathub` installs.

## Workstation contract

`recipes/layers/shared/workstation-common.yml` is the DE-agnostic workstation orchestrator.

It should stay small and delegate real ownership to explicit sublayers:

- `workstation-substrate.yml`: shared desktop, hardware, audio, printing, scanning, camera, input, language, and base workstation packages
- `workstation-admin-tools.yml`: workstation-only diagnostics, storage, network, and admin utilities
- `workstation-policy.yml`: graphical target, display-manager reconciliation, and workstation sleep policy
- `workstation-user-tools.yml`: opinionated user-facing workstation tooling such as Homebrew and Brave Origin Beta

`recipes/layers/shared/workstation-modern.yml` owns the extra workstation delta shared by the Alma 10 and Fedora lanes.

Workstation images are the operator desktop and laptop lane. They should remain useful as normal desktop systems while still sharing the same image-based operating model as the server and lab lanes.

## Workstation environment contract

GNOME and COSMIC are workstation-environment implementations.

- `workstation-gnome.yml` owns GNOME session, extension, and Software integration behavior; `flatpak-gnome.yml` owns GNOME portal selection and GNOME-specific Flatpaks.
- `workstation-gnome-modern.yml` owns the extra GNOME app delta shared by the Alma 10 and Fedora lanes.
- `workstation-cosmic.yml` owns common COSMIC session, greeter, and validation; `flatpak-cosmic.yml` owns COSMIC portal selection and COSMIC Flatpak remotes; `alma/cosmic.yml` and `fedora/cosmic.yml` own distro source/config drift.
- `files/gnome/shared/usr/share/current/workstation/desktop.env` and `files/cosmic/shared/usr/share/current/workstation/desktop.env` are the family markers consumed by the shared DM helper.

## NVIDIA contract

- `shared/nvidia-base.yml` owns the common NVIDIA repo bootstrap, NVIDIA container toolkit setup, NVIDIA PCP PMDA package, copied NVIDIA support payloads, and kernel args.
- `shared/nvidia-open-common.yml` owns the open-driver helper shim.
- `shared/nvidia-common.yml` and `shared/nvidia-open.yml` own the Alma-family NVIDIA lanes.
- `fedora/nvidia-open.yml` owns only the Fedora-specific open-driver delta on top of the shared NVIDIA layers.
- `fedora/nvidia-580.yml` owns the Fedora-specific proprietary R580 akmod build path: Negativo17 repo setup, matched kernel-devel install, akmods build, `modinfo` verification, userspace package install, and akmod/kernel-devel cleanup.

## Current namespace

`current` is the only project command wrapper. Justfile command payloads live under `/usr/share/current/just`. Runtime data payloads live under `/usr/share/current`. New scripts and workflows use `CURRENT_*` environment variables.
