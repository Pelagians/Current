#!/usr/bin/env bash
set -eux
HELM_VERSION="v4.2.0"
ARCH="$(uname -m)"
case "$ARCH" in
  x86_64) HELM_ARCH="amd64" ;;
  aarch64) HELM_ARCH="arm64" ;;
  *) echo "unsupported arch: $ARCH" >&2; exit 1 ;;
esac
HELM_TARBALL="helm-${HELM_VERSION}-linux-${HELM_ARCH}.tar.gz"
curl -fsSLO "https://get.helm.sh/${HELM_TARBALL}"
curl -fsSLO "https://get.helm.sh/${HELM_TARBALL}.sha256sum"
sha256sum -c "${HELM_TARBALL}.sha256sum"
tar -xzf "${HELM_TARBALL}"
install -m 0755 "linux-${HELM_ARCH}/helm" /usr/bin/helm
rm -rf "linux-${HELM_ARCH}" "${HELM_TARBALL}" "${HELM_TARBALL}.sha256sum"
helm version
