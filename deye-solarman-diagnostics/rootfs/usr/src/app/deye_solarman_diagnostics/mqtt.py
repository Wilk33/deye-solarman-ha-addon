from __future__ import annotations

import json
from typing import Any

import paho.mqtt.client as mqtt

from .models import InverterConfig
from .models import MqttConfig
from .models import SensorDefinition


class MqttPublisher:
	def __init__(self, config: MqttConfig, inverter: InverterConfig) -> None:
		self._config=config
		self._inverter=inverter
		self._client=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=config.client_id)
		if config.username:
			self._client.username_pw_set(config.username, config.password)

	def connect(self) -> None:
		self._client.connect(self._config.host, self._config.port, 60)
		self._client.loop_start()

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
		self._client.publish(topic, json.dumps(payload), retain=self._config.retain)

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
