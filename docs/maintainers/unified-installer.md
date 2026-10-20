# Unified installer (draft qualification)

## Audit and implementation layout — 2026-10-20

Baseline: stable e71fb4b0. The Alma 10 Anaconda installer already separates its
runtime and installed payload, preserves manual storage/users, defaults to XFS,
and restores signed EFI assets from bootupd. Keep its script/workflow unchanged.
The shared TSV is authoritative for 45 native candidates and 24 shared public
image names; reuse its strict parser in both build tooling and setup. Do not
introduce a second inventory or replace ARM compatibility aliases.

`current rebase` provides an architecture-filtered fzf picker, but no hardware
qualification or persistent transaction state. Leave that established interface
alone. Add `current setup` dispatch before just, with a reusable Python package
in `files/setup/usr/lib/current_setup`. Shared destination images include its
boot-state reconciler so staging can be distinguished from successful boot.

`core-base.yml` includes k3s, PCP and Tailscale; `core.yml` adds Cockpit/Ceph and
development tools. Neither is a minimal bootstrap. `recipes/bootstrap.yml` uses
the Fedora bootc base, a small package set, the existing signing module and
repository public key. Fedora is provisional for hardware enablement; Alma's
older kernel and EL10 CPU baseline constrain the initial bootstrap. No distro
transition is boot-qualified yet. Keep firmware/kernel/shim from the base.

The new `installer/unified` runtime follows the existing Anaconda model using
the unified image-builder CLI and `bootc-generic-iso`. Installer-only credentials,
Anaconda services and packages never enter the bootstrap payload. Use native
runners and architecture-specific EFI assets. Existing installer workflows stay.

First-boot prompting belongs to an authenticated local console login, guarded by
a vendor bootstrap marker. No root autologin or blocking system service reads
from a user's terminal. SSH remains usable; `sudo current setup` resumes. State
lives in `/var/lib/current/setup`, never in a bootstrap-owned default.target.
Destination display-manager reconciliation retains authority.

## Consulted upstream documentation

- [BlueBuild](https://blue-build.org/) and [ISO wrapper](https://blue-build.org/how-to/generate-iso/): the wrapper uses build-container-installer.
- [bootc](https://bootc.dev/) and [switch](https://bootc.dev/bootc/man/bootc-switch.8.html): digest targets, signature-policy enforcement and explicit reboot.
- [image-builder ISOs](https://osbuild.org/docs/developer-guide/projects/image-builder/advanced/bootc/isos/): prefer bootc-generic-iso; bootc-installer is historical; separate runtime and embedded payload.
- [CLI usage](https://osbuild.org/docs/developer-guide/projects/image-builder/usage/): local container storage, buildroot, filesystem and seed options.
- [CLI installation](https://osbuild.org/docs/developer-guide/projects/image-builder/installation/): native x64 and ARM container tooling.

Upstream documents an Anaconda systemd-remount-fs failure. Record it in VM tests;
do not silently mask the unit. Cross-distribution bootloader, SELinux, /etc merge
and retained network/user configuration need explicit tests before qualification.
