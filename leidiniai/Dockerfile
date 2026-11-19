# Home Assistant app "Leidiniai" (amd64 only).
# Supervisor 2026.04+ no longer passes BUILD_FROM, so the base image is set here.
FROM python:3.12-slim-bookworm

ARG BUILD_VERSION=dev
ARG BUILD_ARCH=amd64
LABEL \
  io.hass.version="${BUILD_VERSION}" \
  io.hass.type="app" \
  io.hass.arch="amd64"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    LANG=C.UTF-8

RUN apt-get update \
 && apt-get install -y --no-install-recommends util-linux tzdata ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt

COPY app /opt/leidiniai
WORKDIR /opt/leidiniai

CMD ["python", "-m", "leidiniai"]
