# Installer ISO

The experimental [unified installer](setup.md) instead installs a minimal bootstrap
and selects the final image after first boot. Its [native build instructions and
qualification gates](../maintainers/unified-installer.md) are separate from the
existing Alma workflow below.

The Current Alma 10 installer installs a published bootc payload through Anaconda.

## What this builds

The installer flow uses two images:

```text
installer environment = local image built from installer/alma10-server/Containerfile
installed payload     = ghcr.io/pelagians/alma10-server:latest by default
root filesystem       = xfs by default
installer config      = installer/alma10-server/iso.toml
```

The installer environment includes Anaconda and related installer dependencies. The installed system payload is passed separately to `bootc-image-builder` with `--installer-payload-ref`.

This installer targets x86_64. Its build restores Alma's signed shim and
MokManager from `/usr/lib/bootupd/updates/EFI/almalinux` when they are absent
from `/boot/efi/EFI/almalinux`. It checks those binaries, the separately packaged
CD-boot GRUB binary, and the GRUB font before invoking osbuild. This preparation
only affects the installer environment.

The config uses the builder's default ISO volume metadata: the current
`bootc-installer` builder rejects `[customizations.iso]`. The interactive
Kickstart and Anaconda module settings remain in the canonical config.

## Build from the repository config

From the repository root:

```bash
bash ./scripts/build-alma10-installer-iso.sh
```

The script uses this file by default:

```text
installer/alma10-server/iso.toml
```

The default output directory is:

```text
output/installer/alma10-server/
```

The builder currently writes `bootiso/install.iso` and `bootiso/install.iso.sha256`
under that directory. CI uploads both files, including nested output directories.
After downloading, run `sha256sum -c install.iso.sha256` from the directory
containing the ISO.

## Override the installer config

To test a modified TOML file without changing the repo copy:

```bash
cp installer/alma10-server/iso.toml /tmp/current-iso.toml
$EDITOR /tmp/current-iso.toml

CURRENT_INSTALLER_CONFIG=/tmp/current-iso.toml \
  bash ./scripts/build-alma10-installer-iso.sh
```

## Override the payload image

To install a different tag or digest:

```bash
CURRENT_INSTALLER_PAYLOAD_REF=ghcr.io/pelagians/alma10-server:latest \
  bash ./scripts/build-alma10-installer-iso.sh
```

For release media, prefer a digest instead of a mutable tag.

## Override the filesystem

The default root filesystem is XFS:

```bash
CURRENT_INSTALLER_ROOTFS=xfs \
  bash ./scripts/build-alma10-installer-iso.sh
```

XFS is the recommended default for the Alma lanes. Avoid Btrfs if the installed system is expected to move between Alma and Fedora image lanes.

## Direct builder equivalent

The build script wraps this shape:

```bash
sudo podman run \
  --rm \
  --privileged \
  --pull=newer \
  --security-opt label=type:unconfined_t \
  -v "$PWD/installer/alma10-server/iso.toml:/config.toml:ro" \
  -v "$PWD/output/installer/alma10-server:/output" \
  -v /var/lib/containers/storage:/var/lib/containers/storage \
  quay.io/centos-bootc/bootc-image-builder:latest \
  build \
  --type bootc-installer \
  --rootfs xfs \
  --installer-payload-ref ghcr.io/pelagians/alma10-server:latest \
  --output /output \
  localhost/current-alma10-server-installer:dev
```

Use the script unless you are debugging the builder invocation itself.

## Notes

- Do not add generated ISO files to git.
- Keep `iso.toml` interactive by default. It should let the user walk through Anaconda.
- Do not add `firewall --enabled` to the Kickstart unless `firewalld` is present in the installed payload image.
- Keep storage decisions visible in Anaconda unless a separate automated installer profile is introduced.

## Environment variables

The build script uses `CURRENT_INSTALLER_*` variables for payload, output, config, and root filesystem overrides.
