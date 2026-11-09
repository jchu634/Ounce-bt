#!/usr/bin/env bash
# Run the desktop as the current user with the two Linux HCI capabilities.
set -euo pipefail
if [[ $# -eq 0 || $EUID -eq 0 ]]; then
    echo "Usage (as your desktop user): $0 /absolute/path/to/Ounce-bt.AppImage [arguments...]" >&2
    exit 1
fi
appimage_environment=()
if [[ -v APPIMAGE_EXTRACT_AND_RUN ]]; then
    appimage_environment+=("APPIMAGE_EXTRACT_AND_RUN=$APPIMAGE_EXTRACT_AND_RUN")
fi
exec sudo setpriv --reuid="$(id -u)" --regid="$(id -g)" --init-groups \
    --inh-caps=+net_raw,+net_admin --ambient-caps=+net_raw,+net_admin \
    env HOME="$HOME" USER="$(id -un)" LOGNAME="$(id -un)" PATH="$PATH" \
    DISPLAY="${DISPLAY:-}" WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-}" \
    XAUTHORITY="${XAUTHORITY:-}" XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-}" \
    DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-}" \
    XDG_CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}" \
    XDG_DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}" \
    XDG_STATE_HOME="${XDG_STATE_HOME:-$HOME/.local/state}" \
    "${appimage_environment[@]}" "$@"
