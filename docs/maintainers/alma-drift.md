# Alma Drift

These are the intentional lane differences that remain between the Alma distro lanes.

## Alma 9

- provides standard and NVIDIA open server/GNOME/COSMIC candidates on x64 and ARM
- retains the proprietary NVIDIA 580 compatibility lane on x64
- ARM has no equivalent prebuilt proprietary R580 module-stream contract
- uses version 9 explicitly for new standard/open recipes

The internal layer file now matches the public lane naming: `recipes/layers/alma9/nvidia-580.yml`.

## Alma 10

- is the stable baseline lane
- supports `server`, `gnome`, and `cosmic` environments
- supports standard images and `nvidia-open`
- does not support the NVIDIA 580 compatibility lane

## Shared across both Alma lanes

- workstation remains available with GNOME and COSMIC
- Alma-family repository setup, including EPEL/CRB enablement and subscription-manager cleanup, belongs in `recipes/layers/alma/core.yml`
- shared k3s, Ceph host, Cockpit, Podman, Vulkan, and base runtime support stay in the shared contracts where possible
- Alma-version ROCm userspace drift stays in the matching Alma version layer

When adding new divergence, prefer `recipes/layers/alma/` for Alma-family drift and `recipes/layers/alma9/` or `recipes/layers/alma10/` for version-specific drift instead of weakening the shared contracts.

## Temporary EL9 COSMIC asset source

The 2026-10-20 build failed on all five Alma 9 COSMIC candidates: both EL9
Enterprise COSMIC repositories advertised `cosmic-settings`/`cosmic-osd` 1.9.0
requiring `cosmic-icon-theme >= 1.9.0`, but contained no icon-theme package.
See [the failed run](https://github.com/Pelagians/Current/actions/runs/39396476017).
The full dependency probe also found that `cosmic-wallpapers` is absent.

`alma9/cosmic-assets.yml` runs before the Alma COSMIC consumers. It installs only
`cosmic-icon-theme.noarch` and `cosmic-wallpapers.noarch` from the same publisher's
[EL10 repository](https://download.copr.fedorainfracloud.org/results/ligenix/enterprise-cosmic/rhel+epel-10-aarch64/),
using a transaction-local repository restricted to those two package names by
`includepkgs`. RPM signature checking is explicitly enabled with the existing
[Enterprise COSMIC project key](https://download.copr.fedorainfracloud.org/results/ligenix/enterprise-cosmic/pubkey.gpg).
There is no persistent extra repository or general EL10 package source on EL9.

The inspected `1.10.0-1.el10.noarch` RPMs verified against that key in a temporary
RPM database. The icon theme's 683 payload paths are under `/usr/share/icons/`
and `/usr/share/licenses/`; wallpaper paths are under `/usr/share/backgrounds/cosmic`
and `/usr/share/licenses/`. Neither package has package scriptlets or native
executable/library payload. The icon theme's ordinary dependency is
`pop-icon-theme`, resolved from the native EL9 COSMIC repository; wallpapers
require only RPM capabilities. The asset step enables that EL9 repository before
its transaction, because the ordinary Alma COSMIC layer runs later. Qualification
must begin without that repository already configured to catch ordering failures.

Build checks require both packages to be noarch, reject package scriptlets and
payload paths outside the data directories, and require an installed icon theme
satisfying the EL9 consumers' minimum version. Signature and contract failures
fail the build. This exception permits those assets, not EL10 desktop libraries
or programs.

Remove this layer, script and recipe includes once both EL9 CPU repositories
publish signed compatible assets and the complete EL9 COSMIC transaction
resolves without the supplemental source. Update the matrix graph and isolated
source/signature/version regressions when retiring the exception.

Local qualification installed both signed RPMs in a disposable native Alma 9 ARM
container and resolved the full package request from `alma/cosmic.yml` plus
`shared/workstation-cosmic.yml` with `--assumeno`, using the existing ARM
fingerprint-PAM prerequisite. The solve selected 258 packages without dependency
errors. Both CPU repositories' asset RPMs were signature-verified; their file
paths/content digests, requirements and package scriptlets match, although RPM
archive checksums differ. Isolated fixtures cover both source URLs, signature failures,
wrong lanes/architectures, old versions, scriptlets and unexpected payloads.
Full native image builds and booted login/session qualification remain required;
local x64 container execution was unavailable on the ARM host.
