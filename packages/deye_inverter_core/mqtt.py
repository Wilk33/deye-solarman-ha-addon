from __future__ import annotations

import json
import logging
import ssl
import threading
from contextlib import nullcontext
from functools import wraps
from typing import Any

import paho.mqtt.client as mqtt

from .models import InverterConfig
from .models import MqttConfig
from .models import SensorDefinition
from .logging_utils import success
from .ownership import EntityOwnership


LOGGER=logging.getLogger(__name__)


def owned_operation(kind: str | None=None, removal: bool=False):
	def decorate(method):
		@wraps(method)
		def call(self, entity, *args, **kwargs):
			from .controls import CONTROLS, component
			key=entity if isinstance(entity,str) else entity["key"] if isinstance(entity,dict) else entity.key
			entity_kind=kind or component(CONTROLS[key])
			with self.ownership.guard(entity_kind,key,unowned=removal) if self.ownership else nullcontext(True) as allowed:
				if not allowed:
					return False
				method(self,entity,*args,**kwargs)
				return True
		return call
	return decorate


class MqttPublisher:
	def __init__(self, config: MqttConfig, inverter: InverterConfig, ownership: EntityOwnership | None=None) -> None:
		self._config=config
		self._inverter=inverter
		self.ownership=ownership
		self.source=ownership.source if ownership else "solarman_tcp"
		self.origin={"name":ownership.name if ownership else "Deye Solarman Local","sw_version":"1.3.0","support_url":"https://github.com/Wilk33/deye-solarman-ha-addon"}
		self._connected=threading.Event()
		self._connection_error: str | None=None
		self._client=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=config.client_id+"-"+self.source)
		self._client.on_connect=self._on_connect
		self._client.on_disconnect=self._on_disconnect
		self._control_handler=None
		self._control_topics={}
		self._control_discovery={}
		self._client.on_message=self._on_control_message
		self._client.will_set(self.control_source_base()+"/availability","offline",retain=True)
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
			self._config.client_id+"-"+self.source,
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
			self._publish_confirmed(self.control_source_base()+"/availability","offline",True,"control availability")
			self._client.loop_stop()
			self._client.disconnect()
		except Exception:
			pass

	@owned_operation("sensor")
	def publish_discovery(self, sensor: SensorDefinition) -> None:
		topic=self.discovery_topic(sensor.key)
		state_topic=self.state_topic(sensor)
		attributes_topic=f"{state_topic}/attributes"
		payload: dict[str, Any]={
			"origin":self.origin,
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

	@owned_operation("sensor",removal=True)
	def remove_discovery(self, sensor_key: str) -> None:
		self._publish_confirmed(self.discovery_topic(sensor_key),"",True,"discovery removal")

	def discovery_topic(self, sensor_key: str) -> str:
		return (
			f"{self._config.discovery_prefix}/sensor/"
			f"deye_solarman_{self._inverter.serial_number}_{sensor_key}/config"
		)

	@owned_operation("sensor")
	def publish_state(self, sensor: SensorDefinition, value: int | float | str, attributes: dict[str, Any]) -> None:
		retain=self._config.retain and sensor.retain
		self._publish_confirmed(self.state_topic(sensor),value,retain,"state")
		self._publish_confirmed(
			f"{self.state_topic(sensor)}/attributes",
			json.dumps(attributes),
			retain,"attributes",
		)

	@owned_operation("sensor")
	def publish_raw(self, sensor: SensorDefinition, raw_registers: list[int]) -> None:
		self._publish_confirmed(f"{self.state_topic(sensor)}/raw",json.dumps(raw_registers),self._config.retain and sensor.retain,"raw")

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
			_client.publish(self.control_source_base()+"/availability","online",retain=True)
		else:
			self._connection_error=f"MQTT broker rejected the connection reason={reason_code}"
			LOGGER.error(self._connection_error)
		self._connected.set()

	def control_base(self) -> str:
		return f"{self._config.base_topic}/{self._inverter.serial_number}/controls"

	def control_source_base(self) -> str:
		return f"{self._config.base_topic}/{self._inverter.serial_number}/source/{self.source}/controls"

	def control_command_topic(self, key: str) -> str:
		return f"{self.control_source_base()}/{key}/set"

	def configure_controls(self, handler: Any, keys: list[str]) -> None:
		from .controls import CONTROLS, component
		self._control_handler=handler
		previous=set(self._control_topics)
		self._control_topics={self.control_command_topic(key):key for key in keys if not self.ownership or self.ownership.owns(component(CONTROLS[key]),key)}
		for topic in previous-self._control_topics.keys():
			self._client.unsubscribe(topic)
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

	@owned_operation(removal=True)
	def remove_control_discovery(self, definition: dict) -> None:
		self._publish_confirmed(self.control_discovery_topic(definition),"",True,"control removal")

	@owned_operation()
	def publish_control_discovery(self, entry: dict, result: dict) -> None:
		from .controls import CONTROLS, component
		key=entry["key"]
		definition=CONTROLS[key]
		settings=entry["definition"]
		base=f"{self.control_base()}/{key}"
		payload={
			"origin":self.origin,
			"name":settings["name"],"unique_id":f"deye_solarman_{self._inverter.serial_number}_{key}",
			"state_topic":base+"/state","command_topic":self.control_command_topic(key),"json_attributes_topic":base+"/attributes",
			"retain":False,"optimistic":False,"entity_category":"config","icon":settings["icon"],
			"availability":[{"topic":self.control_source_base()+"/availability"},{"topic":f"{self.control_source_base()}/{key}/availability"}],"availability_mode":"all",
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

	@owned_operation()
	def publish_control_state(self, entry: dict, result: dict) -> None:
		base=f"{self.control_base()}/{entry['key']}"
		retain=self._config.retain and entry["definition"]["retain"]
		# Unknown enum labels are diagnostic attributes, never valid select options.
		if result.get("status") != "unknown":
			self._publish_confirmed(base+"/state",result["value"],retain,"control state")
		self._publish_confirmed(base+"/attributes",json.dumps(result),retain,"control attributes")

	@owned_operation()
	def control_availability(self, key: str, available: bool) -> None:
		self._publish_confirmed(f"{self.control_source_base()}/{key}/availability","online" if available else "offline",True,"control availability")

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
		try:
			info=self._client.publish(topic,payload,retain=retain,qos=1)
			if hasattr(info,"wait_for_publish"):
				info.wait_for_publish(timeout=10)
				if not info.is_published():
					raise ConnectionError(f"MQTT {kind} publish timed out topic={topic}")
		except Exception:
			# Stop this client's retry loop before releasing ownership. The runtime
			# creates a fresh client on reconnect, without this pending send queue.
			self._client.disconnect()
			self._client.loop_stop()
			raise
		success(LOGGER,"MQTT %s published topic=%s retain=%s",kind,topic,retain)
