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

The fourteen completed flows above describe product `3bdfcaa1` and installer
`6d27cf9a`. The following work does not retroactively qualify a newer image.

Avahi's upstream [NSS check](https://github.com/avahi/avahi/blob/master/avahi-client/check-nss.c)
tries to load an mDNS library; a quiet log alone does not prove that the machine's
`hosts:` chain uses it. All captured distributions lacked that library. The
sporadic resolver/chroot warnings occur on early boots and disappear on ordinary
reboots. Upstream [issue 153](https://github.com/avahi/avahi/issues/153) describes
the same NetworkManager volatile-resolver startup race. Native resolver symlink,
DNS, dependency and timestamp diagnostics are now captured before choosing any
additional policy change.

Product `2592911a` adds the native `nss-mdns` and `avahi-tools` packages to the
shared workstation substrate and an immutable Avahi drop-in with
`Wants=network-online.target` and `After=network-online.target`. It retains chroot,
NetworkManager and the distribution packages' NSS integration; it does not write
a static resolver file, force an authselect profile, rewrite live hosts/PAM
chains, or create empty resolver targets. The
[NetworkManager wait-online contract](https://networkmanager.dev/docs/api/latest/NetworkManager-wait-online.service.html)
waits for startup to complete, not internet availability, and can delay offline
boot depending on connection profiles. Existing workstation Brew setup already
requests this target; native VM dependency/timing captures must verify the effect.

The new `workstation-mdns-flow` workflow option retains the entire workstation
flow and adds `--require-mdns`: a short-lived `avahi-publish` record on the
isolated guest, both explicit-provider and normal `getent ahostsv4` lookups, and
absence of the original Avahi startup warnings. The publisher is terminated on
success, lookup failure or timeout. This tests the local daemon/NSS path; external
LAN discovery and administrator-custom resolver profiles remain separate gates.

COSMIC's [first-run program](https://github.com/pop-os/cosmic-initial-setup/blob/master/src/main.rs)
intentionally runs until its own Finish action records completion. Earlier tests
left that window open. The new probe captures its actual locale/environment and
uses unique visible Next/Finish controls; it requires the native completion marker
and process exit. It never writes the marker, masks autostart or resets preferences.
Its expected first-run UI is not itself a failure. Upstream
[session teardown](https://github.com/pop-os/cosmic-session/blob/master/src/main.rs)
stops compositor work before its deferred systemd target stop; warnings from
clients losing Wayland need actual lifecycle evidence before a downstream fix.

Rendering capture retains the original 1280×800 software virtio GPU. Each COSMIC
stage captures repeated unmodified QMP frames before and after onboarding and
requests a native noninteractive portal screenshot through the real user-manager
environment. Missing portal captures are reported explicitly; they do not become
rendering passes. These two capture paths share the same guest rendering stack
and are not independent physical GPU qualification. No renderer/driver setting
or warning suppression is introduced.

[Native rebuild 39905610863](https://github.com/Pelagians/Current/actions/runs/39905610863)
is running at `2592911a` with the existing signature, NVIDIA and full shared-index
gates. ISO/runtime content is unchanged from `6d27cf9a`; its receipts are reused.
Local validation passes 80 runtime and 99 image tests, plus Actionlint and diff
checks. Baseline investigation runs
[39905046419](https://github.com/Pelagians/Current/actions/runs/39905046419) and
[39905053393](https://github.com/Pelagians/Current/actions/runs/39905053393) use
unchanged `3bdfcaa1` images and harness `c8f9c554`; they do not test the Avahi fix.
Fresh current-image mDNS flows remain required after publication.

The first two controls (`39905046419`, `39905053393`) both stopped at the new
onboarding gate. Retained Fedora frames prove the capture probe itself opened
COSMIC's normal “Allow Apps to Take Screenshots?” permission dialog, which remained
over the first-run page after the blocking request timed out. These are probe
failures, not evidence that Next/Finish is broken. Harness `4c077165` makes that
request asynchronous, recognizes the exact visible permission title and a unique
Allow control, and records normal GUI consent in the disposable user's session.
No permission-store edit, portal bypass or product policy change is made. Sparse
text OCR handles small footer controls; missing/ambiguous controls still fail.
The early native pilot `39907117956` was cancelled during tool setup because it
retained the confirmed probe defect; replacement
[39908306518](https://github.com/Pelagians/Current/actions/runs/39908306518) uses
the corrected probe and individually verified signed `2592911a` candidates.

The Fedora control also captures `LANG=C.UTF-8` in both the real graphical session
and system locale, despite the English Kickstart answer. This is a valid POSIX
locale; COSMIC's locale parser warnings do not make it corrupt. Upstream
[Anaconda language installation](https://github.com/rhinstaller/anaconda/blob/main/pyanaconda/modules/localization/installation.py)
falls back to `C.UTF-8` when the installed payload cannot support the selected
locale. A fresh
[bootstrap locale control 39908189677](https://github.com/Pelagians/Current/actions/runs/39908189677)
collects installed locale packages and final Anaconda language logs before a
payload change is chosen. No forced LANG/LC_ALL override is introduced. Local
checks now pass 80 runtime and 100 image tests, including title-guarded screenshot
consent and rejection of ambiguous controls.

The bootstrap locale control passed its ordinary label/authentication/reboot gates
and confirmed the missing support: `glibc-minimal-langpack` was installed,
`glibc-langpack-en` and `glibc-all-langpacks` were absent, and `locale -a` listed
only `C`, `C.utf8`, `POSIX`. The final Anaconda journal explicitly records
`en_US.UTF-8` matching no installed locale, the unsupported-locale decision,
and writing `C.UTF-8` as its fallback. This is a payload-content issue rather
than an invented greeter-language override.

Revision `809c0fc3` adds `glibc-langpack-en` to the minimal bootstrap and common
OS layer. The latter keeps the installer's English choice available on server
as well as workstation destinations. This adds locale data, not a desktop or
persistent environment override. Anaconda still selects the locale. Other
bootstrap languages remain limited to installed support; broad multilingual
setup and deliberately selected C locales are not qualified by this correction.

The Avahi-only build `39905610863` was intentionally cancelled as superseded.
Its shared-publisher job executed no steps; partial native successes are not a
complete publication pass. The individually signed `2592911a` pilot remains a
diagnostic of that earlier content. The coherent rebuilds are now
[native images 39909852390](https://github.com/Pelagians/Current/actions/runs/39909852390)
and [both ISOs 39909853781](https://github.com/Pelagians/Current/actions/runs/39909853781),
with all existing signature/NVIDIA/shared-index gates retained. These builds
must pass before the new revision is called qualified.

Strict workstation mDNS, bootstrap-locale and server rebase-locale scenarios now
require the selected English locale in `/etc/locale.conf` and native libc; real
graphical-session captures must retain it too. They do not set LANG/LC_ALL to make
an assertion pass. Fresh current-ISO flows must repeat native home/ICC, accounts,
mDNS, first-run completion, password login, reboot, exact-source rollback and
full final journal/shutdown gates. The earlier fourteen-flow matrix remains
historical evidence for `3bdfcaa1` / `6d27cf9a`.

The Avahi-only native pilot `39908306518` passed its source Alma 9 mDNS checks:
both explicit `mdns4` and ordinary NSS returned the temporary published address,
and the captured Avahi startup-warning count was zero. Its full flow failed at
onboarding because default OCR omitted the visibly present Next control; it is
not a completed transition. Original PNGs remain unchanged. Local calibration
against that exact frame found Tesseract's adaptive thresholding recognizes Next
at 93% confidence; harness `cfbb3b76` uses that standard OCR option, retains the
unique-control gate, and accepts both observed screenshot-permission titles
(“Allow Apps…” and “Allow Applications…”). It still requires upstream's own
completion marker and process exit. No guessed coordinate or fabricated state
replaces the UI.

Both `809c0fc3` ISO jobs passed. Small receipt reads bind x86_64 artifact
`12483430069` to ISO SHA-256
`8d1457e8d86d922c8a2796a8c4f532314469bf7985bb3892d47e5783dee3f356`
and bootstrap digest
`sha256:93a1b1ca7d56574b940cb6882fb94d2e29b3f5e2c8db89a08dc944e13828ccfc`.
The native ARM64 artifact `12482603287` has ISO SHA-256
`c25fd94cd7e18cff89365698d9a438305e021358817114b09278c85c1928fd40`
and bootstrap digest
`sha256:87e1006462b5214dcc0922eb27ee7f5dc1948074e297fa21fe1dad03f76f25c6`.
Native ARM assembly is not ARM boot qualification. The x86_64 locale control
[39911888427](https://github.com/Pelagians/Current/actions/runs/39911888427)
uses this new ISO. The native image rebuild is still pending at this checkpoint;
individually signed native candidates can be tested before publication, but the
complete publication and shared-index checks remain mandatory and separate.

The first three pending COSMIC runs (`39912392568`, `39912482280`, `39912488784`)
were cancelled before VM qualification as superseded: the longer Alma screenshot
permission title wraps, and actual TSV inserts blank hierarchy rows between its
words. Harness `36884f41` collapses OCR whitespace before matching either observed
title, with a wrapped-word fixture; it still requires one visible Allow control.
Replacement COSMIC runs are `39912696556`, `39912702689`, `39912710312`.
The final representative matrix uses exact signed native candidate tags from
`39909852390`; shared publication/architecture/index receipts are independently
qualified afterward. Native-candidate runs are not evidence that a partial
publication succeeded.

Both new `809c0fc3` server locale controls passed the entire rebase/reboot/rollback
flow: Fedora→Alma 9 (`39912020799`, 18 final archives) and Alma 10→Fedora
(`39912031177`, 14 archives), with five clean shutdown pivots each. Their native
locale assertions passed at every stage. The warning review nevertheless found
`No NSS support for mDNS` in the Fedora bootstrap/server boots: those already
inherit a running Avahi from the Fedora bootc base, outside the workstation
substrate. Revision `dd43ff64` supplies `nss-mdns` in bootstrap and the Fedora distro
core layer too. It does not enable a new service or add Alma server dependencies.
These server passes remain exact-revision diagnostic evidence; the amended
payload requires new ISO/image builds and affected-flow reruns.

The existing vendor Avahi network-online drop-in is shared through the base
runtime files and explicitly included in the minimal bootstrap. Its content is
unchanged; workstation, inherited Fedora server and bootstrap Avahi use one
ordering policy. No persistent service mask, resolver file or chroot exception
is introduced. Alma servers without Avahi are not given a new daemon. Ordinary
DNS/locale/rebase checks are distinct from the workstation's temporary-record
mDNS qualification.

Artifact retrieval then returned HTTP 503, “Egress is over the account limit,”
including a bounded range request for only the failed COSMIC result JSON.
[Azure's error reference](https://learn.microsoft.com/rest/api/storageservices/common-rest-api-error-codes)
classifies that as `ServerBusy`; it is not by itself evidence of billing or
permission failure. The completed Alma 9 COSMIC→Fedora COSMIC run `39912696556`
failed its VM step, but its actual error/captures could not yet be retrieved.
The normal job-log connector also failed, and the CLI's redirected log endpoint
returned 403. No root cause or compatibility pass is inferred from missing logs.
Artifact retries use backoff; automatic dispatch of the amended build was held
while this failure was investigated. Existing VM jobs remain observed.

The new `--require-clean-avahi` qualification mode shares the native journal
checker with workstation mDNS health, saves complete current-boot unit output
through the existing bounded HTTP evidence collector, and applies at every
bootstrap/server/workstation checkpoint. Missing/failed journal reads fail;
absence of an Avahi unit on an Alma server does not start one. The workstation's
separate active-service and provider/default lookup checks remain mandatory.
Local validation now passes 80 runtime and 101 image tests.

Artifact service access recovered. The complete `809c0fc3` native publisher passed
all 51 jobs; independent checks matched all 45 native receipts, 24 shared indexes
and 21 ARM compatibility aliases. The earlier six-of-nine representative results
are: bootstrap, both server rebases and all three GNOME transitions passed; all
three COSMIC controls stopped in the UI probe, not in a qualified complete flow.
The failed Fedora frame retains a native screenshot-permission modal; the
adaptive whole-frame OCR omitted its white title/Allow label. The Alma 9 frame
reached “Get connected,” but the hand cursor covered Next. The Alma 10 frame
retains its permission modal after the screenshot request failed, so it did not
test onboarding beyond that obstacle.

Harness `dc78334d` reads the unmodified full frame plus small OCR-only control
interiors derived from bounded cyan regions, requires the real title and unique
recognized control, and moves the pointer away after releasing a click. Raw QMP
and portal images are retained. The later confidence filter excludes the actual
low-confidence icon OCR between Alma's wrapped title words; local calibration
recognizes Allow on both saved permission frames and Next on the saved first-run
frame. The optional native Wi-Fi page's visible Skip control is used only with
“No networks have been found”; these guests have already passed wired networking
checks. No Wi-Fi, preference reset or fabricated first-run completion is implied.
Native Finish/marker/process-exit gates remain mandatory.

Both amended ISO jobs
[39917099704](https://github.com/Pelagians/Current/actions/runs/39917099704) passed
at source `480b323e`; the later probe changes do not alter installed payloads.
The x86_64 artifact `12486396307` has ISO SHA-256
`f8e20767b4b3d7d1dffc11a37e9cb7192d15e966d920e94da5ac0205378055ef`
and bootstrap digest
`sha256:55397bb2b78a3d0d620af38f84b43ae70804744ca600606fa052a8f1801a5926`.
ARM64 artifact `12486225521` has ISO SHA-256
`62b20b75ad1cc1ae37ab60bf00bf77d679831b051c4dce122cd787303a5152d3`
and bootstrap digest
`sha256:ab3feaaeae6cda5fe50ec52a782d202bde208482df5b51ae9614d3cff84a6f01`.
The fresh strict bootstrap control
[39919245213](https://github.com/Pelagians/Current/actions/runs/39919245213)
passed native Avahi warning/English-locale assertions, authenticated setup,
persistence, reboot and shutdown. Native ARM assembly still does not qualify
ARM boot or Secure Boot.

The amended full native matrix
[39920333623](https://github.com/Pelagians/Current/actions/runs/39920333623) is
running at `dc78334d`. The corrected UI pilot
[39919462672](https://github.com/Pelagians/Current/actions/runs/39919462672)
uses the amended `480b323e` ISO and exact signed `809c0fc3` Alma 9/Fedora COSMIC
candidates. That isolates the probe/NSS-bootstrap changes; it is not evidence
that the amended destination matrix has passed. Local checks pass 80 runtime
and 102 image tests, plus Actionlint and diff checks. XFS is unchanged.
