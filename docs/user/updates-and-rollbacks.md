# Updates And Rollbacks

Current keeps updates explicit.

## Updates

Use the Current project wrapper to update managed system Flatpaks, remove unused system Flatpak refs, and stage an OS image update:

```bash
current update-system
```

If you only want to stage the OS image update, use plain `bootc`:

```bash
sudo bootc upgrade
```

To remove unused system Flatpak refs, including stale pinned runtimes that are no longer needed by installed system apps:

```bash
current clean-system
```

`current clean-system` clears system runtime pins first, then lets Flatpak remove only refs it considers unused.

Current disables the stock `bootc-fetch-apply-updates` timer and service. Updates are downloaded and applied when you choose, then activated on reboot.

## Rebase

To switch roles, environments, distro lanes, or driver lanes:

```bash
current rebase
```

Workstation images re-apply the expected display manager on boot after a switch so GNOME and COSMIC rebases do not leave stale `display-manager.service` state behind.

## Rollback

If a new deployment is not what you want, use normal `bootc` rollback flow:

```bash
sudo bootc rollback
```

Then reboot into the previous deployment.

## User-space updates

`current update-user` refreshes user Flatpaks, Homebrew when present on workstation images, and Distrobox containers.

## Workstation desktop ownership

The destination workstation image selects its native graphical login manager:
GDM for GNOME, COSMIC greeter for COSMIC. Current repairs stale managed masks,
aliases and enablement before graphical login starts. It preserves user homes,
dconf, AccountsService and COSMIC desktop preferences. A failure is recorded in
`journalctl -b -u current-workstation-dm-apply.service`; native greeter startup
failures are recorded in that manager's own journal.

Administrators who manage login-manager selection themselves can opt out:

```bash
sudo mkdir -p /etc/current
sudo touch /etc/current/workstation-dm-unmanaged
sudo systemctl daemon-reload
```

After opting out, configure your own manager and default target. Current stops
repairing their selection. Remove the marker and reboot to restore Current's
ownership. Ordinary workstation rebases do not require this opt-out or manual
`systemctl` repair commands. Booted convergence qualification is tracked in the
[maintainer procedure](../maintainers/workstation-rebase-qualification.md).
