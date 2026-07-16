#!/bin/sh
set -eu
if [ -z "${NOVNC_PASSWORD:-}" ]; then
    echo "NOVNC_PASSWORD is required" >&2
    exit 1
fi
until xdpyinfo -display "${DISPLAY:-:1}" >/dev/null 2>&1; do
    sleep 0.2
done
x11vnc -storepasswd "$NOVNC_PASSWORD" /data/novnc/passwd >/dev/null
exec x11vnc \
    -display "${DISPLAY:-:1}" \
    -rfbauth /data/novnc/passwd \
    -rfbport 5900 \
    -localhost \
    -forever \
    -shared \
    -noxdamage
