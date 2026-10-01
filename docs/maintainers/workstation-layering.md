# Workstation Layering

Workstation is the operator desktop and laptop role. GNOME and COSMIC are implementations of that role.

## Layer order

All workstation recipes build in this order:

1. distro core stack
2. `layers/shared/flatpak-base.yml`
3. `layers/shared/workstation-common.yml`
4. distro workstation drift
5. environment layer
6. optional workstation NVIDIA layer when applicable

Alma 10 and Fedora add one more shared layer in the middle:

- `layers/shared/workstation-modern.yml` after `workstation-common`
- `layers/shared/workstation-gnome-modern.yml` for GNOME images after `workstation-gnome.yml`

## Flatpak layering

Flatpak ownership is split from session ownership:

- `flatpak-base` owns Flatpak packages, user `flathub`, hidden admin-managed `org-system`, shared managed apps, policy payloads, cleanup/repair helper inclusion, and the graphical session environment import hook.
- `flatpak-gnome` owns GNOME portal backend packages, explicit GNOME portal selection, and GNOME-specific system Flatpaks.
- `flatpak-gnome-legacy` owns only the Alma 9 GNOME Flatpak app delta for apps that are native RPMs on modern GNOME lanes.
- `flatpak-cosmic` owns COSMIC portal backend packages, explicit COSMIC portal selection, and COSMIC Flatpak remotes.

Server images do not consume these layers and should not receive desktop portal backends or session Flatpak hooks.

The system Flatpak policy is intentionally opinionated. It keeps managed shared apps separate from user-owned `flathub` installs so multi-user machines do not drift into sharing the wrong application state.

## Workstation common orchestration

`workstation-common.yml` should stay small. It is an orchestrator, not a dumping ground.

It includes:

- `workstation-substrate.yml`: shared desktop, hardware, input, audio, printing, scanning, camera, language, and base workstation package substrate
- `workstation-media.yml`: shared distro-native VAAPI/media runtime packages; distro/vendor-specific diagnostics and backends stay in distro or driver layers
- `workstation-admin-tools.yml`: workstation-only diagnostics, storage, network, and admin utilities
- `workstation-policy.yml`: graphical target, display-manager reconciliation, and workstation sleep policy
- `workstation-user-tools.yml`: opinionated user-facing workstation tooling such as Homebrew and Brave Origin

This prevents GNOME and COSMIC from duplicating the same substrate while keeping workstation product opinions visible and reviewable.

## Brave Origin

Brave Origin is intentionally shipped in workstation images from the RPM repository because it is not available through Flathub.

That is a product opinion, not an accidental dependency. Keep it in `workstation-user-tools.yml` so the opinion stays explicit. The same layer owns the bootc `/opt` compatibility tmpfiles rule that recreates `/var/opt/brave.com -> /usr/lib/opt/brave.com` on boot, because Brave still expects its vendor payload at `/opt/brave.com` while bootc deployments expose package-owned `/opt` content through `/usr/lib/opt`.

## GNOME layering

GNOME workstation is:

- `flatpak-base`
- `workstation-common`
- optional `workstation-modern`
- distro workstation drift
- `workstation-gnome`, which includes `flatpak-gnome`
- optional `workstation-gnome-modern`
- distro-specific GNOME drift where needed

Alma 9 keeps its extra GNOME delta in `recipes/layers/alma9/gnome.yml`; its modern app Flatpaks are isolated in `recipes/layers/shared/flatpak-gnome-legacy.yml`.

Alma 10 keeps only shell-version-specific dconf drift in `recipes/layers/alma10/gnome.yml`.

Fedora no longer needs a dedicated GNOME layer because the shared GNOME layers already cover its supported delta.

## COSMIC layering

COSMIC workstation is:

- `flatpak-base`
- `workstation-common`
- optional `workstation-modern`
- distro workstation drift
- distro COSMIC source layer (`alma/cosmic.yml` or `fedora/cosmic.yml`)
- `workstation-cosmic`, which includes `flatpak-cosmic`

COSMIC-specific behavior such as greeter wiring, session bits, common packages, validation, and COSMIC markers stays under `recipes/layers/shared/workstation-cosmic.yml` and `files/cosmic/**`. Alma-specific COPR source setup and selected COPR applets stay in `recipes/layers/alma/cosmic.yml`; Fedora keeps only native COSMIC config drift in `recipes/layers/fedora/cosmic.yml`.

## NVIDIA workstation extras

`recipes/layers/shared/nvidia-workstation.yml` remains the shared workstation-display NVIDIA add-on for both environments.

Alma 9 also adds `libva-utils` in `recipes/layers/alma9/workstation.yml` because EPEL 9 provides `vainfo` there while current EPEL 10 metadata does not. Keep the shared `workstation-media.yml` layer limited to media runtime packages available across supported workstation lanes.

Alma 9 NVIDIA workstations add `recipes/layers/alma9/nvidia-workstation.yml` for the EPEL `libva-nvidia-driver` VAAPI backend. That layer is deliberately not included by the Alma 9 NVIDIA server recipe.

That keeps display/session and browser/media NVIDIA extras separate from the core lane plumbing in the shared NVIDIA layers.

## Display-manager ownership across rebases

`/usr/share/current/workstation/desktop.env` remains the destination image's
family marker. The shared helper validates the marker, packaged unit, greeter
configuration and session entry before modifying persistent selection.

A small systemd generator delegates to that helper before units are loaded. Its
`generator.early` output selects the native destination unit and graphical
default target, overriding stale managed aliases/masks in `/etc`, and masks only
the two competing managed units. The selected manager requires and follows the
oneshot reconciliation service. That service repairs persistent enablement and
verifies the alias resolves to the expected vendor unit. It stays active after
success, so another dependency cannot rerun reconciliation during the same boot.
There are no asynchronous service start/stop calls or mid-reconciliation reloads.
The ordinary graphical target starts the selected manager after successful repair.

GNOME uses `gdm.service`; COSMIC uses `cosmic-greeter.service` with
`/etc/greetd/cosmic-greeter.toml` on Fedora, Alma 9 and Alma 10. Generic
`greetd.service` is never the fallback. Native COSMIC PAM under `/usr/lib/pam.d`
is accepted, with administrator `/etc/pam.d` precedence and no PAM rewrites.
The helper retires an old override only when its first line is Current's exact
ownership marker and the native vendor stack exists. This lets vendor PAM
updates take effect without deleting administrator overrides or symlinks.

The policy owns the three managed units' masks/enablement, display-manager alias
and graphical default. It does not remove arbitrary services or write user
session preferences. Regular administrator unit replacements and aliases to
unrelated managers are rejected with an opt-out diagnostic. Drop-ins and other
configuration remain administrator-owned; changing native commands or desktop
ownership requires the explicit opt-out below.

Create `/etc/current/workstation-dm-unmanaged` to take ownership of login-manager
selection. Both generator and helper then leave state untouched. Run
`systemctl daemon-reload` after creating/removing that marker, outside an active
reconciliation, and configure/start the desired manager yourself. Opting back in
requires a reboot for the normal first-boot policy. This is a single ownership
opt-out, not a desktop configuration framework.

See [rebase qualification](workstation-rebase-qualification.md) for package
evidence, session persistence analysis, contamination tests and pending release gates.

## ARM candidates

The same workstation reconciliation and desktop layers apply to ARM64. CPU
architecture is selected before role in CI, while the destination desktop marker
retains its existing contract. Intel microcode/thermald are installed only for
x86_64, and shared ROCm source/install layers execute only on x64. See
[ARM image candidates](arm-image-lanes.md) for the initial lane set and pending
build/boot qualification.
