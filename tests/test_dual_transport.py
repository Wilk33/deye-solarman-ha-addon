import json
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"packages"))
sys.path.insert(0,str(ROOT/"apps/deye-solarman/src"))

from deye_inverter_core.config import load_config
from deye_inverter_core.models import Rs485Config
from deye_inverter_core.models import SolarmanConfig
from deye_inverter_core.models import TransportPollingConfig
from deye_solarman_diagnostics.rs485 import ModbusRtuTransport
from deye_inverter_core.transport import TransportConnectionClosedError
from deye_inverter_core.transport import TransportProtocolError


def make_common_options() -> dict[str,object]:
	return {
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
			"default_profile": [],
			"overrides_file": "/config/user_sensors.yaml",
			"state_file": "/config/runtime_state.json",
			"scan_report_file": "/share/report.json",
		},
		"advanced": {
			"emit_raw_topics": True,
			"emit_scan_report": True,
		},
	}


def make_polling(default_interval: int=60) -> dict[str,object]:
	return {
		"default_interval": default_interval,
		"slow_interval": 600,
		"read_message_spacing": 0.05,
		"batch_gap": 1,
		"max_registers_per_request": 20,
		"publish_unchanged_every": 900,
		"startup_probe_register": 10040,
		"startup_probe_count": 1,
		"allow_reconnect": True,
	}


def load_options(options: dict[str,object]):
	with tempfile.TemporaryDirectory() as directory:
		path=Path(directory)/"options.json"
		path.write_text(json.dumps(options),encoding="utf-8")
		return load_config(path)


def make_rs485_config() -> Rs485Config:
	return Rs485Config(
		enabled=True,
		device="/dev/ttyUSB1",
		baudrate=19200,
		bytesize=8,
		parity="N",
		stopbits=1,
		modbus_id=17,
		timeout=1.5,
		reconnect_delay=7,
		polling=TransportPollingConfig(**make_polling()),
	)


class FakeModbusResponse:
	def __init__(self, *, registers: list[int] | None=None, error: bool=False) -> None:
		self.registers=registers
		self._error=error

	def isError(self) -> bool:
		return self._error


class FakeModbusSerialClient:
	def __init__(self, *, connect_result: bool=True) -> None:
		self.connected=False
		self.connect_result=connect_result
		self.close_calls=0
		self.read_calls: list[dict[str,object]]=[]
		self.write_calls: list[dict[str,object]]=[]
		self.read_response=FakeModbusResponse(registers=[101,202])
		self.write_response=FakeModbusResponse()
		self.read_error: Exception | None=None
		self.write_error: Exception | None=None

	def connect(self) -> bool:
		self.connected=self.connect_result
		return self.connect_result

	def close(self) -> None:
		self.close_calls+=1
		self.connected=False

	def read_holding_registers(self, **kwargs: object) -> FakeModbusResponse:
		self.read_calls.append(kwargs)
		if self.read_error is not None:
			raise self.read_error
		return self.read_response

	def write_registers(self, **kwargs: object) -> FakeModbusResponse:
		self.write_calls.append(kwargs)
		if self.write_error is not None:
			raise self.write_error
		return self.write_response


class RecordingModbusClientFactory:
	def __init__(self, clients: list[FakeModbusSerialClient]) -> None:
		self.clients=clients
		self.calls: list[dict[str,object]]=[]

	def __call__(self, **kwargs: object) -> FakeModbusSerialClient:
		self.calls.append(kwargs)
		return self.clients[len(self.calls)-1]


class DualTransportConfigTests(unittest.TestCase):
	def test_loads_version_2_transport_sections_with_independent_polling(self) -> None:
		options=make_common_options()
		options["solarman"]={
			"enabled": True,
			"host": "192.168.177.144",
			"port": 8899,
			"serial_number": 3556142832,
			"modbus_id": 1,
			"timeout": 3,
			"reconnect_delay": 10,
			"polling": make_polling(61),
		}
		options["rs485"]={
			"enabled": True,
			"device": "/dev/ttyUSB1",
			"baudrate": 19200,
			"bytesize": 8,
			"parity": "N",
			"stopbits": 1,
			"modbus_id": 2,
			"timeout": 1,
			"reconnect_delay": 7,
			"polling": make_polling(13),
		}

		config=load_options(options)

		self.assertIsInstance(config.solarman,SolarmanConfig)
		self.assertIsInstance(config.rs485,Rs485Config)
		self.assertIsInstance(config.solarman.polling,TransportPollingConfig)
		self.assertEqual(config.solarman.host,"192.168.177.144")
		self.assertEqual(config.solarman.polling.default_interval,61)
		self.assertEqual(config.rs485.device,"/dev/ttyUSB1")
		self.assertEqual(config.rs485.baudrate,19200)
		self.assertEqual(config.rs485.modbus_id,2)
		self.assertEqual(config.rs485.polling.default_interval,13)

	def test_migrates_version_1_logger_and_polling_to_solarman(self) -> None:
		options=make_common_options()
		options["logger"]={
			"host": "192.168.177.144",
			"port": 8899,
			"serial_number": 3556142832,
			"modbus_id": 1,
			"timeout": 3,
			"reconnect_delay": 10,
		}
		legacy_polling=make_polling(73)
		legacy_polling.update(
			{
				"slow_interval": 731,
				"read_message_spacing": 0.17,
				"batch_gap": 3,
				"max_registers_per_request": 41,
				"publish_unchanged_every": 937,
				"startup_probe_register": 10041,
				"startup_probe_count": 2,
				"allow_reconnect": False,
			}
		)
		options["polling"]=legacy_polling

		config=load_options(options)

		self.assertTrue(config.solarman.enabled)
		self.assertFalse(config.rs485.enabled)
		self.assertEqual(config.solarman.host,"192.168.177.144")
		self.assertEqual(
			config.solarman.polling,
			TransportPollingConfig(
				default_interval=73,
				slow_interval=731,
				read_message_spacing=0.17,
				batch_gap=3,
				max_registers_per_request=41,
				publish_unchanged_every=937,
				startup_probe_register=10041,
				startup_probe_count=2,
				allow_reconnect=False,
			),
		)
		self.assertIs(config.logger,config.solarman)
		self.assertIs(config.polling,config.solarman.polling)

	def test_accepts_rs485_as_the_only_enabled_transport(self) -> None:
		options=make_common_options()
		options["solarman"]={
			"enabled": False,
			"host": "",
			"port": 8899,
			"serial_number": 0,
			"modbus_id": 1,
			"timeout": 3,
			"reconnect_delay": 10,
			"polling": make_polling(),
		}
		options["rs485"]={
			"enabled": True,
			"device": "/dev/ttyUSB0",
			"baudrate": 9600,
			"bytesize": 8,
			"parity": "N",
			"stopbits": 1,
			"modbus_id": 1,
			"timeout": 1,
			"reconnect_delay": 10,
			"polling": make_polling(),
		}

		config=load_options(options)

		self.assertFalse(config.solarman.enabled)
		self.assertTrue(config.rs485.enabled)

	def test_rejects_configuration_with_both_transports_disabled(self) -> None:
		options=make_common_options()
		options["solarman"]={
			"enabled": False,
			"host": "",
			"port": 8899,
			"serial_number": 0,
			"modbus_id": 1,
			"timeout": 3,
			"reconnect_delay": 10,
			"polling": make_polling(),
		}
		options["rs485"]={
			"enabled": False,
			"device": "/dev/ttyUSB0",
			"baudrate": 9600,
			"bytesize": 8,
			"parity": "N",
			"stopbits": 1,
			"modbus_id": 1,
			"timeout": 1,
			"reconnect_delay": 10,
			"polling": make_polling(),
		}

		with self.assertRaisesRegex(ValueError,"at least one transport must be enabled"):
			load_options(options)

	def test_addon_uses_version_2_sections_and_disables_rs485_by_default(self) -> None:
		addon=yaml.safe_load((ROOT/"deye-solarman-diagnostics/config.yaml").read_text(encoding="utf-8"))

		self.assertEqual(addon["version"],"2.0.0")
		self.assertNotIn("logger",addon["options"])
		self.assertNotIn("polling",addon["options"])
		self.assertTrue(addon["options"]["solarman"]["enabled"])
		self.assertFalse(addon["options"]["rs485"]["enabled"])
		self.assertEqual(addon["options"]["rs485"]["device"],"/dev/ttyUSB0")
		self.assertEqual(addon["schema"]["rs485"]["device"],"device(subsystem=tty)")
		self.assertIn("polling",addon["schema"]["solarman"])
		self.assertIn("polling",addon["schema"]["rs485"])


class ModbusRtuTransportTests(unittest.TestCase):
	def test_connect_uses_serial_configuration_without_library_retries(self) -> None:
		client=FakeModbusSerialClient()
		factory=RecordingModbusClientFactory([client])
		transport=ModbusRtuTransport(make_rs485_config(),client_factory=factory)

		transport.connect()

		self.assertEqual(
			factory.calls,
			[{
				"port": "/dev/ttyUSB1",
				"baudrate": 19200,
				"bytesize": 8,
				"parity": "N",
				"stopbits": 1,
				"timeout": 1.5,
				"retries": 0,
			}],
		)
		self.assertEqual(transport.transport_id,"modbus_rtu")

	def test_read_returns_register_list_and_passes_device_id(self) -> None:
		client=FakeModbusSerialClient()
		transport=ModbusRtuTransport(
			make_rs485_config(),
			client_factory=RecordingModbusClientFactory([client]),
		)
		transport.connect()

		values=transport.read_holding_registers(10040,2)

		self.assertEqual(values,[101,202])
		self.assertEqual(
			client.read_calls,
			[{"address": 10040,"count": 2,"device_id": 17}],
		)

	def test_write_uses_one_write_registers_operation_with_device_id(self) -> None:
		client=FakeModbusSerialClient()
		transport=ModbusRtuTransport(
			make_rs485_config(),
			client_factory=RecordingModbusClientFactory([client]),
		)
		transport.connect()

		result=transport.write_holding_registers(128,[25,30])

		self.assertIs(result,client.write_response)
		self.assertEqual(
			client.write_calls,
			[{"address": 128,"values": [25,30],"device_id": 17}],
		)

	def test_protocol_error_responses_raise_transport_error(self) -> None:
		client=FakeModbusSerialClient()
		transport=ModbusRtuTransport(
			make_rs485_config(),
			client_factory=RecordingModbusClientFactory([client]),
		)
		transport.connect()
		client.read_response=FakeModbusResponse(error=True)

		with self.assertRaisesRegex(TransportProtocolError,"read holding registers"):
			transport.read_holding_registers(10040,1)

		client.write_response=FakeModbusResponse(error=True)
		with self.assertRaisesRegex(TransportProtocolError,"write holding registers"):
			transport.write_holding_registers(128,[25])

	def test_read_io_error_with_stale_connected_flag_requests_reconnect(self) -> None:
		client=FakeModbusSerialClient()
		client.read_error=OSError("USB device disappeared")
		transport=ModbusRtuTransport(
			make_rs485_config(),
			client_factory=RecordingModbusClientFactory([client]),
		)
		transport.connect()

		with self.assertRaisesRegex(TransportConnectionClosedError,"USB device disappeared"):
			transport.read_holding_registers(10040,1)

		self.assertTrue(client.connected)
		self.assertEqual(len(client.read_calls),1)

	def test_write_io_error_with_stale_connected_flag_is_not_retried(self) -> None:
		client=FakeModbusSerialClient()
		client.write_error=OSError("serial port write failed")
		transport=ModbusRtuTransport(
			make_rs485_config(),
			client_factory=RecordingModbusClientFactory([client]),
		)
		transport.connect()

		with self.assertRaisesRegex(TransportConnectionClosedError,"serial port write failed"):
			transport.write_holding_registers(128,[25])

		self.assertTrue(client.connected)
		self.assertEqual(len(client.write_calls),1)

	def test_operations_require_an_active_connection(self) -> None:
		client=FakeModbusSerialClient()
		transport=ModbusRtuTransport(
			make_rs485_config(),
			client_factory=RecordingModbusClientFactory([client]),
		)

		with self.assertRaisesRegex(TransportConnectionClosedError,"not connected"):
			transport.read_holding_registers(10040,1)

		transport.connect()
		client.connected=False
		with self.assertRaisesRegex(TransportConnectionClosedError,"connection is closed"):
			transport.write_holding_registers(128,[25])

	def test_failed_connect_raises_transport_connection_error(self) -> None:
		client=FakeModbusSerialClient(connect_result=False)
		transport=ModbusRtuTransport(
			make_rs485_config(),
			client_factory=RecordingModbusClientFactory([client]),
		)

		with self.assertRaisesRegex(TransportConnectionClosedError,"Could not connect"):
			transport.connect()

		self.assertEqual(client.close_calls,1)

	def test_reconnect_closes_old_client_and_creates_a_new_one(self) -> None:
		first=FakeModbusSerialClient()
		second=FakeModbusSerialClient()
		factory=RecordingModbusClientFactory([first,second])
		transport=ModbusRtuTransport(make_rs485_config(),client_factory=factory)
		transport.connect()

		transport.reconnect()
		transport.read_holding_registers(10040,1)

		self.assertEqual(first.close_calls,1)
		self.assertEqual(len(factory.calls),2)
		self.assertEqual(second.read_calls,[{"address": 10040,"count": 1,"device_id": 17}])

	def test_addon_grants_uart_and_pins_pymodbus(self) -> None:
		addon=yaml.safe_load((ROOT/"deye-solarman-diagnostics/config.yaml").read_text(encoding="utf-8"))
		requirements=(ROOT/"deye-solarman-diagnostics/rootfs/requirements.txt").read_text(encoding="utf-8").splitlines()

		self.assertIs(addon["uart"],True)
		self.assertIn("pymodbus==3.14.0",requirements)


if __name__ == "__main__":
	unittest.main()
