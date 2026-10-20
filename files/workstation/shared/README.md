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

The generator selects the destination manager before systemd loads the boot
transaction. Its generated dependencies gate login on successful reconciliation
and exclude competing managers. The helper does not queue start/stop jobs or
reload units halfway through the repair. See
[workstation layering](../../../docs/maintainers/workstation-layering.md) for
ownership and the administrator opt-out.

The shared tmpfiles payload also restores the policy-defined writable labels for
TuneD runtime state files under `/etc/tuned` and the TuneD log tree under
`/var/log/tuned`, which avoids SELinux denials when `tuned-ppd` updates the
power-profile state or opens its log on deployments that retained generic
labels.
