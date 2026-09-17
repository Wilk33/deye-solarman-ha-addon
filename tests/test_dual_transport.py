import json
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"packages"))

from deye_inverter_core.config import load_config
from deye_inverter_core.models import Rs485Config
from deye_inverter_core.models import SolarmanConfig
from deye_inverter_core.models import TransportPollingConfig


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


if __name__ == "__main__":
	unittest.main()
