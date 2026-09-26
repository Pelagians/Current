# Apps And Flatpak

Current keeps two Flatpak lanes on workstation images.

## User-managed apps

`flathub` is available in user scope for normal personal app installs.

In interactive shells, `flatpak install APP` and `flatpak update` default to user scope without administrator authorization. `flatpak --user ...` remains explicit and supported. Global verbosity options work; an explicit `--system` or `--installation NAME` selection is preserved. Read-only commands are unchanged. Scripts should always specify scope.

## Admin-managed apps

`org-system` is the image-managed system scope for curated shared apps.

The remote is marked `--no-enumerate` at rest, limiting ordinary app browsing to installed refs. This does not conceal the remote from administrative commands such as `flatpak remotes`. Managed maintenance temporarily permits enumeration so Flatpak can discover newly required runtime branches, then restores the hidden policy.

System changes require an administrator. Use `sudo flatpak --system ...` for deliberate direct operations, or `current update-system` for updates with dependency discovery. GUI system mutations require a wheel member to authenticate through polkit. The interactive shell function is only a convenience, not the security boundary.

This is where the image or an admin can keep a clean shared app set without turning every machine into an anything-goes system-wide app bucket.

## Startup behavior

Workstation sessions import `DISPLAY`, `WAYLAND_DISPLAY`, `XDG_CURRENT_DESKTOP`, `XDG_DATA_DIRS`, and `PATH` into D-Bus activation and `systemd --user` early in the graphical login.

That keeps portal backends and D-Bus activated Flatpak helpers aligned with the real desktop session instead of inheriting a stale or incomplete environment.

## Maintenance helpers

System-scope maintenance never touches user Flatpak installs.

Useful targets:

- `current flatpak-status` shows system remotes, apps, runtimes, and extensions.
- `current flatpak-clean-system` removes unused system-scope Flatpak runtime content.
- `current flatpak-repair-system` runs system-scope Flatpak repair inside the managed remote transaction.
- `current flatpak-portal-status` shows the current user's portal service state.

`current update-system` updates system Flatpaks and safely cleans unused refs. It attempts the independent bootc image upgrade even if Flatpak fails, reports both results, and exits nonzero if either fails.

Cleanup uses Flatpak's own `--unused` handling. Required runtimes, including EOL runtimes, and administrator-created pins are retained. EOL warnings are not themselves update failures. Do not delete a runtime still needed by an application. Flatpak selects runtime and graphics extensions from app/runtime metadata; Current no longer installs or pins a separate extension baseline.

Startup reconciliation and managed maintenance hold the same lock for the whole transaction. Direct `sudo flatpak` and direct BlueBuild script invocations do not participate in that lock; avoid running them concurrently with managed maintenance.


## Why this split exists

The split is there so both of these can be true at once:

- users keep ownership of their own app installs
- admins still get a real, deliberate place for shared curated apps

That is why Current keeps the system-vs-user Flatpak model instead of flattening everything into one scope.
