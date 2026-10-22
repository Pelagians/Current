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

The final x86_64 ISO passed complete Fedora, Alma 10 and Alma 9 server flows in
disposable UEFI/KVM VMs, using the shipped partitioning defaults and enforcing
SELinux on both bootstrap and destination. Broader hardware and recovery
qualification remains pending as recorded below. The development host is ARM64, lacks `/dev/kvm`, and had only
4.6 GiB free on the container-storage filesystem. A large local installer build
was not attempted. No host installation or host bootc mutation occurred.

| Transition / hardware | Status |
| --- | --- |
| Bootstrap Fedora 44 → Fedora server | Final ISO full UEFI/KVM flow passed, including XFS repair-tool recognition, enforcing SELinux, completion and rollback; physical hardware unqualified |
| Bootstrap Fedora 44 → Fedora GNOME/COSMIC | Experimental; desktop login and rendering tests required |
| Bootstrap Fedora 44 → Alma 10 server | Final ISO full UEFI/KVM flow passed, including SELinux finalization, XFS repair-tool recognition, enforcing SELinux, completion and rollback |
| Bootstrap Fedora 44 → Alma 10 GNOME/COSMIC | Experimental; desktop login and rendering tests required |
| Bootstrap Fedora 44 → Alma 9 server | Final UEFI/KVM flow passed with parent=0/exchange=0 XFS, Alma 9 repair-tool recognition, enforcing SELinux, completion and rollback; journal/shutdown warnings recorded below |
| Bootstrap Fedora 44 → Alma 9 GNOME/COSMIC | Experimental; desktop login and rendering tests required |
| Generic ARM64 UEFI | Native build path implemented; EFI/board/installer boot required |
| NVIDIA R580/open, hybrid systems | Synthetic recommendations only; physical rendering/module tests required |
| Apple Silicon/Asahi | Unsupported and rejected |

Use disposable UEFI VMs with a new virtual disk and snapshot. Never attach the
development host's block devices. For each distro, install the ISO interactively,
confirm XFS, networking, timezone and an administrator, then reboot and record
the authenticated setup launch. Use `--channel br-codex_unified-installer` for matching candidate
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

## Qualification history

The following entries preserve results at their recorded revisions, including
superseded failures and artifacts. Use the qualification table above and the
latest receipts below for the current state.

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

### Final implementation build verification — 2026-10-20 (Vancouver)

[Push run 39519851052](https://github.com/Pelagians/Current/actions/runs/39519851052)
succeeded on both native architectures. Both archived `build-inputs.txt` receipts
identify exact branch source `d00468df19b3dca60d51d4ba1a65b0a54602dd60`, including
the final policy-precedence and malformed-metadata guards. This closes the prior
native rebuild gap. Later harness-only changes do not change the installed payload.

| Architecture | ISO SHA256 from archived receipt | Bootstrap digest |
| --- | --- | --- |
| x86_64 | `546538e79b6d235ebfe66efcca98f736fc360dd93d86a1cb2aa7578bed1e00a8` | `sha256:74ea3d799b760dd465edb65743ec8f7ff2b9eab65548b059ebb5d457f88cf2cc` |
| aarch64 | `a02641771479945664eabe77c5dd6557bb5042af0319b1535c9953aeb400d5f9` | `sha256:d24a7f92986b2b009d0c7ac0391c21f4dcb2355e8e3d62a80b6cfa042bb9263a` |

Artifacts: [x86_64](https://github.com/Pelagians/Current/actions/runs/39519851052/artifacts/12310459257),
[aarch64](https://github.com/Pelagians/Current/actions/runs/39519851052/artifacts/12310608726).
The small source/checksum receipts were read independently; the VM harness also
hashes the complete downloaded ISO before boot. These are ISO checksum values,
not GitHub ZIP archive digests. PR-event builds use synthetic merge revisions;
do not silently equate their receipt revision with the branch head.

Harness safety/receipt tests increase local validation to 144 passing tests
(77 runtime, 67 image), with Actionlint and diff checks passing. The runtime suite
requires the bundled Node binary on PATH and ordinary systemd socket access.
The harness follows the upstream [Kickstart bootc contract](https://pykickstart.readthedocs.io/en/latest/kickstart-docs.html#bootc)
and [QEMU monitor interface](https://www.qemu.org/docs/master/system/monitor.html).

[UEFI run 39521364548](https://github.com/Pelagians/Current/actions/runs/39521364548)
verified the full x86_64 ISO checksum, used working KVM on a 15 GiB runner, and
booted the unmodified ISO into graphical Anaconda. The 135/180-second screenshots
were visually inspected: the language-selection welcome screen is rendered.
This qualifies initial UEFI/graphical installer startup only, not installation.
The first continuation failed in the harness before installation: `fdspawn`
closed a serial descriptor still owned by a Python socket, whose later destructor
closed the next QMP descriptor. Ownership is now explicitly transferred with
`detach()`, and QMP/serial handles are closed before restarting. Three real local
QEMU socket lifecycles passed after the fix using an empty 64 MiB emulated machine,
with no disks or guest OS attached. This socket regression check is not boot
qualification. The same original ISO must now continue through installation.

[Diagnostic run 39522612550](https://github.com/Pelagians/Current/actions/runs/39522612550)
repeated the graphical smoke boot but was stopped to inspect a stalled continuation.
Its serial transcript shows keyboard setup text interleaved with serial `linux`
commands: the ISO's GRUB already provided serial input, and the harness consumed a
stale prompt. GRUB rejected the corrupted commands and never started the kernel.
This is a harness failure, not an Anaconda installation result. The continuation
now waits for the rendered menu, uses one serial command stream, checks every
GRUB command for errors, and requires an observed kernel-start message. Anaconda
errors also upload an explicit marker so the harness can stop promptly. The
cancelled run's JSON still says `running` because runner termination interrupted
receipt finalization; the Actions cancellation status is authoritative.

[Installation run 39525121044](https://github.com/Pelagians/Current/actions/runs/39525121044)
booted graphical Anaconda, deployed the checksum-bound bootstrap through its real
bootc payload task, installed the Fedora shim/GRUB EFI entry, and rebooted to the
new administrator's password-authenticated console login. Normal sudo authentication
automatically launched the distribution questionnaire; `q` paused it successfully.
`systemd-remount-fs.service` succeeded, and NetworkManager acquired a DHCP lease.
These are real installed-bootstrap observations, not a destination qualification.

The run used Anaconda `44.30-2.fc44` and exposed a material storage defect: automatic LVM partitioning created a
separate `/home` volume, but the account's home was absent on first boot. Anaconda's
`packaging.log` shows it unmounting and removing `/mnt/sysimage/home` before bootc
deployment, then binding only `/proc`, `/sys`, `/var` and `/boot`. The first boot
mounted `var-home.mount`, hiding the account directory created on the root volume.
This is consistent with the older Anaconda mount assembly path. Upstream
[commit dc4d94d](https://github.com/rhinstaller/anaconda/commit/dc4d94d279fee544b9ab58cef57a3987172963a2)
now preserves user mount points and handles them in `PrepareBootcMountTargetsTask`;
that source is not evidence that the RPM in this ISO contains the fix. Do not
qualify separate-home installation or silently recreate a home after boot.

The next bounded test uses the documented
[`autopart --nohome`](https://pykickstart.readthedocs.io/en/latest/kickstart-docs.html#autopart)
layout, and asserts that the installed home exists and is writable. This test-only
choice does not fix or qualify the shipping automatic partitioning defaults.
The harness also now waits for bash after sudo exits, disables terminal echo and
distinguishes prompt output from echoed commands. The previous run timed out in
that synchronization before any destination staging attempt.

The installed kernel command line also retained `selinux=0` from the generic ISO
runtime. SELinux-enforcing installation and transitions are therefore unqualified;
capture `/proc/cmdline` and `getenforce` in subsequent tests. Resolve runtime versus
payload kernel-argument handling before promoting this ISO. Secure Boot remains
disabled in these disposable VM tests.

[Root-only diagnostic run 39528084333](https://github.com/Pelagians/Current/actions/runs/39528084333)
repeated installation and authenticated setup launch with `autopart --nohome`.
The login shell now entered `/home/currenttest`; the missing-home warning was
absent. A systemd OSC terminal marker immediately before the new shell prompt
exposed another harness parsing assumption. Prompt matching now tolerates those
markers and passed a real local Bash/PTY regression check. Writable-home and
full-flow assertions still require the next VM run.

[Run 39529174507](https://github.com/Pelagians/Current/actions/runs/39529174507)
adds explicit `selinux --enforcing` to test-only Kickstart answers and requires
`getenforce` to report `Enforcing` after installed login. Anaconda 44.30's
[security module](https://github.com/rhinstaller/anaconda/blob/anaconda-44.30/pyanaconda/modules/security/security.py)
honors this installed-system setting; runtime SELinux mode alone is not the
intended installed policy. This is a test, not yet a qualification result.

### Registry publication and enforcing-mode gate

[Destination run 39521369181](https://github.com/Pelagians/Current/actions/runs/39521369181)
passed all 45 native builds and the existing all-record/signature/index publisher.
Its `pr-29` indexes identify synthetic merge source
`52cd589cbde99f2c9bae7f010235eec98c3b84e5`. The real read-only setup resolver
successfully validated these x86_64 children against the live registry:

| Destination | Native digest |
| --- | --- |
| Fedora server | `sha256:776f85a171f439dcb7b2e17e2155bff382917d38b6f96116eaf8d56a58aceb93` |
| Alma 10 server | `sha256:a8096a6c9771a5738ec4d21861881c893c0296b24c65f91ea0dbb4ea7d7c8b7f` |
| Alma 9 server | `sha256:6a0b95ef642ae1505fe2353caabf28ad4ccb52122878368c474bbdd9d13a0cc3` |

Registry metadata and publisher signature verification do not prove a booted
transition. The ISO still names its own exact bootstrap digest and branch source.

[Run 39529174507](https://github.com/Pelagians/Current/actions/runs/39529174507)
passed authenticated first-boot launch, safe exit, shell synchronization and the
writable-home assertion with root-only storage. Installed `/sysroot` was XFS and
`systemd-remount-fs.service` reported `Result=success`. It failed the new security
gate: despite `selinux --enforcing`, Anaconda passed `--karg=selinux=0` to bootc,
and installed `getenforce` returned `Disabled`. The
[Alma 10 attempt](https://github.com/Pelagians/Current/actions/runs/39529627410)
reproduced that bootstrap failure **before any destination selection or staging**.
These runs do not qualify either transition.

The next diagnostic [run 39530314066](https://github.com/Pelagians/Current/actions/runs/39530314066)
uses `selinux=1 enforcing=0` only for the installer runtime and retains the explicit
enforcing payload policy/assertion. Upstream's
[bootc integration source](https://github.com/rhinstaller/anaconda/blob/anaconda-44.30/pyanaconda/modules/payloads/payload/rpm_ostree/installation.py)
describes an enabled-but-permissive installer mode. This bounded test must pass
before changing the shipped ISO arguments; do not remove the enforcing assertion
or call the disabled installation qualified.

### Corrected installer policy and rebuild

[SELinux-enabled runtime run 39530314066](https://github.com/Pelagians/Current/actions/runs/39530314066)
passed authenticated bootstrap login/automatic setup, writable home, XFS `/sysroot`,
NetworkManager connectivity and `getenforce=Enforcing`. The installed kernel used
`selinux=1` without runtime `enforcing=0`. Hardware discovery identified x86-64-v3,
UEFI and virtio graphics, and selection reached the Fedora server review screen.
The network-disconnection test then hit a harness-only QMP keyword collision;
renaming its command argument fixes that, with a regression covering link down/up.
No staging happened in this run.

The installer source now uses the tested SELinux settings and a root-only automatic
layout. XFS remains the default; manual storage remains interactive. Separate-home
layouts still require the upstream Anaconda mount-preservation fix and qualification.
The default root grows without a fixed cap, with a 10 GiB minimum.

Btrfs is explicitly excluded for Alma destination compatibility, not merely avoided
by the default. Anaconda's native root-device allowlist excludes Btrfs. Because
Anaconda 44 has no filesystem denylist, `storage-policy.py` registers one check in
its existing storage validator: Btrfs assigned to a mount point or newly created
by the installer is an error; existing unused Btrfs volumes are left alone. The
build fails if the registration anchor changes and validates the registration anchor and compiles
the actual installed Anaconda source. It preserves every upstream check. Unit
tests cover root/home/data mounts, new formats, unused volumes and source drift.
The VM `reject-btrfs` scenario requests Btrfs and requires the policy error plus
no allocated virtual-disk data (`qemu-img map`) before calling it passed.

These source changes require new native ISO receipts and boot validation. Previous
ISO artifacts remain evidence for their recorded revision only. The bootstrap and
destination backend code are unchanged; no publishing or trust gate was relaxed.

The first policy rebuild, [39531502843](https://github.com/Pelagians/Current/actions/runs/39531502843),
failed on ARM because importing Anaconda's storage package probes live EFI
firmware, absent in the native build container. The build now locates the installed
package without importing its storage module, applies guarded source registration
and compiles it without execution. This does not pretend the build host is UEFI.
Runtime registration and pre-write rejection remain VM qualification gates.
Both repository validators passed after the policy changes: 77 runtime and 70
image tests (147 total); Actionlint and diff checks also passed.

### Fedora server end-to-end result

[Run 39531508575](https://github.com/Pelagians/Current/actions/runs/39531508575)
passed the full server sequence with original ISO source `d00468df`, harness
`d352feee`, test-only root-only storage and SELinux-enabled runtime arguments.
The original default ISO graphical boot was also retained as a separate smoke
check. The installed bootstrap had a writable home, XFS and enforcing SELinux.

Disconnecting the virtual NIC caused a real registry/DNS error. The wizard kept
the selection and offered retry; restoring the link staged native Fedora server
digest `776f85a171f439dcb7b2e17e2155bff382917d38b6f96116eaf8d56a58aceb93`.
Bootc's receipt recorded `signature: containerPolicy` and `phase: image-staged`,
then the same digest booted and the reconciler recorded `destination-booted`.
The original UID, home sentinel and NetworkManager profile hashes survived;
NetworkManager ran and the registry was reachable. Explicit acceptance produced
`complete`, and repeated setup did not restart the questionnaire.

A real `bootc rollback` and reboot returned to the bootstrap with authenticated
login intact. The completed receipt remains historical after rollback; the
bootstrap prints the completed message and directs later changes to `current
rebase`. Do not interpret that receipt as asserting that the destination is still
booted. Destination SELinux enforcement was not separately asserted in this run;
subsequent harness revisions add that check. No graphical desktop or Secure Boot
qualification is implied. Replacement ISO defaults and Btrfs rejection still need
their own VM results.

### Alma 10 staging versus activation

[Run 39531595719](https://github.com/Pelagians/Current/actions/runs/39531595719)
installed the enforcing XFS bootstrap, retained selection through the deliberate
network failure and staged signed Alma 10 native digest
`a8096a6c9771a5738ec4d21861881c893c0296b24c65f91ea0dbb4ea7d7c8b7f`.
The reboot displayed only the original Fedora bootstrap entry and returned to
that bootstrap. `ostree-boot-complete.service` failed; no Alma kernel was observed.
This is an activation failure, not evidence of an Alma XFS kernel failure.
The original test timed out at the unexpected bootstrap wizard; the harness now
recognizes that recovery login and collects bootc/setup state, boot entries and
staged-finalization journals before failing explicitly. Alma 10 remains unqualified.

The next VM revision uses bare `autopart`, so the shipping Anaconda configuration
must supply both the XFS filesystem and root-only layout. It also asserts enforcing
SELinux after the destination reboot, not only on the bootstrap.

### Alma 9 XFS incompatibility — confirmed boot failure

[Run 39531601375](https://github.com/Pelagians/Current/actions/runs/39531601375)
staged signed Alma 9 native digest
`6a0b95ef642ae1505fe2353caabf28ad4ccb52122878368c474bbdd9d13a0cc3`.
GRUB exposed both Alma 9 and the Fedora rollback entry. Alma kernel
`5.14.0-687.58.1.el9_8.x86_64` then rejected `/sysroot`: unknown incompatible
XFS feature `0x80`, error `-22`, and entered the initramfs emergency shell.
The installation log records `parent=1`. Upstream's
[XFS format definitions](https://github.com/torvalds/linux/blob/master/fs/xfs/libxfs/xfs_format.h)
identify bit 7 as parent pointers. This is a real filesystem compatibility failure,
not a signature or image-build failure. Do not use this installer for Alma 9 yet.

The safest next experiment is an explicitly pinned XFS feature profile for every
new XFS installation filesystem, including `/boot`, verified against the oldest
supported destination kernel. The upstream
[mkfs.xfs interface](https://kernel.googlesource.com/pub/scm/fs/xfs/xfsprogs-dev/+/master/man/man8/mkfs.xfs.8.in)
provides `-n parent=0`; disabling that observed blocker alone is not proof of full
compatibility. Validate all enabled features, actual Alma boot, SELinux, network,
rollback and repair tooling before adopting a shipping profile. Do not rewrite
existing filesystem superblocks or switch to Btrfs. Current artifacts retain
Fedora's XFS feature defaults and therefore retain this Alma 9 blocker.

### Corrected native ISO receipts

Both native jobs in [run 39532339329](https://github.com/Pelagians/Current/actions/runs/39532339329)
passed at source `dbdb3cab56b612752fd339af1711848ed53659d9`. This is the shipping
installer/bootstrap revision; subsequent commits change tests and documentation
only. Both archived receipts were independently read and checked, including the
native bootstrap digest and digest-derived embedded source binding.

| Architecture | ISO SHA256 | Artifact |
| --- | --- | --- |
| x86_64 | `3b6b2cf4240cb0bd5061b64ce7e566fc06ec0708a854abdaeaed621fce49a44f` | [12317320241](https://github.com/Pelagians/Current/actions/runs/39532339329/artifacts/12317320241) |
| aarch64 | `08cbb734f7775f673a38ac5316273ed2f5180e56485f941843496ce71744895d` | [12315654996](https://github.com/Pelagians/Current/actions/runs/39532339329/artifacts/12315654996) |

The x86 bootstrap digest is
`65fc1717ea57d8d7b9f5c611d1eead4932edb07ab96ca9129d28a02070308bb8`;
the ARM bootstrap digest is
`7e73aaffa73ec077467a70bdfd5ee6b32a8c2ba11041b0c47df8142879f00747`.
Both receipts pin builder
`b35d715cd67099355b9e2ee022e1f73333b917d5a1a594f01b6a82c366dc10d1`
and Fedora base
`e6fffeed9e9a13ca4d351c1ce4ae2b4a5119fe121268479e247a63a3ba2bfda2`.
ISO SHA256 values differ from GitHub ZIP archive digests. Artifacts expire after
seven days. Native ARM assembly success does not qualify ARM installation.

Replacement-ISO VM runs use harness source `e070faba`, bare `autopart` to exercise
shipping defaults and explicit destination SELinux assertions:
[Fedora](https://github.com/Pelagians/Current/actions/runs/39534009481),
[Btrfs rejection](https://github.com/Pelagians/Current/actions/runs/39534012141), and
[Alma 10 diagnosis](https://github.com/Pelagians/Current/actions/runs/39534014947).
Completed results are recorded below.

The first replacement Btrfs test stopped before installation: Tesseract exceeded
its 15-second deadline while reading an OVMF frame. It did not exercise storage
validation. The harness now limits OCR to one thread and retries a timed-out
frame within the existing overall GRUB deadline; it does not skip that boot gate.

### Corrected ISO Fedora server flow — passed

[Run 39534009481](https://github.com/Pelagians/Current/actions/runs/39534009481)
passed on the replacement x86_64 ISO identified above. The 180-second original
ISO screenshot was visually inspected: graphical Anaconda reached its language
selection screen. The subsequent install supplied automated disk/account answers
with bare `autopart`; the shipped configuration produced a root-only XFS layout,
a writable user home and enforcing SELinux. No `--nohome` or filesystem override
was supplied by the test.

The authenticated console login automatically opened setup, which paused and
resumed correctly. A disconnected NIC caused a real registry failure; retry kept
the questionnaire selection. Bootc staged signed Fedora server native digest
`776f85a171f439dcb7b2e17e2155bff382917d38b6f96116eaf8d56a58aceb93`
and the reboot ran that exact digest. Destination SELinux was **Enforcing**;
UID, home sentinel and NetworkManager profile hashes were retained, networking
was active and the registry reachable. The reconciler moved from `image-staged`
to `destination-booted`; explicit acceptance produced `complete`, and completed
resume did not repeat setup. Real `bootc rollback` and reboot restored authenticated
bootstrap access. The receipt remains historical after that completed rollback.

This qualifies the recorded virtual server sequence, not manual storage/user UI,
GNOME/COSMIC, physical GPUs, Secure Boot, ARM boot or the Alma transitions. The
compatibility catalogue remains conservative; a single virtio VM is not general
hardware qualification.

### Corrected ISO Alma 10 activation — SELinux finalization blocked

[Run 39534014947](https://github.com/Pelagians/Current/actions/runs/39534014947)
reproduced the activation failure on the corrected ISO with shipping defaults.
The enforcing bootstrap installed and staged the same signed Alma 10 digest.
After reboot it returned to the bootstrap, retained authenticated access and
recorded `recovery-required`; the previous selection remained available to resume.
The failure receipt in `ostree-boot-complete.service` reports:

```text
ostree-finalize-staged.service failed on previous boot:
Finalizing deployment: Finalizing SELinux policy:
failed to run semodule: Child process exited with code 1
```

Only the bootstrap boot entry remained; no Alma kernel ran. The previous boot's
journal was not persistent, so the underlying `semodule` stderr is unavailable.
The next diagnostic should enable persistent journaling only in the disposable
VM before staging, then capture the finalizer's complete error and compare the
Fedora/Alma SELinux policy stores and tool versions. Resolve that incompatibility
with a supported policy migration or reconsider the bootstrap base; do not
remove policy stores, disable SELinux or call a staged image boot-qualified.
This result does verify the recovery receipt and authenticated bootstrap path.

The next negative run, [39534995634](https://github.com/Pelagians/Current/actions/runs/39534995634),
reached graphical Anaconda but waited at its summary with Installation Destination
in error and Begin Installation disabled. It was interrupted to inspect that
screen. Correctable GUI validation errors do not execute Kickstart `%onerror`.
The test-only negative Kickstart now starts a read-only log observer in `%pre`:
it forwards the real storage validator's anchored error record and logs to the
runner. It neither calls the validator nor changes storage. The harness still
requires that exact backend error, no post-install marker and an entirely
unwritten virtual disk; it archives `disk-map.json` for review. The observer is
covered by an isolated shell test with mocked HTTP uploads. No shipping ISO or
payload changes were needed.

### Corrected ISO Btrfs rejection — passed

[Run 39536166058](https://github.com/Pelagians/Current/actions/runs/39536166058),
harness `001b6a0c`, passed against the same corrected x86_64 ISO. Anaconda's real
storage validator reported Current's explicit Btrfs error for the planned volume,
root mount and partition, then reported validation failure. The inspected GUI
screenshot shows Installation Destination in error and Begin Installation disabled.
No post-install marker was produced. After stopping the VM, `qemu-img map` reported
one extent covering all 68,719,476,736 bytes, with `present=false`, `zero=true` and
`data=false`: the entire installation disk remained unallocated. This is disk
allocation evidence, not a separate block-I/O trace. The archive includes the
validation logs, screenshot, result receipt and `disk-map.json`.

Final checks after the observer change passed: 77 runtime tests (runtime sources
unchanged), 71 image tests, Actionlint for both new workflows and diff checks.
The shipping installer/bootstrap inputs remain identical to build `dbdb3cab`.
PR #29 stays draft because Alma transitions and the remaining hardware/UI gates
are not qualified. No development-host installation or bootc switch occurred.

### Alma transition fixes under qualification

The Alma 9 kernel rejected XFS incompatible feature bit `0x80`, parent pointers.
The installer now adds `-nparent=0` at Blivet's XFS formatter, for all newly
formatted XFS filesystems (including `/boot` and manual partitioning). XFS remains
the default and the Btrfs validator remains active. Existing filesystems are not
rewritten. An explicit conflicting parent-pointer option is rejected by mkfs.xfs
before formatting. The guarded integration fails the ISO build if Blivet's XFS
task changes; it does not import storage detection during container construction.

A disposable 512 MiB regular-file check with xfsprogs 7.1.1 created XFS with
`parent=0` and incompatible flags `0x6b`; conflicting parent options exited 1.
This verifies the formatter option, not Alma boot compatibility. The replacement
native ISOs and complete Fedora/Alma UEFI flows must still pass before removing
the current transition holds.

The persistent-journal [Alma 10 diagnostic run 39537058913](https://github.com/Pelagians/Current/actions/runs/39537058913)
identified the finalization failure precisely:

```text
bwrap: execvp semodule: No such file or directory
Finalizing deployment: Finalizing SELinux policy: failed to run semodule
```

[OSTree's finalizer](https://github.com/ostreedev/ostree/blob/main/src/libostree/ostree-sysroot-deploy.c)
inherits its service environment while executing the destination's `semodule`.
Fedora's merged bin/sbin layout does not ensure that PATH finds Alma's separate
`/usr/sbin`. A bootstrap-only vendor drop-in now sets the finalizer's PATH to
`/usr/sbin:/usr/bin:/sbin:/bin`. No policy store is deleted and no SELinux checks,
enforcement or policy refresh are disabled. Keeping the setting in bootstrap
`/usr` avoids carrying it into the destination's `/etc`; the VM harness checks
that it disappears after the destination boots, and records the actual previous
finalization journal and XFS feature reports. Full boot qualification is pending.

### Combined Alma fixes: native ISO receipts

Both jobs in [run 39538575885](https://github.com/Pelagians/Current/actions/runs/39538575885)
passed at installer/bootstrap source `7d1994f37f312a1091137b485e988e139187c481`.
Both archived checksum/build-input files were independently read, including the
native architecture, immutable payload and digest-bound embedded source.
Subsequent harness/documentation changes do not change these product inputs.

| Architecture | ISO SHA256 | Artifact |
| --- | --- | --- |
| x86_64 | `e938802184bb8c611d0632447942217470a64701c2e0916a261de011389676fe` | [12318762090](https://github.com/Pelagians/Current/actions/runs/39538575885/artifacts/12318762090) |
| aarch64 | `e3b37d2ca50dbe5ad156b3e5fada1c61acc5e8bccc3765660133a79aa4e2b22f` | [12319315828](https://github.com/Pelagians/Current/actions/runs/39538575885/artifacts/12319315828) |

Signed native bootstrap payloads:

- x86_64: `ghcr.io/pelagians/current-bootstrap-x86_64@sha256:4add8053fcb609c4153e85d76e3f696510476edb673759092ed3c8fe7a99ffca`
- aarch64: `ghcr.io/pelagians/current-bootstrap-aarch64@sha256:982b5578d626450b63cc05173070520c77dc8cd6010675b5504c20f147d8674c`

The pinned Fedora base and image-builder digests are unchanged. These are ISO
hashes, not GitHub ZIP hashes. Artifacts expire after seven days. The ARM result
establishes native assembly only, not UEFI/board/Secure Boot qualification.
The earlier XFS-only build `39537608289` was superseded and cancelled by this
combined build; it is not a qualified artifact.

The final source passed 77 runtime tests and 72 image tests (149 total), Actionlint
for both installer workflows, and diff checks. The three Alma 9 R580 static recipe
contracts also passed. The optional live NVIDIA package-transaction preflight
could not start locally because the sandbox's `/run/user/1000/libpod` is read-only;
that transaction and physical driver qualification were not rerun in this pass.
No driver recipe or destination publishing/trust gate changed.

The same combined-fix ISO passed the [Btrfs rejection run 39539805272](https://github.com/Pelagians/Current/actions/runs/39539805272).
Both the original ISO graphical Anaconda welcome screen and the negative-test
summary screenshot were visually inspected. The validator logged Current's
explicit Btrfs rejection; Begin Installation stayed disabled, no post-install
marker appeared, and `disk-map.json` reported all 68,719,476,736 bytes as
`present=false`, `zero=true`, `data=false`. This is allocation evidence, not a
separate block-I/O trace. The unchanged harness source was `438f2579`.

### Combined-fix server observations and command-path follow-up

[Fedora run 39539802663](https://github.com/Pelagians/Current/actions/runs/39539802663)
passed the complete server flow, including enforcing SELinux, destination
completion/resume and authenticated bootstrap rollback.

[Alma 9 run 39539797589](https://github.com/Pelagians/Current/actions/runs/39539797589)
booted the signed Alma 9 destination on kernel `5.14.0-687.58.1.el9_8.x86_64`.
The XFS blocker is resolved: both filesystems mounted, and Alma's
`xfsprogs-6.4.0-7.el9` inspected `/sysroot` and `/boot`. SELinux was enforcing;
account/data/network-profile retention and registry connectivity passed. The
previous-boot journal records successful SELinux refresh and finalization.

The flow then exposed a separate completion-command issue: `sudo current setup
status` reported `sudo: current: command not found`. The shared setup layer now
installs the existing command implementation at `/usr/bin/current` as well as
its legacy location. This avoids dependence on a distribution's sudo secure_path
or mutable `/usr/local` population without changing sudo permissions. Destination
images and bootstrap must be rebuilt, and the full flows rerun before claiming
completion/rollback qualification for Alma 9. Additional VM diagnostics record
both command locations and sudo's actual PATH.

[Alma 10 run 39539800249](https://github.com/Pelagians/Current/actions/runs/39539800249)
also booted its signed destination. Its previous-boot journal records SELinux
policy refresh in 1337 ms and successful finalization. Destination enforcement,
XFS inspection with `xfsprogs-6.16.0-1.el10`, retained account/data/network and
registry access passed. Both bootstrap drop-in absence checks passed. It then
hit the same `sudo current` command-lookup failure; completion/rollback were not
reached. The standard-path command fix is shared across both Alma versions.

The command-path rebuild's [existing publication workflow 39541158494](https://github.com/Pelagians/Current/actions/runs/39541158494)
subsequently passed the live Alma 9 NVIDIA transaction prerequisite on its native
x86_64 runner, as well as all runtime and image tests. This resolves the local
container-runtime verification limitation for package transactions; it does not
qualify physical NVIDIA hardware. The existing complete native matrix and signed
multi-architecture publisher are retained for the command-path image update.

The old-candidate [command-path diagnostic 39541164363](https://github.com/Pelagians/Current/actions/runs/39541164363)
confirmed the cause: `/usr/local/bin/current` existed and was executable, but
`/usr/bin/current` was absent and sudo's actual PATH was
`/sbin:/bin:/usr/sbin:/usr/bin`. This was a sudo lookup failure, not a missing
setup backend. The correction supplies the command on that standard path and
leaves sudo's permissions and search policy unchanged.

### Superseded command-path correction: native ISO receipts

Both native jobs in [run 39541161544](https://github.com/Pelagians/Current/actions/runs/39541161544)
passed at product source `2d3b0b61c0a723e5a4121dca2075d63a57e5c17a`.
Both archived receipts were independently read and their architecture, immutable
bootstrap digest and embedded-source binding verified. These artifacts were later
superseded by the recovery-tool compatibility correction below.

| Architecture | ISO SHA256 | Artifact |
| --- | --- | --- |
| x86_64 | `f99beee82dbfdad0b6a95911de0e579a81504b11c8669d1d879eec5985eaad88` | [12320061655](https://github.com/Pelagians/Current/actions/runs/39541161544/artifacts/12320061655) |
| aarch64 | `02eaf646909688ee4557f54b32903df91292b77b3ac70e40a4997668ff178a9c` | [12319957146](https://github.com/Pelagians/Current/actions/runs/39541161544/artifacts/12319957146) |

Signed native bootstrap payloads:

- x86_64: `ghcr.io/pelagians/current-bootstrap-x86_64@sha256:368e4475a9d56dee212a858518b4e3c40c996714f19bae6f69f09e8b94a2f430`
- aarch64: `ghcr.io/pelagians/current-bootstrap-aarch64@sha256:a00051fa02ada507fcdddccd56a45e245ae8ac06d93b64afbde42e316551f5bd`

The Fedora base and image-builder pins are unchanged. ISO digests differ from
GitHub archive digests. Artifact retention is seven days. ARM boot qualification
is still required independently of these successful native builds.

That ISO also passed [Btrfs rejection run 39542388652](https://github.com/Pelagians/Current/actions/runs/39542388652),
harness `ad4303b7`, with its exact `f99beee8...` ISO checksum. The original
Anaconda welcome screen and rejection summary were visually inspected. Current's
validator reported Btrfs errors, Begin Installation remained disabled, and the
entire 64 GiB disk remained unallocated. The receipt now states that allocation
result precisely rather than claiming a separate history of block writes.

### Alma 9 recovery-tool compatibility: atomic extent exchange

The read-only [probe run 39544426326](https://github.com/Pelagians/Current/actions/runs/39544426326)
booted Alma 9 successfully but its `xfsprogs-6.4.0-7.el9` repair tool rejected the
clean, unmounted filesystem fixture created by Fedora with `parent=0`:

```text
Superblock has unknown compat/rocompat/incompat features (0x0/0x0/0x40).
Found unsupported filesystem features. Exiting now.
```

The installer now disables atomic extent exchange too: `-nparent=0 -iexchange=0`
at the XFS formatter. Fedora's mkfs reports `parent=0, exchange=0`, and a disposable
regular-file check reduced incompatible flags from `0x6b` to `0x2b`; its current
repair tool passed a read-only scan. The installed root and `/boot` must use this
same profile, and the full VM flow now probes the destination's repair tool with
`xfs_repair -n -f` on a clean disposable file. This checks feature recognition;
it is not a corruption-recovery drill on the installed root filesystem.

Existing filesystem feature bits are never rewritten. Earlier `parent=0, exchange=1` artifacts boot Alma 9 but remain unsuitable
for qualification with its bundled recovery tools. Native ISOs are rebuilding;
destination code is unchanged from the ongoing `2d3b0b61` publication.


### Final XFS recovery-compatible native ISO receipts

Both native jobs in [run 39545861516](https://github.com/Pelagians/Current/actions/runs/39545861516)
passed at installer source `ef173594cfddf5a68a5cb9f12ef829672476262c`.
Both archived receipts were independently checked for revision, architecture,
immutable bootstrap payload and embedded-source binding. Subsequent changes are
qualification assertions, workflow inputs and documentation, not product code.

| Architecture | ISO SHA256 | Artifact |
| --- | --- | --- |
| x86_64 | `0003f27fb65832308ea3632528abfd01f9332db70e804bce2ef7cb5d029b053f` | [12321783886](https://github.com/Pelagians/Current/actions/runs/39545861516/artifacts/12321783886) |
| aarch64 | `fb2efe82e5e35e2f641d8f16467c4e4965968b82dfcaad7c9cc68b7098a0d2c4` | [12321941605](https://github.com/Pelagians/Current/actions/runs/39545861516/artifacts/12321941605) |

Signed native bootstrap payloads:

- x86_64: `ghcr.io/pelagians/current-bootstrap-x86_64@sha256:49d15b4fa05856592b0d67197be86350558b74bf6a87679394f32ed1afeb4cbd`
- aarch64: `ghcr.io/pelagians/current-bootstrap-aarch64@sha256:9d3e723dd946f4280c166be62651f710ce5c9d1a1445ac363dd23a1712d006ad`

The Fedora base and image-builder pins are unchanged. These are ISO hashes, not
GitHub ZIP hashes. Artifacts expire after seven days. Native ARM assembly does not
establish ARM boot qualification.

The final ISO passed [Btrfs rejection run 39547374723](https://github.com/Pelagians/Current/actions/runs/39547374723),
using harness `7eaf9e1f0e2be96c4c07974b136a1e25f6a4c00d` and the exact
`0003f27f...` checksum above. The original graphical welcome screen and rejection
summary were visually inspected. Anaconda logged Current's explicit Btrfs
validation errors, Begin Installation remained disabled, and the entire
68,719,476,736-byte virtual disk remained unallocated. This is allocation evidence,
not a separate block-I/O trace. No destination switch occurs in this scenario.


### Final destination publication and server qualification

[Run 39541158494](https://github.com/Pelagians/Current/actions/runs/39541158494)
completed successfully: all 45 native image builds, repository/prerequisite
checks and the signed index publisher passed (51 jobs total). The publisher
verified and published all 24 image indexes, preserving ARM compatibility aliases.
The final destination source is `2d3b0b61c0a723e5a4121dca2075d63a57e5c17a`,
with the shared `/usr/bin/current` command correction. Subsequent product changes
only affect installer XFS formatting; use the final `ef173594` ISO above.

The qualification channel is `br-codex_unified-installer`. The earlier `pr-29`
candidates lack the command-path correction and are superseded for these tests.
The publisher's actual native server digests match the build receipts:

| Destination | x86_64 native digest |
| --- | --- |
| `alma10-server` | `sha256:b4245ea1bc7b3526b64972b8dda7f92eb8bd43c3e40ab64dd35b54cf35724f7f` |
| `alma9-server` | `sha256:ebeaf297f4a26877d7ba646b010997663f11d14f172443256a446234e45f38ae` |
| `fedora-server` | `sha256:08fbf66d2e348a41c789dc1d126a4fcf5efc7ea9e02ac12169a977f560d8446e` |

[Alma 9 final run 39824369788](https://github.com/Pelagians/Current/actions/runs/39824369788)
passed the entire server flow with harness
`d0be48e4a9a6e4a260a5f4de86716644578b23c6` and the exact final ISO checksum.
The serial log confirms `parent=0, exchange=0` on both installed XFS filesystems
before switching. Alma 9 booted the expected native digest, kept SELinux enforcing,
and `xfsprogs-6.4.0-7.el9` completed all read-only fixture scan phases with exit 0.
The previous-boot journal records successful SELinux refresh (1374 ms), finalization
and bootloader update. Root remount completed successfully. The bootstrap-only
PATH drop-in was absent on the destination, `/usr/bin/current` was present, and
sudo resolved the command using Alma's unchanged search policy. Retained account,
data and NetworkManager profile checks, registry access, explicit completion,
completed resume and authenticated rollback all passed. The original graphical
Anaconda and bootstrap rollback screenshots were visually inspected.

The same serial log includes journald's “corrupted or uncleanly shut down,
renaming and replacing” messages across the Alma 9 transition and rollback, and
Alma 9 shutdown reported busy loop/DM devices before continuing the reboot. The
previous-boot finalizer journal remained readable and the asserted flow passed.
These messages are retained as diagnostic limits: journal integrity across
versions and clean device teardown need separate investigation. The clean-file
`xfs_repair -n` check does not establish crash or corruption recovery of the
installed root filesystem.

[Fedora final run 39824414128](https://github.com/Pelagians/Current/actions/runs/39824414128)
passed the same complete server flow with the final ISO and harness. The booted
native digest matched the publication receipt, SELinux remained enforcing,
`xfsprogs-7.1.1-1.fc44` passed the read-only fixture scan, and account/data/network
retention, explicit completion, completed resume and authenticated rollback passed.
The finalizer journal records successful policy refresh (2297 ms) and bootloader
update. Original graphical Anaconda and rollback screenshots were visually checked.

[Alma 10 attempt 39824394236](https://github.com/Pelagians/Current/actions/runs/39824394236)
was cancelled during runner setup after prolonged Ubuntu package downloads.
Its completed log shows slow transfers from `azure.archive.ubuntu.com`, not a
Current install failure; QEMU was still downloading and no VM had started.
A fresh run uses identical ISO, destination channel and harness inputs.


[Alma 10 final run 39826727232](https://github.com/Pelagians/Current/actions/runs/39826727232)
passed the complete flow after runner preparation finished. It used the same
`ef173594` ISO and `d0be48e4` harness as the other final server runs. The booted
native digest matched `b4245ea1...` with `containerPolicy` verification. The journal
records SELinux policy refresh in 1441 ms, successful finalization and bootloader
update. Bootstrap and destination enforcement checks passed; the bootstrap-only
PATH drop-in was absent from the destination. Both installed XFS filesystems had
`parent=0, exchange=0`; `xfsprogs-6.16.0-1.el10` passed the read-only fixture scan.
The standard-path command, retained account/data/network, registry access,
explicit completion, completed resume and authenticated rollback all passed.
Original graphical Anaconda and bootstrap rollback screenshots were visually
inspected. Root remount also completed successfully.

The Alma 10 run's bootstrap audit includes a `PAM:setcred` failure for
`systemd-executor` both before the initial switch and after rollback; normal
console login and sudo authentication succeeded. This predates the transition
and is not evidence of the fixed SELinux finalizer failure. User-manager/session
health is not asserted by this server harness and needs separate qualification,
alongside the Alma 9 journal/device-detach diagnostics above. No speculative PAM,
SELinux-policy or shutdown override was introduced to suppress these messages.

These results qualify the recorded server flows and pinned digests on disposable
x86_64 UEFI/KVM machines with Secure Boot disabled. They do not promote the
compatibility catalogue to universal hardware or driver qualification. Test-only
Kickstart answers automate storage/user input; manual Anaconda interaction,
separate-home layouts, graphical sessions, physical GPUs, Secure Boot, ARM UEFI
boot and crash/corruption recovery remain open. A completed receipt is historical
after rollback, as documented in the recovery section. PR #29 remains draft.
