# Current initial setup (experimental)

The unified installer is under qualification. It installs a small Fedora-based
bootstrap through graphical Anaconda; it does not install a full desktop at that
stage. Existing image-specific installers remain available. See the
[build architecture and test limits](../maintainers/unified-installer.md).

Keep this draft ISO on disposable test disks. Earlier builds exposed missing home
directories with separate `/home` volumes and disabled SELinux after installation.
The source now defaults to root-only automatic partitioning and an enabled,
permissive installer runtime with an enforcing installed system. Those settings
passed a complete Fedora server UEFI VM installation, first-boot setup, signed
switch, destination boot with enforcing SELinux, and rollback. Manual separate-home layouts remain unqualified.

The corrected XFS profile and bootstrap finalizer PATH allowed both AlmaLinux 9
and 10 servers to boot with enforcing SELinux and retained networking in UEFI
VMs. Those runs then exposed a `sudo current` command-lookup failure during setup
completion. The shared command-path fix is rebuilding; full completion and
rollback remain under qualification. Earlier ISOs with XFS parent pointers remain
unsuitable for Alma 9. Use only disposable test disks and consult the linked
maintainer evidence for exact artifact revisions.

In Anaconda choose storage, timezone, networking and an administrator account.
The default root filesystem is XFS; Btrfs is excluded because the selected system
may be AlmaLinux. The installer rejects Btrfs assigned to the installation, including
separate home/data mount points. A disposable VM test verified the explicit
rejection with Begin Installation disabled and an entirely unallocated disk.
Unused existing volumes are not installation targets.
Root login is locked. After reboot, log in
on the local console with the account you created. Setup opens after normal
administrator authentication. It never uses root autologin. SSH remains usable.

Start or resume manually:

```bash
sudo current setup
```

Choose AlmaLinux 10, Fedora, AlmaLinux 9 or automatic recommendation; then server
or workstation; then GNOME or COSMIC for a workstation. Menus accept numbers and
Enter, without requiring a mouse or terminal graphics. `q`, Ctrl-D or Ctrl-C
returns to your shell. Use `nmtui` to configure networking if needed.

The review shows hardware, distribution, role, desktop, driver, exact image tag,
compatibility reasons and warnings. You can select another eligible image. Known
architecture, CPU and driver incompatibilities cannot be overridden. Unknown graphics hardware gets an
explicit manual fallback; NVIDIA driver choices are based on recorded PCI IDs,
not just its vendor. Apple Silicon/Asahi is unsupported.

Nothing is staged until you confirm. Setup checks registry metadata, resolves the
native immutable digest and requires Current's image-signing policy. Failed
networking or staging offers retry with your existing selection. It preserves
your current bootc deployment and does not reboot automatically.

When staging succeeds, reboot when ready:

```bash
sudo systemctl reboot
```

After the destination boots, verify networking and your intended login/desktop,
then run `sudo current setup` to accept completion. A successful switch command
alone does not complete setup. Completed setup will not repeat the questionnaire.

During PR qualification, use images containing the new reconciler:

```bash
sudo current setup --channel pr-29
```

This requires successful candidate builds and publication. Pre-feature `latest`
images are rejected. All transitions currently remain experimental, including
Fedora-to-Alma rebases and generic ARM64 UEFI. Successful builds do not establish
boot or GPU compatibility. Keep installation tests on disposable disks/VMs.

Preview selection without writing state or contacting a registry:

```bash
current setup --dry-run
current setup plan --distribution auto --role workstation --desktop gnome
```

The second command prints JSON for frontends and diagnostic tools. Developers can
run a synthetic fixture from the repository without installing anything:

```bash
PYTHONPATH=files/setup/usr/lib python3 -m current_setup.cli plan \
  --fixture scripts/tests/fixtures/setup/intel-uefi.json \
  --matrix files/base/runtime/usr/share/current/image-matrix.tsv \
  --compatibility files/setup/usr/share/current/setup-compatibility.json
```

If something fails, inspect `sudo current setup status` and `sudo bootc status`.
Use the previous boot-menu deployment if the destination cannot boot; from a
working destination `sudo bootc rollback` stages the prior deployment, followed
by an explicit reboot. Keep `/var/lib/current/setup/state.json` and the journal
for diagnosis. See the [recovery procedure](../maintainers/unified-installer.md#trust-state-and-recovery).

Setup leaves the destination pinned to a digest. Normal automatic image updates
will not follow a moving tag until you deliberately select one with the ordinary
`current rebase` flow after qualification.
