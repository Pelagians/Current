#!/usr/bin/env bash
set -euxo pipefail
version='v1.36.1+k3s1'
arch="$(uname -m)"
case "$arch" in
  x86_64|amd64) k3s_asset='k3s'; checksum_asset='sha256sum-amd64.txt' ;;
  aarch64|arm64) k3s_asset='k3s-arm64'; checksum_asset='sha256sum-arm64.txt' ;;
  *) echo "Unsupported k3s build architecture: ${arch}" >&2; exit 1 ;;
esac
base_url="https://github.com/k3s-io/k3s/releases/download/${version}"
curl -fsSL "${base_url}/${k3s_asset}" -o "/tmp/${k3s_asset}"
curl -fsSL "${base_url}/${checksum_asset}" -o "/tmp/${checksum_asset}"
grep "  ${k3s_asset}$" "/tmp/${checksum_asset}" > "/tmp/${k3s_asset}.sha256"
(cd /tmp && sha256sum -c "${k3s_asset}.sha256")
install -m 0755 "/tmp/${k3s_asset}" /usr/local/bin/k3s
rm -f "/tmp/${k3s_asset}" "/tmp/${checksum_asset}" "/tmp/${k3s_asset}.sha256"
