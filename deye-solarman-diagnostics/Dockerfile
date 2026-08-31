ARG BUILD_FROM=ghcr.io/home-assistant/base:3.21
FROM ${BUILD_FROM}

ENV LANG=C.UTF-8
ENV PATH="/opt/venv/bin:${PATH}"

WORKDIR /usr/src/app

COPY rootfs/requirements.txt /tmp/requirements.txt
RUN apk add --no-cache python3 py3-pip bash \
	&& python3 -m venv /opt/venv \
	&& /opt/venv/bin/pip install --no-cache-dir -r /tmp/requirements.txt

COPY rootfs/usr/src/app /usr/src/app
COPY run.sh /run.sh

RUN chmod a+x /run.sh

CMD ["/run.sh"]
