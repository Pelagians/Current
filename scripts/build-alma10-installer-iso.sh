#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

PAYLOAD_REF="${CURRENT_INSTALLER_PAYLOAD_REF:-ghcr.io/pelagians/alma10-server:latest}"
INSTALLER_IMAGE="${CURRENT_INSTALLER_IMAGE:-localhost/current-alma10-server-installer:dev}"
BUILDER_IMAGE="${BOOTC_IMAGE_BUILDER:-quay.io/centos-bootc/bootc-image-builder:latest}"
ROOTFS="${CURRENT_INSTALLER_ROOTFS:-xfs}"
OUTPUT_DIR="${CURRENT_INSTALLER_OUTPUT_DIR:-$REPO_ROOT/output/installer/alma10-server}"
CONFIG="${CURRENT_INSTALLER_CONFIG:-$REPO_ROOT/installer/alma10-server/iso.toml}"
CONTAINERFILE="${CURRENT_INSTALLER_CONTAINERFILE:-$REPO_ROOT/installer/alma10-server/Containerfile}"
PODMAN="${PODMAN:-podman}"
SUDO="${SUDO:-sudo}"
OUTPUT_OWNER="${CURRENT_INSTALLER_OUTPUT_OWNER:-$(id -u):$(id -g)}"

run_sudo() {
  if [[ -n "$SUDO" ]]; then
    $SUDO "$@"
  else
    "$@"
  fi
}

if [[ ! -f "$CONFIG" ]]; then
  echo "Missing installer config: $CONFIG" >&2
  exit 1
fi

if [[ ! -f "$CONTAINERFILE" ]]; then
  echo "Missing installer Containerfile: $CONTAINERFILE" >&2
  exit 1
fi

mkdir -p "$OUTPUT_DIR"
OUTPUT_DIR="$(cd "$OUTPUT_DIR" && pwd)"

cat <<EOF
== Current Alma 10 installer ISO build ==
Payload ref:     $PAYLOAD_REF
Installer image: $INSTALLER_IMAGE
Builder image:   $BUILDER_IMAGE
Rootfs:          $ROOTFS
Config:          $CONFIG
Output:          $OUTPUT_DIR
Output owner:    $OUTPUT_OWNER
EOF

run_sudo "$PODMAN" pull "$PAYLOAD_REF"

run_sudo "$PODMAN" build \
  --build-arg "CURRENT_PAYLOAD_REF=$PAYLOAD_REF" \
  -f "$CONTAINERFILE" \
  -t "$INSTALLER_IMAGE" \
  "$REPO_ROOT"

run_sudo "$PODMAN" pull "$BUILDER_IMAGE"

run_sudo "$PODMAN" run \
  --rm \
  --privileged \
  --pull=newer \
  --security-opt label=type:unconfined_t \
  -v "$CONFIG:/config.toml:ro" \
  -v "$OUTPUT_DIR:/output" \
  -v /var/lib/containers/storage:/var/lib/containers/storage \
  "$BUILDER_IMAGE" \
  build \
  --type bootc-installer \
  --rootfs "$ROOTFS" \
  --installer-payload-ref "$PAYLOAD_REF" \
  --chown "$OUTPUT_OWNER" \
  --output /output \
  "$INSTALLER_IMAGE"

run_sudo chown -R "$OUTPUT_OWNER" "$OUTPUT_DIR" 2>/dev/null || true

ISO_PATH="$(find "$OUTPUT_DIR" -type f -iname '*.iso' | head -n1 || true)"

if [[ -z "$ISO_PATH" ]]; then
  echo "No ISO produced under $OUTPUT_DIR" >&2
  find "$OUTPUT_DIR" -maxdepth 4 -type f -print >&2 || true
  exit 1
fi

# Keep the checksum usable after downloading the artifact to another machine.
(cd "$(dirname "$ISO_PATH")" && sha256sum "$(basename "$ISO_PATH")") > "$ISO_PATH.sha256"

cat <<EOF
== installer ISO complete ==
ISO:    $ISO_PATH
SHA256: $ISO_PATH.sha256
EOF
