FROM node:22-bookworm-slim AS frontend
WORKDIR /build/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN addgroup --system --gid 1000 forwarder \
    && adduser --system --uid 1000 --ingroup forwarder --home /home/forwarder forwarder
COPY pyproject.toml README.md alembic.ini ./
COPY app/ app/
COPY migrations/ migrations/
COPY scripts/ scripts/
COPY config/ config/
RUN pip install --upgrade pip && pip install .
COPY --from=frontend /build/web/dist web/dist
RUN mkdir -p /data/downloads /data/sessions /data/history \
    && chown -R forwarder:forwarder /app /data
USER forwarder
CMD ["python", "-m", "app.entrypoints.web"]
