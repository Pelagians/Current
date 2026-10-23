# Current initial setup (experimental)

The unified installer is under qualification. It installs a small Fedora-based
bootstrap through graphical Anaconda; it does not install a full desktop at that
stage. Existing image-specific installers remain available. See the
[build architecture and test limits](../maintainers/unified-installer.md).

Keep this draft ISO on disposable test disks. An earlier x86_64 baseline passed
complete Fedora, AlmaLinux 10 and AlmaLinux 9 server UEFI/KVM flows: root-only
automatic partitioning, authenticated first-boot setup, network-failure retry,
signed switch, enforcing destination boot, explicit completion and rollback.
All six directed server rebase pairs among these distributions now pass the
recorded VM flow, including target reboot and exact-source rollback. Manual
separate-home and encrypted layouts remain unqualified.

The Alma 10 SELinux finalizer correction passed. The XFS profile disables parent
pointers and atomic extent exchange so Alma 9 can mount it and its bundled repair
tool can inspect it. A read-only clean-file repair scan passed; filesystem
corruption recovery remains unqualified. Earlier ISOs enabling these features
remain unsuitable for Alma 9.

The shutdown initramfs lookup correction passed all recorded server reboots,
including an ordinary Alma 9 reboot. Initial device-busy messages can still
appear before the shutdown initramfs unmounts the old root. Alma 9 also rotates
newer Fedora journals and cannot verify their format; all retained archives in
the final rerun passed verification after rollback to Fedora. Structural checks
use closed archives because upstream verification can race active journal writes.
Authenticated user services passed on all three distributions despite nonfatal
bootstrap PAM credential audit messages. Recorded GNOME/COSMIC graphical-login,
switch and rollback cases are listed in the
[recorded baseline VM matrix](../maintainers/workstation-rebase-qualification.md#current-complete-flow-matrix).
The prior ISO (`6d27cf9a`) corrected native-policy labels for newly created
homes/account files; prior workstation images (`3bdfcaa1`) added package-derived
Avahi account provisioning and an Alma 9 Homebrew setup correction. Their fourteen
recorded cross-distro GNOME/COSMIC flows passed native home/ICC type, Avahi account,
real Homebrew execution, graphical-login, reboot and rollback checks.

Current ISO source `480b323e` supplies native mDNS support, orders Avahi after
network startup, and includes minimal English locale data. Destination images
retain that English support across distributions. The older payload lacked the
selected locale, so Anaconda used its C.UTF-8 fallback. This correction supplies
data without forcing LANG/LC_ALL or resetting user preferences. Other languages
and deliberately selected C locales remain separate qualification work.

The current ISO passed strict bootstrap locale/Avahi/authentication/reboot checks.
Five amended server/GNOME flows passed with destination source `dc78334d`.
The final COSMIC image source `782560bf` corrects an older Alma 9 country-data
schema that left its language page empty. Fresh-source Fedora→Alma 10,
Alma 10→Alma 9 and Alma 9→Fedora COSMIC flows passed actual native welcome,
graphical login, reboot, exact rollback and recovery. Missing flag fields derive
from existing native country codes without changing names, identities or user
preferences. The complete native/shared candidate publication passed independent receipt
and reference checks, including the tested COSMIC image digests. COSMIC portal
shutdown panics, an intermittent oversized welcome window and reproduced
software-rendered dock artifacts remain unresolved. See the
[warning/first-run evidence](../maintainers/workstation-rebase-qualification.md#avahi-cosmic-onboarding-and-rendering-follow-up)
for exact receipts and remaining shutdown/rendering warnings. These tests do not
qualify all applications, Brew packages, external LAN discovery or physical GPUs.
Keep testing disposable; prior image results do not qualify a replacement.

If an earlier COSMIC image has an empty language page, use a console login to
inspect the journal and `sudo bootc status`, then recover through the prior
boot-menu deployment if needed. Do not create the native first-run completion
marker or reset your home to bypass the failure.

The added installer relabel hook excludes reused homes. Earlier draft installs
with incorrect labels need administrator review; use a fresh disposable install
for qualification. There is no automatic recursive repair of existing homes.

In Anaconda choose storage, timezone, networking and an administrator account.
The default root filesystem is XFS; Btrfs is excluded because the selected system
may be AlmaLinux. The installer rejects Btrfs assigned to the installation, including
separate home/data mount points. A disposable VM test verified the explicit
rejection with Begin Installation disabled and an entirely unallocated disk.
Unused existing volumes are not installation targets.
Root login is locked. After reboot, log in
on the local console with the account you created. Setup opens after normal
administrator authentication. It never uses root autologin. SSH remains enabled;
setup does not automatically launch in an SSH login.

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
sudo current setup --channel br-codex_unified-installer
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
