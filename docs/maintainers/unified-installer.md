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

## Backend and frontend contract

`hardware.py` reads CPU flags (intersection across cores), PCI display devices,
UEFI variables and DMI/device-tree platform strings. `matrix.py` is the same
strict parser used by `scripts/image_matrix.py`; the latter retains build-side
recipe graph traversal and existing public interfaces. `execution.py` owns
subprocesses, registry resolution, effective signature-policy checking, locking,
atomic/fsynced state and boot observation. `cli.py` owns only presentation,
questionnaire orchestration and confirmation. No menu library is required.

`current setup plan` emits schema-1 JSON with hardware, preferences, recommended
candidate, eligible alternatives, rejection reasons and warnings. It is read-only
and does not contact a registry. `--fixture`, `--matrix` and `--compatibility`
overrides are permitted only for plan/dry-run. Real staging always discovers the
host again and reads the installed vendor catalogue. A GUI can call these Python
functions or consume the JSON plan; keep execution behind ordinary administrator
authentication and explicit confirmation. Do not put arbitrary image-reference
entry, shell commands or hardware overrides into a privileged GUI API.

The questionnaire asks distribution, server/workstation and (for workstations)
desktop. Auto currently prefers Fedora, avoiding an initial cross-distribution
switch. Within that distribution it prefers a compatible open NVIDIA lane, then
R580, then standard. Preferences filter candidates before ranking; the inventory
never silently invents a missing distro/driver combination.

The companion JSON is compatibility evidence, not another image inventory:

- x86_64 and aarch64 are accepted; UEFI is required in this first implementation.
- Alma 9 requires x86-64-v2; Current's default Alma 10 lane requires v3. The
  separate Alma x86-64-v2 product is not in Current's inventory. See
  [Alma 10 architecture policy](https://wiki.almalinux.org/release-notes/10.0.html).
- AMD/Intel and recognized virtual graphics use standard images without claiming
  device-level rendering qualification. Headless systems also use standard.
- The NVIDIA shortlist records six exact PCI IDs from the linked R580 supported
  chips table and the open-module Turing-or-newer contract. It deliberately does
  not infer compatibility from numeric ranges, PCI vendor alone or device names.
  R580-only and open-capable GPUs are distinguished; multiple NVIDIA GPUs require
  the intersection of their driver sets. Hybrid display routing remains untested.
- Unknown GPUs require manual selection. Unknown NVIDIA IDs only offer standard
  fallback, with an explicit warning that graphics/acceleration may not work.
  Add further IDs only with source evidence and tests; subsystem-specific quirks
  may require stricter matching later.
- NVIDIA candidates are withheld when Secure Boot is enabled or unknown because
  signing/enrollment is not driver-qualified. Standard fallback is still marked
  experimental. This does not establish Secure Boot qualification of the base.
- Apple/Asahi platform strings and non-UEFI ARM fail closed. Other ARM UEFI
  candidates still need board/firmware testing; successful native image builds do
  not provide an Apple hardware port.

All recommendations report inventory-only build status and false boot/driver
qualification. Registry resolution verifies a single native child, architecture,
Linux OS, digest, bootc/revision labels and `io.current.setup-api=1`. The latter
ensures the destination includes the reconciler. A candidate needs independent
build, boot and driver evidence before those claims can change. No qualification
flag is inferred from a signed artifact.

## Trust, state and recovery

The bootstrap uses the existing repository `cosign.pub` and BlueBuild signing
module. Its build-time policy extension requires that same key with repository
identity binding for Current destinations. Setup rejects a more specific
permissive override. `bootc switch --enforce-container-sigpolicy --retain` performs
signature verification and staging; errors from either remain recovery errors.
There is no insecure switch option, alternate registry or alternate key input.
ISO construction separately verifies the exact bootstrap digest with cosign.

State schema 1 is stored root-only in `/var/lib/current/setup/state.json` with a
nonblocking flock. Each transition uses a same-directory temporary file, fsync,
rename and directory fsync. A source deployment receipt, selection, hardware,
resolved target/revision, boot ID and phase history remain available on failure.

| State | Meaning / next action |
| --- | --- |
| not-configured | No selection; authenticate and start the questionnaire. |
| image-selected | Review accepted; validation/staging pending or interrupted. |
| image-staged | Exact native digest observed in bootc's staged slot; reboot pending. |
| destination-booted | Exact target reference and digest observed in booted slot. |
| complete | User accepted networking and intended login/session after destination boot. |
| recovery-required | A command failed, target disappeared, or a rollback was observed; inspect and resume. |

The vendor systemd service only observes state; it never downloads, switches or
reboots. It is inert without a receipt. Interrupted staging is reconciled against
bootc status before retry; an existing unrelated staged deployment is never
intentionally replaced. Do not run separate bootc transactions concurrently with
setup: the setup lock serializes setup sessions, not every external bootc client.
State corruption fails closed and is retained for diagnosis. Do not delete state
as the first recovery step.

The console profile hook requires an interactive authenticated local login and
bootstrap vendor marker. Wheel users authenticate through normal sudo; root is
locked by the installer. SSH never auto-starts the questionnaire. No default
password, autologin, sudo exemption or root getty is installed in the payload.
The Anaconda runtime's install/root login arrangement is confined to the ISO.

The bootstrap's default target is vendor-owned under `/usr/lib`, not a persistent
`/etc/systemd/system/default.target` override. A leftover profile file is inert
when the vendor marker disappears. The destination owns its display manager and
default target; no user homes, session preferences or NetworkManager profiles are
rewritten. The shared workstation reconciliation remains unchanged.

Rollback: keep the previous deployment and choose it from the boot menu if the
new destination cannot boot. From a booted destination, `sudo bootc rollback`
stages the previous deployment; reboot explicitly when ready. Capture `bootc
status --json`, `journalctl -b -u current-setup-reconcile.service`, the setup receipt,
and the previous boot's journal before changing anything else. Resume with
`sudo current setup`. A newer unrelated staged update requires operator review.
`--retain` preserves the prior image reference; this is not an archival guarantee
across later unrelated upgrades. Snapshot the disposable VM disk for qualification.

Setup stages a digest to prevent tag movement between validation and installation.
It stays pinned: `bootc upgrade` will not track `latest` while pinned. After
qualification, explicitly use the ordinary Current rebase flow to choose a moving
channel. Setup itself does not silently move the digest back to a tag.

## Native ISO builds

The recipe pins Fedora 44's multi-architecture base index. The installer runtime
uses the same pinned base but adds Anaconda, native shim/CD-boot GRUB, fonts,
initramfs and ISO tools. The builder is also pinned by index digest. The wrapper
refuses architecture emulation, unpinned inputs and nonempty output directories;
sets XFS/seed 42; records source commit and runtime image ID; and writes a portable
SHA256 checksum beside `current-installer-x86_64.iso` or
`current-installer-aarch64.iso`.

The native workflow builds and signs isolated bootstrap repositories
`current-bootstrap-x86_64` and `current-bootstrap-aarch64`. Unique run/attempt tags
and revision labels prevent an old or concurrent build from being installed.
These are intermediate payload artifacts, not new user-facing destination lanes.
The eventual distribution remains two ISO names. Existing destination indexes
and ARM migration aliases remain unchanged. ISO artifacts are experimental CI
artifacts, not release assets.

After building/signing a bootstrap, run on a native Linux builder with sudo,
Podman and cosign (both image-builder and its native buildroot are containers):

```bash
# Substitute the verified native bootstrap digest; do not paste the placeholder.
CURRENT_INSTALLER_PAYLOAD_REF='ghcr.io/pelagians/current-bootstrap-x86_64@sha256:<digest>' \
  bash scripts/build-unified-installer-iso.sh

# On an aarch64 builder:
CURRENT_INSTALLER_ARCH=aarch64 \
CURRENT_INSTALLER_PAYLOAD_REF='ghcr.io/pelagians/current-bootstrap-aarch64@sha256:<digest>' \
  bash scripts/build-unified-installer-iso.sh
```

Alternatively run **Build experimental unified installer** on the feature branch.
The workflow prepares the native BlueBuild recipe, checks the built revision,
verifies its signature and supplies its digest automatically. It uses x64 and
native GitHub ARM runners. It does not flash media or install on runner disks.

The script accepts pinned `CURRENT_IMAGE_BUILDER` and `CURRENT_INSTALLER_BASE`
overrides and a new `CURRENT_INSTALLER_OUTPUT_DIR`. Package repositories and
BlueBuild modules still evolve: pinned OCI inputs and a fixed seed improve
repeatability but do not establish byte-for-byte reproducibility. Preserve
build logs, RPM metadata and receipts. For release reproducibility, qualify
snapshot package repositories and pin the module/tool versions as well.

## Qualification gates

No real installer boot or destination transition has been verified in this PR's
local environment. The development host is ARM64, lacks `/dev/kvm`, and had only
4.6 GiB free on the container-storage filesystem. A large local installer build
was not attempted. No host installation or host bootc mutation occurred.

| Transition / hardware | Status |
| --- | --- |
| Bootstrap Fedora 44 → Fedora server/GNOME/COSMIC | Implemented, experimental; UEFI VM boot required |
| Bootstrap Fedora 44 → Alma 10 server/GNOME/COSMIC | Experimental cross-distribution; bootloader/SELinux/network tests required |
| Bootstrap Fedora 44 → Alma 9 server/GNOME/COSMIC | Experimental downgrade/cross-distribution; same tests plus older userspace compatibility |
| Generic ARM64 UEFI | Native build path implemented; EFI/board/installer boot required |
| NVIDIA R580/open, hybrid systems | Synthetic recommendations only; physical rendering/module tests required |
| Apple Silicon/Asahi | Unsupported and rejected |

Use disposable UEFI VMs with a new virtual disk and snapshot. Never attach the
development host's block devices. For each distro, install the ISO interactively,
confirm XFS, networking, timezone and an administrator, then reboot and record
the authenticated setup launch. Use `--channel pr-29` for matching candidate
destination images after all native builds and the existing index publisher pass.
Older `latest` images without the reconciler intentionally fail validation.

Record ISO checksum, bootstrap/destination digest, source commit, EFI/bootloader
versions, bootc JSON, network profile and UID/home sentinel hashes. Test server
first, then both desktops with [workstation rebase qualification](workstation-rebase-qualification.md).
Check `systemd-remount-fs.service` explicitly against the upstream warning. Test
registry outage, rejected signature, interrupted staging, reboot, boot-menu
rollback, retained networking/credentials, setup resume and accepted completion.
Repeat with Secure Boot and representative GPU hardware separately. A container
lint pass or ISO build is not a successful installed boot.

Local regression commands (no real bootc mutation):

```bash
python3 -m unittest discover -s scripts/tests -p 'test_runtime_setup.py' -v
python3 -m unittest discover -s scripts/tests -p 'test_image_unified_installer.py' -v
bash scripts/validate-runtime-artifacts.sh
bash scripts/validate-image-matrix.sh
```

The systemd graph checks need ordinary local socket access; a sandbox denial is
an environment failure and must not be hidden by skipping the assertion.

### Initial native build evidence

[CI run 39517286831](https://github.com/Pelagians/Current/actions/runs/39517286831)
built both native bootstraps and passed the isolated runtime/image validators.
Bootstrap lint passed 11 checks with warnings for runtime-directory, log and
`/var` tmpfiles content; these are not boot qualification. Both native installer
runtimes also built with native EFI assets and its Anaconda initramfs.

The first assembly attempt reproduced an upstream containers-storage constraint:
`Copying this image would require changing layer representation ... Destination
specifies a digest`. Skopeo cannot reserialize a local destination named by the
remote compressed-manifest digest. The wrapper now verifies/pulls the immutable
signed remote artifact first, creates a digest-derived local storage tag, and
checks that both names resolve to the identical image ID. Only that local name
is passed for embedding and the Kickstart source. The installed target remains
the original immutable registry reference. No mutable remote tag is trusted and
no signature verification is bypassed. The local transport reference and original
registry target are recorded separately in the build receipt. [Native run 39518324445](https://github.com/Pelagians/Current/actions/runs/39518324445)
validated this transport change on both architectures at source candidate
`c4ad00b92db854ac0981682afe0f687efcde050d`. Both complete bootstrap → Anaconda
runtime → generic ISO builds succeeded, with checksum and provenance receipts:

- [x86_64 artifact](https://github.com/Pelagians/Current/actions/runs/39518324445/artifacts/12309972577): `current-installer-x86_64.iso` (artifact archive approximately 2.15 GB).
- [aarch64 artifact](https://github.com/Pelagians/Current/actions/runs/39518324445/artifacts/12310117567): `current-installer-aarch64.iso` (artifact archive approximately 1.98 GB).

Artifacts expire after seven days; rebuild from the recorded inputs when needed.
These sizes/digests describe CI archives, not installation or boot qualification.
Osbuild also emitted nonfatal read-only `/usr/local/sbin` tmpfiles warnings;
retain the logs and inspect the installed system during boot qualification.
The final follow-up adds exact-digest/wildcard trust-policy precedence and malformed
metadata guards; its isolated setup tests pass, but the linked ISO artifacts
predate that follow-up. Final-HEAD native rebuild results must be checked separately.

Local validation passed all 77 runtime and 65 image tests, including 33 new setup
and installer cases, plus Actionlint 1.7.12, YAML/shell checks and `git diff --check`.
No UEFI VM installation or destination boot is included in these results.

### Disposable UEFI qualification harness

`test-unified-installer-vm.yml` downloads an explicitly selected ISO run, checks
its checksum and exact source receipt, and runs
`scripts/test-unified-installer-vm.py` on a native x86_64 runner. It creates a new
64 GiB sparse QEMU disk and a private OVMF variable store; existing output paths
are refused. No host block devices, forwarded host ports, shared folders or
privileged guest agents are attached. KVM is detected, with bounded software
emulation as a diagnostic fallback. GitHub does not guarantee nested
virtualization; a runner failure is not an installer qualification result.

The original ISO boots first with its default arguments for graphical screenshot
review. A second boot uses the original ISO's UEFI GRUB, kernel, initrd and payload,
with a test-only Kickstart supplied through QEMU's user-network gateway. It answers
storage/timezone/user questions and appends a serial console. That automated
storage path is distinct from manually exercising Anaconda's storage/user UI.
The locked root account and normal wheel-user password/sudo authentication remain
in force. Test credentials are generated per VM, redacted from evidence and never
added to an image. Only the newly created `vda` disk is eligible for partitioning.

The harness attempts authenticated first-boot prompting and safe exit, manual
resume on the chosen PR channel, real signature-enforced destination staging,
reboot, retained UID/home sentinel/NetworkManager profile hashes, destination
completion, already-completed resume and bootc rollback. No registry response,
bootc command or hardware discovery is mocked inside the VM. A failed stage keeps
its recovery receipt and fails the test. The current server flow does not qualify
desktop login, GPU drivers, Secure Boot, manual storage UI, interruption under real
power loss or ARM firmware. Screenshot capture alone is not a graphical success
assertion; inspect the frames and logs before recording that result.

Artifacts contain a JSON result, source/digest receipt, QEMU/serial/Anaconda logs
and screenshots. Disk images, EFI variables and Kickstart credentials remain
private ephemeral runner files. Use separate runs for `fedora`, `alma10` and
`alma9`; the workflow accepts the ISO run/revision and destination channel. Record
both ISO and destination source identities: a moving PR channel may be newer
than the installed bootstrap. Keep this workflow experimental until actual
results are recorded below.
