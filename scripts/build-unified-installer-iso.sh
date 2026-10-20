#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARCH="${CURRENT_INSTALLER_ARCH:-$(uname -m)}"
PAYLOAD="${CURRENT_INSTALLER_PAYLOAD_REF:?Set an immutable signed current-bootstrap reference}"
BUILDER="${CURRENT_IMAGE_BUILDER:-ghcr.io/osbuild/image-builder-cli@sha256:b35d715cd67099355b9e2ee022e1f73333b917d5a1a594f01b6a82c366dc10d1}"
INSTALLER_BASE="${CURRENT_INSTALLER_BASE:-quay.io/fedora/fedora-bootc:44@sha256:e6fffeed9e9a13ca4d351c1ce4ae2b4a5119fe121268479e247a63a3ba2bfda2}"
OUTPUT="${CURRENT_INSTALLER_OUTPUT_DIR:-$REPO_ROOT/output/installer/unified/$ARCH}"
PODMAN="${PODMAN:-podman}"
SUDO="${SUDO-sudo}"
COSIGN="${COSIGN:-cosign}"
run_root() { if [[ -n "$SUDO" ]]; then "$SUDO" env -u XDG_RUNTIME_DIR -u REGISTRY_AUTH_FILE "$@"; else "$@"; fi; }
case "$ARCH" in x86_64) OCI_ARCH=amd64 ;; aarch64) OCI_ARCH=arm64 ;; *) echo 'Unsupported architecture' >&2; exit 1 ;; esac
[[ "$(uname -m)" = "$ARCH" ]] || { echo 'Use a native builder for the requested architecture' >&2; exit 1; }
[[ "$PAYLOAD" =~ ^ghcr\.io/pelagians/current-bootstrap[-a-z0-9_]*@sha256:[a-f0-9]{64}$ ]] || { echo 'Payload must be a pinned Current bootstrap' >&2; exit 1; }
for ref in "$BUILDER" "$INSTALLER_BASE"; do
  [[ "$ref" =~ @sha256:[a-f0-9]{64}$ ]] || { echo 'Builder and runtime base must be pinned' >&2; exit 1; }
done
if [[ -d "$OUTPUT" && -n "$(find "$OUTPUT" -mindepth 1 -print -quit)" ]]; then
  echo 'Use an empty output directory so stale ISOs cannot be uploaded' >&2; exit 1
fi
mkdir -p "$OUTPUT"
OUTPUT="$(cd "$OUTPUT" && pwd)"
# Verify the exact embedded artifact with the repository's existing key.
"$COSIGN" verify --key "$REPO_ROOT/cosign.pub" "$PAYLOAD" > "$OUTPUT/payload-verification.json"
run_root "$PODMAN" pull --arch "$OCI_ARCH" "$PAYLOAD"
run_root "$PODMAN" pull --arch "$OCI_ARCH" "$BUILDER"
run_root "$PODMAN" pull --arch "$OCI_ARCH" "$INSTALLER_BASE"
[[ "$(run_root "$PODMAN" image inspect --format '{{.Architecture}}' "$PAYLOAD")" = "$OCI_ARCH" ]]
[[ "$(run_root "$PODMAN" image inspect --format '{{index .Labels "containers.bootc"}}' "$PAYLOAD")" = 1 ]]
# containers-storage may reserialize layers during ISO embedding. A digest
# destination forbids that; bind a local tag to the already verified image ID.
PAYLOAD_LOCAL="localhost/current-bootstrap-payload:sha256-${PAYLOAD##*@sha256:}"
run_root "$PODMAN" tag "$PAYLOAD" "$PAYLOAD_LOCAL"
[[ "$(run_root "$PODMAN" image inspect --format '{{.Id}}' "$PAYLOAD")" = \
   "$(run_root "$PODMAN" image inspect --format '{{.Id}}' "$PAYLOAD_LOCAL")" ]]
INSTALLER="localhost/current-unified-installer:$ARCH"
run_root "$PODMAN" build --build-arg "CURRENT_PAYLOAD_REF=$PAYLOAD" \
  --build-arg "CURRENT_PAYLOAD_SOURCE=$PAYLOAD_LOCAL" \
  --build-arg "CURRENT_INSTALLER_BASE=$INSTALLER_BASE" \
  -f "$REPO_ROOT/installer/unified/Containerfile" -t "$INSTALLER" "$REPO_ROOT"
# Record all inputs before image-builder; failed builds retain their receipt.
{
  printf 'architecture=%s\npayload=%s\nbuilder=%s\ninstaller_base=%s\n' "$ARCH" "$PAYLOAD" "$BUILDER" "$INSTALLER_BASE"
  printf 'embedded_source=%s\n' "$PAYLOAD_LOCAL"
  printf 'revision=%s\n' "$(git -C "$REPO_ROOT" rev-parse HEAD)"
  run_root "$PODMAN" image inspect --format '{{.Id}}' "$INSTALLER"
} > "$OUTPUT/build-inputs.txt"
run_root "$PODMAN" run --rm --privileged --security-opt label=type:unconfined_t \
  -v "$OUTPUT:/output" -v /var/lib/containers/storage:/var/lib/containers/storage \
  "$BUILDER" build --bootc-ref "$INSTALLER" --bootc-installer-payload-ref "$PAYLOAD_LOCAL" \
  --bootc-default-fs xfs --seed 42 --output-dir /output --with-buildlog bootc-generic-iso
mapfile -t isos < <(find "$OUTPUT" -type f -name '*.iso')
[[ "${#isos[@]}" = 1 ]] || { echo 'Expected exactly one ISO' >&2; exit 1; }
final="$OUTPUT/current-installer-$ARCH.iso"
if [[ "${isos[0]}" != "$final" ]]; then run_root mv -- "${isos[0]}" "$final"; fi
run_root chown -R "$(id -u):$(id -g)" "$OUTPUT"
(cd "$OUTPUT" && sha256sum "current-installer-$ARCH.iso") > "$final.sha256"
printf 'Experimental installer: %s\n' "$final"
