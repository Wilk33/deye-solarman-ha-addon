from __future__ import annotations

import json
import logging
import sys
import tempfile
import threading
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from urllib.request import Request
from urllib.request import urlopen
from urllib.error import HTTPError
from pathlib import Path
from unittest.mock import Mock
from unittest.mock import patch

import yaml


APP_ROOT=Path(__file__).resolve().parents[1]/"packages"
sys.path.insert(0, str(APP_ROOT))

from deye_inverter_core.config import load_config
from deye_inverter_core.configuration_coordinator import ConfigurationCoordinator
from deye_inverter_core.custom_sensors import load_custom_sensors
from deye_inverter_core.custom_sensors import save_custom_sensors
from deye_inverter_core.codec import decode_registers
from deye_inverter_core.codec import registers_to_ascii
from deye_inverter_core.definitions import load_sensor_definitions
from deye_inverter_core.formula import FormulaError
from deye_inverter_core.formula import FormulaExecutor
from deye_inverter_core.main import _handle_sensor
from deye_inverter_core.main import _is_due
from deye_inverter_core.main import SensorRuntime
from deye_inverter_core.main import _test_custom_sensor
from deye_inverter_core.main import run_iteration
from deye_inverter_core.logging_utils import AddonLogFormatter
from deye_inverter_core.logging_utils import SUCCESS
from deye_inverter_core.models import InverterConfig
from deye_inverter_core.models import CatalogConfig
from deye_inverter_core.models import MqttConfig
from deye_inverter_core.models import PollingConfig
from deye_inverter_core.models import SensorDefinition
from deye_inverter_core.models import SensorState
from deye_inverter_core.mqtt import MqttPublisher
from deye_inverter_core.scheduler import group_sensors_for_read
from deye_inverter_core.scan_catalog import ScanCandidate
from deye_inverter_core.scan_catalog import load_scan_candidates
from deye_inverter_core.remote_catalog import RemoteCatalog
from deye_inverter_core.remote_catalog import apply_remote_catalog
from deye_inverter_core.remote_catalog import load_remote_catalog
from deye_inverter_core.control_catalog import load_remote_control_catalog
from deye_inverter_core.supervisor import discover_mqtt_service
from deye_inverter_core.transport import TransportConnectionClosedError as SolarmanConnectionClosedError
from deye_inverter_core.transport_manager import TransportManager
from deye_inverter_core.transport_manager import TransportSlot
from deye_inverter_core.scanner import load_monitored_definitions
from deye_inverter_core.scanner import clear_detected_sensors
from deye_inverter_core.scanner import load_pending_discovery_removals
from deye_inverter_core.scanner import reset_detected_sensors
from deye_inverter_core.scanner import save_detected_sensors
from deye_inverter_core.scanner import scan_candidates
from deye_inverter_core.scanner import update_detected_sensors
from deye_inverter_core.storage import load_state
from deye_inverter_core.storage import save_state
from deye_inverter_core.web import IngressPanel


class FakeMqtt:
	def __init__(self) -> None:
		self.states: list[tuple[str, int | float | str, dict[str, object]]]=[]
		self.raw: list[tuple[str, list[int]]]=[]
		self.availability: list[tuple[str,bool]]=[]

	def publish_state(self, sensor: SensorDefinition, value: int | float | str, attributes: dict[str, object]) -> None:
		self.states.append((sensor.key, value, attributes))

	def publish_raw(self, sensor: SensorDefinition, raw_registers: list[int]) -> None:
		self.raw.append((sensor.key, raw_registers))

	def sensor_availability(self,sensor: SensorDefinition,available: bool) -> None:
		self.availability.append((sensor.key,available))


class FakePahoClient:
	def __init__(self) -> None:
		self.messages: list[tuple[str, object, bool]]=[]

	def publish(self, topic: str, payload: object, retain: bool=False, qos: int=0) -> None:
		self.messages.append((topic, payload, retain))


class FakeSolarman:
	def __init__(self, values: list[int]) -> None:
		self.values=values
		self.calls: list[tuple[int, int]]=[]

	def read_holding_registers(self, register: int, count: int) -> list[int]:
		self.calls.append((register, count))
		return self.values


class FailingSolarman:
	def read_holding_registers(self, register: int, count: int) -> list[int]:
		raise RuntimeError("Modbus exception: illegal data address")


class RegisterSolarman:
	def __init__(self, registers: dict[int,int]) -> None:
		self.registers=registers
		self.calls: list[tuple[int,int]]=[]

	def read_holding_registers(self, register: int, count: int) -> list[int]:
		self.calls.append((register,count))
		return [self.registers[address] for address in range(register,register+count)]


class ClosedSolarman:
	def read_holding_registers(self, register: int, count: int) -> list[int]:
		raise SolarmanConnectionClosedError("Connection already closed")


class RuntimeTransport:
	def __init__(self,transport_id: str,values: dict[int,int] | None=None) -> None:
		self.transport_id=transport_id
		self.values=values or {}
		self.reads=[]
		self.connect_error=None

	def connect(self) -> None:
		if self.connect_error is not None:
			raise self.connect_error

	def reconnect(self) -> None:
		self.connect()

	def close(self) -> None:
		pass

	def read_holding_registers(self,start: int,count: int) -> list[int]:
		self.reads.append((start,count))
		return [self.values.get(register,0) for register in range(start,start+count)]


class RuntimeClock:
	def __init__(self) -> None:
		self.value=0.0

	def __call__(self) -> float:
		return self.value


class FakeSupervisorResponse:
	def __init__(self, payload: dict[str, object]) -> None:
		self._payload=json.dumps(payload).encode("utf-8")

	def __enter__(self) -> "FakeSupervisorResponse":
		return self

	def __exit__(self, exception_type: object, exception: object, traceback: object) -> None:
		return None

	def read(self) -> bytes:
		return self._payload


def make_options(logger_serial_number: int=3556142832) -> dict[str, object]:
	return {
		"logger": {
			"host": "192.168.177.144",
			"port": 8899,
			"serial_number": logger_serial_number,
			"modbus_id": 1,
			"timeout": 3,
			"reconnect_delay": 10,
		},
		"mqtt": {
			"use_supervisor": False,
			"host": "core-mosquitto",
			"port": 1883,
			"username": "",
			"password": "",
			"client_id": "test",
			"base_topic": "deye_solarman",
			"discovery_prefix": "homeassistant",
			"retain": True,
		},
		"inverter": {
			"serial_number": "2507092018",
			"name": "Deye",
			"manufacturer": "Deye",
			"model": "SG05LP3",
		},
		"profiles": {
			"default_profile": "deye_battery_packs",
			"overrides_file": "/config/user_sensors.yaml",
			"state_file": "/config/runtime_state.json",
			"scan_report_file": "/share/report.json",
		},
		"polling": {
			"default_interval": 60,
			"slow_interval": 600,
			"read_message_spacing": 0.05,
			"batch_gap": 1,
			"max_registers_per_request": 20,
			"publish_unchanged_every": 900,
			"startup_probe_register": 10040,
			"startup_probe_count": 1,
			"allow_reconnect": True,
		},
		"advanced": {
			"emit_raw_topics": True,
			"emit_scan_report": True,
		},
	}


def make_polling() -> PollingConfig:
	return PollingConfig(
		default_interval=60,
		slow_interval=600,
		read_message_spacing=0.05,
		batch_gap=1,
		max_registers_per_request=20,
		publish_unchanged_every=900,
		startup_probe_register=10040,
		startup_probe_count=1,
		allow_reconnect=True,
	)


class RuntimeTests(unittest.TestCase):
	def test_panel_configuration_transaction_rolls_back_every_tracked_file(self) -> None:
		from deye_inverter_core.controls import ControlService

		with tempfile.TemporaryDirectory() as directory:
			root=Path(directory)
			detected=root/"detected.yaml"
			custom=root/"custom.yaml"
			queue=root/"deye_solarman_discovery_removals.yaml"
			controls=ControlService(str(root/"controls.json"),None,threading.Lock(),0)
			detected.write_text("detected-before",encoding="utf-8")
			custom.write_text("custom-before",encoding="utf-8")
			panel=IngressPanel(
				str(detected),
				lambda:{},
				custom_sensors_file=str(custom),
				control_service=controls,
			)
			def fail_after_writes():
				detected.write_text("detected-after",encoding="utf-8")
				custom.write_text("custom-after",encoding="utf-8")
				queue.write_text("queued",encoding="utf-8")
				controls.path.write_text("controls-after",encoding="utf-8")
				raise OSError("disk full")

			with self.assertRaisesRegex(OSError,"disk full"):
				panel._configuration_action(fail_after_writes)

			self.assertEqual(detected.read_text(encoding="utf-8"),"detected-before")
			self.assertEqual(custom.read_text(encoding="utf-8"),"custom-before")
			self.assertFalse(queue.exists())
			self.assertFalse(controls.path.exists())

	def test_panel_uses_the_injected_runtime_configuration_coordinator(self) -> None:
		with tempfile.TemporaryDirectory() as directory:
			detected=Path(directory)/"detected.yaml"
			coordinator=ConfigurationCoordinator([detected])

			panel=IngressPanel(
				str(detected),
				lambda:{},
				configuration_coordinator=coordinator,
			)

			self.assertIs(panel._configuration,coordinator)

	def test_runtime_discovery_ack_does_not_clear_a_concurrent_panel_queue_update(self) -> None:
		from deye_inverter_core import main as runtime_main
		from deye_inverter_core.scanner import _queue_discovery_removal_keys

		with tempfile.TemporaryDirectory() as directory:
			root=Path(directory)
			detected=root/"detected.yaml"
			custom=root/"custom.yaml"
			queue_path=root/"deye_solarman_discovery_removals.yaml"
			_queue_discovery_removal_keys(detected,{"old_sensor"})
			coordinator=ConfigurationCoordinator([detected,custom,queue_path])
			started=threading.Event()
			release=threading.Event()
			updated=threading.Event()
			class BlockingMqtt:
				@contextmanager
				def discovery_transaction(self):
					yield

				def remove_discovery(self,key):
					started.set()
					if not release.wait(5):
						raise TimeoutError("test did not release discovery")

			config=SimpleNamespace(
				scan=SimpleNamespace(detected_sensors_file=str(detected)),
				profiles=SimpleNamespace(custom_sensors_file=str(custom)),
			)
			publisher=threading.Thread(target=lambda:runtime_main._publish_sensor_configuration(
				config,
				BlockingMqtt(),
				[],
				{},
				reset_state=False,
				configuration_coordinator=coordinator,
			))
			def update_queue():
				coordinator.apply(lambda:_queue_discovery_removal_keys(detected,{"new_sensor"}))
				updated.set()

			publisher.start()
			self.assertTrue(started.wait(5))
			writer=threading.Thread(target=update_queue)
			writer.start()
			self.assertFalse(updated.wait(0.1))
			release.set()
			publisher.join(5)
			writer.join(5)

			self.assertEqual(load_pending_discovery_removals(str(detected)),["new_sensor"])

	def test_runtime_discovery_rollback_finishes_before_a_concurrent_panel_update(self) -> None:
		from deye_inverter_core import main as runtime_main
		from deye_inverter_core.scanner import _queue_discovery_removal_keys

		with tempfile.TemporaryDirectory() as directory:
			root=Path(directory)
			detected=root/"detected.yaml"
			custom=root/"custom.yaml"
			queue_path=root/"deye_solarman_discovery_removals.yaml"
			_queue_discovery_removal_keys(detected,{"old_sensor"})
			coordinator=ConfigurationCoordinator([detected,custom,queue_path])
			started=threading.Event()
			release=threading.Event()
			updated=threading.Event()
			errors=[]
			class FailingMqtt:
				@contextmanager
				def discovery_transaction(self):
					yield

				def remove_discovery(self,key):
					started.set()
					if not release.wait(5):
						raise TimeoutError("test did not release discovery")
					raise ConnectionError("broker unavailable")

			config=SimpleNamespace(
				scan=SimpleNamespace(detected_sensors_file=str(detected)),
				profiles=SimpleNamespace(custom_sensors_file=str(custom)),
			)
			def publish():
				try:
					coordinator.apply(lambda:runtime_main._publish_sensor_configuration(
						config,
						FailingMqtt(),
						[],
						{},
						reset_state=False,
					))
				except Exception as error:
					errors.append(error)
			def update_queue():
				coordinator.apply(lambda:_queue_discovery_removal_keys(detected,{"new_sensor"}))
				updated.set()

			publisher=threading.Thread(target=publish)
			publisher.start()
			self.assertTrue(started.wait(5))
			writer=threading.Thread(target=update_queue)
			writer.start()
			self.assertFalse(updated.wait(0.1))
			release.set()
			publisher.join(5)
			writer.join(5)

			self.assertEqual(len(errors),1)
			self.assertIsInstance(errors[0],ConnectionError)
			self.assertEqual(load_pending_discovery_removals(str(detected)),["new_sensor","old_sensor"])

	def test_runtime_configuration_retries_and_orders_offline_before_reload_and_handler_activation(self) -> None:
		from deye_inverter_core import main as runtime_main
		from deye_inverter_core.controls import ControlService

		with tempfile.TemporaryDirectory() as directory:
			root=Path(directory)
			detected=root/"detected.yaml"
			custom=root/"custom.yaml"
			controls=ControlService(str(root/"controls.json"),None,threading.Lock(),0)
			coordinator=ConfigurationCoordinator([detected,custom,controls.path])
			events=[]
			class RetryMqtt:
				def __init__(self):
					self.handler="old-handler"
					self.configure_attempts=0

				def disable_control_commands(self):
					self.handler=None
					events.append("disable")

				@contextmanager
				def discovery_transaction(self):
					yield

				def publish_discovery(self,sensor):
					events.append("discovery")

				def sensor_availability(self,sensor,available):
					events.append("offline" if not available else "online")

				def configure_controls(self,handler,keys):
					self.configure_attempts+=1
					events.append("activate")
					if self.configure_attempts == 1:
						raise ConnectionError("subscribe failed")
					self.handler=handler

				def remove_control_discovery(self,definition):
					pass

			class SensorRuntimeProbe:
				def reload(self,sensors, *, reset_state=False):
					events.append("reload")
			sensor=SensorDefinition("value","Value",[100],"uint16",transport="modbus_rtu")
			config=SimpleNamespace(
				scan=SimpleNamespace(detected_sensors_file=str(detected)),
				profiles=SimpleNamespace(custom_sensors_file=str(custom)),
			)
			mqtt=RetryMqtt()

			with patch.object(runtime_main,"_load_runtime_sensors",return_value=[sensor]),patch.object(
				runtime_main.time,
				"sleep",
			):
				control_runtime=runtime_main._apply_runtime_configuration_until_success(
					config,
					mqtt,
					SensorRuntimeProbe(),
					{},
					coordinator,
					Mock(),
					controls,
					reset_state=True,
				)

			self.assertEqual(mqtt.configure_attempts,2)
			self.assertIsNotNone(control_runtime)
			self.assertIsNotNone(mqtt.handler)
			self.assertGreaterEqual(events.count("disable"),2)
			last_offline=max(index for index,event in enumerate(events) if event == "offline")
			last_activate=max(index for index,event in enumerate(events) if event == "activate")
			last_reload=max(index for index,event in enumerate(events) if event == "reload")
			self.assertLess(last_offline,last_activate)
			self.assertLess(last_activate,last_reload)

	def test_confirmed_control_discovery_survives_failed_next_publish_and_can_be_removed(self) -> None:
		from deye_inverter_core import main as runtime_main
		from deye_inverter_core.controls import ControlService

		class StopRetry(BaseException):
			pass

		with tempfile.TemporaryDirectory() as directory:
			root=Path(directory)
			detected=root/"detected.yaml"
			custom=root/"custom.yaml"
			controls=ControlService(str(root/"controls.json"),None,threading.Lock(),0)
			first=controls.entry("control_inverter_enabled")
			second=controls.entry("control_off_grid_mode")
			for entry in (first,second):
				entry["monitor"]=True
				entry["last_scan"]={"status":"supported"}
			controls.store({"available_sensors":[first,second],"published":[]})
			coordinator=ConfigurationCoordinator([detected,custom,controls.path])
			controls.configuration_coordinator=coordinator
			controls.configuration_action=coordinator.apply
			manager=TransportManager([TransportSlot(
				RuntimeTransport("solarman_tcp",{80:1,179:0}),
				make_polling(),
				10,
			)])
			config=SimpleNamespace(
				scan=SimpleNamespace(detected_sensors_file=str(detected)),
				profiles=SimpleNamespace(custom_sensors_file=str(custom)),
			)
			class PartialMqtt:
				def __init__(self):
					self.publish_calls=0
					self.removed=[]

				def disable_control_commands(self):
					pass

				@contextmanager
				def discovery_transaction(self):
					yield

				def publish_control_discovery(self,entry,result):
					self.publish_calls+=1
					if self.publish_calls == 2:
						raise ConnectionError("second retained publish failed")
					if self.publish_calls == 3:
						raise StopRetry()

				def remove_control_discovery(self,definition):
					self.removed.append(definition["key"])

				def publish_control_state(self,entry,result):
					pass

				def control_availability(self,key,available):
					pass

				def configure_controls(self,handler,keys):
					pass

				def publish_discovery(self,sensor):
					pass

				def sensor_availability(self,sensor,available):
					pass

			class SensorRuntimeProbe:
				def reload(self,sensors, *, reset_state=False):
					pass
			mqtt=PartialMqtt()

			with patch.object(runtime_main,"_load_runtime_sensors",return_value=[]),patch.object(
				runtime_main.time,
				"sleep",
			):
				with self.assertRaises(StopRetry):
					runtime_main._apply_runtime_configuration_until_success(
						config,
						mqtt,
						SensorRuntimeProbe(),
						{},
						coordinator,
						manager,
						controls,
						reset_state=True,
					)

			self.assertEqual(controls.load()["published"],[first["key"]])
			self.assertEqual(controls.load()["pending_published"],[second["key"]])
			data=controls.load()
			for entry in data["available_sensors"]:
				entry["monitor"]=False
			controls.store(data)
			mqtt.publish_calls=3
			with patch.object(runtime_main,"_load_runtime_sensors",return_value=[]):
				runtime_main._apply_runtime_configuration_until_success(
					config,
					mqtt,
					SensorRuntimeProbe(),
					{},
					coordinator,
					manager,
					controls,
					reset_state=True,
				)

			self.assertEqual(mqtt.removed,[first["key"],second["key"]])
			self.assertEqual(controls.load()["published"],[])
			self.assertEqual(controls.load()["pending_published"],[])

	def test_worker_iteration_marks_each_group_and_formula_before_physical_read(self) -> None:
		events=[]
		class OrderedTransport(RuntimeTransport):
			def read_holding_registers(self,start: int,count: int) -> list[int]:
				events.append(("read",start,count))
				return super().read_holding_registers(start,count)
		sensors=[
			SensorDefinition("first","First",[10],"uint16",transport="modbus_rtu"),
			SensorDefinition("second","Second",[20],"uint16",transport="modbus_rtu"),
			SensorDefinition("formula","Formula",[],"auto",formula="return RAW(R30)",transport="modbus_rtu"),
		]
		state={sensor.key:SensorState() for sensor in sensors}
		transport=OrderedTransport("modbus_rtu",{10:1,20:2,30:3})

		run_iteration(
			sensors,
			state,
			transport,
			FakeMqtt(),
			make_polling(),
			False,
			force=True,
			mark_attempted=lambda keys:events.append(("attempt",tuple(keys))),
		)

		self.assertEqual(events,[
			("attempt",("first",)),("read",10,1),
			("attempt",("second",)),("read",20,1),
			("attempt",("formula",)),("read",30,1),
		])

	def test_sensor_runtime_keeps_workers_independent_and_honors_one_second_deadline(self) -> None:
		clock=RuntimeClock()
		solarman=RuntimeTransport("solarman_tcp")
		solarman.connect_error=SolarmanConnectionClosedError("logger offline")
		rs485=RuntimeTransport("modbus_rtu",{100:7})
		polling=make_polling()
		manager=TransportManager([
			TransportSlot(solarman,polling,10),
			TransportSlot(rs485,polling,10),
		],clock=clock)
		sensors=[
			SensorDefinition("logger","Logger",[100],"uint16",read_every=1,transport="solarman_tcp"),
			SensorDefinition("serial","Serial",[100],"uint16",read_every=1,transport="modbus_rtu"),
		]
		mqtt=FakeMqtt()
		runtime=SensorRuntime(manager,mqtt,sensors,{sensor.key:SensorState() for sensor in sensors},clock=clock)
		workers=dict(runtime._workers)

		runtime.run_once("solarman_tcp",clock())
		runtime.run_once("modbus_rtu",clock())
		runtime.reload(sensors)
		self.assertEqual(runtime._workers,workers)
		clock.value=0.5
		self.assertIsNone(runtime.run_once("modbus_rtu",clock()))
		clock.value=1.0
		runtime.run_once("modbus_rtu",clock())

		self.assertEqual(runtime.worker_ids,("solarman_tcp","modbus_rtu"))
		self.assertEqual(rs485.reads,[(100,1),(100,1)])
		self.assertEqual([state[0] for state in mqtt.states],["serial","serial"])
		self.assertIn(("logger",False),mqtt.availability)
		self.assertNotIn(("serial",False),mqtt.availability)

	def test_sensor_runtime_discards_stale_read_after_definition_reload(self) -> None:
		started=threading.Event()
		release=threading.Event()
		class BlockingTransport(RuntimeTransport):
			def read_holding_registers(self,start: int,count: int) -> list[int]:
				self.reads.append((start,count))
				if start == 100:
					started.set()
					self.assert_release()
				return [self.values.get(register,0) for register in range(start,start+count)]

			def assert_release(self) -> None:
				if not release.wait(5):
					raise TimeoutError("test did not release transport")

		clock=RuntimeClock()
		transport=BlockingTransport("modbus_rtu",{100:11,101:22})
		manager=TransportManager([TransportSlot(transport,make_polling(),10)],clock=clock)
		old=SensorDefinition("value","Value",[100],"uint16",read_every=1,transport="modbus_rtu")
		updated=SensorDefinition("value","Value",[101],"uint16",read_every=1,transport="modbus_rtu")
		mqtt=FakeMqtt()
		state={"value":SensorState()}
		runtime=SensorRuntime(manager,mqtt,[old],state,clock=clock)
		worker=threading.Thread(target=lambda:runtime.run_once("modbus_rtu",clock()))

		worker.start()
		self.assertTrue(started.wait(5))
		runtime.reload([updated])
		release.set()
		worker.join(5)

		self.assertEqual(mqtt.states,[])
		runtime.run_once("modbus_rtu",clock())
		self.assertEqual([(key,value) for key,value,_ in mqtt.states],[("value",22)])
		self.assertEqual(state["value"].last_value,22)

	def test_sensor_runtime_persistence_failure_does_not_escape_or_mark_transport_offline(self) -> None:
		clock=RuntimeClock()
		transport=RuntimeTransport("modbus_rtu",{100:7})
		manager=TransportManager([TransportSlot(transport,make_polling(),10)],clock=clock)
		sensor=SensorDefinition("value","Value",[100],"uint16",read_every=1,transport="modbus_rtu")
		mqtt=FakeMqtt()
		runtime=SensorRuntime(
			manager,
			mqtt,
			[sensor],
			{"value":SensorState()},
			state_file="ignored.json",
			scan_report_file="ignored-report.json",
			emit_scan_report=True,
			clock=clock,
		)

		with patch("deye_inverter_core.main.save_state",side_effect=OSError("disk full")),patch(
			"deye_inverter_core.main.save_scan_report",
			side_effect=OSError("disk full"),
		):
			first=runtime.run_once("modbus_rtu",clock())
			clock.value=1.0
			second=runtime.run_once("modbus_rtu",clock())

		self.assertIsNotNone(first)
		self.assertIsNotNone(second)
		self.assertEqual(transport.reads,[(100,1),(100,1)])
		self.assertNotIn(("value",False),mqtt.availability)

	def test_sensor_runtime_commits_timeout_state_when_the_whole_batch_raises(self) -> None:
		class TimeoutTransport(RuntimeTransport):
			def read_holding_registers(self,start: int,count: int) -> list[int]:
				self.reads.append((start,count))
				raise TimeoutError("device timeout")
		transport=TimeoutTransport("modbus_rtu")
		manager=TransportManager([TransportSlot(transport,make_polling(),10)])
		sensor=SensorDefinition("value","Value",[100],"uint16",transport="modbus_rtu")
		state={"value":SensorState()}
		runtime=SensorRuntime(manager,FakeMqtt(),[sensor],state)

		runtime.run_once("modbus_rtu")

		self.assertEqual(state["value"].last_status,"timeout")
		self.assertEqual(state["value"].timeout_count,1)
		self.assertEqual(runtime._reports["modbus_rtu"][0]["status"],"timeout")

	def test_sensor_runtime_commits_partial_current_generation_before_connection_error(self) -> None:
		class PartialTransport(RuntimeTransport):
			def read_holding_registers(self,start: int,count: int) -> list[int]:
				self.reads.append((start,count))
				if start == 20:
					raise SolarmanConnectionClosedError("connection lost")
				return [7]
		transport=PartialTransport("modbus_rtu")
		manager=TransportManager([TransportSlot(transport,make_polling(),10)])
		first=SensorDefinition("first","First",[10],"uint16",transport="modbus_rtu")
		second=SensorDefinition("second","Second",[20],"uint16",transport="modbus_rtu")
		state={"first":SensorState(),"second":SensorState()}
		runtime=SensorRuntime(manager,FakeMqtt(),[first,second],state)

		runtime.run_once("modbus_rtu")

		self.assertEqual(state["first"].last_value,7)
		self.assertEqual(state["first"].last_status,"supported")
		self.assertEqual(state["second"].last_status,"never_read")
		self.assertEqual([item["sensor"] for item in runtime._reports["modbus_rtu"]],["first"])

	def test_sensor_worker_survives_mqtt_publish_failure_and_runs_next_deadline(self) -> None:
		class FlakyMqtt(FakeMqtt):
			def __init__(self):
				super().__init__()
				self.attempts=0
				self.recovered=threading.Event()

			def publish_state(self,sensor,value,attributes):
				self.attempts+=1
				if self.attempts == 1:
					raise ConnectionError("broker dropped session")
				super().publish_state(sensor,value,attributes)
				self.recovered.set()

		transport=RuntimeTransport("modbus_rtu",{100:7})
		polling=make_polling()
		manager=TransportManager([TransportSlot(transport,polling,10)])
		sensor=SensorDefinition("value","Value",[100],"uint16",read_every=0.05,transport="modbus_rtu")
		mqtt=FlakyMqtt()
		runtime=SensorRuntime(manager,mqtt,[sensor],{"value":SensorState()})

		runtime.start()
		try:
			self.assertTrue(mqtt.recovered.wait(2))
		finally:
			runtime.stop()

		self.assertGreaterEqual(mqtt.attempts,2)

	def test_sensor_runtime_persists_an_isolated_state_snapshot(self) -> None:
		transport=RuntimeTransport("modbus_rtu",{100:7})
		manager=TransportManager([TransportSlot(transport,make_polling(),10)])
		sensor=SensorDefinition("value","Value",[100],"uint16",transport="modbus_rtu")
		state={"value":SensorState()}
		runtime=SensorRuntime(manager,FakeMqtt(),[sensor],state,state_file="ignored.json")
		captured=[]

		with patch("deye_inverter_core.main.save_state",side_effect=lambda path,payload:captured.append(payload)):
			runtime.run_once("modbus_rtu")

		self.assertIsNot(captured[0],state)
		self.assertIsNot(captured[0]["value"],state["value"])

	def test_iteration_stop_signal_prevents_starting_later_read_groups(self) -> None:
		stop=threading.Event()
		class StopAfterFirst(RuntimeTransport):
			def read_holding_registers(self,start: int,count: int) -> list[int]:
				result=super().read_holding_registers(start,count)
				stop.set()
				return result
		transport=StopAfterFirst("modbus_rtu",{10:1,20:2})
		sensors=[
			SensorDefinition("first","First",[10],"uint16",transport="modbus_rtu"),
			SensorDefinition("second","Second",[20],"uint16",transport="modbus_rtu"),
		]

		run_iteration(
			sensors,
			{sensor.key:SensorState() for sensor in sensors},
			transport,
			FakeMqtt(),
			make_polling(),
			False,
			force=True,
			should_stop=stop.is_set,
		)

		self.assertEqual(transport.reads,[(10,1)])

	def test_sensor_runtime_stop_waits_for_every_worker_without_timeout(self) -> None:
		transport=RuntimeTransport("modbus_rtu")
		manager=TransportManager([TransportSlot(transport,make_polling(),10)])
		runtime=SensorRuntime(manager,FakeMqtt(),[],{})
		joins=[]
		class ThreadProbe:
			def join(self,timeout=None):
				joins.append(timeout)
		runtime._threads=[ThreadProbe()]

		runtime.stop()

		self.assertEqual(joins,[None])

	def test_sensor_worker_consumes_wake_before_each_runtime_cycle(self) -> None:
		transport=RuntimeTransport("modbus_rtu")
		manager=TransportManager([TransportSlot(transport,make_polling(),10)])
		runtime=SensorRuntime(manager,FakeMqtt(),[],{})
		events=[]
		class WakeProbe:
			def clear(self):
				events.append("clear")

			def wait(self,timeout=None):
				events.append("wait")
				return True

			def set(self):
				events.append("set")
		runtime._wake["modbus_rtu"]=WakeProbe()
		def run_once(transport_id):
			events.append("run")
			if events.count("run") == 2:
				runtime._stop.set()
		runtime.run_once=run_once

		runtime._worker_loop("modbus_rtu")

		self.assertEqual(events,["clear","run","wait","clear","run"])

	def test_panel_stop_waits_for_manual_sensor_scan(self) -> None:
		started=threading.Event()
		release=threading.Event()
		stopped=threading.Event()
		def scan():
			started.set()
			if not release.wait(5):
				raise TimeoutError("test did not release sensor scan")
			return {}
		panel=IngressPanel("unused.yaml",scan,port=0)
		panel.start()
		try:
			self.assertTrue(panel._start_scan())
			self.assertTrue(started.wait(5))
			stopper=threading.Thread(target=lambda:(panel.stop(),stopped.set()))
			stopper.start()
			self.assertFalse(stopped.wait(0.75))
			release.set()
			stopper.join(5)
			self.assertTrue(stopped.is_set())
		finally:
			release.set()
			panel.stop()

	def test_panel_stop_waits_for_active_http_sensor_test(self) -> None:
		started=threading.Event()
		release=threading.Event()
		stopped=threading.Event()
		def custom_test(definition):
			started.set()
			if not release.wait(5):
				raise TimeoutError("test did not release HTTP test")
			return {"value":1}
		with tempfile.TemporaryDirectory() as directory:
			panel=IngressPanel(
				str(Path(directory)/"detected.yaml"),
				lambda:{},
				custom_sensors_file=str(Path(directory)/"custom.yaml"),
				custom_test_handler=custom_test,
				port=0,
			)
			panel.start()
			port=panel._server.server_address[1]
			request=Request(
				f"http://127.0.0.1:{port}/api/custom-sensors/test",
				data=b'{"definition":{}}',
				headers={"Content-Type":"application/json"},
				method="POST",
			)
			request_thread=threading.Thread(target=lambda:urlopen(request).read())
			request_thread.start()
			try:
				self.assertTrue(started.wait(5))
				stopper=threading.Thread(target=lambda:(panel.stop(),stopped.set()))
				stopper.start()
				self.assertFalse(stopped.wait(0.75))
				release.set()
				request_thread.join(5)
				stopper.join(5)
				self.assertTrue(stopped.is_set())
			finally:
				release.set()
				panel.stop()

	def test_custom_sensor_test_reads_only_its_selected_transport(self) -> None:
		solarman=RuntimeTransport("solarman_tcp",{10040:11})
		rs485=RuntimeTransport("modbus_rtu",{10040:37})
		manager=TransportManager([
			TransportSlot(solarman,make_polling(),10),
			TransportSlot(rs485,make_polling(),10),
		])
		definition={
			"key":"custom_voltage",
			"name":"Custom voltage",
			"registers":[10040],
			"type":"uint16",
			"transport":"modbus_rtu",
			"transports":["solarman_tcp","modbus_rtu"],
		}

		result=_test_custom_sensor(manager,definition)

		self.assertEqual(result["value"],37)
		self.assertEqual(result["transport"],"modbus_rtu")
		self.assertEqual(solarman.reads,[])
		self.assertEqual(rs485.reads,[(10040,1)])

	def test_custom_status_sensor_decodes_enum_and_bitmask_without_writing(self) -> None:
		manager=TransportManager([
			TransportSlot(RuntimeTransport("solarman_tcp",{500:2,552:5}),make_polling(),10),
		])

		run_state=_test_custom_sensor(manager,{
			"key":"custom_run_state",
			"registers":[500],
			"type":"enum",
			"options":{"0":"Standby","2":"Normal"},
			"unknown":"Unknown ({value})",
			"transport":"solarman_tcp",
			"transports":["solarman_tcp"],
		})
		relays=_test_custom_sensor(manager,{
			"key":"custom_relays",
			"registers":[552],
			"type":"bitmask",
			"options":{"0":"Inverter relay","2":"Grid connected"},
			"zero":"All relays off",
			"unknown":"Bit {bit}",
			"transport":"solarman_tcp",
			"transports":["solarman_tcp"],
		})

		self.assertEqual(run_state["value"],"Normal")
		self.assertEqual(relays["value"],"Inverter relay, Grid connected")
		self.assertEqual(run_state["raw_registers"],[2])
		self.assertEqual(relays["raw_registers"],[5])
	def test_formula_sensor_and_raw_decode_direct_registers(self) -> None:
		registers={587:5420,591:65536-238}
		executor=FormulaExecutor(lambda address,count: [registers[index] for index in range(address,address+count)])
		result=executor.execute(
			"voltage=sensor(R587,uint16,0.01)\n"
			"current=sensor(R591,int16,0.01)\n"
			"raw_current=RAW(R591)\n"
			"return round(abs(voltage*current)+raw_current*0,3)"
		)

		self.assertEqual(result.value,128.996)
		self.assertEqual([read.address for read in result.reads],[587,591,591])
		self.assertEqual(result.reads[1].value,-2.38)
		self.assertEqual(result.reads[2].register_type,"raw")

	def test_formula_supports_local_function_if_match_and_limited_for(self) -> None:
		registers={10040:1,10041:2,10042:3}
		executor=FormulaExecutor(lambda address,count: [registers[index] for index in range(address,address+count)])
		result=executor.execute(
			"def scale(value):\n"
			"\treturn value*2\n"
			"total=0\n"
			"for address in range(10040,10043):\n"
			"\ttotal+=RAW(address)\n"
			"match total:\n"
			"\tcase 6:\n"
			"\t\treturn scale(total)\n"
			"\tcase _:\n"
			"\t\treturn 0"
		)

		self.assertEqual(result.value,12)

	def test_formula_supports_raw_bitwise_checks_and_word_order_symbol(self) -> None:
		registers={500:3,504:2,505:0}
		executor=FormulaExecutor(lambda address,count: [registers[index] for index in range(address,address+count)])
		result=executor.execute(
			"raw_status=RAW(R500)\n"
			"energy=sensor(R504,uint32,0.1,0,low_high)\n"
			"if raw_status & 1:\n"
			"\treturn energy\n"
			"return None"
		)

		self.assertEqual(result.value,0.2)

	def test_formula_sensor_supports_ascii_byte_order(self) -> None:
		registers={10032:0x3530,10033:0x3034}
		executor=FormulaExecutor(lambda address,count: [registers[index] for index in range(address,address+count)])
		result=executor.execute("return sensor(R10032,ascii,1,0,high_low,low_high)")

		self.assertEqual(result.value,"05")
		self.assertEqual(result.reads[0].byte_order,"low_high")

	def test_formula_rejects_unsafe_or_unbounded_syntax(self) -> None:
		for source in [
			"import os\nreturn 1",
			"while True:\n\treturn 1\nreturn 0",
			"return __import__('os')",
			"for index in range(65):\n\tpass\nreturn 0",
		]:
			with self.assertRaises(FormulaError):
				FormulaExecutor(lambda address,count: [0]*count).execute(source)

	def test_custom_formula_persistence_and_runtime_publication(self) -> None:
		with tempfile.TemporaryDirectory() as directory:
			custom_path=Path(directory) / "custom_sensors.yaml"
			saved=save_custom_sensors(
				str(custom_path),
				[
					{
						"key": "battery_1_apparent_power",
						"monitor": True,
						"definition": {
							"key": "battery_1_apparent_power",
							"name": "Battery 1 Apparent Power",
							"registers": [],
							"type": "auto",
							"unit": "VA",
							"read_every": 60,
							"report_every": 300,
							"change_by": 0,
							"topic_suffix": "battery_1_apparent_power",
							"formula": "return abs(sensor(R587,uint16,0.01)*sensor(R591,int16,0.01))",
						},
					}
				],
			)
			self.assertEqual(saved["sensors"][0]["definition"]["type"],"auto")
			self.assertEqual(load_custom_sensors(str(custom_path))["sensors"][0]["key"],"battery_1_apparent_power")
			sensors=load_sensor_definitions(["deye_battery_packs"],str(Path(directory) / "user_sensors.yaml"),None,str(custom_path))
			formula_sensor=next(sensor for sensor in sensors if sensor.key == "battery_1_apparent_power")
			mqtt=FakeMqtt()
			run_iteration(
				[formula_sensor],
				{formula_sensor.key: SensorState()},
				RegisterSolarman({587:5420,591:65536-238}),
				mqtt,
				make_polling(),
				True,
			)

			self.assertEqual(mqtt.states[0][0],"battery_1_apparent_power")
			self.assertEqual(mqtt.states[0][1],128.996)
			self.assertEqual(mqtt.states[0][2]["type"],"auto")

	def test_empty_custom_sensor_file_is_a_valid_startup_state(self) -> None:
		with tempfile.TemporaryDirectory() as directory:
			custom_path=Path(directory) / "custom_sensors.yaml"
			custom_path.write_text("version: 1\nsensors: []\n",encoding="utf-8")

			sensors=load_sensor_definitions(
				["deye_battery_packs"],
				str(Path(directory) / "user_sensors.yaml"),
				None,
				str(custom_path),
			)

			self.assertTrue(sensors)
			self.assertTrue(all(sensor.enabled is False for sensor in sensors))

	def test_ingress_panel_manages_and_tests_custom_sensors(self) -> None:
		with tempfile.TemporaryDirectory() as directory:
			detected_path=Path(directory) / "detected_sensors.yaml"
			custom_path=Path(directory) / "custom_sensors.yaml"
			configuration_changes=[]
			test_requests=[]
			panel=IngressPanel(
				str(detected_path),
				lambda: {"count": 0},
				configuration_changed_handler=lambda: configuration_changes.append(True),
				custom_sensors_file=str(custom_path),
				custom_test_handler=lambda definition: test_requests.append(definition) or {"value": 12,"reads": []},
				port=0,
			)
			panel.start()
			try:
				assert panel._server is not None
				address=f"http://127.0.0.1:{panel._server.server_address[1]}"
				entry={
					"key": "custom_raw_status",
					"monitor": True,
					"definition": {
						"key": "custom_raw_status",
						"name": "Custom Raw Status",
						"registers": [],
						"type": "auto",
						"read_every": 60,
						"report_every": 300,
						"change_by": 0,
						"formula": "return RAW(R500)",
					},
				}
				request=Request(
					f"{address}/api/custom-sensors",
					data=json.dumps({"sensors": [entry]}).encode("utf-8"),
					headers={"Content-Type": "application/json"},
					method="POST",
				)
				with urlopen(request) as response:
					saved=json.loads(response.read())
				self.assertEqual(saved["sensors"][0]["definition"]["type"],"auto")
				self.assertEqual(len(configuration_changes),1)

				request=Request(
					f"{address}/api/custom-sensors/test",
					data=json.dumps({"definition": entry["definition"]}).encode("utf-8"),
					headers={"Content-Type": "application/json"},
					method="POST",
				)
				with urlopen(request) as response:
					self.assertEqual(json.loads(response.read())["value"],12)
				self.assertEqual(test_requests[0]["key"],"custom_raw_status")

				request=Request(f"{address}/api/custom-sensors/custom_raw_status",method="DELETE")
				with urlopen(request) as response:
					self.assertEqual(json.loads(response.read())["sensors"],[])
				self.assertEqual(len(configuration_changes),2)
			finally:
				panel.stop()

	def test_ingress_panel_serves_safe_polish_and_english_i18n_with_language_precedence(self) -> None:
		with tempfile.TemporaryDirectory() as directory:
			panel=IngressPanel(str(Path(directory)/"detected.yaml"),lambda:{},port=0)
			panel.start()
			try:
				assert panel._server is not None
				address=f"http://127.0.0.1:{panel._server.server_address[1]}"
				for language,expected in (("pl","Sensory"),("pl-PL","Sensory"),("en","Sensors"),("en-US","Sensors"),("de","Sensory")):
					with self.subTest(language=language),urlopen(f"{address}/api/i18n/{language}") as response:
						payload=json.loads(response.read())
						self.assertEqual(response.headers.get_content_type(),"application/json")
						self.assertEqual(response.headers["Cache-Control"],"no-store")
						self.assertEqual(payload["translations"]["tabs.sensors"],expected)
				with urlopen(f"{address}/?lang=en-US") as response:
					self.assertIn('data-language="en"',response.read().decode("utf-8"))
				with urlopen(Request(f"{address}/",headers={"Accept-Language":"en-US,en;q=0.9"})) as response:
					self.assertIn('data-language="en"',response.read().decode("utf-8"))
				with self.assertRaises(HTTPError) as context:
					urlopen(f"{address}/api/i18n/%2e%2e%2fpl")
				self.assertEqual(context.exception.code,404)
			finally:
				panel.stop()

	def test_ingress_panel_reports_both_transport_runtime_states(self) -> None:
		statuses=lambda:{
			"transports":[
				{"id":"solarman_tcp","online":True,"latency_ms":12.5,"last_error":None,"error_count":0,"next_reconnect_at":0.0},
				{"id":"modbus_rtu","online":False,"latency_ms":4.25,"last_error":"disconnected","error_count":2,"next_reconnect_at":10.0},
			]
		}
		with tempfile.TemporaryDirectory() as directory:
			panel=IngressPanel(
				str(Path(directory)/"detected.yaml"),
				lambda:{},
				transport_status_handler=statuses,
				port=0,
			)
			panel.start()
			try:
				assert panel._server is not None
				address=f"http://127.0.0.1:{panel._server.server_address[1]}"
				with urlopen(f"{address}/api/runtime") as response:
					payload=json.loads(response.read())
				self.assertEqual([item["id"] for item in payload["transports"]],["solarman_tcp","modbus_rtu"])
				self.assertEqual(payload["transports"][1]["last_error"],"disconnected")
				self.assertEqual(payload["transports"][0]["latency_ms"],12.5)
			finally:
				panel.stop()

	def test_custom_sensor_http_test_runs_both_transports_sequentially(self) -> None:
		calls=[]
		def custom_test(definition):
			calls.append(definition["transport"])
			return {"transport":definition["transport"],"value":len(calls)}
		with tempfile.TemporaryDirectory() as directory:
			panel=IngressPanel(
				str(Path(directory)/"detected.yaml"),
				lambda:{},
				custom_sensors_file=str(Path(directory)/"custom.yaml"),
				custom_test_handler=custom_test,
				port=0,
			)
			panel.start()
			try:
				assert panel._server is not None
				address=f"http://127.0.0.1:{panel._server.server_address[1]}"
				definition={
					"key":"custom_voltage",
					"registers":[10040],
					"type":"uint16",
					"transport":"modbus_rtu",
					"transports":["solarman_tcp","modbus_rtu"],
				}
				request=Request(
					f"{address}/api/custom-sensors/test",
					data=json.dumps({"definition":definition,"transports":["modbus_rtu","solarman_tcp"]}).encode("utf-8"),
					headers={"Content-Type":"application/json"},
					method="POST",
				)
				with urlopen(request) as response:
					payload=json.loads(response.read())
				self.assertEqual(calls,["solarman_tcp","modbus_rtu"])
				self.assertEqual([result["transport"] for result in payload["results"]],["solarman_tcp","modbus_rtu"])
			finally:
				panel.stop()

	def test_config_keeps_builtin_battery_profile_enabled(self) -> None:
		options=make_options()
		options["profiles"]["default_profile"]=[]
		with tempfile.TemporaryDirectory() as directory:
			options_path=Path(directory) / "options.json"
			options_path.write_text(json.dumps(options), encoding="utf-8")
			config=load_config(options_path)

		self.assertEqual(config.profiles.default_profile, ["deye_battery_packs"])
		self.assertEqual(config.scan.mode, "disabled")
		self.assertFalse(config.advanced.detailed_logs)

	def test_config_enables_detailed_logs_explicitly(self) -> None:
		options=make_options()
		options["advanced"]["detailed_logs"]=True
		with tempfile.TemporaryDirectory() as directory:
			options_path=Path(directory) / "options.json"
			options_path.write_text(json.dumps(options), encoding="utf-8")
			config=load_config(options_path)

		self.assertTrue(config.advanced.detailed_logs)

	def test_config_loads_flat_visible_sections_and_persisted_switches(self) -> None:
		options=make_options()
		for section in ("inverter","profiles","advanced","scan"):
			options.pop(section,None)
		options.update({
			"inverter_serial_number":"998877",
			"inverter_name":"Flat inverter",
			"inverter_manufacturer":"Deye",
			"inverter_model":"SG05LP3",
			"default_profile":[],
			"overrides_file":"/config/flat-overrides.yaml",
			"custom_sensors_file":"/config/flat-custom.yaml",
			"state_file":"/config/flat-state.json",
			"scan_report_file":"/share/flat-report.json",
			"emit_raw_topics":False,
			"emit_scan_report":False,
			"detailed_logs":True,
			"scan_mode":"scan_only",
			"scan_candidate_report_file":"/share/flat-scan.json",
			"detected_sensors_file":"/config/flat-detected.yaml",
			"bms_pack_count":3,
		})
		with tempfile.TemporaryDirectory() as directory:
			options_path=Path(directory)/"options.json"
			options_path.write_text(json.dumps(options),encoding="utf-8")
			config=load_config(options_path)

		self.assertEqual(config.inverter.serial_number,"998877")
		self.assertEqual(config.profiles.custom_sensors_file,"/config/flat-custom.yaml")
		self.assertFalse(config.advanced.emit_raw_topics)
		self.assertFalse(config.advanced.emit_scan_report)
		self.assertTrue(config.advanced.detailed_logs)
		self.assertEqual(config.scan.mode,"scan_only")
		self.assertEqual(config.scan.bms_pack_count,3)

	def test_config_accepts_manual_scan_options(self) -> None:
		options=make_options()
		options["scan"]={
			"mode": "scan_only",
			"report_file": "/share/candidate-scan.json",
			"detected_sensors_file": "/config/detected_sensors.yaml",
			"bms_pack_count": 6,
		}
		with tempfile.TemporaryDirectory() as directory:
			options_path=Path(directory) / "options.json"
			options_path.write_text(json.dumps(options), encoding="utf-8")
			config=load_config(options_path)

		self.assertEqual(config.scan.mode, "scan_only")
		self.assertEqual(config.scan.bms_pack_count, 6)

	def test_config_uses_supervisor_mqtt_service_by_default(self) -> None:
		options=make_options()
		del options["mqtt"]["use_supervisor"]
		service={
			"data": {
				"host": "172.30.33.4",
				"port": "1883",
				"username": "supervisor-user",
				"password": "supervisor-password",
				"ssl": False,
			},
		}
		with tempfile.TemporaryDirectory() as directory:
			options_path=Path(directory) / "options.json"
			options_path.write_text(json.dumps(options), encoding="utf-8")
			with patch("deye_inverter_core.supervisor.urlopen",return_value=FakeSupervisorResponse(service)):
				config=load_config(options_path)

		self.assertEqual(config.mqtt.host, "172.30.33.4")
		self.assertEqual(config.mqtt.username, "supervisor-user")
		self.assertTrue(config.mqtt.password)
		self.assertEqual(config.mqtt.source, "supervisor")

	def test_supervisor_mqtt_failure_keeps_manual_configuration(self) -> None:
		with patch("deye_inverter_core.supervisor.urlopen",side_effect=OSError("unavailable")):
			self.assertIsNone(discover_mqtt_service())

	def test_config_rejects_placeholder_logger_serial(self) -> None:
		with tempfile.TemporaryDirectory() as directory:
			options_path=Path(directory) / "options.json"
			options_path.write_text(json.dumps(make_options(0)), encoding="utf-8")

			with self.assertRaisesRegex(ValueError, "logger.serial_number"):
				load_config(options_path)

	def test_unknown_profile_fails_before_polling(self) -> None:
		with self.assertRaisesRegex(ValueError, "Unknown sensor profile"):
			load_sensor_definitions(["not_a_profile"], "does-not-exist.yaml")

	def test_default_profile_requires_explicit_sensor_selection(self) -> None:
		self.assertEqual(load_sensor_definitions([], "does-not-exist.yaml"),[])

	def test_config_exposes_a_separate_control_catalog_source(self) -> None:
		options=make_options()
		options["catalog"]={
			"refresh_on_start":True,
			"url":"https://example.invalid/sensors.yaml",
			"cache_file":"/config/sensors.yaml",
			"control_url":"https://example.invalid/control.yaml",
			"control_cache_file":"/config/control.yaml",
			"timeout":5,
		}
		with tempfile.TemporaryDirectory() as directory:
			options_path=Path(directory) / "options.json"
			options_path.write_text(json.dumps(options),encoding="utf-8")
			config=load_config(options_path)

		self.assertEqual(config.catalog.control_url,"https://example.invalid/control.yaml")
		self.assertEqual(config.catalog.control_cache_file,"/config/control.yaml")

	def test_remote_control_catalog_uses_the_configured_url(self) -> None:
		payload={
			"format":1,
			"map_id":"control",
			"catalog_set":"deye_sg04_sg05_3ph_lv",
			"commands":[
				{"key":"grid_charge_current","name":"Grid charge current","registers":[128],"method":"NumberRWSensor","factor":1,"unit":"A","bitmask":0,"min":0,"max":210}
			],
		}
		with tempfile.TemporaryDirectory() as directory:
			config=CatalogConfig(True,"https://example.invalid/sensors.yaml",str(Path(directory)/"sensors.yaml"),5,"https://example.invalid/controls.yaml",str(Path(directory)/"controls.yaml"))
			with patch("deye_inverter_core.control_catalog.urlopen",return_value=FakeSupervisorResponse(payload)):
				catalog=load_remote_control_catalog(config)

		self.assertEqual(catalog.source,"github")
		self.assertEqual(catalog.commands[0]["key"],"grid_charge_current")

	def test_catalog_covers_live_telemetry_and_configured_bms_packs(self) -> None:
		candidates=load_scan_candidates(4)
		by_key={candidate.sensor.key: candidate.sensor for candidate in candidates}

		self.assertEqual(len(candidates), 186)
		self.assertEqual(by_key["grid_power_total"].registers, [619])
		self.assertEqual(by_key["pv_energy_total"].registers, [534,535])
		self.assertEqual(by_key["pv_energy_total"].word_order, "low_high")
		self.assertEqual(by_key["battery_2_voltage"].registers, [10078])
		self.assertEqual(by_key["battery_4_cycles"].registers, [10170])
		self.assertEqual(by_key["battery_1_temperature"].offset, -100.0)
		self.assertEqual(by_key["battery_1_temperature"].unit, "°C")
		self.assertEqual(by_key["battery_1_soc"].multiplier, 0.1)
		self.assertEqual(by_key["battery_4_bms_serial"].register_type,"ascii")
		self.assertEqual(by_key["battery_4_bms_serial"].byte_order,"low_high")
		self.assertEqual(by_key["battery_1_fault"].registers,[10060,10061])
		self.assertEqual(by_key["battery_1_heat_memory_temperature"].registers,[10046])
		self.assertEqual(by_key["run_state"].register_type,"enum")
		self.assertEqual(by_key["run_state"].options[2],"Normal")
		self.assertEqual(by_key["relay_status"].register_type,"bitmask")
		self.assertEqual(by_key["relay_status"].options[2],"Grid connected")
		self.assertEqual(by_key["warning_flags"].zero,"No warnings")
		self.assertEqual(by_key["fault_flags"].zero,"No faults")

	def test_status_types_decode_known_unknown_and_clear_states(self) -> None:
		self.assertEqual(
			decode_registers([2],"enum","high_low",options={0:"Standby",2:"Normal"},unknown="Unknown ({value})"),
			"Normal",
		)
		self.assertEqual(
			decode_registers([7],"enum","high_low",options={0:"Standby",2:"Normal"},unknown="Unknown ({value})"),
			"Unknown (7)",
		)
		self.assertEqual(
			decode_registers([0],"bitmask","high_low",options={0:"Relay"},zero="All relays off",unknown="Bit {bit}"),
			"All relays off",
		)
		self.assertEqual(
			decode_registers([0x0005],"bitmask","high_low",options={0:"Inverter relay",2:"Grid connected"},zero="All relays off",unknown="Bit {bit}"),
			"Inverter relay, Grid connected",
		)
		self.assertEqual(
			decode_registers([0,0x0002],"bitmask","high_low",options={},zero="No faults",unknown="F{code:02d}"),
			"F18",
		)

	def test_scan_candidates_wait_for_external_sensor_catalog(self) -> None:
		self.assertEqual(load_scan_candidates(4,RemoteCatalog([],"built-in")),[])

	def test_remote_full_register_catalog_matches_builtin_fallback(self) -> None:
		path=APP_ROOT.parent/"deye-solarman-diagnostics/deye_sg04_sg05_3ph_lv_catalog.yaml"
		payload=yaml.safe_load(path.read_text(encoding="utf-8"))
		catalog=RemoteCatalog(payload["sensors"],"repository",payload["bms_pack"],payload["version"])

		remote={sensor.key: sensor for sensor in apply_remote_catalog([],catalog,4)}
		fallback={candidate.sensor.key: candidate.sensor for candidate in load_scan_candidates(4)}

		self.assertEqual(payload["version"],2)
		self.assertEqual(len(payload["sensors"]),94)
		self.assertEqual(len(payload["bms_pack"]["sensors"]),23)
		self.assertEqual({entry["key"] for entry in payload["sensors"]},{candidate.sensor.key for candidate in load_scan_candidates(0)})
		self.assertEqual(remote,fallback)

		maximum={sensor.key: sensor for sensor in apply_remote_catalog([],catalog,10)}
		self.assertEqual(len(maximum),324)
		self.assertEqual(maximum["battery_10_voltage"].registers,[10382])

	def test_ascii_type_decodes_modbus_words_and_replaces_control_bytes(self) -> None:
		registers=[0x3530,0x3034,0x3037,0x3030,0x3145,0x3630,0x3930,0x3830]

		self.assertEqual(decode_registers(registers,"ascii","high_low"),"500407001E609080")
		self.assertEqual(decode_registers(registers,"ascii","high_low","low_high"),"05407000E1060908")
		self.assertEqual(registers_to_ascii([0x4100,0x1F42]),"A..B")
		self.assertEqual(registers_to_ascii([0x4100,0x1F42],"low_high"),".AB.")

	def test_remote_catalog_can_patch_and_extend_scan_candidates(self) -> None:
		catalog=RemoteCatalog(
			[
				{"key": "battery_1_temperature", "definition": {"unit": "°C", "multiplier": 0.01}},
				{
					"key": "firmware_build",
					"definition": {
						"name": "Firmware Build",
						"registers": [550],
						"type": "uint16",
						"schedule": "slow",
					},
				},
			],
			"test",
		)
		by_key={candidate.sensor.key: candidate.sensor for candidate in load_scan_candidates(4,catalog)}

		self.assertEqual(by_key["battery_1_temperature"].multiplier,0.01)
		self.assertEqual(by_key["firmware_build"].registers,[550])

	def test_remote_catalog_uses_cached_data_after_download_failure(self) -> None:
		payload={"version": 1,"sensors": [{"key": "ac_temperature","definition": {"unit": "°C"}}]}
		with tempfile.TemporaryDirectory() as directory:
			config=CatalogConfig(True,"https://example.invalid/catalog.yaml",str(Path(directory) / "catalog.yaml"),1)
			with patch("deye_inverter_core.remote_catalog.urlopen",return_value=FakeSupervisorResponse(payload)):
				downloaded=load_remote_catalog(config)
			with patch("deye_inverter_core.remote_catalog.urlopen",side_effect=OSError("offline")):
				cached=load_remote_catalog(config)

		self.assertEqual(downloaded.source,"github")
		self.assertEqual(cached.source,"cache")
		self.assertEqual(cached.sensors[0]["key"],"ac_temperature")

	def test_remote_catalog_force_refresh_ignores_startup_setting(self) -> None:
		payload={"version": 1,"sensors": []}
		with tempfile.TemporaryDirectory() as directory:
			config=CatalogConfig(False,"https://example.invalid/catalog.yaml",str(Path(directory) / "catalog.yaml"),1)
			with patch("deye_inverter_core.remote_catalog.urlopen",return_value=FakeSupervisorResponse(payload)):
				catalog=load_remote_catalog(config,force_refresh=True)

		self.assertEqual(catalog.source,"github")

	def test_candidate_scan_reports_raw_hex_and_supported_status(self) -> None:
		candidate=ScanCandidate(
			SensorDefinition("battery_voltage", "Battery Voltage", [587], "uint16", 0.01, unit="V"),
			"documented",
			"test",
		)
		solarman=FakeSolarman([5240])

		report=scan_candidates([candidate], solarman, make_polling())

		self.assertEqual(report[0]["status"], "supported")
		self.assertEqual(report[0]["raw_hex"], ["0x1478"])
		self.assertEqual(report[0]["value"], 52.4)
		self.assertEqual(report[0]["raw_ascii"],".x")

	def test_candidate_scan_identifies_unsupported_modbus_address(self) -> None:
		candidate=ScanCandidate(
			SensorDefinition("unknown", "Unknown", [65535], "uint16"),
			"candidate",
			"test",
		)

		report=scan_candidates([candidate], FailingSolarman(), make_polling())

		self.assertEqual(report[0]["status"], "unsupported")

	def test_detected_sensor_selection_is_preserved_and_loaded(self) -> None:
		report=[
			{
				"key": "battery_2_voltage",
				"name": "Battery 2 Voltage",
				"definition": {
					"key": "battery_2_voltage",
					"name": "Battery 2 Voltage",
					"registers": [10078],
					"type": "uint16",
					"multiplier": 0.1,
					"offset": 0.0,
					"unit": "V",
					"word_order": "high_low",
					"schedule": "default",
					"read_every": 60,
					"report_every": 300,
					"change_by": 0.0,
					"enabled": False,
					"retain": True,
					"device_class": "voltage",
					"state_class": "measurement",
					"icon": "",
					"category": "",
					"topic_suffix": "battery_2/voltage",
					"attributes": {},
				},
				"status": "supported",
				"raw_registers": [524],
				"raw_hex": ["0x020C"],
				"decoded": 524,
				"value": 52.4,
				"latency_ms": 1.0,
				"verification": "candidate",
				"description": "test",
			}
		]
		with tempfile.TemporaryDirectory() as directory:
			detected_path=Path(directory) / "detected_sensors.yaml"
			save_detected_sensors(str(detected_path), report)
			payload=yaml.safe_load(detected_path.read_text(encoding="utf-8"))
			payload["available_sensors"][0]["monitor"]=True
			payload["available_sensors"][0]["definition"]["read_every"]=120
			detected_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

			save_detected_sensors(str(detected_path), report)
			selected=load_monitored_definitions(str(detected_path))
			loaded=load_sensor_definitions(["deye_battery_packs"], "does-not-exist.yaml", str(detected_path))

			self.assertEqual(selected[0]["read_every"], 120)
			self.assertTrue(selected[0]["enabled"])
			self.assertTrue(next(sensor for sensor in loaded if sensor.key == "battery_2_voltage").enabled)

	def test_rescan_migrates_legacy_bms_serial_byte_order(self) -> None:
		report=[
			{
				"key": "battery_1_bms_serial",
				"name": "Battery 1 BMS Serial",
				"definition": {
					"key": "battery_1_bms_serial",
					"name": "Battery 1 BMS Serial",
					"registers": [10032,10033],
					"type": "ascii",
					"multiplier": 1.0,
					"offset": 0.0,
					"unit": "",
					"word_order": "high_low",
					"byte_order": "low_high",
					"schedule": "slow",
					"read_every": 600,
					"report_every": 900,
					"change_by": 0.0,
					"enabled": False,
					"retain": True,
					"device_class": "",
					"state_class": "",
					"icon": "",
					"category": "battery",
					"topic_suffix": "battery_1/bms_serial",
					"attributes": {},
				},
				"status": "supported",
				"raw_registers": [0x3530,0x3034],
				"raw_hex": ["0x3530","0x3034"],
				"decoded": "0540",
				"value": "0540",
				"latency_ms": 1.0,
				"verification": "candidate",
				"description": "test",
			}
		]
		with tempfile.TemporaryDirectory() as directory:
			detected_path=Path(directory) / "detected_sensors.yaml"
			save_detected_sensors(str(detected_path),report)
			payload=yaml.safe_load(detected_path.read_text(encoding="utf-8"))
			payload["available_sensors"][0]["monitor"]=True
			payload["available_sensors"][0]["definition"].pop("byte_order")
			detected_path.write_text(yaml.safe_dump(payload,sort_keys=False),encoding="utf-8")

			save_detected_sensors(str(detected_path),report)
			migrated=yaml.safe_load(detected_path.read_text(encoding="utf-8"))["available_sensors"][0]

			self.assertTrue(migrated["monitor"])
			self.assertEqual(migrated["definition"]["byte_order"],"low_high")

	def test_detected_sensor_selection_can_be_updated_without_editing_yaml(self) -> None:
		report=[
			{
				"key": "battery_2_voltage",
				"name": "Battery 2 Voltage",
				"definition": {
					"key": "battery_2_voltage",
					"name": "Battery 2 Voltage",
					"registers": [10078],
					"type": "uint16",
					"multiplier": 0.1,
					"offset": 0.0,
					"unit": "V",
					"word_order": "high_low",
					"schedule": "default",
					"read_every": 60,
					"report_every": 300,
					"change_by": 0.0,
					"enabled": False,
					"retain": True,
					"device_class": "voltage",
					"state_class": "measurement",
					"icon": "",
					"category": "battery",
					"topic_suffix": "battery_2/voltage",
					"attributes": {},
				},
				"status": "supported",
				"raw_registers": [524],
				"raw_hex": ["0x020C"],
				"decoded": 524,
				"value": 52.4,
				"latency_ms": 1.0,
				"verification": "candidate",
				"description": "test",
			}
		]
		with tempfile.TemporaryDirectory() as directory:
			detected_path=Path(directory) / "detected_sensors.yaml"
			save_detected_sensors(str(detected_path),report)
			updated=update_detected_sensors(
				str(detected_path),
				[
					{
						"key": "battery_2_voltage",
						"monitor": True,
						"definition": {
							"read_every": 120,
							"report_every": 600,
							"change_by": 0.2,
							"retain": False,
						},
					}
				],
			)

			entry=updated["available_sensors"][0]
			self.assertTrue(entry["monitor"])
			self.assertEqual(entry["definition"]["read_every"],120)
			self.assertFalse(entry["definition"]["retain"])

			update_detected_sensors(
				str(detected_path),
				[{"key": "battery_2_voltage","monitor": False,"definition": {}}],
			)
			self.assertEqual(load_pending_discovery_removals(str(detected_path)),["battery_2_voltage"])

	def test_detected_sensors_can_be_reset_to_catalog_defaults_or_cleared(self) -> None:
		candidate=ScanCandidate(
			SensorDefinition("battery_voltage","Battery Voltage",[10040],"uint16",0.1,unit="V",read_every=60),
			"candidate",
			"test",
		)
		report=[
			{
				"key": "battery_voltage",
				"name": "Battery Voltage",
				"definition": {
					"key": "battery_voltage", "name": "Edited Voltage", "registers": [10040], "type": "uint16",
					"multiplier": 0.2, "offset": 0.0, "unit": "V", "word_order": "high_low",
					"schedule": "default", "read_every": 120, "report_every": 300, "change_by": 0.0,
					"enabled": False, "retain": True, "device_class": "", "state_class": "", "icon": "",
					"category": "", "topic_suffix": "battery_voltage", "attributes": {},
				},
				"status": "supported", "raw_registers": [524], "raw_hex": ["0x020C"], "decoded": 524,
				"value": 52.4, "latency_ms": 1.0, "verification": "candidate", "description": "test",
			}
		]
		with tempfile.TemporaryDirectory() as directory:
			detected_path=Path(directory) / "detected_sensors.yaml"
			save_detected_sensors(str(detected_path),report)
			update_detected_sensors(str(detected_path),[{"key": "battery_voltage","monitor": True,"definition": {"name": "Custom","read_every": 120}}])

			reset=reset_detected_sensors(str(detected_path),[candidate])
			entry=reset["available_sensors"][0]
			self.assertFalse(entry["monitor"])
			self.assertEqual(entry["definition"]["name"],"Battery Voltage")
			self.assertEqual(entry["definition"]["read_every"],60)
			self.assertEqual(entry["last_scan"]["value"],52.4)
			self.assertEqual(load_pending_discovery_removals(str(detected_path)),["battery_voltage"])

			cleared=clear_detected_sensors(str(detected_path))
			self.assertEqual(cleared["available_sensors"],[])
			self.assertIsNone(cleared["scanned_at"])

	def test_ingress_panel_exposes_and_updates_detected_sensors(self) -> None:
		report=[
			{
				"key": "grid_power_total",
				"name": "Grid Power Total",
				"definition": {
					"key": "grid_power_total",
					"name": "Grid Power Total",
					"registers": [619],
					"type": "int16",
					"multiplier": 1.0,
					"offset": 0.0,
					"unit": "W",
					"word_order": "high_low",
					"schedule": "default",
					"read_every": 60,
					"report_every": 300,
					"change_by": 1.0,
					"enabled": False,
					"retain": True,
					"device_class": "power",
					"state_class": "measurement",
					"icon": "",
					"category": "grid",
					"topic_suffix": "grid_power_total",
					"attributes": {},
				},
				"status": "supported",
				"raw_registers": [800],
				"raw_hex": ["0x0320"],
				"decoded": 800,
				"value": 800,
				"latency_ms": 1.0,
				"verification": "documented",
				"description": "test",
			}
		]
		with tempfile.TemporaryDirectory() as directory:
			detected_path=Path(directory) / "detected_sensors.yaml"
			save_detected_sensors(str(detected_path),report)
			reset_calls=[]
			clear_calls=[]
			configuration_changes=[]
			panel=IngressPanel(
				str(detected_path),
				lambda: {"count": 1},
				lambda: reset_calls.append(True) or {"available_sensors": []},
				lambda: clear_calls.append(True) or {"available_sensors": []},
				lambda: configuration_changes.append(True),
				port=0,
			)
			panel.start()
			try:
				assert panel._server is not None
				address=f"http://127.0.0.1:{panel._server.server_address[1]}"
				with urlopen(
					Request(
						f"{address}/",
						headers={"X-Ingress-Path": "/api/hassio_ingress/example-token"},
					)
				) as response:
					page=response.read().decode("utf-8")
				self.assertIn('<base href="/api/hassio_ingress/example-token/">',page)
				self.assertIn("char.charCodeAt(0) === 34",page)
				self.assertIn("var(--primary-background-color",page)
				self.assertIn("syncHomeAssistantTheme",page)
				self.assertIn("Home Assistant theme synchronized",page)
				self.assertIn("Reset konfiguracji",page)
				self.assertIn("Usun sensory",page)
				self.assertIn("data-select-control",page)
				self.assertIn("asciiFromRaw",page)
				self.assertIn('"ascii"',page)
				self.assertNotIn("ownership"+"-panel.js",page)
				self.assertNotIn("ownershipBadge",page)
				self.assertNotIn('"""',page)
				with urlopen(f"{address}/panel.js") as response:
					diagnostics_script=response.read().decode("utf-8")
				self.assertIn("external diagnostics script loaded",diagnostics_script)
				with urlopen(f"{address}/api/sensors") as response:
					listed=json.loads(response.read())
				self.assertEqual(listed["available_sensors"][0]["key"],"grid_power_total")

				body=json.dumps(
					{
						"sensors": [
							{
								"key": "grid_power_total",
								"monitor": True,
								"definition": {"read_every": 120},
							}
						]
					}
				).encode("utf-8")
				request=Request(
					f"{address}/api/sensors",
					data=body,
					headers={"Content-Type": "application/json"},
					method="POST",
				)
				with urlopen(request) as response:
					updated=json.loads(response.read())
				self.assertTrue(updated["available_sensors"][0]["monitor"])
				self.assertEqual(updated["available_sensors"][0]["definition"]["read_every"],120)
				self.assertEqual(len(configuration_changes),1)
				before_invalid_update=detected_path.read_bytes()
				invalid=Request(
					f"{address}/api/sensors",
					data=json.dumps({"sensors":[{"key":"grid_power_total","monitor":True,"definition":{"read_every":0}}]}).encode("utf-8"),
					headers={"Content-Type":"application/json"},
					method="POST",
				)
				with self.assertRaises(HTTPError) as invalid_response:
					urlopen(invalid)
				self.assertEqual(invalid_response.exception.code,400)
				self.assertEqual(detected_path.read_bytes(),before_invalid_update)
				with self.assertRaises(HTTPError) as ownership_response:
					urlopen(f"{address}/api/{'owner'+'ship'}")
				self.assertEqual(ownership_response.exception.code,404)

				for endpoint,calls in [("/api/reset",reset_calls),("/api/sensors/delete",clear_calls)]:
					request=Request(
						f"{address}{endpoint}",
						data=b"{}",
						headers={"Content-Type": "application/json"},
						method="POST",
					)
					with urlopen(request) as response:
						response_payload=json.loads(response.read())
					self.assertEqual(response_payload["available_sensors"],[])
					self.assertEqual(len(calls),1)
				self.assertEqual(len(configuration_changes),3)

				panel._run_scan()
				self.assertEqual(len(configuration_changes),4)
			finally:
				panel.stop()

	def test_non_contiguous_registers_are_decoded_by_address(self) -> None:
		sensor=SensorDefinition(
			key="combined",
			name="Combined",
			registers=[10040,10042],
			register_type="uint32",
		)
		mqtt=FakeMqtt()
		state=SensorState()

		result=_handle_sensor(sensor, [1,57005,2], 10040, 1.5, state, mqtt, True, 900)

		self.assertEqual(result["raw"], [1,2])
		self.assertEqual(result["decoded"], 65538)
		self.assertEqual(mqtt.raw, [("combined", [1,2])])

	def test_iteration_reads_the_full_range_for_non_contiguous_registers(self) -> None:
		sensor=SensorDefinition(
			key="combined",
			name="Combined",
			registers=[10042,10040],
			register_type="uint32",
		)
		solarman=FakeSolarman([1,57005,2])
		mqtt=FakeMqtt()

		report=run_iteration([sensor], {"combined": SensorState()}, solarman, mqtt, make_polling(), False)

		self.assertEqual(solarman.calls, [(10040,3)])
		self.assertEqual(report[0]["raw"], [2,1])
		self.assertEqual(report[0]["decoded"], 131073)

	def test_iteration_reconnects_when_solarman_session_is_closed(self) -> None:
		sensor=SensorDefinition("voltage", "Voltage", [10040], "uint16")
		with self.assertRaisesRegex(SolarmanConnectionClosedError, "Connection already closed"):
			run_iteration([sensor], {"voltage": SensorState()}, ClosedSolarman(), FakeMqtt(), make_polling(), False)

	def test_scheduler_uses_actual_register_range(self) -> None:
		first=SensorDefinition("first", "First", [10042,10040], "uint32")
		second=SensorDefinition("second", "Second", [10043], "uint16")

		groups=group_sensors_for_read([first, second], make_polling())

		self.assertEqual(groups, [[first, second]])

	def test_slow_schedule_uses_global_slow_interval(self) -> None:
		sensor=SensorDefinition("soc", "SOC", [10047], "uint16", schedule="slow", read_every=30)
		state=SensorState(last_read_at=450)

		with patch("deye_inverter_core.main.time.time", return_value=1000):
			self.assertFalse(_is_due(sensor, state, make_polling()))

	def test_mqtt_global_retain_setting_overrides_sensor_setting(self) -> None:
		publisher=MqttPublisher(
			MqttConfig("host", 1883, "", "", "test", "base", "homeassistant", False),
			InverterConfig("2507092018", "Deye", "Deye", "SG05LP3"),
		)
		client=FakePahoClient()
		publisher._client=client
		sensor=SensorDefinition("voltage", "Voltage", [10040], "uint16", retain=True)

		publisher.publish_state(sensor, 52.1, {})
		publisher.publish_raw(sensor, [521])

		self.assertTrue(client.messages)
		self.assertTrue(all(retain is False for _, _, retain in client.messages))

	def test_mqtt_publication_waits_for_qos_one_ack_and_stops_failed_session(self) -> None:
		publisher=MqttPublisher(
			MqttConfig("host",1883,"","","test","base","homeassistant",True),
			InverterConfig("123","Deye","Deye","SG05LP3"),
		)
		publisher._client=Mock()
		info=publisher._client.publish.return_value
		info.is_published.return_value=False
		sensor=SensorDefinition("voltage","Voltage",[10040],"uint16")

		with self.assertRaises(ConnectionError):
			publisher.publish_state(sensor,52,{})

		self.assertEqual(publisher._client.publish.call_args.kwargs["qos"],1)
		info.wait_for_publish.assert_called_once_with(timeout=10)
		publisher._client.disconnect.assert_called_once()
		publisher._client.loop_stop.assert_called_once()

	def test_mqtt_reconnects_once_before_next_publication_after_session_failure(self) -> None:
		publisher=MqttPublisher(
			MqttConfig("host",1883,"","","test","base","homeassistant",True),
			InverterConfig("123","Deye","Deye","SG05LP3"),
		)
		client=Mock()
		failed=Mock()
		failed.is_published.return_value=False
		online=Mock()
		succeeded=Mock()
		succeeded.is_published.return_value=True
		client.publish.side_effect=[failed,online,online,succeeded]
		publisher._client=client
		client.reconnect.side_effect=lambda:publisher._on_connect(client,None,None,0,None)
		sensor=SensorDefinition("voltage","Voltage",[10040],"uint16")

		with self.assertRaises(ConnectionError):
			publisher.sensor_availability(sensor,True)
		publisher.sensor_availability(sensor,True)

		client.reconnect.assert_called_once_with()
		succeeded.wait_for_publish.assert_called_once_with(timeout=10)

	def test_temperature_discovery_uses_home_assistant_celsius_unit(self) -> None:
		publisher=MqttPublisher(
			MqttConfig("host",1883,"","","test","base","homeassistant",True),
			InverterConfig("2507092018","Deye","Deye","SG05LP3"),
		)
		client=FakePahoClient()
		publisher._client=client
		publisher.publish_discovery(
			SensorDefinition("temperature","Temperature",[10042],"uint16",unit="°C",device_class="temperature")
		)
		payload=json.loads(client.messages[0][1])
		self.assertEqual(payload["unit_of_measurement"],"°C")

	def test_mqtt_uses_exact_client_id_and_common_topics_with_transport_metadata(self) -> None:
		config=MqttConfig("host",1883,"","","deye-runtime","base","homeassistant",True)
		with patch("deye_inverter_core.mqtt.mqtt.Client") as client_factory:
			publisher=MqttPublisher(config,InverterConfig("123","Deye","Deye","SG05LP3"))
		self.assertEqual(client_factory.call_args.kwargs["client_id"],"deye-runtime")
		client_factory.return_value.will_set.assert_called_once_with("base/123/availability","offline",retain=True)
		publisher._client=Mock()
		publisher._publish_confirmed=Mock()
		sensor=SensorDefinition("voltage","Voltage",[10040],"uint16",transport="modbus_rtu")

		publisher.publish_discovery(sensor)
		discovery=json.loads(publisher._publish_confirmed.call_args.args[1])
		self.assertEqual(discovery["state_topic"],"base/123/voltage")
		self.assertEqual(discovery["availability"],[
			{"topic":"base/123/availability"},
			{"topic":"base/123/voltage/availability"},
		])
		self.assertEqual(discovery["availability_mode"],"all")
		self.assertEqual(discovery["origin"]["name"],"SolarMan Diagnostics")
		self.assertEqual(discovery["origin"]["sw_version"],"2.0.2")

		publisher._publish_confirmed.reset_mock()
		publisher.publish_state(sensor,52,{"raw_registers":[52]})
		attributes=json.loads(publisher._publish_confirmed.call_args_list[1].args[1])
		self.assertEqual(attributes["transport"],"modbus_rtu")
		publisher.sensor_availability(sensor,False)
		self.assertEqual(publisher._publish_confirmed.call_args.args[:2],("base/123/voltage/availability","offline"))

	def test_control_topics_and_payloads_never_include_source_segment(self) -> None:
		from deye_inverter_core.controls import ControlService

		with tempfile.TemporaryDirectory() as directory:
			service=ControlService(str(Path(directory)/"controls.json"),None,threading.Lock(),0)
			key="control_grid_charge_battery_current"
			entry=service.entry(key)
			entry["definition"]["transport"]="modbus_rtu"
			publisher=MqttPublisher(
				MqttConfig("host",1883,"","","test","base","homeassistant",True),
				InverterConfig("123","Deye","Deye","SG05LP3"),
			)
			publisher._client=Mock()
			publisher._publish_confirmed=Mock()

			publisher.publish_control_discovery(entry,{"min":0,"max":210,"write_allowed":True})
			topic,payload=publisher._publish_confirmed.call_args.args[:2]
			discovery=json.loads(payload)
			self.assertNotIn("/source/",topic+payload)
			self.assertEqual(discovery["command_topic"],f"base/123/controls/{key}/set")
			self.assertEqual(discovery["availability"],[
				{"topic":"base/123/availability"},
				{"topic":"base/123/controls/availability"},
				{"topic":f"base/123/controls/{key}/availability"},
			])

			publisher._publish_confirmed.reset_mock()
			publisher.publish_control_state(entry,{"status":"supported","value":25,"write_allowed":True})
			attributes=json.loads(publisher._publish_confirmed.call_args_list[1].args[1])
			self.assertEqual(attributes["transport"],"modbus_rtu")

	def test_discovery_removal_publishes_retained_empty_configuration(self) -> None:
		publisher=MqttPublisher(
			MqttConfig("host",1883,"","","test","base","homeassistant",True),
			InverterConfig("2507092018","Deye","Deye","SG05LP3"),
		)
		client=FakePahoClient()
		publisher._client=client

		publisher.remove_discovery("battery_voltage")

		topic,payload,retain=client.messages[0]
		self.assertEqual(topic,"homeassistant/sensor/deye_solarman_2507092018_battery_voltage/config")
		self.assertEqual(payload,"")
		self.assertTrue(retain)

	def test_control_discovery_can_be_republished_after_confirmed_removal(self) -> None:
		from deye_inverter_core.controls import ControlService

		with tempfile.TemporaryDirectory() as directory:
			service=ControlService(str(Path(directory)/"controls.json"),None,threading.Lock(),0)
			entry=service.entry("control_grid_charge_battery_current")
			publisher=MqttPublisher(
				MqttConfig("host",1883,"","","test","base","homeassistant",True),
				InverterConfig("123","Deye","Deye","SG05LP3"),
			)
			publisher._publish_confirmed=Mock()
			result={"min":0,"max":210,"write_allowed":True}

			publisher.publish_control_discovery(entry,result)
			publisher.remove_control_discovery(entry["definition"])
			publisher.publish_control_discovery(entry,result)

			self.assertEqual(publisher._publish_confirmed.call_count,3)

	def test_sensor_and_control_discovery_share_one_serial_queue(self) -> None:
		from deye_inverter_core.controls import ControlService

		with tempfile.TemporaryDirectory() as directory:
			service=ControlService(str(Path(directory)/"controls.json"),None,threading.Lock(),0)
			entry=service.entry("control_grid_charge_battery_current")
			publisher=MqttPublisher(
				MqttConfig("host",1883,"","","test","base","homeassistant",True),
				InverterConfig("123","Deye","Deye","SG05LP3"),
			)
			first_started=threading.Event()
			release=threading.Event()
			second_started=threading.Event()
			calls=[]
			def publish(*args):
				calls.append(args[0])
				if len(calls) == 1:
					first_started.set()
					self.assertTrue(release.wait(5))
				else:
					second_started.set()
			publisher._publish_confirmed=publish
			sensor=SensorDefinition("voltage","Voltage",[10040],"uint16")
			first=threading.Thread(target=lambda:publisher.publish_discovery(sensor))
			second=threading.Thread(target=lambda:publisher.publish_control_discovery(entry,{"min":0,"max":210,"write_allowed":True}))

			first.start()
			self.assertTrue(first_started.wait(5))
			second.start()
			serialized=not second_started.wait(0.1)
			release.set()
			first.join(5)
			second.join(5)

			self.assertTrue(serialized)
			self.assertTrue(second_started.is_set())

	def test_graceful_disconnect_publishes_shared_process_availability_offline(self) -> None:
		publisher=MqttPublisher(
			MqttConfig("host",1883,"","","test","base","homeassistant",True),
			InverterConfig("123","Deye","Deye","SG05LP3"),
		)
		publisher._client=Mock()
		publisher._publish_confirmed=Mock()

		publisher.disconnect()

		calls=[call.args[:2] for call in publisher._publish_confirmed.call_args_list]
		self.assertIn(("base/123/availability","offline"),calls)
		self.assertIn(("base/123/controls/availability","offline"),calls)

	def test_log_formatter_has_readable_colored_status_markers(self) -> None:
		formatter=AddonLogFormatter(color=True)
		record=logging.LogRecord("deye_inverter_core.main",SUCCESS,"",0,"Connected %s",("logger",),None)
		warning=logging.LogRecord("deye_inverter_core.main",logging.WARNING,"",0,"Read timeout",(),None)

		self.assertIn("\033[32m",formatter.format(record))
		self.assertIn("[ OK  ] main",formatter.format(record))
		self.assertIn("\033[33m",formatter.format(warning))
		self.assertIn("[WARN ] main",formatter.format(warning))

	def test_closed_tcp_session_omits_register_range_in_normal_logs(self) -> None:
		sensor=SensorDefinition("voltage","Voltage",[10040],"uint16")
		with self.assertLogs("deye_inverter_core.main",logging.WARNING) as logs:
			with self.assertRaises(SolarmanConnectionClosedError):
				run_iteration([sensor],{"voltage":SensorState()},ClosedSolarman(),FakeMqtt(),make_polling(),False)

		self.assertEqual(logs.output,["WARNING:deye_inverter_core.main:Solarman TCP session closed; reconnecting"])

	def test_closed_tcp_session_includes_register_range_in_detailed_logs(self) -> None:
		sensor=SensorDefinition("voltage","Voltage",[10040],"uint16")
		with self.assertLogs("deye_inverter_core.main",logging.WARNING) as logs:
			with self.assertRaises(SolarmanConnectionClosedError):
				run_iteration([sensor],{"voltage":SensorState()},ClosedSolarman(),FakeMqtt(),make_polling(),False,detailed_logs=True)

		self.assertEqual(logs.output,["WARNING:deye_inverter_core.main:Solarman TCP session closed start=10040 count=1; reconnecting"])

	def test_failed_transport_worker_omits_traceback_in_normal_logs(self) -> None:
		transport=RuntimeTransport("solarman_tcp")
		transport.connect_error=SolarmanConnectionClosedError("Connection closed on read")
		polling=make_polling()
		manager=TransportManager([TransportSlot(transport,polling,10)])
		sensor=SensorDefinition("voltage","Voltage",[10040],"uint16")
		runtime=SensorRuntime(manager,FakeMqtt(),[sensor],{"voltage":SensorState()})

		with self.assertLogs("deye_inverter_core.main",logging.WARNING) as logs:
			runtime.run_once("solarman_tcp")

		self.assertEqual(logs.output,["WARNING:deye_inverter_core.main:Transport worker failed transport=solarman_tcp error=Connection closed on read"])

	def test_invalid_state_file_is_ignored_and_replaced_safely(self) -> None:
		with tempfile.TemporaryDirectory() as directory:
			state_path=Path(directory) / "runtime_state.json"
			state_path.write_text("not-json", encoding="utf-8")
			self.assertEqual(load_state(str(state_path)), {})

			save_state(str(state_path), {"voltage": SensorState(last_value=52.1)})
			loaded=load_state(str(state_path))

			self.assertEqual(loaded["voltage"].last_value, 52.1)
			self.assertFalse((state_path.parent / ".runtime_state.json.tmp").exists())


if __name__ == "__main__":
	unittest.main()
