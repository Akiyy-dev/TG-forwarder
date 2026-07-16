#!/bin/sh
set -eu
until xdpyinfo -display "${DISPLAY:-:1}" >/dev/null 2>&1; do
    sleep 0.2
done
until dbus-send --session --print-reply \
    --dest=org.freedesktop.Notifications \
    /org/freedesktop/Notifications \
    org.freedesktop.Notifications.GetServerInformation >/dev/null 2>&1; do
    sleep 0.2
done
exec /opt/safew/SafeW -workdir /data/safew-profile
