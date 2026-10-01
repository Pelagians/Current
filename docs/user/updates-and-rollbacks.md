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

To remove unused, unpinned system Flatpak refs:

```bash
current clean-system
```

`current clean-system` is an alias for `current flatpak-clean-system`. Cleanup preserves administrator pins and runtimes still required by apps, even when EOL. It never clears runtime pins automatically.

`current update-system` runs system Flatpak maintenance and `bootc upgrade` independently. It prints each result and exits nonzero if either fails. A successful bootc command can mean the image was already current; reboot activates an update only if one was staged.

`current update-all` attempts system, user, Podman, and firmware categories even if an earlier category fails. Its final summary retains each category's failure and returns nonzero if any failed.

Current disables the stock `bootc-fetch-apply-updates` timer and service. Updates are downloaded and applied when you choose, then activated on reboot.

## Rebase

To switch roles, environments, distro lanes, or driver lanes:

```bash
current rebase
```

The picker detects your running machine's CPU architecture and displays only
matching images: x86_64 on x64, or aarch64 on ARM64. It prints the detected
architecture and uses the shared image name on both CPUs. The OCI index selects
the native build. Unsupported architectures, mismatched image names and a matrix with no
matching entries stop before `bootc switch` is called.

This requires the updated picker and image matrix. Once released, use
`sudo bootc upgrade` and reboot to install the updated picker on an older image.
CPU architecture cannot be changed by rebasing.

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
