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

### Account and label corrections under qualification

Product revision `3bdfcaa1` changes the installer runtime's `create_user` integration to
resolve the home inside the installed root and run that payload's `restorecon`
after successful creation of a **new** home. It also labels the new account
database/lock files. Existing home trees are excluded from the added operation;
no forced context, policy exception, recursive whole-system relabel or persistent
relabel service is installed. A build-time contract check rejects upstream source
drift. Native installed-policy assertions and ICC captures must validate this in
fresh VMs before it is called a fix.

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
and its full shared publisher remain under qualification. Initial workstation
pilots use only individually verified/signed native candidate receipts; they do
not advance that publisher's gates. Local validation now passes 80 runtime and
95 image tests, Actionlint and diff checks. The new GNOME health assertion requires
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
guards and isolated mount/availability fixtures pass; another fresh-ISO VM run
is required to establish actual installed labels.

The destination image content remains at product source `3bdfcaa1`; this follow-up
changes only the installer runtime, tests and documentation. Reuse verified native
receipts, rebuild the ISO and keep the failing assertion for the reruns.

### Current complete-flow matrix

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
