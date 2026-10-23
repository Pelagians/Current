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
source `e8fc3698f6a6ecf1ec30f4bb8b2a6610bcdd49f7`. The initial rebuilt-image tests use the signed run-specific native tags:
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

The Alma 9 → Alma 10 [attempt 39871054202](https://github.com/Pelagians/Current/actions/runs/39871054202)
resolved and staged the correct signed Alma 10 digest, then timed out at a normal
sudo password prompt before any reboot: the large pull had expired sudo's cached
authentication. The harness now runs `sudo -v` through its existing password
handler immediately before every reboot. It does not add passwordless sudo or
change authentication timeout policy. The incomplete attempt is retained and a
fresh full flow is required.

The Alma 10 COSMIC [attempt 39871077641](https://github.com/Pelagians/Current/actions/runs/39871077641)
also rendered the real authenticated COSMIC desktop, then hit the same missing
session-variable checker failure. Fedora GNOME [attempt 39870389579](https://github.com/Pelagians/Current/actions/runs/39870389579)
and Alma 10 GNOME [attempt 39871071643](https://github.com/Pelagians/Current/actions/runs/39871071643)
and Alma 9 COSMIC [attempt 39871067688](https://github.com/Pelagians/Current/actions/runs/39871067688)
did not produce completed autostart proof under the earlier harness. These remain
failed attempts, pending corrected runs. A greeter screenshot alone is insufficient.

The corrected Fedora COSMIC [attempt 39873480173](https://github.com/Pelagians/Current/actions/runs/39873480173)
passed real COSMIC login, signed GNOME staging and real GNOME login, with active
logind sessions matching inherited Wayland environments. After the ordinary
GNOME reboot, GDM remained active but no authenticated graphical session or new
autostart receipt appeared. The pre-password screenshot showed the actual GDM
password entry. Focus/timing remains under investigation; the harness now focuses
that entry, allows PAM initialization to settle, paces input and records native
manager/PAM/AVC diagnostics. This is not a complete rollback qualification.

The corrected Alma 9 GNOME [attempt 39873485350](https://github.com/Pelagians/Current/actions/runs/39873485350)
passed its real graphical login and staged COSMIC, then hit the already identified
expired-sudo prompt before reboot. The fixed handler is used for its next full run.
GNOME screenshots also show SELinux troubleshooting notifications; these are
retained and require audit-event investigation rather than blanket policy changes.

Cross-distro staging logs retain unknown target SELinux-context warnings under
the source policy. The recorded passing cases still require enforcing target
boot, successful finalization, reboot and rollback. Those observations do not
qualify other policy/package combinations, and no policy bypass is applied.


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
[Alma 10 → Fedora run 39871057506](https://github.com/Pelagians/Current/actions/runs/39871057506)
and [Fedora → Alma 9 run 39871045283](https://github.com/Pelagians/Current/actions/runs/39871045283)
also passed the complete flow, each with five shutdown pivots and exact-source
rollback. Their final archive counts were 14 and 22 respectively. Subsequent source-pair and workstation results are recorded in the current
complete-flow matrix below.

Current local validation passes **168 tests (80 runtime, 88 image)**, Bash syntax,
Actionlint for both installer workflows and `git diff --check`. These checks do
not promote any failed or incomplete VM attempt.


[Native build and publication 39866965417](https://github.com/Pelagians/Current/actions/runs/39866965417)
completed successfully with all **51 jobs** passing: 45 native images,
prerequisites and the unmodified signed index publisher. Post-publication registry inspection matched all 24 shared indexes to the exact
45 native children and verified all 21 ARM compatibility digests. Representative
full flows now exercise the normal shared channel. Run-specific candidate tests do not advance
that channel or bypass its validation/signature gates.


### First complete workstation flows

[Fedora GNOME → COSMIC 39873752449](https://github.com/Pelagians/Current/actions/runs/39873752449)
(harness `9a3a941b`) and [Alma 10 GNOME → COSMIC 39875275268](https://github.com/Pelagians/Current/actions/runs/39875275268)
(harness `3059a1ee`) passed the complete flow on the new ISO and the exact signed
native candidates above. Each recorded four real greeter password logins:
GNOME source, COSMIC destination, COSMIC after an ordinary reboot, and the exact
GNOME source after rollback. Each session had the intended inherited desktop,
Wayland environment, logind UID 1000, matching type and active state. All eight
greeter/session screenshot pairs are retained; session images were visually
inspected. Both flows retained UID/home/network, kept SELinux enforcing, passed
all five shutdown pivots and verified all 14 final journal archives.

GNOME sessions displayed SELinux troubleshooting notifications. Alma 9's earlier
source diagnostics also recorded failed `avahi-daemon.service` (missing `avahi`
user) and `brew-setup.service`, while authenticated login and user services worked.
These are outstanding workstation service/application and policy investigations,
not a claim of complete desktop health. No daemon account, UID, permissive policy
or masked unit is fabricated to silence them. Current native PAM/AVC diagnostics
are being collected separately. Physical GPU/rendering, application behavior and
contaminated session state remain unqualified even for these passing VM flows.


### Shared-reference confirmation

[Fedora → Alma 10 39876032534](https://github.com/Pelagians/Current/actions/runs/39876032534)
passed the same complete rebase flow through `br-codex_unified-installer` after
full publication. Its source and target native digests match the run-specific
candidate receipts exactly. All five shutdowns released the old root, and final
closed-archive verification passed. This supplements the complete 24-index / 45-child
/ 21-ARM-alias mapping check without repeating every identical child solely for
a different tag spelling. Remaining shared workstation runs are recorded separately.


### Additional measured failure paths

- [39874003674](https://github.com/Pelagians/Current/actions/runs/39874003674)
  (Alma 9 COSMIC) and [39874842757](https://github.com/Pelagians/Current/actions/runs/39874842757)
  (Alma 9 → Alma 10 repeat) saw a fresh serial getty prompt discard the first
  username before requesting any password. The bounded handler retries a username
  only after that fresh prompt; password authentication remains mandatory.
- [39874091349](https://github.com/Pelagians/Current/actions/runs/39874091349)
  (Alma 10 COSMIC) authenticated its desktop and staged GNOME, then stopped at an
  expired sudo prompt before reboot. It requires the same fixed reauthentication
  handler used by the successful server reruns.
- [39876868579](https://github.com/Pelagians/Current/actions/runs/39876868579)
  (Alma 9 GNOME) passed all four graphical logins and exact-source rollback, then
  timed out during recovery-bootstrap diagnostics: kernel audit output interrupted
  the newline after the actual `VM_RC=0`. The framing matcher now accepts that
  complete zero status while still rejecting nonzero statuses and echoed formats.
  The incomplete attempt is not counted as a full journal/shutdown pass.
- [39876036036](https://github.com/Pelagians/Current/actions/runs/39876036036)
  (shared Fedora GNOME) produced no source autostart receipt with the earlier
  keyboard handler. The paced/focused rerun is recorded separately. The same
  pacing change already passed the complete shared Fedora COSMIC → GNOME flow.

### SELinux audit evidence and remaining health gates

The Alma 9 COSMIC → GNOME passing run's native audit capture identifies two
separate events. Its `chcon` invocation uses the exact
`invalid_bootcinstall_testlabel_t` argument from
[bootc 1.16.4's install-domain capability probe](https://github.com/bootc-dev/bootc/blob/v1.16.4/crates/lib/src/lsm.rs).
That code deliberately tests labels unknown to the loaded policy and can re-exec
in the install domain. The captured denial is retained; it does not justify
permissive mode or a new broad allow rule.

The later `colord_t` denial is substantive: reading the user's ICC profile under
`/var/home/currenttest/.local/share/icc` was denied while the file and home tree
carried `var_t`. The record includes UID, contexts, path and native audit event;
all four graphical logins nevertheless passed. This is a separate home-labeling
and color-management release gate. Read-only `matchpathcon` and
`restorecon -nRv` diagnostics compare native policy expectations without changing
labels. Service-account/NSS and Homebrew unit diagnostics are collected alongside
that repeat. A safe correction needs to establish installer-versus-native-policy
responsibility and preserve administrator contexts, accounts and user data.
No recursive relabel, guessed UID, policy exception or warning suppression is
applied on the strength of an unverified assumption.


### Native account, label and EL9 package findings

Read-only native-policy captures in
[39879990328](https://github.com/Pelagians/Current/actions/runs/39879990328) and
[39880235197](https://github.com/Pelagians/Current/actions/runs/39880235197)
record the account as UID/GID 1000 and show `altfiles` already present in the
passwd/group NSS chains. Nevertheless `getent` cannot resolve `avahi`, and
`avahi-daemon.service` exits with “Failed to find user 'avahi'”. Inspect the native
account databases, NSS library and package/sysusers provisioning before choosing
a correction; adding another NSS entry or inventing a service UID is not justified.

Native `matchpathcon` expects `user_home_dir_t` for the home root,
`icc_data_home_t` for its ICC directory and `passwd_file_t` for `/etc/.pwd.lock`.
The captures instead show `var_t` on the home/ICC data and `etc_t` on the lock.
Dry-run `restorecon` proposes corrections; it does not apply them. The narrow
next experiment is to establish correct installed-policy labeling of newly
created Anaconda account state before first login, while preserving reused homes
and administrator contexts. The enforcing `colord_t` denial remains a real
desktop-health gate, distinct from bootc's deliberate capability probe above.

The EL9 `brew-setup.service` invokes `cp -R --update=none`, which its bundled
coreutils rejects with “option '--update' doesn't allow an argument”. The unit
then specifies ownership `1000:1000` for the prefix. This matches the
[BlueBuild Brew module's documented user-owned prefix](https://blue-build.org/reference/modules/brew/);
absence of a separate `linuxbrew` login is not itself a defect. A follow-up should
make this module's initial copy compatible with EL9 while retaining existing-prefix
and no-overwrite semantics. Do not replace `cp` globally or mask the failed unit.

The broader dry-run home traversal in `39880235197` exceeded the diagnostic
deadline while enumerating Flatpak AppStream cache files. That is a harness
timeout, not evidence of a guest boot failure; the attempt remains incomplete.
The extra diagnostic repeat `39879990328` was cancelled after its source and
destination captures became available and is not counted as a complete pass.
Harness `2c5e7bc0` bounds the dry-run scan to the home root and ICC subtree, with
account and unit logs collected first. No guest labels or accounts were changed.

That bounded harness passed
[39883148573](https://github.com/Pelagians/Current/actions/runs/39883148573): all
four real graphical logins, exact GNOME source rollback, five shutdown pivots and
all 20 final journal archives. Its four greeter/session screenshot pairs were
visually inspected. GNOME's SELinux notifications and COSMIC's initial accessibility
screen remain visible; desktop applications and completion of COSMIC onboarding
were not tested. Native account/label captures reproduce the unresolved findings
above even though the login, user-service and rollback gates pass.

### Account and label corrections: initial attempts

Product revision `3bdfcaa1` changes the installer runtime's `create_user` integration to
resolve the home inside the installed root and run that payload's `restorecon`
after successful creation of a **new** home. It also labels the new account
database/lock files. Existing home trees are excluded from the added operation;
no forced context, policy exception, recursive whole-system relabel or persistent
relabel service is installed. A build-time contract check rejects upstream source
drift. This first attempt was insufficient; the subsequent SELinux API correction
and current native-policy VM results are recorded below.

The shared workstation build explicitly installs Avahi and derives a sysusers
declaration from its actual package-created UID/GID, description, home and disabled
shell. This follows [bootc's account merge guidance](https://bootc.dev/bootc/building/bootc-users-and-groups.7.html):
new package accounts in image `/etc/passwd` need runtime provisioning when the
machine has already customized that file. Existing local identities are retained
by sysusers; no UID or NSS change is guessed. VM assertions require both NSS
records and an active daemon, rather than merely a successful image build.

An Alma 9 vendor drop-in changes only Brew's initial copy from `--update=none` to
the older coreutils' `-n`. The upstream conditions, prefix, ownership and completion
marker remain in effect. Isolated copy tests preserve existing files and symlinks;
VM checks additionally require a successful setup unit, real `brew --version` as
UID 1000 and a prefix sentinel retained through rebase/reboot/rollback.

`workstation-flow` now accepts a destination distribution and optional desktop.
Across distributions the default preserves GNOME or COSMIC; within one distro
it retains the existing opposite-desktop test. All four authenticated graphical
session checks, exact-source rollback, signature policy, SELinux enforcement,
XFS, account/network retention and final journal/shutdown gates still apply.
The earlier matrix below describes the prior revision; new-image cross-distro
workstation results must be recorded separately with exact receipts.

[ISO rebuild 39888308688](https://github.com/Pelagians/Current/actions/runs/39888308688)
passed both architectures at this product revision. The x86_64 ISO checksum is
`e61f47dc1d94140b2804ab8d5e8c2a082529d98697885c58ee0ffb32dee16f1e`
(artifact `12473578764`); ARM is
`514e6d7003b63ba16eec97e64a889b1934d344027be21e4d496fcf898a38f097`
(artifact `12474600352`). Range-read receipts bind source, architecture and signed
bootstrap digest; VM jobs also hash the complete downloaded ISO. Both retain the
same pinned builder/runtime bases and XFS profile. ARM assembly is not a boot test.

[Native rebuild 39888299554](https://github.com/Pelagians/Current/actions/runs/39888299554)
was still publishing when these initial pilots began. Those pilots used only
individually verified/signed native candidate receipts and did not advance the
publisher's gates. At that point local validation passed 80 runtime and 95 image
tests, Actionlint and diff checks; final publication and tests are recorded below. The new GNOME health assertion requires
an ICC profile with native types and no captured color-daemon denial in the
current boot's kernel journal, alongside Avahi/Brew and persistent-data checks.


### First label-fix attempts and SELinux API correction

The first rebuilt ISO's stronger label assertion failed **before any destination
pull** in workstation runs `39890077246`, `39890109731`, `39890625831` and
`39890685357`, and bootstrap control `39889645399`. They are not workstation or
Avahi/Brew qualification passes. The follow-up
[installer-log capture 39892108856](https://github.com/Pelagians/Current/actions/runs/39892108856)
also failed that same gate and retained the final Anaconda journal. It proves the
new-home hook executed: `restorecon -R -v -- /var/home/currenttest` and the account
file relabel both returned zero, without changing the resulting `var_t` home.
The native policy already contained the expected home and ICC rules.

[Anaconda's bootc API setup](https://github.com/rhinstaller/anaconda/blob/main/pyanaconda/modules/payloads/payload/rpm_ostree/installation.py)
binds `/sys` nonrecursively, excluding its separate SELinux filesystem mount.
[Upstream restorecon](https://github.com/SELinuxProject/selinux/blob/main/policycoreutils/setfiles/setfiles.c)
deliberately exits zero when SELinux is unavailable to the process. The added
correction binds only `/sys/fs/selinux` after `/sys`, records it in Anaconda's
existing reverse-order teardown, and requires `selinuxenabled` to succeed before
new-home relabeling. It does not recursively expose every `/sys` submount, change
enforcement or create persistent mount/relabel configuration. Build-time source
guards and isolated mount/availability fixtures passed. The fresh-ISO control and
workstation reruns below establish the resulting native label types.

The destination image content remains at product source `3bdfcaa1`; this follow-up
changed only the installer runtime, tests and documentation. The rebuilt ISO and
reruns below reuse verified native receipts and retain the original label gate.

### Previous complete-flow matrix (e8fc3698)

All entries use ISO `39867706688` / source `7eae0d4b`, the shipped XFS profile,
UEFI/KVM with Secure Boot disabled, and signed native images at product source
`e8fc3698`. Native candidate and shared-reference digests were matched after
publication. A passed row requires the complete journal/shutdown and exact-source
rollback checks; partial graphical observations above do not count as full passes.

Server distro pairs:

| Case | Run | Reference | Result |
| --- | --- | --- | --- |
| Fedora → Alma 9 | [39871045283](https://github.com/Pelagians/Current/actions/runs/39871045283) | Native | Passed; 5 shutdowns, 22 final archives |
| Fedora → Alma 10 | [39876032534](https://github.com/Pelagians/Current/actions/runs/39876032534) | Shared | Passed; 5 shutdowns, 14 final archives |
| Alma 9 → Fedora | [39873495754](https://github.com/Pelagians/Current/actions/runs/39873495754) | Native | Passed; 5 shutdowns, 22 final archives |
| Alma 9 → Alma 10 | [39877251418](https://github.com/Pelagians/Current/actions/runs/39877251418) | Shared | Passed; 5 shutdowns, 22 final archives |
| Alma 10 → Fedora | [39871057506](https://github.com/Pelagians/Current/actions/runs/39871057506) | Native | Passed; 5 shutdowns, 14 final archives |
| Alma 10 → Alma 9 | [39871060957](https://github.com/Pelagians/Current/actions/runs/39871060957) | Native | Passed; 5 shutdowns, 18 final archives |

Workstation desktop pairs:

| Case | Run | Reference | Result |
| --- | --- | --- | --- |
| Fedora GNOME → COSMIC | [39878271136](https://github.com/Pelagians/Current/actions/runs/39878271136) | Shared | Passed; 5 shutdowns, 14 final archives; 4 graphical logins |
| Fedora COSMIC → GNOME | [39876398617](https://github.com/Pelagians/Current/actions/runs/39876398617) | Shared | Passed; 5 shutdowns, 14 final archives; 4 graphical logins |
| Alma 9 GNOME → COSMIC | [39883148573](https://github.com/Pelagians/Current/actions/runs/39883148573) | Shared | Passed; 5 shutdowns, 20 final archives; 4 graphical logins |
| Alma 9 COSMIC → GNOME | [39877182333](https://github.com/Pelagians/Current/actions/runs/39877182333) | Shared | Passed; 5 shutdowns, 18 final archives; 4 graphical logins |
| Alma 10 GNOME → COSMIC | [39875275268](https://github.com/Pelagians/Current/actions/runs/39875275268) | Native | Passed; 5 shutdowns, 14 final archives; 4 graphical logins |
| Alma 10 COSMIC → GNOME | [39877933996](https://github.com/Pelagians/Current/actions/runs/39877933996) | Shared | Passed; 5 shutdowns, 16 final archives; 4 graphical logins |

Each workstation pass contains four authenticated Wayland/logind checks: source,
destination, destination after an ordinary reboot, and original source after
rollback. Greeter and session screenshots are retained alongside the probe logs.
A final return to the original bootstrap verifies every deferred archive after
actual source rollback. No physical GPU, ARM boot, Secure Boot enabled, encrypted
layout, crash/corruption, or cross-distro workstation qualification follows from
these standard x86_64 VM cases. Desktop policy/service/account health remains
gated by the native audit evidence described above.


### Current complete-flow matrix

This matrix is the preceding `3bdfcaa1` / `6d27cf9a` baseline. The newer
`809c0fc3` warning/locale qualification is recorded in the follow-up below; these
older passes are not promoted to that revision. The heading/anchor is retained
for existing evidence links.

Destination images use product source `3bdfcaa1`; the installer uses source
`6d27cf9a`. [Native publication 39888299554](https://github.com/Pelagians/Current/actions/runs/39888299554)
passed all 51 jobs. Independent read-only checks matched all 45 native receipts,
24 shared indexes and 21 ARM compatibility references. Signing and NVIDIA gates
were retained. These checks do not qualify hardware drivers.

[ISO rebuild 39893211536](https://github.com/Pelagians/Current/actions/runs/39893211536)
passed both native architectures. The x86_64 checksum is
`be3a6b5df92c60cd3fa2eb9a04a69b31a807335d6c1682a1dd36bd9800a39aea`
(artifact `12475714467`); ARM is
`7e5bc66470a953e7fe1ec65aeed0ee666bd5c2f854d153143d020a8d5cc65836`
(artifact `12476091848`). Inputs retain the pinned builder/runtime bases and XFS
parent=0/exchange=0 profile. ARM assembly is not ARM boot qualification.

[Fresh bootstrap control 39894407267](https://github.com/Pelagians/Current/actions/runs/39894407267)
passed authenticated first boot and reboot with enforcing SELinux, correct native
home/account-file types, persistent user/network/journals and a clean shutdown
pivot/old-root unmount. The original ISO's graphical Anaconda welcome screen was
visually inspected. The final installer journal now records actual account-file
relabeling. SELinux user/range values are preserved; the assertions compare native
policy types rather than forcing a complete context.

The first six workstation runs against this ISO reached real source sessions and
completed the native health script, then failed uploading
`source-workstation-health.log`: the bounded collector's stage allowlist omitted
`source`. The `&& curl` error is a test-transport failure, not a native label,
Avahi or Brew setup failure. Runs `39896492203`, `39896498280`, `39896504809`,
`39896510990`, `39896518979`, `39896525686` remain incomplete and are not full-flow
passes. The collector now admits the exact source health path; a regression test
checks all four session stages and rejects unrelated/traversal paths. No health,
authentication, rollback or journal gate was relaxed. Local validation passes
80 runtime and 97 image tests, Actionlint and diff checks.

The current fourteen reruns use the verified shared channel on fresh x86_64
UEFI/KVM disks with software virtio graphics, Secure Boot disabled, root-only XFS
and a UID 1000 administrator. Each requires a native ICC profile for GNOME,
matching label types, no captured current-boot colord denial, a resolvable and
active Avahi daemon, successful Brew setup and real user `brew --version`, plus
a Brew-prefix sentinel retained across the target reboot and exact-source rollback.
All four real password logins and all five shutdown/journal gates remain mandatory.
All fourteen current runs passed the complete recorded flow. Individual results
are recorded below; failed earlier attempts remain failures.

One complete-flow attempt,
[39898528290](https://github.com/Pelagians/Current/actions/runs/39898528290),
passed all four COSMIC password logins, native health checks and source rollback,
then timed out during final bootstrap diagnostics. Its raw serial output shows a
complete timestamped kernel audit record inserted between `VM` and `_RC=0`.
This is not a complete-flow pass. The test reader now admits only complete audit
records between status-marker characters; tests retain nonzero-status, echo,
unrelated-text and truncated-record rejection. The affected case is rerun from
a fresh disk with unchanged ISO/product receipts and all final gates retained.

A second attempt,
[39898514712](https://github.com/Pelagians/Current/actions/runs/39898514712),
also passed all four graphical/native-health stages and exact-source rollback,
then timed out reading historical unit diagnostics after bootstrap recovery.
The retained output contains thousands of repeated COSMIC first-run Wayland
broken-pipe messages from shutdown. Optional historical/warning dumps are now
bounded to the last 1,000 entries. All closed-archive, checkpoint, full shutdown
and final-reader assertions remain unchanged. That attempt remains incomplete;
a fresh rerun uses the same signed images and ISO. COSMIC first-run completion,
application behavior and shutdown-message cleanup remain separate limitations.

Avahi's packaged UID/GID is 70 in the captured stages, with a disabled shell;
no linuxbrew login account is fabricated. Successful account resolution and
active daemon state do not prove LAN discovery. Native Avahi logs still include
missing mDNS NSS support and a chroot resolver warning on recorded EL targets.
No resolver/NSS policy is rewritten to silence those messages. The Homebrew
checks cover setup, client version and retained prefix bytes/ownership, not
arbitrary installed package ABI compatibility across distributions.

The fresh Alma 10 COSMIC→Alma 9 COSMIC rerun's
`rebase-rollback-session.png` also shows colored horizontal streaks near the
bottom edge of the software-rendered Alma 10 COSMIC session. Authentication,
session ownership and native health assertions passed, but this single frame is
not a clean-rendering qualification. The disposable guest was torn down after
collection; persistence/reproduction of that visual artifact needs a separate
rendering test. No compositor or driver workaround is introduced from one frame.

### Completed current-revision assessment (2026-10-23 UTC)

All twelve directed same-desktop distro pairs (six GNOME and six COSMIC) and
both mixed-desktop cases passed on the current receipts. Across these fourteen
fresh flows, all 56 graphical/native-health stages passed, with zero captured
current-boot colord denials and 31 ICC-file label checks. The final bootstrap
readers verified 266 archives in total across the separate VM filesystems;
that total is not a count of independent tests. All 70 recorded shutdown pivots
and old-root unmounts passed. Home/account/ICC native types, Avahi resolution and
active daemon, real user Homebrew execution and retained prefix were mandatory
at source, target, target reboot and exact-source rollback.

Target and rollback session screenshots were visually reviewed for every current
case; source and target-reboot frames were additionally sampled in three cases.
The native autostart/logind proof and greeter/password captures cover all four
stages in each flow. COSMIC frames show an authenticated session with its own
first-run window; that UI was not completed or qualified by this probe. No visual
review claim extends to all application behavior or physical GPU rendering.

The two fresh recovery reruns retain the same ISO/product receipts: the audit
marker reader correction is exercised by the Alma 10 COSMIC→Alma 9 COSMIC rerun,
and bounded observational dumps by Fedora COSMIC→Alma 10 COSMIC. Prior timeouts
remain documented above. A replay of the actual failed audit-split serial trace
also recovers its exact zero status with the corrected reader. All 177 local
tests (80 runtime and 97 image), Actionlint and diff checks pass. Later commits
modify qualification tools, workflow test/default wiring and documentation;
installed destination contents remain `3bdfcaa1` and installer runtime contents
remain `6d27cf9a`. XFS remains the default and PR #29 remains draft.

<!-- CURRENT-HEALTH-MATRIX -->

| Case | Run | Result |
| --- | --- | --- |
| Alma 10 COSMIC → Alma 9 COSMIC | [39901294471](https://github.com/Pelagians/Current/actions/runs/39901294471) | Passed; 4 graphical/native-health checks, 5 shutdowns, 20 final archives |
| Alma 10 COSMIC → Fedora COSMIC | [39898327339](https://github.com/Pelagians/Current/actions/runs/39898327339) | Passed; 4 graphical/native-health checks, 5 shutdowns, 14 final archives |
| Alma 10 GNOME → Alma 9 GNOME | [39898507969](https://github.com/Pelagians/Current/actions/runs/39898507969) | Passed; 4 graphical/native-health checks, 5 shutdowns, 18 final archives |
| Alma 10 GNOME → Fedora GNOME | [39898305861](https://github.com/Pelagians/Current/actions/runs/39898305861) | Passed; 4 graphical/native-health checks, 5 shutdowns, 14 final archives |
| Alma 9 COSMIC → Alma 10 COSMIC | [39898319639](https://github.com/Pelagians/Current/actions/runs/39898319639) | Passed; 4 graphical/native-health checks, 5 shutdowns, 22 final archives |
| Alma 9 COSMIC → Fedora COSMIC | [39898522018](https://github.com/Pelagians/Current/actions/runs/39898522018) | Passed; 4 graphical/native-health checks, 5 shutdowns, 24 final archives |
| Alma 9 COSMIC → Fedora GNOME | [39898544040](https://github.com/Pelagians/Current/actions/runs/39898544040) | Passed; 4 graphical/native-health checks, 5 shutdowns, 22 final archives |
| Alma 9 GNOME → Alma 10 GNOME | [39898299628](https://github.com/Pelagians/Current/actions/runs/39898299628) | Passed; 4 graphical/native-health checks, 5 shutdowns, 22 final archives |
| Alma 9 GNOME → Fedora GNOME | [39898500747](https://github.com/Pelagians/Current/actions/runs/39898500747) | Passed; 4 graphical/native-health checks, 5 shutdowns, 22 final archives |
| Fedora COSMIC → Alma 10 COSMIC | [39901481474](https://github.com/Pelagians/Current/actions/runs/39901481474) | Passed; 4 graphical/native-health checks, 5 shutdowns, 14 final archives |
| Fedora COSMIC → Alma 9 COSMIC | [39898312453](https://github.com/Pelagians/Current/actions/runs/39898312453) | Passed; 4 graphical/native-health checks, 5 shutdowns, 18 final archives |
| Fedora GNOME → Alma 10 GNOME | [39898493525](https://github.com/Pelagians/Current/actions/runs/39898493525) | Passed; 4 graphical/native-health checks, 5 shutdowns, 16 final archives |
| Fedora GNOME → Alma 9 COSMIC | [39898535728](https://github.com/Pelagians/Current/actions/runs/39898535728) | Passed; 4 graphical/native-health checks, 5 shutdowns, 18 final archives |
| Fedora GNOME → Alma 9 GNOME | [39898293054](https://github.com/Pelagians/Current/actions/runs/39898293054) | Passed; 4 graphical/native-health checks, 5 shutdowns, 22 final archives |

These results cover fresh unified-installer XFS layouts and standard images.
Existing/reused homes are not automatically relabeled by the added installer hook.
Classic mutable installs, older installer layouts, encrypted/separate-home setups,
custom account IDs, contaminated session preferences, full application/Brew-package
ABI behavior, physical GPUs, Secure Boot enabled and ARM boot remain unqualified.
The software graphics and version/prefix tests do not establish physical rendering,
color accuracy, LAN discovery or arbitrary package compatibility.

### Avahi, COSMIC onboarding and rendering follow-up

The fourteen completed flows above are historical results for product `3bdfcaa1`
and installer `6d27cf9a`. This follow-up retains separate installer, destination
and harness receipts; passing an earlier image does not qualify its replacement.
XFS remains the default, with Alma 9-compatible features. All tests below use
fresh disposable x86_64 UEFI/KVM disks, enforcing SELinux, standard images and
software virtio graphics, with Secure Boot disabled.

#### Current receipts and completed flows

Both [native ISO builds 39917099704](https://github.com/Pelagians/Current/actions/runs/39917099704)
passed at source `480b323e`. Later COSMIC data and probe changes do not change the
bootstrap payload or installer runtime.

| Architecture | Artifact | ISO SHA-256 | Bootstrap manifest digest |
| --- | --- | --- | --- |
| x86_64 | `12486396307` | `f8e20767b4b3d7d1dffc11a37e9cb7192d15e966d920e94da5ac0205378055ef` | `sha256:55397bb2b78a3d0d620af38f84b43ae70804744ca600606fa052a8f1801a5926` |
| aarch64 | `12486225521` | `62b20b75ad1cc1ae37ab60bf00bf77d679831b051c4dce122cd787303a5152d3` | `sha256:ab3feaaeae6cda5fe50ec52a782d202bde208482df5b51ae9614d3cff84a6f01` |

The strict [bootstrap control 39919245213](https://github.com/Pelagians/Current/actions/runs/39919245213)
passed native home/account labels, English locale, complete native Avahi startup
journals, authenticated setup/resume, retained networking, ordinary reboot and
shutdown. ARM ISO assembly does not qualify ARM boot or Secure Boot.

The final [native rebuild 39932122029](https://github.com/Pelagians/Current/actions/runs/39932122029)
at `782560bf` passed all 51 native/publication jobs after the inspected retries.
Independent inspection matched all 45 native receipts, 24 shared indexes and
21 ARM compatibility references to that exact source. The three tested COSMIC
source/target digests also match the published x86_64 children; these are not
merely same-commit images with different native digests. The native x86_64 and ARM64 Alma 9 logs record 249 missing
country flag fields added; already-compatible Alma 10 data receives zero changes.
Three final-source COSMIC flows below passed actual native first-run completion,
reboot, exact rollback and recovery. Rendering remains separately unqualified.

Its first attempt retained 41 successful native images. Three x86_64 Alma 9
COSMIC variants exhausted native COPR RPM downloads with curl timeout 28 before
reaching the compatibility helper. The last Alma 10 NVIDIA server lane was
cancelled after about 50 minutes to inspect its log and release the held retry.
That log shows a core-package step taking 24 minutes, partial/slow native mirror
downloads, then successful layer export; cancellation stopped its push. It is a
cancelled diagnostic attempt, not a measured recipe failure. The publisher ran
no steps. The first retry retained successful artifacts. Standard/R580 Alma 9 COSMIC
passed; open-driver COPR timeouts and NVIDIA-server CUDA HTTP/2 errors required
further isolated retries. The server passed on attempt 3; Alma 9 open-driver
passed on attempt 4. Successful artifacts from the same source were retained;
all signing, NVIDIA and complete-publication gates remain.

The preceding amended build `dc78334d` passed all 45 native image jobs. Its
publisher was cancelled as superseded by the measured country-schema fix.
Independent checks after cancellation still matched all 24 shared references and
21 ARM aliases to the preceding complete `809c0fc3` publication
([39909852390](https://github.com/Pelagians/Current/actions/runs/39909852390), all
51 jobs). No partial publication is advertised.

These five complete amended flows use the current ISO and exact signed native
`dc78334d` candidates. Each passed five shutdown pivots, target reboot,
exact-source rollback and final bootstrap verification of all retained archives.
They test the NSS/locale correction; the later country-data change is COSMIC-only.

| Source → destination | Run | Final closed archives |
| --- | --- | ---: |
| Fedora server → Alma 9 server | [39923105988](https://github.com/Pelagians/Current/actions/runs/39923105988) | 20 |
| Alma 10 server → Fedora server | [39924899585](https://github.com/Pelagians/Current/actions/runs/39924899585) | 14 |
| Fedora GNOME → Alma 9 GNOME | [39925741875](https://github.com/Pelagians/Current/actions/runs/39925741875) | 18 |
| Alma 9 GNOME → Alma 10 GNOME | [39925752932](https://github.com/Pelagians/Current/actions/runs/39925752932) | 23 |
| Alma 10 GNOME → Fedora GNOME | [39925761838](https://github.com/Pelagians/Current/actions/runs/39925761838) | 14 |

All checkpoints passed complete native Avahi unit-journal and English-locale
assertions. Each GNOME flow passed four real greeter/password logins, native
home/ICC/account types, zero captured colord denials, Avahi account resolution,
both provider/default mDNS lookups and actual non-root Homebrew version/prefix
checks. These do not establish arbitrary Homebrew package ABI compatibility.

#### Final-source COSMIC flows

These three full functional passes use the current `480b323e` ISO and signed
`782560bf` native candidates. Exact source/target native digests are asserted at
source, target, target reboot and rollback. Each starts with a fresh source home
and completes the native welcome through visible Next/Finish, then requires its
own marker and process exit. Destinations correctly retain that native marker.

| Source → destination | Run | Final closed archives | Primary capture review |
| --- | --- | ---: | --- |
| Fedora COSMIC → Alma 10 COSMIC | [39938983888](https://github.com/Pelagians/Current/actions/runs/39938983888) | 14 | Artifact after Alma 10 reboot; 32 captures, 8 pixel-distinct frames reviewed |
| Alma 10 COSMIC → Alma 9 COSMIC | [39943996307](https://github.com/Pelagians/Current/actions/runs/39943996307) | 18 | Clean sampled source/target/reboot/rollback; 32 captures, 7 distinct reviewed |
| Alma 9 COSMIC → Fedora COSMIC | [39946774367](https://github.com/Pelagians/Current/actions/runs/39946774367) | 22 | Clean sampled source/target/reboot/rollback; 32 captures, 9 distinct reviewed |

Together these passed 12 actual greeter/password logins and native health checks,
15 shutdown pivots/old-root unmounts, and 54 final closed archives verified by the
original bootstrap reader. Every checkpoint passed complete native Avahi unit
journals and English-locale assertions; every graphical stage passed both mDNS
resolver paths, native home/account types, actual non-root Brew execution and
zero captured current-boot colord denials. All 96 primary captures retain their
original pixels (72 QMP, 24 portal); decoded-pixel equality only groups duplicates
for manual review. Captures share the same guest rendering stack, so they do not
independently qualify physical GPUs. The initial unmodified ISO screenshot was
also reviewed and shows graphical Anaconda's language page.

The preceding corrected Fedora→Alma 10 run `39925428329` passed on this ISO with
`809c0fc3` candidates. It is historical probe/onboarding evidence, superseded by
the final-source functional flow above; none of these passes establishes clean
COSMIC client teardown, all application behavior or physical rendering.

#### Avahi and locale corrections

Avahi's [NSS check](https://github.com/avahi/avahi/blob/master/avahi-client/check-nss.c)
loads an mDNS library; absence of its warning alone does not prove that the
normal resolver chain uses that library. Earlier images lacked the native
module. Early resolver/chroot warnings match the NetworkManager volatile-file
startup race described in [upstream issue 153](https://github.com/avahi/avahi/issues/153).

Shared workstation layers now install native `nss-mdns` and `avahi-tools`.
Fedora bootstrap/server images also receive `nss-mdns` because their base already
runs Avahi. The vendor drop-in requests and orders after `network-online.target`;
Alma servers do not acquire an unnecessary daemon. Chroot, NetworkManager and the
distro RPMs' NSS integration remain enabled. There is no static resolver file,
forced authselect/PAM rewrite or empty resolver target. The
[wait-online contract](https://networkmanager.dev/docs/api/latest/NetworkManager-wait-online.service.html)
can delay offline startup; it establishes startup completion, not internet access.

`--require-clean-avahi` saves the complete native current-boot Avahi unit journal
at every checkpoint and rejects the three original NSS/resolver/chroot warnings.
Read failure fails qualification. Missing Avahi on an Alma server does not start
it. Workstation `--require-mdns` additionally requires an active daemon and
short-lived isolated `avahi-publish` record, resolved through both explicit
`mdns4` and normal `getent ahostsv4`. Cleanup is bounded on success/failure.
This qualifies local daemon/NSS integration, not external LAN discovery or
administrator-custom resolver profiles.

The earlier bootstrap contained only `glibc-minimal-langpack`; `locale -a` listed
C, C.utf8 and POSIX. Native Anaconda logs explicitly rejected the selected
`en_US.UTF-8` as absent and used its valid C.UTF-8 fallback, consistent with
[upstream installation logic](https://github.com/rhinstaller/anaconda/blob/main/pyanaconda/modules/localization/installation.py).
Minimal `glibc-langpack-en` in bootstrap and the common OS layer preserves the
actual English choice across distributions. No LANG/LC_ALL or per-user override
is introduced. Strict tests require native libc support, system configuration
and real graphical-session LANG. Other languages and intentional C locales
remain unqualified.

#### Measured Alma 9 COSMIC first-run incompatibility

[Native session journal 39927020805](https://github.com/Pelagians/Current/actions/runs/39927020805)
explains the empty language page: `json parsing error: missing field flag at
line 8 column 5`. System/session English and compiled locales were valid. The
[signed read-only Podman inventory 39925412874](https://github.com/Pelagians/Current/actions/runs/39925412874)
proved that `iso-codes-4.6.0-3.el9.noarch` and all three required JSON documents
already existed and parsed. Merely installing that package would not fix the
client-schema mismatch.

The [exact 1.9 registry dependency](https://github.com/AerynOS/locales-rs/blob/e5b66fbe3a55182174caf6aec171ff4ae8285626/src/iso_3166.rs)
requires a string `flag` in every country record. The 1.11 dependency differs
only in repository funding metadata, not runtime code. Shared COSMIC builds now
explicitly require iso-codes and run `cosmic-locale-compat.sh` after desktop and
Flatpak layers. It adds only absent flag strings as
[Unicode regional-indicator pairs](https://unicode.org/reports/tr51/#Flags)
derived from existing native `alpha_2` codes. No countries, identifiers, names
or existing flag values are replaced. Compatible files remain byte-identical;
malformed metadata fails before writing.

This build-time compatibility step deliberately changes a package-owned data
file: `rpm -V iso-codes` can report that expected modification. Current's image
signature authenticates the resulting bytes; native package provenance/license
remain. There is no second catalogue, per-user environment override or forged
first-run marker. Three fixture tests cover identity/data/mode preservation,
idempotence, compatible bytes and fail-before-write. All 185 final local tests pass
(80 runtime, 105 image), plus Actionlint and diff checks. Native GUI completion
on the new image remains the acceptance gate.

The signed x86_64 Alma 9 standard retry passed and added 249 fields, as the
native ARM build did. Fresh run `39943977653` has no country-registry error, but
stops on the Accessibility page: the native 1.9 window extends below the 1280×800
output and Next is offscreen. No completion action/marker was manufactured.
The fresh [rerun 39946774367](https://github.com/Pelagians/Current/actions/runs/39946774367)
fit naturally and completed visible Next/Skip/timezone/Finish with the native
marker and process exit. Its action trace contains no fullscreen/window action.
A guarded shortcut introduced in harness `92d343ed` was therefore unexercised
and removed in `3d43d6c4`; the final harness returns to the actually exercised
control path, with the original display and renderer. The intermittent viewport
failure remains a qualification limitation, not a claimed UI fix. The country
schema fix is validated by actual native completion, without preference resets,
resolution changes or fabricated state.

COSMIC's [native Finish action](https://github.com/pop-os/cosmic-initial-setup/blob/master/src/main.rs)
records completion. The probe requires that action, its marker and process exit;
it never writes the marker, resets preferences or masks autostart. It uses
recognized unique visible controls, real screenshot consent, optional Wi-Fi Skip
only on the explicit no-networks page, and the native timezone search/Enter for
Dakar (UTC), an ordinary disposable-user preference. Wired networking is checked
separately; wireless setup is not qualified.

#### Warning and rendering limits

All three final-source serial captures have zero matches for the known locale
parser, locale-registry and first-run disconnect patterns after native completion.
Other COSMIC/portal clients still emit Wayland Broken-pipe messages and portal
thread panics during teardown. Their retained serial captures contain 3,216,
3,291 and 2,957 matching client-disconnect lines respectively. These include
replayed diagnostic history, not independent failures or complete unique-event
counts; bounded snapshots overlap. All 15 shutdown pivots and final archive
checks passed. These are filesystem/lifecycle passes, not clean app-shutdown
qualification.
[The 1.9](https://github.com/pop-os/cosmic-session/blob/epoch-1.9.0/src/main.rs)
and [1.11 session implementations](https://github.com/pop-os/cosmic-session/blob/epoch-1.11.0/src/main.rs)
abort compositor work before deferred target teardown; that is consistent with
client disconnects, not proof that every message is harmless. No speculative
session backport, service mask, log suppression or renderer override is applied.
Fresh-session missing configuration/cache, UTC geodata and virtual-GPU Mesa
warnings remain recorded; general application behavior is not qualified.

The earlier Alma 10 COSMIC rollback `39901294471` retained colored horizontal
streaks at the bottom edge of `rebase-rollback-session.png`. The completed newer
Alma 10 target sample `39925428329/rebase-target-after-render-2.png` is visibly
clean. It is a different transition checkpoint, so this does not establish an
artifact fix. The final Alma 10 rollback in `39943996307` is also clean, while
the separate target-reboot case below reproduces the problem.

Final-source Fedora→Alma 10 run `39938983888` passed the functional flow (four
native graphical/health checks, five shutdown pivots, 14 final archives), but
**reproduced the bottom-edge streaks after the Alma 10 target reboot**. All six
QMP frames and both native portal captures across that stage's before/after
sets have identical pixels and show the artifact. The initial Alma 10 target
and Fedora rollback frames are clean. All 32 primary captures reduce to eight
pixel-distinct frames, each visually reviewed; crops/consent probes are excluded
from that count. Software rendering is not qualified by the functional pass.
The affected and clean boots use the same Alma 10 cosmic-comp 1.11.0 and Mesa
25.2.7 packages. The panel's EGL BAD_ALLOC initialization warning appears in all
four sessions, including clean ones, so that line alone does not identify the
cause.

[Upstream panel issue 576](https://github.com/pop-os/cosmic-panel/issues/576)
reports intermittent software-rendered VM artifacts around a floating dock.
That is a close candidate match for the observed location/configuration, not a
confirmed Current root cause. The issue remains open without an attached fix at
this checkpoint. The safe next rendering step is an upstream/minimal software-VM
reproduction and a qualified native package fix, followed by the same original
QMP/portal comparison. No persistent dock expansion, renderer/environment override
or preference reset is applied to hide the artifact. Native portal processes
also retain shutdown panics on Wayland disconnect; this is stronger than a quiet
shutdown claim, even though filesystem pivots and archive checks pass. No coredump
suppression or service-success override is used.

Each COSMIC login retains three unmodified QMP frames three seconds apart before
and after onboarding, plus a native portal screenshot through the actual user
manager. These capture paths share the guest graphics stack and do not provide
independent physical-GPU evidence. Crops/contrast changes exist only in separately
named OCR diagnostics; original evidence is never altered. Missing portal output
or nonzero exit fails before any onboarding/rendering claim.

#### Retained diagnostic failures

Earlier probe failures are retained instead of being promoted to compatibility
passes. Artifact service 503/redirect failures temporarily prevented inspection;
access recovered. No conclusion was inferred from inaccessible evidence.

| Run(s) | Result and subsequent action |
| --- | --- |
| `39905046419`, `39905053393` | Original-image controls exposed a blocking screenshot-consent probe; changed to asynchronous native consent |
| `39907117956`, `39912392568`, `39912482280`, `39912488784` | Cancelled as superseded before qualification |
| `39908306518` | Native signed Avahi pilot stopped in OCR; not a complete flow |
| `39908189677` | Bootstrap control confirmed absent English locale and Anaconda fallback |
| `39905610863` | Avahi-only build cancelled; publisher executed no steps |
| `39911888427`, `39912020799`, `39912031177`, `39911974392`, `39912956615`, `39912963968` | Six complete bootstrap/server/GNOME controls at `809c0fc3`; inherited Fedora NSS warning subsequently corrected |
| `39912696556`, `39912702689`, `39912710312` | COSMIC probes stopped on cursor-occluded Next or unrecognized permission modal; original frames retained |
| `39919462672`, `39927020805` | Corrected Alma 9 probe reached actual empty language page; latter retained exact schema error |
| `39921090622`, `39921099634` | Populated timezone page required ordinary city selection; harness corrected |
| `39922866183` | Docker inventory failed with max-depth before reading data; Podman inventory subsequently passed |
| `39932122029`, attempt 1 | Three native COSMIC RPM-download failures and one prolonged server build cancelled for diagnosis; four-lane retry retains successful artifacts |
| `39932122029`, attempt 2 | Standard/R580 Alma 9 COSMIC retries passed; Alma 9 open-driver COPR downloads and Alma 10 NVIDIA-server CUDA HTTP/2 downloads failed; two-lane retry retains successful artifacts |
| `39932122029`, attempt 3 | NVIDIA server passed; Alma 9 open-driver COPR timeout remained; that single lane passed on attempt 4 |
| `39943977653` | Country registry error absent; first-run Next below the native viewport; fresh rerun fit naturally and passed without shortcut fallback |

The corrected OCR probe combines original whole-frame OCR with OCR-only interiors
of bounded cyan controls, requires high-confidence exact title/unique label, and
parks the released pointer away from the next button. Native marker/process exit,
real PAM login, signed immutable image validation, native health, closed-journal
and shutdown gates remain mandatory. No test failure is bypassed by creating user
state. Final qualification still excludes physical GPUs, Secure Boot enabled,
ARM boot/Apple Silicon, reused/encrypted/separate homes, custom IDs, arbitrary
applications/Brew packages and external LAN discovery.

#### Native repair candidates for the three remaining COSMIC failures

The follow-up keeps the signed source `782560bf` parent images and the source
`480b323e` XFS installer unchanged while testing narrowly patched native RPMs.
The parent digests, native source RPM checksums and patches are recorded in
[`packages/cosmic-repairs`](../../packages/cosmic-repairs/README.md).

The portal's unrecoverable Wayland dispatch arm explicitly calls `panic!` in
both native 1.9 and 1.11 sources. The candidate logs the dispatch error and exits
unsuccessfully instead, preserving the existing service failure/recovery
semantics without unwinding the worker. This targets the reproduced panic; it
does not classify unexpected compositor disconnects as successful shutdowns.

Alma 9's exact source RPM contains a native `libcosmic` initial window size of
1024×768 while the welcome application specifies only a 900×650 maximum. The
candidate supplies an explicit 900×650 initial size and scrollable content with
native navigation outside the scroll region. It preserves real completion,
user preferences and output configuration. The isolated Alma 10 panel candidate
requests full repaint for non-expanded surfaces so transparent margins cannot
rely on stale EGL buffer contents. Its effect on the reproduced streaks remains
to be established by repeated unmodified QMP/portal captures; repaint cost and
other GPUs are not qualified by source inspection.

The repair-only workflow rebuilds five pinned native source RPMs with vendored
Cargo dependencies and native test/install/license sections, then produces
three signed disposable x86_64 bootc candidates. It does not promote normal
Current image tags or claim ARM repair qualification. The existing main builder
can dispatch this mode without adding a workflow to `stable`.

The first Docker attempt exposed `max depth exceeded` while loading the deep
Alma 9 image, before patch compilation. The retry uses the already established
Podman diagnostic path without squashing the production images. A native Python
3.9 hashing compatibility correction accompanies that retry. Build and VM
receipts must establish effectiveness before the normal recipes consume these
packages.

The VM harness now retains complete native journal JSON for each COSMIC boot,
selected by its kernel boot ID and read using the original bootstrap after
rollback. This avoids both serial diagnostic replay and EL9 reader limitations.
Native COSMIC panic or coredump records fail the flow; Wayland dispatch errors
remain separately reported. Component versions and repair receipts accompany
original rendering captures. Historical functional passes above do not satisfy
this stronger gate retroactively.

Native repair build `40000873803` (source `d1a11feb`) successfully rebuilt and
retained **all five** requested RPM/source-RPM artifacts. Alma 9 welcome's native
check section passed 14 tests. The panel and portal test targets compile, but
those checked targets report zero assertions; they do not qualify these runtime
fixes. Native binary receipts bind the source RPM, original signed parent,
patch bytes and builder script. The obsolete assembly was stopped after all
five package jobs succeeded because its tag lacked the setup API's required
`br-` namespace. Corrected assembly `40008717786` reuses those matching artifacts
at source `5064b03b`, validates their binary checksums, and produces fresh signed
`br-repair-run-*` candidates without recompiling them.

Original-image control `40002682168` completed native onboarding and four real
PAM logins across Fedora→Alma 10, ordinary target reboot and exact rollback, but
failed at the new journal query: this reader rejects the hyphenated kernel UUID
as a boot descriptor. This is a harness failure, not proof of the panic gate.
Source `5064b03b` canonicalizes the authenticated kernel UUID to 32 hex digits
and checks the returned journal's boot identity; a regression fixture includes
the actual failed UUID. The query retains complete messages and diagnostic/core
metadata without uploading memory blobs or process environments. Control rerun
`40007524413` completed the same four real PAM sessions and failed on native
Wayland-dispatch `Broken pipe` panics in all four completed boots. This confirms
the stricter gate detects the original defect; it is not a repaired-image pass.
The first control's Alma 10 initial/reboot dock samples are visually clean and
have zero changes in 38,400 fixed margin pixels. The older reproduced case
`39938983888` has 1,129 changed pixels in those same margins in both QMP and
portal captures. That difference reinforces the intermittent nature of the
artifact; a single clean new sample cannot establish a fix.

Candidate assembly `40008717786` passed all three native image builds and Cosign
verification, but VM `40009759614` correctly rejected its Alma 9 image before
staging: `A signature was required, but no signature exists`. The isolated
publisher omitted Current's existing Cosign v3 legacy-attachment flags. Source
`d677e809` applies `--new-bundle-format=false --use-signing-config=false`, matching
the normal publisher. The bootstrap trust policy is unchanged. Build
`40011318210` reuses the verified native RPMs and reassembles corrected candidates.
Build `40011004179` also exposed an explicit Containerfile-path omission in the
new runtime/source bundle job; its obsolete candidate assembly was cancelled
after all five RPM seed jobs succeeded. No native compiler was cancelled.

All three original candidate VM attempts (`40009759614`, `40010554179`,
`40010568297`) stopped at the same enforced-signature failure before staging;
none reached a repaired desktop. Corrected build `40011318210` at `d677e809`
passed all five native artifact checks, three candidate assemblies and the
runtime/source bundle publication. The immutable bundle references in
`packages/cosmic-repairs/bundle.json` were independently resolved using
`skopeo inspect --no-creds`; the returned manifest hashes matched both pins.
The normal shared COSMIC layer now mounts the approximately 57 MiB runtime
bundle read-only. It verifies RPM bytes, metadata and native versions before
an offline install, retains receipts, and leaves source archives/build tools
out of the payload. CI verifies the bundle's Current signature. ARM retains
its upstream native RPMs, explicitly outside these x86_64 repairs.
