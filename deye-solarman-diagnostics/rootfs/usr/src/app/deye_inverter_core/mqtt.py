from __future__ import annotations

import json
import logging
import ssl
import threading
from typing import Any

import paho.mqtt.client as mqtt

from .models import InverterConfig
from .models import MqttConfig
from .models import SensorDefinition
from .logging_utils import success


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
		self._control_handler=None
		self._control_topics={}
		self._control_discovery={}
		self._client.on_message=self._on_control_message
		self._client.will_set(self.control_base()+"/availability","offline",retain=True)
		if config.tls:
			self._client.tls_set(cert_reqs=ssl.CERT_REQUIRED)
		if config.username:
			self._client.username_pw_set(config.username, config.password)

	def connect(self) -> None:
		self._connected.clear()
		self._connection_error=None
		LOGGER.info(
			"Connecting to MQTT host=%s port=%s client_id=%s source=%s tls=%s",
			self._config.host,
			self._config.port,
			self._config.client_id,
			self._config.source,
			self._config.tls,
		)
		self._client.connect(self._config.host, self._config.port, 60)
		self._client.loop_start()
		if not self._connected.wait(timeout=10):
			raise ConnectionError("MQTT broker did not confirm the connection within 10 seconds")
		if self._connection_error:
			raise ConnectionError(self._connection_error)

	def disconnect(self) -> None:
		try:
			self._publish_confirmed(self.control_base()+"/availability","offline",True,"control availability")
			self._client.loop_stop()
			self._client.disconnect()
		except Exception:
			pass

	def publish_discovery(self, sensor: SensorDefinition) -> None:
		topic=self.discovery_topic(sensor.key)
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

	def remove_discovery(self, sensor_key: str) -> None:
		self._publish_confirmed(self.discovery_topic(sensor_key),"",True,"discovery removal")

	def discovery_topic(self, sensor_key: str) -> str:
		return (
			f"{self._config.discovery_prefix}/sensor/"
			f"deye_solarman_{self._inverter.serial_number}_{sensor_key}/config"
		)

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
			success(LOGGER,"MQTT connection confirmed")
			for topic in self._control_topics:
				_client.subscribe(topic,qos=0)
			_client.publish(self.control_base()+"/availability","online",retain=True)
		else:
			self._connection_error=f"MQTT broker rejected the connection reason={reason_code}"
			LOGGER.error(self._connection_error)
		self._connected.set()

	def control_base(self) -> str:
		return f"{self._config.base_topic}/{self._inverter.serial_number}/controls"

	def configure_controls(self, handler: Any, keys: list[str]) -> None:
		self._control_handler=handler
		self._control_topics={f"{self.control_base()}/{key}/set":key for key in keys}
		for topic in self._control_topics:
			self._client.subscribe(topic,qos=0)

	def _on_control_message(self, _client: Any, _userdata: Any, message: Any) -> None:
		key=self._control_topics.get(message.topic)
		if key is None or self._control_handler is None or len(message.payload) > 128:
			return
		try:
			self._control_handler(key,message.payload.decode("utf-8"),message.retain)
		except (UnicodeDecodeError,ValueError):
			LOGGER.warning("Invalid control command payload")

	def control_discovery_topic(self, definition: dict) -> str:
		from .controls import component
		return f"{self._config.discovery_prefix}/{component(definition)}/deye_solarman_{self._inverter.serial_number}_{definition['key']}/config"

	def remove_control_discovery(self, definition: dict) -> None:
		self._publish_confirmed(self.control_discovery_topic(definition),"",True,"control removal")
		self.control_availability(definition["key"],False)

	def publish_control_discovery(self, entry: dict, result: dict) -> None:
		from .controls import CONTROLS, component
		key=entry["key"]
		definition=CONTROLS[key]
		settings=entry["definition"]
		base=f"{self.control_base()}/{key}"
		payload={
			"name":settings["name"],"unique_id":f"deye_solarman_{self._inverter.serial_number}_{key}",
			"state_topic":base+"/state","command_topic":base+"/set","json_attributes_topic":base+"/attributes",
			"retain":False,"optimistic":False,"entity_category":"config","icon":settings["icon"],
			"availability":[{"topic":self.control_base()+"/availability"},{"topic":base+"/availability"}],"availability_mode":"all",
			"device":{"identifiers":[f"deye_solarman_{self._inverter.serial_number}"],"name":self._inverter.name,"manufacturer":self._inverter.manufacturer,"model":self._inverter.model},
		}
		kind=component(definition)
		if kind == "number":
			payload.update(min=result["min"],max=result["max"],step=abs(definition["factor"]),mode="box")
			if definition["unit"]:
				payload["unit_of_measurement"]=definition["unit"]
		elif kind == "select":
			payload["options"]=result.get("options",list(definition.get("options",{}).values()))
		elif kind == "switch":
			payload.update(payload_on="ON",payload_off="OFF")
		else:
			payload.update(min=19,max=19,pattern=r"[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}")
		encoded=json.dumps(payload)
		if self._control_discovery.get(key) != encoded:
			self._publish_confirmed(self.control_discovery_topic(definition),encoded,True,"control discovery")
			self._control_discovery[key]=encoded

	def publish_control_state(self, entry: dict, result: dict) -> None:
		base=f"{self.control_base()}/{entry['key']}"
		retain=self._config.retain and entry["definition"]["retain"]
		# Unknown enum labels are diagnostic attributes, never valid select options.
		if result.get("status") != "unknown":
			self._client.publish(base+"/state",result["value"],retain=retain)
		self._client.publish(base+"/attributes",json.dumps(result),retain=retain)

	def control_availability(self, key: str, available: bool) -> None:
		self._client.publish(f"{self.control_base()}/{key}/availability","online" if available else "offline",retain=True)

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
		success(LOGGER,"MQTT %s published topic=%s retain=%s",kind,topic,retain)
