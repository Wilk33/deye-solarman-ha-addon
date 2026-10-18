from __future__ import annotations

import logging
import ssl
from collections.abc import Callable
from typing import Any


LOGGER=logging.getLogger(__name__)


class MqttServiceClient:
	def __init__(self,service: dict[str,Any],client_id: str,on_message: Callable[[str,str,bool],None]) -> None:
		import paho.mqtt.client as mqtt
		self._mqtt=mqtt
		self._service=service
		self._on_message_callback=on_message
		self._connected=False
		self._subscriptions: set[str]=set()
		self.client=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,client_id=client_id,protocol=mqtt.MQTTv311)
		username=service.get("username")
		if username:
			self.client.username_pw_set(str(username),str(service.get("password","")))
		if service.get("ssl"):
			self.client.tls_set(cert_reqs=ssl.CERT_REQUIRED)
		self.client.on_connect=self._on_connect
		self.client.on_disconnect=self._on_disconnect
		self.client.on_message=self._on_message

	def set_last_will(self,topic: str,payload: str="offline") -> None:
		self.client.will_set(topic,payload,qos=1,retain=True)

	def connect(self) -> None:
		self.client.connect(str(self._service["host"]),int(self._service["port"]),60)
		self.client.loop_start()

	def subscribe(self,topic: str) -> None:
		self._subscriptions.add(topic)
		if self._connected:
			self.client.subscribe(topic,qos=1)

	def publish(self,topic: str,payload: Any,retain: bool=True) -> Any:
		if isinstance(payload,(dict,list)):
			import json
			payload=json.dumps(payload,ensure_ascii=False,separators=(",",":"))
		return self.client.publish(topic,str(payload),qos=1,retain=retain)

	def publish_and_wait(self,topic: str,payload: Any,retain: bool=True,timeout: float=5) -> None:
		message=self.publish(topic,payload,retain)
		message.wait_for_publish(timeout=timeout)

	def close(self) -> None:
		try:
			self.client.disconnect()
		finally:
			self.client.loop_stop()

	def _on_connect(self,client: Any,_userdata: Any,_flags: Any,reason_code: Any,_properties: Any) -> None:
		self._connected=reason_code == 0
		if self._connected:
			for topic in self._subscriptions:
				client.subscribe(topic,qos=1)
			LOGGER.info("Połączono z MQTT")
		else:
			LOGGER.error("Broker MQTT odrzucił połączenie: %s",reason_code)

	def _on_disconnect(self,_client: Any,_userdata: Any,_flags: Any,reason_code: Any,_properties: Any) -> None:
		self._connected=False
		if reason_code != 0:
			LOGGER.warning("Rozłączono MQTT: %s",reason_code)

	def _on_message(self,_client: Any,_userdata: Any,message: Any) -> None:
		try:
			payload=bytes(message.payload).decode("utf-8").strip()
		except (UnicodeDecodeError,TypeError):
			LOGGER.warning("Odrzucono nieprawidłową wiadomość MQTT z %s",message.topic)
			return
		self._on_message_callback(str(message.topic),payload,bool(message.retain))
