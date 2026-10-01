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

Booted results: **pending**. No disposable bootc workstation was available during
implementation. The native Fedora ARM COSMIC full build passed its greeter
contract checks. A disposable container from that image also repaired all three
contaminations together, passed idempotence and verified the installed unit graph
without an ordering cycle. Its Wayland session directory contains only
`cosmic.desktop`. See [ARM build results](arm-image-lanes.md).

The remaining image builds and visual greeter/login/session checks must be
attached before claiming the requested rebase convergence is qualified.
