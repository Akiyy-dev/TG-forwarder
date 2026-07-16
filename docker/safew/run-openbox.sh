#!/bin/sh
set -eu
until xdpyinfo -display "${DISPLAY:-:1}" >/dev/null 2>&1; do
    sleep 0.2
done
exec openbox-session
