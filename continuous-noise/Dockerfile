ARG BUILD_FROM=ghcr.io/home-assistant/base:3.23
FROM ${BUILD_FROM}

ARG BUILD_ARCH
ARG BUILD_VERSION

LABEL \
	io.hass.name="Continuous Noise" \
	io.hass.description="Ciągły odtwarzacz szumów Home Assistant" \
	io.hass.arch="${BUILD_ARCH}" \
	io.hass.type="app" \
	io.hass.version="${BUILD_VERSION}"

ENV LANG=C.UTF-8
ENV PATH="/opt/venv/bin:${PATH}"
ENV PULSE_SERVER="unix:/run/audio/pulse.sock"

WORKDIR /usr/src/app

COPY rootfs/requirements.txt /tmp/requirements.txt
RUN apk add --no-cache python3 py3-pip pulseaudio-utils \
	&& python3 -m venv /opt/venv \
	&& /opt/venv/bin/pip install --no-cache-dir -r /tmp/requirements.txt

COPY rootfs/usr/src/app /usr/src/app
COPY run.sh /run.sh

RUN chmod a+x /run.sh

CMD ["/run.sh"]
