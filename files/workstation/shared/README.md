# workstation/shared/

This tree contains DE-agnostic workstation payloads shared by GNOME and COSMIC.

It now focuses on workstation behavior that is truly about the workstation role itself.

## Current ownership

- the shared display-manager reconciliation unit and helper
- shared tmpfiles/relabel snippets for workstation runtime state
- workstation-wide payloads that are not specific to GNOME or COSMIC

Flatpak governance payloads live under `files/flatpak/base/`, which keeps app policy separate from workstation-session behavior.

## Display-manager reconciliation

Workstation images ship:

- `usr/lib/systemd/system/current-workstation-dm-apply.service`
- `usr/libexec/current-workstation-dm-apply`

That helper reads the active family marker from `/usr/share/current/workstation/desktop.env` and repairs stale `display-manager.service` ownership after bootc rebases.

It also queues the selected display manager on the first boot after a rebase, so
the handoff is not delayed until the next reboot while still avoiding a boot-time
ordering deadlock.

Non-selected display-manager units are also disabled, stopped, and cleared from
the failed-unit list so stale `greetd` or `gdm` state does not survive as noise
after a desktop switch.

For COSMIC deployments, the helper also reconciles the `cosmic-greeter` PAM file
with `pam_gnome_keyring.so` when the module is installed, which keeps keyring
unlock support aligned even when `/etc` persists across image switches.
For packages with a vendor stack in `/usr/lib/pam.d`, it refreshes its own
`/etc/pam.d` override from the current vendor file on each boot. It leaves
administrator-managed overrides untouched.

The shared tmpfiles payload also restores the policy-defined writable labels for
TuneD runtime state files under `/etc/tuned` and the TuneD log tree under
`/var/log/tuned`, which avoids SELinux denials when `tuned-ppd` updates the
power-profile state or opens its log on deployments that retained generic
labels.
