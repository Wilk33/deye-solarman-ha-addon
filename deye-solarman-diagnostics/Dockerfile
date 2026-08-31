ARG BUILD_FROM=ghcr.io/home-assistant/base:3.21
FROM ${BUILD_FROM}

ENV LANG=C.UTF-8

WORKDIR /usr/src/app

COPY deye-solarman-diagnostics/rootfs/requirements.txt /tmp/requirements.txt
RUN apk add --no-cache python3 py3-pip bash \
	&& pip3 install --no-cache-dir -r /tmp/requirements.txt

COPY deye-solarman-diagnostics/rootfs/usr/src/app /usr/src/app
COPY deye-solarman-diagnostics/run.sh /run.sh

RUN chmod a+x /run.sh

CMD ["/run.sh"]
