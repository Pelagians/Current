# Workstation rebase qualification

This is a release gate for the shared display-manager reconciler. Unit tests do
not qualify a bootc image or a successful graphical login.

## Inspected package contracts (2026-09-30)

Binary RPMs were downloaded and their payloads extracted without installing them:

| Lane | Package | Source |
| --- | --- | --- |
| Fedora 44 | cosmic-greeter-1.8.0-3.fc44.x86_64 | Fedora updates repository |
| Alma 9 | cosmic-greeter-1.9.1-1.el9.x86_64 | ligenix/enterprise-cosmic, epel-9-x86_64 |
| Alma 10 | cosmic-greeter-1.9.1-1.el10.x86_64 | ligenix/enterprise-cosmic, rhel+epel-10-x86_64 |
| Fedora 44 ARM | cosmic-greeter-1.8.0-3.fc44.aarch64 | Native Fedora ARM COSMIC image build |
| Alma 10 ARM | cosmic-greeter-1.9.1-1.el10.aarch64 | ligenix/enterprise-cosmic, rhel+epel-10-aarch64 |

All inspected native `cosmic-greeter.service` files have the same contract:

```ini
[Unit]
After=systemd-user-sessions.service plymouth-quit-wait.service cosmic-greeter-daemon.service
After=getty@tty1.service ksmcon@tty1.service
Conflicts=getty@tty1.service kmscon@tty1.service
Wants=cosmic-greeter-daemon.service

[Service]
Type=simple
ExecStart=greetd --config /etc/greetd/cosmic-greeter.toml
IgnoreSIGPIPE=no
SendSIGHUP=yes
TimeoutStopSec=30s
KeyringMode=shared
Restart=always
RestartSec=1
StartLimitBurst=5
StartLimitInterval=30

[Install]
Alias=display-manager.service
```

GNOME package inspection also covered Alma 9 `gdm-40.1-44.el9_8` and
`gnome-session-wayland-session-40.1.1-11.el9`, plus Alma 10
`gdm-47.0-24.el10_2` and `gnome-session-wayland-session-46.0-11.el10`.
Fedora GDM uses `/usr/bin/gdm`; both Alma lanes use `/usr/sbin/gdm`.
The default session entry is `gnome.desktop` on all lanes, with the bare
`gnome-session` command on Alma 9 and `/usr/bin/gnome-session` on modern lanes.

The daemon is a D-Bus service with `ExecStart=/usr/bin/cosmic-greeter-daemon`.
The COSMIC session file is `/usr/share/wayland-sessions/cosmic.desktop`, with
`Exec=/usr/bin/start-cosmic` and `DesktopNames=COSMIC`. Native PAM is installed
at `/usr/lib/pam.d/cosmic-greeter` and already includes optional keyring unlock
and session startup. An administrator's `/etc/pam.d` override takes precedence.
An override carrying Current's exact generated ownership marker is retired only
after checking the vendor stack exists and successfully selecting the manager.
Unmarked administrator files and symlinks are preserved.

Generic `greetd.service` instead has `ExecStart=greetd` and uses
`/etc/greetd/config.toml`. It also declares the display-manager alias. Current
does not select that generic service or ship a competing generic configuration.

Package provenance: [Fedora packaging](https://src.fedoraproject.org/rpms/cosmic-greeter),
[Enterprise COSMIC repository](https://download.copr.fedorainfracloud.org/results/ligenix/enterprise-cosmic/).
The test fixtures snapshot these units; they do not replace vendor units in images.
Image contract checks fail if upstream changes the inspected command/config/session
contract, rather than guessing a new implementation at runtime.

## Session state investigation

GDM uses AccountsService session fields under `/var/lib/AccountsService/users`.
Older GDM versions also have `.dmrc` compatibility. Saved sessions must resolve to
an installed, usable session before GDM accepts them; its fallback is `gnome`.
See [GDM session selection](https://github.com/GNOME/gdm/blob/main/daemon/gdm-session.c)
and [account settings](https://github.com/GNOME/gdm/blob/main/daemon/gdm-session-settings.c).

COSMIC greeter independently stores a UID-keyed `last_session` map in
`/var/lib/cosmic-greeter/.config/cosmic/com.system76.CosmicGreeter/v1/users`
(with the packaged greeter account home and default XDG configuration paths).
It enumerates Wayland/X11 session desktop entries and remembers their displayed
names. Greetd itself does not choose that user's desktop: the greeter sends the
chosen session command. Greetd's `default_session` starts the greeter; an
administrator-configured `initial_session` can bypass it for automatic login.
See [COSMIC 1.8.0 selection](https://github.com/pop-os/cosmic-greeter/blob/epoch-1.8.0/src/greeter.rs)
and [configuration](https://github.com/pop-os/cosmic-greeter/blob/epoch-1.8.0/cosmic-greeter-config/src/lib.rs).

Thus ordinary GNOME login does not change COSMIC's saved session. GDM rejects an
uninstalled COSMIC session on a GNOME image. However, COSMIC 1.8.0/1.9.1 source
accepts a saved session name without checking availability, and its start path
has a `todo!` for an unavailable name. A previously chosen GNOME session in
COSMIC greeter, a local `/usr/local/share/*sessions` entry, a GDM override, or a
custom greetd automatic-login command needs separate qualification. This is a
source-level risk, not a reproduced booted Current failure. No session-state
rewrite is included: AccountsService, COSMIC greeter preferences, dconf and user
homes are preserved. Do not claim session qualification from the helper tests.

If the booted test reproduces the risk, capture the installed package versions,
installed session entries, greeter's saved session and journal before adding a
narrow session-selection fix. Retain valid per-desktop choices and the original
state as evidence; do not delete an entire config tree.

## Booted procedure

Use disposable bootc machines with a visible console. Use GNOME and COSMIC
images built from the same candidate commit, on the same distro/driver lane.
Record immutable image digests and the commit. Repeat across Fedora, Alma 9 and
Alma 10 supported workstation lanes; driver-specific display qualification
belongs on suitable hardware. A generic VM cannot qualify NVIDIA rendering.

Create one normal test account, give it GNOME and COSMIC preferences, and place a
sentinel file in its home. Save hashes of that file and the chosen preference
files. Preserve the same disk, user UID, home, AccountsService state and `/etc`
throughout each sequence. Do not reinstall or wipe state between switches.

1. Fresh GNOME boot: record the greeter, log in without choosing a different
   session, and run the checks below from that graphical session.
2. Fresh COSMIC boot on a separate disk: repeat the same checks.
3. On the first disk, run `sudo bootc switch <cosmic-candidate-ref>` and reboot.
   Repeat with `<gnome-candidate-ref>`, then `<cosmic-candidate-ref>`.
4. On the COSMIC-first disk, switch to GNOME and reboot.
5. Repeat the sequence with deliberately contaminated state, as described below.
6. Verify the sentinel and per-desktop preferences, log out/back in, and reboot
   the same destination again to check idempotence.

Use `current rebase` with a candidate matrix/registry when testing the picker;
plain `bootc switch` is useful for exact candidate digest references.

For every destination boot, capture:

```bash
systemctl get-default
systemctl status current-workstation-dm-apply.service
systemctl status display-manager.service
systemctl is-enabled gdm.service
systemctl is-enabled cosmic-greeter.service
systemctl is-enabled greetd.service
readlink -f /etc/systemd/system/display-manager.service
bash scripts/qualify-workstation-boot.sh
```

The qualification script is read-only and must run on the **test machine**.
`--system-only` can collect ownership checks from a TTY/SSH session, but leaves
login/session qualification pending. Keep its output with screenshots or a
console recording showing the intended greeter and successful login. Also
capture `systemctl show` for the six relevant units with `Wants`, `Requires`,
`After`, `Before`, `Conflicts`, `FragmentPath` and `DropInPaths`. The selected unit
must require and follow the successful helper, and both competitors must be
inactive. Inspect `/run/systemd/generator.early` to confirm early ownership.

## Deliberately contaminated state

Only run these setup commands in a disposable qualification machine after
staging the destination image and immediately before reboot. These are test
inputs, not repair instructions:

```bash
# Example: GNOME -> COSMIC. Use cosmic-greeter as old and gdm as destination
# for the reverse test. ln deliberately also works for absent vendor units.
sudo mkdir -p /etc/systemd/system/graphical.target.wants
sudo ln -sfn /usr/lib/systemd/system/gdm.service /etc/systemd/system/display-manager.service
sudo ln -sfn /usr/lib/systemd/system/greetd.service /etc/systemd/system/graphical.target.wants/greetd.service
sudo ln -sfn /dev/null /etc/systemd/system/cosmic-greeter.service
```

Test each contamination alone and all together. Also test a dangling old alias
by pointing it to a managed service absent from the destination. No `systemctl`
repair is allowed after the destination boots.

For session investigation, first select GNOME explicitly in a COSMIC greeter
that legitimately offers it (such as an administrator-installed extra session),
record the saved state, then repeat the ordinary image switch sequence. Do not
add both complete desktop stacks to Current recipes just to create this case.
Test missing-session fallback and returning to each desktop's valid prior
choice. An opt-out test should separately demonstrate that administrator state
is untouched; it is not an ordinary Current ownership pass.

## Results and release gate

Local automated results: GNOME -> COSMIC, COSMIC -> GNOME and
GNOME -> COSMIC -> GNOME -> COSMIC converge in isolated persistent `/etc`
fixtures using real offline `systemctl`. Native systemd transaction verification
finds no ordering cycle for either destination. Tests preserve home and greeter
preference fixtures and exercise invalid/missing contracts and failed selection.

Before the PR #29 VM expansion, booted results were **pending**: no disposable
bootc workstation was available during the original reconciler implementation. The native Fedora ARM COSMIC full build passed its greeter
contract checks. A disposable container from that image also repaired all three
contaminations together, passed idempotence and verified the installed unit graph
without an ordering cycle. Its Wayland session directory contains only
`cosmic.desktop`. See [ARM build results](arm-image-lanes.md).

Successful image build/publication results are linked in the ARM build results.
Booted visual greeter/login/session checks must be attached before claiming the
requested rebase convergence is qualified.

## PR #29 disposable UEFI expansion — 2026-10-22

The unified-installer VM harness now has `workstation-flow` and `rebase-flow`
scenarios. They install the recorded unified ISO on a new XFS disk, complete
first-boot setup on a source image, retain the same account/home/network and
perform a signed, digest-resolved switch. The target is rebooted again before
`bootc rollback` returns to the exact source digest. A final signed switch back
to the original Fedora bootstrap verifies all cross-version journal archives
with the newer reader. That final verification hop follows the actual source
rollback and is recorded separately.

Workstation scenarios start with either GNOME or COSMIC, then select the other
desktop on the same distro. QMP sends the normal account password to the real
greeter; no automatic login or PAM override is installed. A test-only user XDG
autostart entry executes the existing read-only workstation qualifier from the
actual graphical session. The probe records inherited display/desktop/session
variables, logind state and processes. Greeter and logged-in screenshots are
retained. A missing greeter, failed authentication, absent autostart proof or
failed qualifier is a failure, not a system-only graphical qualification.

The planned workstation matrix is both directions on Fedora, Alma 9 and Alma 10.
The initial cross-distro matrix is all six directed server pairs among these
three distributions. These start from systems installed through the unified
bootstrap and first-boot wizard; they do not establish compatibility with every
older image-specific installer layout. Initial VM graphics are unaccelerated
`virtio-vga`, with Secure Boot disabled. Physical GPU/NVIDIA qualification,
contaminated greeter state, per-desktop preferences and administrator opt-outs
remain separate gates. Build success and these new harness tests alone do not
establish graphical-login success; completed run evidence is recorded below.

Initial harness `9126c891` runs (failed at the blockers described below):

| Case | Run |
| --- | --- |
| fedora-gnome | [39864465146](https://github.com/Pelagians/Current/actions/runs/39864465146) |
| fedora-cosmic | [39864473827](https://github.com/Pelagians/Current/actions/runs/39864473827) |
| fedora-to-alma9 | [39864478197](https://github.com/Pelagians/Current/actions/runs/39864478197) |
| fedora-to-alma10 | [39864485383](https://github.com/Pelagians/Current/actions/runs/39864485383) |
| alma9-to-fedora | [39864493083](https://github.com/Pelagians/Current/actions/runs/39864493083) |
| alma9-to-alma10 | [39864500928](https://github.com/Pelagians/Current/actions/runs/39864500928) |
| alma10-to-fedora | [39864504802](https://github.com/Pelagians/Current/actions/runs/39864504802) |
| alma10-to-alma9 | [39864517682](https://github.com/Pelagians/Current/actions/runs/39864517682) |


### First runtime blockers and corrections

All six initial directed server cases reached their source image and completed
setup, then stopped before the second switch at the effective-policy check:
`Effective container policy does not require the Current repository signing key`.
The `setup-trust-policy.sh` namespace rule was applied only to the bootstrap;
destination recipes ended at BlueBuild's image-specific signing module. The
correction shares signing plus the same namespace rule across every native
recipe. It preserves BlueBuild's more-specific rules, unrelated transports and
registry configuration. No insecure policy or alternate key is introduced.
Regression fixtures check rule preservation and every matrix recipe's inclusion.

[Fedora GNOME 39864465146](https://github.com/Pelagians/Current/actions/runs/39864465146)
and [Fedora COSMIC 39864473827](https://github.com/Pelagians/Current/actions/runs/39864473827)
booted their correct signed workstation images but failed before graphical
login: the reconciliation service's `systemctl enable <name>` resolved the early
generator's selected-unit symlink and refused to operate on a linked unit.
An isolated real-systemctl fixture reproduces this exact rejection with the
same generated links. Passing the validated `/usr/lib/systemd/system/<name>`
path enables the vendor file directly; the fixture then passes for both desktops
without altering the generated links. Existing administrator guards, failure
restoration, competitor handling, opt-out and transaction tests also pass.
See the documented [absolute-path enable interface](https://www.freedesktop.org/software/systemd/man/latest/systemctl).
These failed runs do not establish a working greeter or graphical session.

The previously tested finalizer PATH correction is also moved from the bootstrap
file tree into the shared setup vendor tree. Every Current source can therefore
find an Alma destination's `/usr/sbin/semodule` during finalization. This extends
the already reproduced Fedora-bootstrap issue to other Fedora sources; its
applicability to the new rebase pairs still requires their full reruns. It is an
immutable vendor drop-in, with no retained `/etc` override or SELinux bypass.

These corrections require rebuilt native images and repeated VM flows. The
recorded `6f48c731` ISO remains the installation control: its bootstrap already
contains the same namespace trust and finalizer PATH behavior. Source and target
digests are recorded separately from the ISO source. Local checks after the
corrections pass 78 runtime and 84 image tests. None of the initial failed cases
is promoted to a qualified result by those tests.

The remaining initial workstation runs use harness `0ce5cf6a`:

| Case | Run |
| --- | --- |
| Alma 9 GNOME → COSMIC | [39865560476](https://github.com/Pelagians/Current/actions/runs/39865560476) |
| Alma 9 COSMIC → GNOME | [39865563599](https://github.com/Pelagians/Current/actions/runs/39865563599) |
| Alma 10 GNOME → COSMIC | [39865566614](https://github.com/Pelagians/Current/actions/runs/39865566614) |
| Alma 10 COSMIC → GNOME | [39865569987](https://github.com/Pelagians/Current/actions/runs/39865569987) |

Alma 9 COSMIC also reproduced the generated-link refusal before its greeter
could start. This supports the shared helper correction across systemd versions;
it does not establish that COSMIC rendering works in this VM.

[Native rebuild 39866965417](https://github.com/Pelagians/Current/actions/runs/39866965417)
uses product source `e8fc3698f6a6ecf1ec30f4bb8b2a6610bcdd49f7`. It retains the
complete 45-image matrix, native ARM runners, NVIDIA preflight and verified/signed
24-index publisher. Rebuilt VM qualification must use that revision and recorded
native digests. Any early tests against existing run-specific native tags are
candidate diagnostics; the shared publication gates are not advanced by them.


### Rebuilt ISO and signed native candidates

[ISO run 39867706688](https://github.com/Pelagians/Current/actions/runs/39867706688)
passed on both native architectures at source
`7eae0d4b856adf5672d9da233264d1115c2350f3`. Both receipts pin image-builder
`sha256:b35d715cd67099355b9e2ee022e1f73333b917d5a1a594f01b6a82c366dc10d1`
and Fedora bootc 44 installer base
`sha256:dc1055df531e11ea6753af22414cb7ff217023e93d68cca3f92198df6214f9ee`.
Receipt validation checked revision, native architecture, embedded payload binding
and checksum filename. The ARM ISO build does not qualify ARM boot or installation.
Package/module snapshots remain a reproducibility gate.

| ISO | SHA-256 | Bootstrap payload digest | Artifact |
| --- | --- | --- | --- |
| x86_64 | `b301fe8829e7e13347d7588d632b09aa81132f9acab1d312ebd26deead4b638a` | `sha256:9cbafe8269906d5a812bae23d41b5386031b27f3fa05b902a4fa2b9ec2f8538e` | [12465048629](https://github.com/Pelagians/Current/actions/runs/39867706688/artifacts/12465048629) |
| aarch64 | `db9a511bd3986cf382101a01bf02d545507275ec0c6949b21b2ef2c1f38912b6` | `sha256:04845cf7280ed9b0533cfbb4cdc4500ce45bdc03b25a273390142c3c7e711a53` | [12465528191](https://github.com/Pelagians/Current/actions/runs/39867706688/artifacts/12465528191) |

The rebuilt x86_64 ISO's [Btrfs rejection run 39871600458](https://github.com/Pelagians/Current/actions/runs/39871600458)
passed: the original ISO showed graphical Anaconda, explicit Btrfs partitioning
was rejected by the real storage validator, Begin Installation was disabled, and
all 64 GiB of the disposable qcow2 remained unallocated. The screenshots were
visually inspected. This allocation check is not an independent block-I/O trace.
Positive installs use the shipped XFS profile, with parent pointers and atomic
extent exchange disabled for Alma 9 compatibility.

Native candidate receipts from run `39866965417`, attempt 1, all name product
source `e8fc3698f6a6ecf1ec30f4bb8b2a6610bcdd49f7`. Before shared publication
finishes, tests use the signed run-specific native tags:
`br-codex_unified-installer-run-39866965417-1-amd64-<version>`, where version is
`44`, `9`, or `10`. Independent source/target channel inputs select the proper
distro versions without modifying matrix inventory or publication gates. Every
resolution requires the exact source revision and Current's signature policy.

| x86_64 image | Native digest |
| --- | --- |
| fedora-server | `sha256:10400dabda5ac910394674b96f7bfd64cc0abf2e8196e3e59811dc6317175dc0` |
| fedora-gnome | `sha256:a97e8be49647cdcadd40d87d4b3e32f0b4d8e58b07b3ca45f5d5677dadee424c` |
| fedora-cosmic | `sha256:541445dad0bb468615f7a93412a3dbff1c6c5aec57ed9b49648930ef41e91013` |
| alma9-server | `sha256:2d84a7f498f4d529ef8503d9d3db90c142385f1a830861b2f4caa0033adffbbd` |
| alma9-gnome | `sha256:f4af617b09538b835dee8b10e072a3f1730a2152a91854f8e2568bbaa500c7c6` |
| alma9-cosmic | `sha256:afc70637337aad0c9d28e151860cd2de956f085f3331a13f7dcd0534fbc1f70d` |
| alma10-server | `sha256:9e32331e1a8d3e8acea199fa95070dbd629ea657bafbc8c9a5fe0ebe5c81ac4c` |
| alma10-gnome | `sha256:d3f981006fa96af1808d3018e91f84e792b17542457898689a1d4368debb48d0` |
| alma10-cosmic | `sha256:9bd9b27c7d0c43b4deeaebdc71fc2093eb13dc50072a1287cfadbb1bd038bd5f` |

### Measurement corrections

The rebuilt Fedora COSMIC [pilot 39870392695](https://github.com/Pelagians/Current/actions/runs/39870392695)
reached its native greeter, authenticated the normal account and rendered COSMIC
on unaccelerated virtio graphics. Screenshots were visually inspected. Its
session checker then failed because the systemd-managed XDG autostart application
had no inherited `XDG_SESSION_ID`. The read-only checker now resolves logind's
primary graphical session through `User.Display` when that variable is absent,
and still requires matching UID, active state, actual graphical session type,
real display variables and the expected desktop. Isolated fixtures reject missing,
foreign, inactive and nongraphical sessions. No environment values, PAM rules or
automatic-login configuration are fabricated. See the primary
[logind User.Display contract](https://www.freedesktop.org/software/systemd/man/254/org.freedesktop.login1.html).
This observed source login is not a completed switch/rollback qualification.

The Alma 9 GNOME [attempt 39871064159](https://github.com/Pelagians/Current/actions/runs/39871064159)
started the correct GDM greeter but the automated pointer event only focused the
user tile; an echoed serial command was then mistaken for completed autostart.
The harness now confirms a visible password field before entering the password,
separates pointer press/release, and requires an anchored numeric session receipt.

The Alma 9 → Fedora [attempt 39871051240](https://github.com/Pelagians/Current/actions/runs/39871051240)
booted the target, rebooted it and returned to its exact source digest. It failed
its final marker assertion because asynchronous kernel audit output split
`rebase-target` in the serial stream. All checkpoint text and closed-archive
verification were present in the raw evidence, but this attempt is not counted
as a complete pass. Journal assertions now transfer unchanged file bytes through
the existing bounded HTTP evidence collector; raw serial diagnostics remain.
These checker changes require VM reruns, not new product images.

### Completed rebuilt-image flows

[Fedora → Alma 10 run 39871048295](https://github.com/Pelagians/Current/actions/runs/39871048295)
passed `rebase-flow` using the new ISO above and harness `d0fd8bec`. It verified
initial setup, a real disconnected-NIC retry, signed source/target staging,
Alma 10 boot and ordinary reboot, exact Fedora source rollback, enforcing SELinux,
XFS, stable account UID, retained home sentinel and NetworkManager configuration,
actual registry access, working user services and persistent checkpoint markers.
All closed journal archives passed final verification; all five shutdown pivots
unmounted the old root with no finalization failure. Its recorded native source
and target digests match the receipts above. [Alma 10 → Alma 9 run 39871060957](https://github.com/Pelagians/Current/actions/runs/39871060957)
also passed the full sequence using the same ISO and harness, with all five
shutdown pivots and all 18 retained archives verified. The older kernel mounted
the installer-created XFS and its repair tool accepted the clean test filesystem.
Other directed pairs and all full workstation switch/rollback cases remain
pending their completed reruns.

Current local validation passes **166 tests (80 runtime, 86 image)**, Bash syntax,
Actionlint for both installer workflows and `git diff --check`. These checks do
not promote any failed or incomplete VM attempt.
