ARG BUILD_ARCH=amd64
ARG BUILD_VERSION=1.1.3

FROM ghcr.io/home-assistant/${BUILD_ARCH}-base-python:3.12-alpine3.22

LABEL \
  io.hass.version="${BUILD_VERSION}" \
  io.hass.type="app" \
  io.hass.arch="${BUILD_ARCH}"

WORKDIR /

COPY requirements.txt /tmp/requirements.txt
RUN python3 -m pip install --no-cache-dir --upgrade pip \
  && python3 -m pip install --no-cache-dir -r /tmp/requirements.txt

COPY rootfs /

RUN chmod a+x /etc/services.d/app/run
