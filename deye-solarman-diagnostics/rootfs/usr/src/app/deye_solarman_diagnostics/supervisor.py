from __future__ import annotations

import json
import logging
import os
from typing import Any
from urllib.request import Request
from urllib.request import urlopen


LOGGER=logging.getLogger(__name__)
SUPERVISOR_MQTT_URL="http://supervisor/services/mqtt"


def discover_mqtt_service(timeout: float=5.0) -> dict[str, Any] | None:
	"""Return MQTT connection data provided by Home Assistant Supervisor."""
	headers={"Content-Type": "application/json"}
	if token:=os.environ.get("SUPERVISOR_TOKEN"):
		headers["Authorization"]=f"Bearer {token}"
	request=Request(SUPERVISOR_MQTT_URL,headers=headers)
	try:
		with urlopen(request,timeout=timeout) as response:
			service=json.loads(response.read().decode("utf-8"))
	except (OSError,ValueError,json.JSONDecodeError) as error:
		LOGGER.warning("Supervisor MQTT service is unavailable, using manual MQTT configuration: %s",error)
		return None

	try:
		host=str(service["host"])
		port=int(service["port"])
		username=str(service["username"])
		password=str(service["password"])
		tls=bool(service.get("ssl",False))
	except (KeyError,TypeError,ValueError) as error:
		LOGGER.warning("Supervisor returned an incomplete MQTT service, using manual MQTT configuration: %s",error)
		return None
	if not host or not 1 <= port <= 65535 or not username or not password:
		LOGGER.warning("Supervisor returned MQTT service without usable credentials, using manual MQTT configuration")
		return None

	LOGGER.info("Using MQTT service credentials supplied by Home Assistant Supervisor host=%s port=%s tls=%s",host,port,tls)
	return {
		"host": host,
		"port": port,
		"username": username,
		"password": password,
		"tls": tls,
	}
