#!/usr/bin/env bash
# Build and flash the pico-uart-bridge firmware (Linux/macOS).
#
# Usage:
#   ./deploy.sh                 # build + flash
#   ./deploy.sh --build-only    # build, do not flash
#   ./deploy.sh --board pico_w
#   ./deploy.sh --clean

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="$SCRIPT_DIR/external/pico-uart-bridge"

BOARD="${PICO_BOARD:-pico}"
CLEAN=0
BUILD_ONLY=0

while [[ $# -gt 0 ]]; do
	case "$1" in
		--board) BOARD="$2"; shift 2 ;;
		--clean) CLEAN=1; shift ;;
		--build-only) BUILD_ONLY=1; shift ;;
		-h|--help) sed -n '2,9p' "$0"; exit 0 ;;
		*) echo "unknown option: $1" >&2; exit 2 ;;
	esac
done

BUILD_DIR="$SRC_DIR/build/$BOARD"

need() {
	command -v "$1" >/dev/null 2>&1 || {
		echo "error: '$1' not found. Install with:" >&2
		echo "  sudo apt install cmake ninja-build gcc-arm-none-eabi \\" >&2
		echo "       libnewlib-arm-none-eabi libstdc++-arm-none-eabi-newlib build-essential git" >&2
		exit 1
	}
}
need cmake
need ninja
need arm-none-eabi-gcc
need git

if [[ ! -e "$SRC_DIR/pico-sdk/.git" ]]; then
	echo "==> Initializing vendored pico-sdk submodule (this takes a while)"
	git -C "$SRC_DIR" submodule update --init --recursive
fi

if [[ $CLEAN -eq 1 ]]; then
	rm -rf "$BUILD_DIR"
fi

echo "==> Configuring ($BOARD)"
cmake -G Ninja -B "$BUILD_DIR" -S "$SRC_DIR" \
	-DPICO_BOARD="$BOARD" -DCMAKE_BUILD_TYPE=Release

echo "==> Building"
cmake --build "$BUILD_DIR"

UF2="$BUILD_DIR/uart_bridge.uf2"
echo "==> Firmware: $UF2"

if [[ $BUILD_ONLY -eq 1 ]]; then
	exit 0
fi

# Prefer picotool: it can reboot a running board into BOOTSEL automatically.
if command -v picotool >/dev/null 2>&1; then
	echo "==> Flashing with picotool"
	if picotool load -x "$UF2" -f; then
		echo "==> Done. The board should re-enumerate as /dev/ttyACM0 and /dev/ttyACM1."
		exit 0
	fi
	echo "picotool failed; falling back to mass-storage copy" >&2
fi

# Fallback: copy to the RPI-RP2 mass-storage device.
echo "==> Waiting for a Pico in BOOTSEL mode (hold BOOTSEL and replug)..."
MOUNT=""
for _ in $(seq 1 60); do
	MOUNT="$(lsblk -o LABEL,MOUNTPOINT -nr 2>/dev/null \
		| awk '$1 == "RPI-RP2" && $2 != "" { print $2; exit }')"
	[[ -n "$MOUNT" ]] && break
	sleep 1
done

if [[ -z "$MOUNT" ]]; then
	echo "error: no mounted RPI-RP2 volume found." >&2
	echo "Mount it manually and copy: cp '$UF2' /path/to/RPI-RP2/" >&2
	exit 1
fi

echo "==> Copying to $MOUNT"
cp "$UF2" "$MOUNT/"
sync
echo "==> Done. The board should re-enumerate as /dev/ttyACM0 and /dev/ttyACM1."
