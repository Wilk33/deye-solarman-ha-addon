from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml


APP_ROOT=Path(__file__).resolve().parents[1] / "deye-solarman-diagnostics" / "rootfs" / "usr" / "src" / "app"
sys.path.insert(0, str(APP_ROOT))

from deye_solarman_diagnostics.config import load_config
from deye_solarman_diagnostics.definitions import load_sensor_definitions
from deye_solarman_diagnostics.main import _handle_sensor
from deye_solarman_diagnostics.main import _is_due
from deye_solarman_diagnostics.main import run_iteration
from deye_solarman_diagnostics.models import InverterConfig
from deye_solarman_diagnostics.models import MqttConfig
from deye_solarman_diagnostics.models import PollingConfig
from deye_solarman_diagnostics.models import SensorDefinition
from deye_solarman_diagnostics.models import SensorState
from deye_solarman_diagnostics.mqtt import MqttPublisher
from deye_solarman_diagnostics.scheduler import group_sensors_for_read
from deye_solarman_diagnostics.scan_catalog import ScanCandidate
from deye_solarman_diagnostics.scan_catalog import load_scan_candidates
from deye_solarman_diagnostics.scanner import load_monitored_definitions
from deye_solarman_diagnostics.scanner import save_detected_sensors
from deye_solarman_diagnostics.scanner import scan_candidates
from deye_solarman_diagnostics.storage import load_state
from deye_solarman_diagnostics.storage import save_state


class FakeMqtt:
	def __init__(self) -> None:
		self.states: list[tuple[str, int | float | str, dict[str, object]]]=[]
		self.raw: list[tuple[str, list[int]]]=[]

	def publish_state(self, sensor: SensorDefinition, value: int | float | str, attributes: dict[str, object]) -> None:
		self.states.append((sensor.key, value, attributes))

	def publish_raw(self, sensor: SensorDefinition, raw_registers: list[int]) -> None:
		self.raw.append((sensor.key, raw_registers))


class FakePahoClient:
	def __init__(self) -> None:
		self.messages: list[tuple[str, object, bool]]=[]

	def publish(self, topic: str, payload: object, retain: bool=False) -> None:
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
	def test_config_accepts_profile_editor_scalar(self) -> None:
		with tempfile.TemporaryDirectory() as directory:
			options_path=Path(directory) / "options.json"
			options_path.write_text(json.dumps(make_options()), encoding="utf-8")
			config=load_config(options_path)

		self.assertEqual(config.profiles.default_profile, ["deye_battery_packs"])
		self.assertEqual(config.scan.mode, "disabled")

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

	def test_config_rejects_placeholder_logger_serial(self) -> None:
		with tempfile.TemporaryDirectory() as directory:
			options_path=Path(directory) / "options.json"
			options_path.write_text(json.dumps(make_options(0)), encoding="utf-8")

			with self.assertRaisesRegex(ValueError, "logger.serial_number"):
				load_config(options_path)

	def test_unknown_profile_fails_before_polling(self) -> None:
		with self.assertRaisesRegex(ValueError, "Unknown sensor profile"):
			load_sensor_definitions(["not_a_profile"], "does-not-exist.yaml")

	def test_catalog_covers_live_telemetry_and_configured_bms_packs(self) -> None:
		candidates=load_scan_candidates(4)
		by_key={candidate.sensor.key: candidate.sensor for candidate in candidates}

		self.assertEqual(len(candidates), 124)
		self.assertEqual(by_key["grid_power_total"].registers, [619])
		self.assertEqual(by_key["pv_energy_total"].registers, [534,535])
		self.assertEqual(by_key["pv_energy_total"].word_order, "low_high")
		self.assertEqual(by_key["battery_2_voltage"].registers, [10078])
		self.assertEqual(by_key["battery_4_cycles"].registers, [10170])
		self.assertEqual(by_key["battery_1_temperature"].offset, -100.0)
		self.assertEqual(by_key["battery_1_soc"].multiplier, 0.1)

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

	def test_scheduler_uses_actual_register_range(self) -> None:
		first=SensorDefinition("first", "First", [10042,10040], "uint32")
		second=SensorDefinition("second", "Second", [10043], "uint16")

		groups=group_sensors_for_read([first, second], make_polling())

		self.assertEqual(groups, [[first, second]])

	def test_slow_schedule_uses_global_slow_interval(self) -> None:
		sensor=SensorDefinition("soc", "SOC", [10047], "uint16", schedule="slow", read_every=30)
		state=SensorState(last_read_at=450)

		with patch("deye_solarman_diagnostics.main.time.time", return_value=1000):
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
