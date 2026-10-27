from __future__ import annotations

import json
import logging
import ssl
import threading
import time
from contextlib import contextmanager
from typing import Any

import paho.mqtt.client as mqtt

from .models import InverterConfig
from .models import MqttConfig
from .models import SensorDefinition
from .logging_utils import success


LOGGER=logging.getLogger(__name__)


TRANSPORT_DIAGNOSTICS={
	"solarman_tcp":"SolarMan TCP",
	"modbus_rtu":"Modbus RTU (RS485)",
}

class MqttPublisher:
	def __init__(self, config: MqttConfig, inverter: InverterConfig, detailed_logs: bool=False) -> None:
		self._config=config
		self._inverter=inverter
		self.detailed_logs=detailed_logs
		self.origin={"name":"SolarMan Diagnostics","sw_version":"2.0.8","support_url":"https://github.com/Wilk33/deye-solarman-ha-addon"}
		self._connected=threading.Event()
		self._connection_error: str | None=None
		self._session_lock=threading.RLock()
		self._discovery_lock=threading.RLock()
		self._needs_reconnect=False
		self._closed=False
		self._client=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,client_id=config.client_id)
		self._client.on_connect=self._on_connect
		self._client.on_disconnect=self._on_disconnect
		self._control_handler=None
		self._control_topics={}
		self._control_discovery={}
		self._transport_diagnostic_discovery: set[str]=set()
		self._transport_diagnostic_cleanup_done=False
		self._publication_context=threading.local()
		self._client.on_message=self._on_control_message
		self._client.will_set(self.availability_topic(),"offline",retain=True)
		if config.tls:
			self._client.tls_set(cert_reqs=ssl.CERT_REQUIRED)
		if config.username:
			self._client.username_pw_set(config.username, config.password)

	def connect(self) -> None:
		with self._session_lock:
			self._closed=False
			self._open_session_locked(reconnect=False)

	def _open_session_locked(self, *, reconnect: bool) -> None:
		self._connected.clear()
		self._connection_error=None
		LOGGER.info(
			"Connecting to MQTT host=%s port=%s client_id=%s config_source=%s tls=%s",
			self._config.host,
			self._config.port,
			self._config.client_id,
			self._config.source,
			self._config.tls,
		)
		if reconnect:
			self._client.reconnect()
		else:
			self._client.connect(self._config.host, self._config.port, 60)
		self._client.loop_start()
		if not self._connected.wait(timeout=10):
			self._needs_reconnect=True
			raise ConnectionError("MQTT broker did not confirm the connection within 10 seconds")
		if self._connection_error:
			self._needs_reconnect=True
			raise ConnectionError(self._connection_error)
		self._needs_reconnect=False

	def disconnect(self) -> None:
		with self._session_lock:
			for topic,kind in (
				(self.control_base()+"/availability","control availability"),
				(self.availability_topic(),"process availability"),
			):
				try:
					self._publish_confirmed(topic,"offline",True,kind)
				except Exception:
					pass
			try:
				self._client.loop_stop()
				self._client.disconnect()
			except Exception:
				pass
			self._closed=True
			self._needs_reconnect=False

	@contextmanager
	def publication_batch(self,kind: str, *, transport: str="shared"):
		if getattr(self._publication_context,"batch",None) is not None:
			yield
			return
		batch={"confirmed":0,"failed":0,"kinds":{}}
		self._publication_context.batch=batch
		started_at=time.perf_counter()
		try:
			yield
		finally:
			self._publication_context.batch=None
			if batch["failed"] or (self.detailed_logs and batch["confirmed"]):
				level=logging.WARNING if batch["failed"] else logging.DEBUG
				LOGGER.log(level,"MQTT batch kind=%s transport=%s confirmed=%s failed=%s duration_ms=%.2f messages=%s",kind,transport,batch["confirmed"],batch["failed"],(time.perf_counter()-started_at)*1000,dict(sorted(batch["kinds"].items())))

	@contextmanager
	def discovery_transaction(self):
		with self.publication_batch("discovery"),self._discovery_lock:
			yield

	def publish_discovery(self, sensor: SensorDefinition) -> None:
		with self._discovery_lock:
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
				"availability":[{"topic":self.availability_topic()}],
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
		with self._discovery_lock:
			self._publish_confirmed(self.discovery_topic(sensor_key),"",True,"discovery removal")

	def discovery_topic(self, sensor_key: str) -> str:
		return (
			f"{self._config.discovery_prefix}/sensor/"
			f"deye_solarman_{self._inverter.serial_number}_{sensor_key}/config"
		)

	def publish_state(self, sensor: SensorDefinition, value: int | float | str, attributes: dict[str, Any]) -> None:
		retain=self._config.retain and sensor.retain
		self._publish_confirmed(self.state_topic(sensor),value,retain,"state")
		attributes={**attributes,"transport":sensor.transport}
		self._publish_confirmed(
			f"{self.state_topic(sensor)}/attributes",
			json.dumps(attributes),
			retain,"attributes",
		)

	def publish_raw(self, sensor: SensorDefinition, raw_registers: list[int]) -> None:
		self._publish_confirmed(f"{self.state_topic(sensor)}/raw",json.dumps(raw_registers),self._config.retain and sensor.retain,"raw")

	def state_topic(self, sensor: SensorDefinition) -> str:
		suffix=sensor.topic_suffix or sensor.key
		return f"{self._config.base_topic}/{self._inverter.serial_number}/{suffix}"

	def availability_topic(self) -> str:
		return f"{self._config.base_topic}/{self._inverter.serial_number}/availability"

	def sensor_availability_topic(self,sensor: SensorDefinition) -> str:
		return f"{self.state_topic(sensor)}/availability"

	def sensor_availability(self,sensor: SensorDefinition,available: bool) -> None:
		self._publish_confirmed(
			self.sensor_availability_topic(sensor),
			"online" if available else "offline",
			True,
			"sensor availability",
		)

	def publish_transport_diagnostics(self,status: dict[str,Any]) -> None:
		transports={str(item["id"]):item for item in status.get("transports",[]) if item.get("id") in TRANSPORT_DIAGNOSTICS}
		with self.publication_batch("diagnostics"),self._discovery_lock:
			if not self._transport_diagnostic_cleanup_done:
				for transport_id in TRANSPORT_DIAGNOSTICS.keys()-transports.keys():
					for metric in ("latency","errors"):
						self._publish_confirmed(self.transport_diagnostic_discovery_topic(transport_id,metric),"",True,"transport diagnostic removal")
				self._transport_diagnostic_cleanup_done=True
			for transport_id,transport_status in transports.items():
				for metric in ("latency","errors"):
					key=f"{transport_id}:{metric}"
					if key not in self._transport_diagnostic_discovery:
						self._publish_confirmed(
							self.transport_diagnostic_discovery_topic(transport_id,metric),
							json.dumps(self._transport_diagnostic_payload(transport_id,metric)),
							True,
							"transport diagnostic discovery",
						)
						self._transport_diagnostic_discovery.add(key)
				attributes={
					"transport":transport_id,
					"online":bool(transport_status.get("online",False)),
					"last_error":transport_status.get("last_error"),
					"reconnect_in_seconds":transport_status.get("reconnect_in_seconds",0.0),
				}
				for field in ("connection_losses","last_outage_seconds","last_disconnect_interval_seconds","periodic_reset_detected"):
					attributes[field]=transport_status.get(field)
				values={
					"latency":transport_status.get("latency_ms",0.0),
					"errors":transport_status.get("error_count",0),
				}
				for metric,value in values.items():
					state_topic=self.transport_diagnostic_state_topic(transport_id,metric)
					self._publish_confirmed(state_topic,value,self._config.retain,"transport diagnostic state")
					self._publish_confirmed(
						f"{state_topic}/attributes",
						json.dumps(attributes),
						self._config.retain,
						"transport diagnostic attributes",
					)

	def transport_diagnostic_discovery_topic(self,transport_id: str,metric: str) -> str:
		return (
			f"{self._config.discovery_prefix}/sensor/"
			f"deye_solarman_{self._inverter.serial_number}_transport_{transport_id}_{metric}/config"
		)

	def transport_diagnostic_state_topic(self,transport_id: str,metric: str) -> str:
		suffix="latency_ms" if metric == "latency" else "errors"
		return f"{self._config.base_topic}/{self._inverter.serial_number}/diagnostics/{transport_id}/{suffix}"

	def _transport_diagnostic_payload(self,transport_id: str,metric: str) -> dict[str,Any]:
		label=TRANSPORT_DIAGNOSTICS[transport_id]
		state_topic=self.transport_diagnostic_state_topic(transport_id,metric)
		metric_label="Latency" if metric == "latency" else "Errors"
		payload={
			"origin":self.origin,
			"name":f"{label} {metric_label}",
			"state_topic":state_topic,
			"unique_id":f"deye_solarman_{self._inverter.serial_number}_transport_{transport_id}_{metric}",
			"object_id":f"deye_solarman_{self._inverter.serial_number}_transport_{transport_id}_{metric}",
			"json_attributes_topic":f"{state_topic}/attributes",
			"availability":[{"topic":self.availability_topic()}],
			"entity_category":"diagnostic",
			"device":{
				"identifiers":[f"deye_solarman_{self._inverter.serial_number}"],
				"name":self._inverter.name,
				"manufacturer":self._inverter.manufacturer,
				"model":self._inverter.model,
				"serial_number":self._inverter.serial_number,
			},
		}
		if metric == "latency":
			payload.update({
				"device_class":"duration",
				"state_class":"measurement",
				"unit_of_measurement":"ms",
				"icon":"mdi:timer-outline",
			})
		else:
			payload["icon"]="mdi:alert-circle-outline"
		return payload

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
			_client.publish(self.availability_topic(),"online",retain=True,qos=1)
			_client.publish(self.control_base()+"/availability","online",retain=True,qos=1)
		else:
			self._connection_error=f"MQTT broker rejected the connection reason={reason_code}"
			LOGGER.error(self._connection_error)
		self._connected.set()

	def control_base(self) -> str:
		return f"{self._config.base_topic}/{self._inverter.serial_number}/controls"

	def control_command_topic(self, key: str) -> str:
		return f"{self.control_base()}/{key}/set"

	def configure_controls(self, handler: Any, keys: list[str]) -> None:
		self.disable_control_commands()
		previous=set(self._control_topics)
		new_topics={self.control_command_topic(key):key for key in keys}
		for topic in previous-new_topics.keys():
			self._require_subscription_result("unsubscribe",self._client.unsubscribe(topic))
		for topic in new_topics:
			self._require_subscription_result("subscribe",self._client.subscribe(topic,qos=0))
		self._control_topics=new_topics
		self._control_handler=handler

	def disable_control_commands(self) -> None:
		self._control_handler=None

	@staticmethod
	def _require_subscription_result(operation: str,result: Any) -> None:
		if isinstance(result,tuple) and result and result[0] != mqtt.MQTT_ERR_SUCCESS:
			raise ConnectionError(f"MQTT {operation} failed code={result[0]}")

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
		with self._discovery_lock:
			self._publish_confirmed(self.control_discovery_topic(definition),"",True,"control removal")
			self._control_discovery.pop(definition["key"],None)

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
			"availability":[{"topic":self.availability_topic()},{"topic":self.control_base()+"/availability"},{"topic":f"{self.control_base()}/{key}/availability"}],"availability_mode":"all",
			"device":{"identifiers":[f"deye_solarman_{self._inverter.serial_number}"],"name":self._inverter.name,"manufacturer":self._inverter.manufacturer,"model":self._inverter.model},
		}
		kind=component(definition)
		if kind == "number":
			payload.update(min=result["min"],max=result["max"],step=abs(definition["factor"]),mode=definition.get("mode","box"))
			if definition["unit"]:
				payload["unit_of_measurement"]=definition["unit"]
		elif kind == "select":
			payload["options"]=result.get("options",list(definition.get("options",{}).values()))
		elif kind == "switch":
			payload.update(payload_on="ON",payload_off="OFF")
		else:
			payload.update(min=19,max=19,pattern=r"[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}")
		encoded=json.dumps(payload)
		with self._discovery_lock:
			if self._control_discovery.get(key) != encoded:
				self._publish_confirmed(self.control_discovery_topic(definition),encoded,True,"control discovery")
				self._control_discovery[key]=encoded

	def publish_control_state(self, entry: dict, result: dict) -> None:
		base=f"{self.control_base()}/{entry['key']}"
		retain=self._config.retain and entry["definition"]["retain"]
		result={**result,"transport":entry["definition"]["transport"]}
		# Unknown enum labels are diagnostic attributes, never valid select options.
		if result.get("status") != "unknown":
			self._publish_confirmed(base+"/state",result["value"],retain,"control state")
		self._publish_confirmed(base+"/attributes",json.dumps(result),retain,"control attributes")

	def control_availability(self, key: str, available: bool) -> None:
		self._publish_confirmed(f"{self.control_base()}/{key}/availability","online" if available else "offline",True,"control availability")

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
		with self._session_lock:
			if self._closed:
				raise ConnectionError("MQTT publisher is closed")
			if self._needs_reconnect:
				self._open_session_locked(reconnect=True)
			try:
				info=self._client.publish(topic,payload,retain=retain,qos=1)
				if hasattr(info,"wait_for_publish"):
					info.wait_for_publish(timeout=10)
					if not info.is_published():
						raise ConnectionError(f"MQTT {kind} publish timed out topic={topic}")
			except Exception as error:
				batch=getattr(self._publication_context,"batch",None)
				if batch is not None:
					batch["failed"]+=1
				LOGGER.warning("MQTT publish failed kind=%s topic=%s error=%s",kind,topic,error)
				self._needs_reconnect=True
				try:
					self._client.disconnect()
				finally:
					self._client.loop_stop()
				raise
		batch=getattr(self._publication_context,"batch",None)
		if batch is not None:
			batch["confirmed"]+=1
			batch["kinds"][kind]=batch["kinds"].get(kind,0)+1
