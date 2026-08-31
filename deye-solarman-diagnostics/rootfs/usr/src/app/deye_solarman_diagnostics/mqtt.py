from __future__ import annotations

import json
import logging
import threading
from typing import Any

import paho.mqtt.client as mqtt

from .models import InverterConfig
from .models import MqttConfig
from .models import SensorDefinition


LOGGER=logging.getLogger(__name__)


class MqttPublisher:
	def __init__(self, config: MqttConfig, inverter: InverterConfig) -> None:
		self._config=config
		self._inverter=inverter
		self._connected=threading.Event()
		self._connection_error: str | None=None
		self._client=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=config.client_id)
		self._client.on_connect=self._on_connect
		self._client.on_disconnect=self._on_disconnect
		if config.username:
			self._client.username_pw_set(config.username, config.password)

	def connect(self) -> None:
		self._connected.clear()
		self._connection_error=None
		LOGGER.info(
			"Connecting to MQTT host=%s port=%s client_id=%s",
			self._config.host,
			self._config.port,
			self._config.client_id,
		)
		self._client.connect(self._config.host, self._config.port, 60)
		self._client.loop_start()
		if not self._connected.wait(timeout=10):
			raise ConnectionError("MQTT broker did not confirm the connection within 10 seconds")
		if self._connection_error:
			raise ConnectionError(self._connection_error)

	def disconnect(self) -> None:
		try:
			self._client.loop_stop()
			self._client.disconnect()
		except Exception:
			pass

	def publish_discovery(self, sensor: SensorDefinition) -> None:
		topic=(
			f"{self._config.discovery_prefix}/sensor/"
			f"deye_solarman_{self._inverter.serial_number}_{sensor.key}/config"
		)
		state_topic=self.state_topic(sensor)
		attributes_topic=f"{state_topic}/attributes"
		payload: dict[str, Any]={
			"name": sensor.name,
			"state_topic": state_topic,
			"unique_id": f"deye_solarman_{self._inverter.serial_number}_{sensor.key}",
			"object_id": f"deye_solarman_{self._inverter.serial_number}_{sensor.key}",
			"json_attributes_topic": attributes_topic,
			"device": {
				"identifiers": [f"deye_solarman_{self._inverter.serial_number}"],
				"name": self._inverter.name,
				"manufacturer": self._inverter.manufacturer,
				"model": self._inverter.model,
				"serial_number": self._inverter.serial_number,
			},
		}
		if sensor.category:
			payload["entity_category"]=sensor.category
		if sensor.unit:
			payload["unit_of_measurement"]=sensor.unit
		if sensor.device_class:
			payload["device_class"]=sensor.device_class
		if sensor.state_class:
			payload["state_class"]=sensor.state_class
		if sensor.icon:
			payload["icon"]=sensor.icon
		self._publish_confirmed(topic,json.dumps(payload),self._config.retain,"discovery")

	def publish_state(self, sensor: SensorDefinition, value: int | float | str, attributes: dict[str, Any]) -> None:
		retain=self._config.retain and sensor.retain
		self._client.publish(self.state_topic(sensor), value, retain=retain)
		self._client.publish(
			f"{self.state_topic(sensor)}/attributes",
			json.dumps(attributes),
			retain=retain,
		)

	def publish_raw(self, sensor: SensorDefinition, raw_registers: list[int]) -> None:
		self._client.publish(f"{self.state_topic(sensor)}/raw", json.dumps(raw_registers), retain=self._config.retain and sensor.retain)

	def state_topic(self, sensor: SensorDefinition) -> str:
		suffix=sensor.topic_suffix or sensor.key
		return f"{self._config.base_topic}/{self._inverter.serial_number}/{suffix}"

	def _on_connect(
		self,
		_client: mqtt.Client,
		_userdata: Any,
		_flags: Any,
		reason_code: Any,
		_properties: Any,
	) -> None:
		if reason_code == 0:
			LOGGER.info("MQTT connection confirmed")
		else:
			self._connection_error=f"MQTT broker rejected the connection reason={reason_code}"
			LOGGER.error(self._connection_error)
		self._connected.set()

	def _on_disconnect(
		self,
		_client: mqtt.Client,
		_userdata: Any,
		_disconnect_flags: Any,
		reason_code: Any,
		_properties: Any,
	) -> None:
		if reason_code != 0:
			LOGGER.warning("MQTT disconnected reason=%s",reason_code)

	def _publish_confirmed(self, topic: str, payload: str, retain: bool, kind: str) -> None:
		info=self._client.publish(topic,payload,retain=retain)
		if hasattr(info,"wait_for_publish"):
			info.wait_for_publish(timeout=10)
			if not info.is_published():
				raise ConnectionError(f"MQTT {kind} publish timed out topic={topic}")
		LOGGER.info("MQTT %s published topic=%s retain=%s",kind,topic,retain)
