FROM python:3.12-slim-bookworm
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DISPLAY=:1
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates dbus-x11 fonts-noto-cjk libasound2 libdbus-1-3 libegl1 \
        libfontconfig1 libfreetype6 libgl1 libglib2.0-0 libgtk-3-0 libnotify4 \
        libnss3 libopengl0 libpulse0 libsecret-1-0 libx11-6 libxcb-cursor0 \
        libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0 \
        libxcb-render-util0 libxcb-shape0 libxcb-xfixes0 libxcb-xinerama0 \
        libxcb-xkb1 libxcb1 libxcomposite1 libxcursor1 libxdamage1 libxext6 \
        libxfixes3 libxi6 libxkbcommon-x11-0 libxrandr2 libxrender1 libxtst6 \
        novnc openbox procps supervisor tini websockify x11-utils x11vnc xvfb xz-utils \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml README.md ./
COPY app/ app/
RUN pip install --no-cache-dir .
COPY image/tsetup.3.6.2.tar.xz /tmp/safew.tar.xz
RUN mkdir -p /opt/safew \
    && tar -xJf /tmp/safew.tar.xz -C /opt/safew --strip-components=1 \
    && rm /tmp/safew.tar.xz \
    && chmod 0755 /opt/safew/SafeW /opt/safew/Updater \
    && addgroup --system --gid 1000 forwarder \
    && adduser --system --uid 1000 --ingroup forwarder --home /data/safew-home forwarder \
    && mkdir -p /data/safew-home /data/safew-profile /data/novnc /var/log/supervisor \
    && chown -R forwarder:forwarder /app /opt/safew /data /var/log/supervisor
COPY docker/safew/ /opt/container/
RUN chmod 0755 /opt/container/*.sh
USER forwarder
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/bin/dbus-run-session", "--"]
CMD ["/usr/bin/supervisord", "-c", "/opt/container/supervisord.conf"]
