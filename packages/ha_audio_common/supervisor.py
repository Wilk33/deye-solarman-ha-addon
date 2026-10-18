from __future__ import annotations

import json
import logging
import os
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request
from urllib.request import urlopen


LOGGER=logging.getLogger(__name__)


def _request_json(url: str,token: str,method: str="GET",payload: dict[str,Any] | None=None,timeout: float=10) -> Any:
	body=None if payload is None else json.dumps(payload).encode("utf-8")
	headers={"Authorization":f"Bearer {token}","Content-Type":"application/json"}
	request=Request(url,data=body,headers=headers,method=method)
	with urlopen(request,timeout=timeout) as response:
		content=response.read()
	return json.loads(content.decode("utf-8")) if content else None


def discover_mqtt_service(token: str | None=None,base_url: str="http://supervisor") -> dict[str,Any]:
	token=token or os.environ.get("SUPERVISOR_TOKEN","")
	if not token:
		raise RuntimeError("Brak SUPERVISOR_TOKEN")
	payload=_request_json(f"{base_url.rstrip('/')}/services/mqtt",token)
	service=payload.get("data",payload) if isinstance(payload,dict) else payload
	if not isinstance(service,dict):
		raise RuntimeError("Supervisor zwrócił nieprawidłową konfigurację MQTT")
	for key in ("host","port","username","password"):
		if key not in service:
			raise RuntimeError(f"Brak pola MQTT Supervisor: {key}")
	return service


class HomeAssistantClient:
	def __init__(self,token: str | None=None,base_url: str="http://supervisor/core/api",timeout: float=10) -> None:
		self.token=token or os.environ.get("SUPERVISOR_TOKEN","")
		if not self.token:
			raise RuntimeError("Brak SUPERVISOR_TOKEN")
		self.base_url=base_url.rstrip("/")
		self.timeout=timeout

	def get_state(self,entity_id: str) -> dict[str,Any]:
		encoded=quote(entity_id,safe="")
		payload=_request_json(f"{self.base_url}/states/{encoded}",self.token,timeout=self.timeout)
		if not isinstance(payload,dict):
			raise RuntimeError(f"Nieprawidłowy stan encji {entity_id}")
		return payload

	def call_service(self,domain: str,service: str,data: dict[str,Any]) -> Any:
		return _request_json(
			f"{self.base_url}/services/{quote(domain,safe='')}/{quote(service,safe='')}",
			self.token,
			method="POST",
			payload=data,
			timeout=self.timeout,
		)

	def persistent_notification(self,title: str,message: str,notification_id: str) -> None:
		self.call_service("persistent_notification","create",{
			"title":title,
			"message":message,
			"notification_id":notification_id,
		})

	def dismiss_persistent_notification(self,notification_id: str) -> None:
		self.call_service("persistent_notification","dismiss",{"notification_id":notification_id})

	def send_notification(self,target: str,title: str,message: str) -> None:
		if not target.startswith("notify."):
			raise ValueError(f"Cel powiadomienia musi zaczynać się od notify.: {target}")
		try:
			self.call_service("notify","send_message",{
				"entity_id":target,
				"title":title,
				"message":message,
			})
		except HTTPError as error:
			if error.code not in {400,404,405}:
				raise
			LOGGER.debug("notify.send_message niedostępne dla %s, używam usługi zgodności",target)
			self.call_service("notify",target.removeprefix("notify."),{
				"title":title,
				"message":message,
			})
