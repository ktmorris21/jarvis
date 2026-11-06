#!/usr/bin/env bash
# Run as shadowfax on the Raspberry Pi. No modification of system libcamera.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE="${JARVIS_LIBCAMERA_SOURCE:-/home/shadowfax/src/libcamera-0.3}"
if [[ ! -d "$SOURCE/build" ]]; then
  echo "Missing verified isolated libcamera build: $SOURCE/build" >&2
  exit 1
fi
command -v c++ >/dev/null
command -v pkg-config >/dev/null
command -v meson >/dev/null
# Use the very same meson development environment as the working
# capture_libcamera.py implementation. Verify pkg-config resolves the
# expected isolated libcamera, not the incompatible Ubuntu system copy.
meson devenv -C "$SOURCE/build" /bin/bash -c '
set -euo pipefail
version="$(pkg-config --modversion libcamera)"
echo "Resolved libcamera version: $version"
case "$version" in
  0.3.*) ;;
  *) echo "Refusing to link against non-0.3 libcamera: $version" >&2; exit 1;;
esac
pkg-config --variable=libdir libcamera
c++ -std=c++17 -O2 -pthread "$1" -o "$2" \
  $(pkg-config --cflags --libs libcamera)
' bash "$ROOT/clients/voice/camera_native.cpp" "$ROOT/clients/voice/camera_native"
chmod 0755 "$ROOT/clients/voice/camera_native"
echo "Built: $ROOT/clients/voice/camera_native"
