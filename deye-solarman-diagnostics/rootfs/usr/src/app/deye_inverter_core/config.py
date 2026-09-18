from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import AdvancedConfig
from .models import AppConfig
from .models import CatalogConfig
from .models import InverterConfig
from .models import MqttConfig
from .models import ProfilesConfig
from .models import Rs485Config
from .models import ScanConfig
from .models import SolarmanConfig
from .models import TransportPollingConfig
from .supervisor import discover_mqtt_service


OPTIONS_PATH=Path("/data/options.json")
BUILTIN_SENSOR_PROFILES=["deye_battery_packs"]


def _read_options(path: Path=OPTIONS_PATH) -> dict[str, Any]:
	with path.open("r", encoding="utf-8") as handle:
		return json.load(handle)


def _default_polling() -> dict[str, Any]:
	return {
		"default_interval": 60,
		"slow_interval": 600,
		"read_message_spacing": 0.05,
		"batch_gap": 1,
		"max_registers_per_request": 20,
		"publish_unchanged_every": 900,
		"startup_probe_register": 10040,
		"startup_probe_count": 1,
		"allow_reconnect": True,
	}


def _parse_polling(polling: dict[str, Any]) -> TransportPollingConfig:
	return TransportPollingConfig(
		default_interval=int(polling["default_interval"]),
		slow_interval=int(polling["slow_interval"]),
		read_message_spacing=float(polling["read_message_spacing"]),
		batch_gap=int(polling["batch_gap"]),
		max_registers_per_request=int(polling["max_registers_per_request"]),
		publish_unchanged_every=int(polling["publish_unchanged_every"]),
		startup_probe_register=int(polling["startup_probe_register"]),
		startup_probe_count=int(polling["startup_probe_count"]),
		allow_reconnect=bool(polling["allow_reconnect"]),
	)


def load_config(path: Path=OPTIONS_PATH) -> AppConfig:
	options=_read_options(path)

	legacy_config="solarman" not in options
	if legacy_config:
		logger=options["logger"]
		solarman={**logger,"enabled": True,"polling": options["polling"]}
	else:
		solarman=options["solarman"]
	rs485=options.get(
		"rs485",
		{
			"enabled": False,
			"device": "/dev/ttyUSB0",
			"baudrate": 9600,
			"bytesize": 8,
			"parity": "N",
			"stopbits": 1,
			"modbus_id": 1,
			"timeout": 1,
			"reconnect_delay": 10,
			"polling": _default_polling(),
		},
	)
	mqtt=options["mqtt"]
	supervisor_mqtt=discover_mqtt_service() if mqtt.get("use_supervisor",True) else None
	mqtt_connection=supervisor_mqtt or mqtt
	inverter=options.get("inverter") or {
		"serial_number":options.get("inverter_serial_number","2507092018"),
		"name":options.get("inverter_name","SolarMan Diagnostics"),
		"manufacturer":options.get("inverter_manufacturer","Deye"),
		"model":options.get("inverter_model","SG05LP3"),
	}
	profiles=options.get("profiles") or {
		"overrides_file":options.get("overrides_file","/config/user_sensors.yaml"),
		"custom_sensors_file":options.get("custom_sensors_file","/config/custom_sensors.yaml"),
		"state_file":options.get("state_file","/config/runtime_state.json"),
		"scan_report_file":options.get("scan_report_file","/share/deye_solarman_scan_report.json"),
	}
	advanced=options.get("advanced") or {
		"emit_raw_topics":options.get("emit_raw_topics",True),
		"emit_scan_report":options.get("emit_scan_report",True),
		"detailed_logs":options.get("detailed_logs",False),
	}
	scan=options.get("scan") or {
		"mode":options.get("scan_mode","disabled"),
		"report_file":options.get("scan_candidate_report_file","/share/deye_solarman_candidate_scan.json"),
		"detected_sensors_file":options.get("detected_sensors_file","/config/detected_sensors.yaml"),
		"bms_pack_count":options.get("bms_pack_count",4),
	}
	catalog=options.get(
		"catalog",
		{
			"refresh_on_start": True,
			"url": "https://raw.githubusercontent.com/Wilk33/deye-solarman-ha-addon/main/deye-solarman-diagnostics/deye_sg04_sg05_3ph_lv_catalog.yaml",
			"cache_file": "/config/deye_solarman_catalog.yaml",
			"control_url": "https://raw.githubusercontent.com/Wilk33/deye-solarman-ha-addon/main/catalogs/models/deye_sg04_sg05_3ph_lv/control.yaml",
			"control_cache_file": "/config/deye_solarman_control_catalog.yaml",
			"timeout": 5,
		},
	)

	solarman_enabled=bool(solarman["enabled"])
	rs485_enabled=bool(rs485["enabled"])
	if not solarman_enabled and not rs485_enabled:
		raise ValueError("at least one transport must be enabled")
	solarman_serial_number=int(solarman["serial_number"])
	if solarman_enabled and solarman_serial_number <= 0:
		field="logger.serial_number" if legacy_config else "solarman.serial_number"
		raise ValueError(f"{field} must be the positive serial number of the Solarman logger")
	if scan["mode"] not in {"disabled","scan_only","scan_and_monitor"}:
		raise ValueError("scan.mode must be disabled, scan_only, or scan_and_monitor")
	if not 1 <= int(scan["bms_pack_count"]) <= 10:
		raise ValueError("scan.bms_pack_count must be between 1 and 10")
	if not 1 <= int(catalog["timeout"]) <= 30:
		raise ValueError("catalog.timeout must be between 1 and 30")

	return AppConfig(
		solarman=SolarmanConfig(
			enabled=solarman_enabled,
			host=str(solarman["host"]),
			port=int(solarman["port"]),
			serial_number=solarman_serial_number,
			modbus_id=int(solarman["modbus_id"]),
			timeout=int(solarman["timeout"]),
			reconnect_delay=int(solarman["reconnect_delay"]),
			polling=_parse_polling(solarman["polling"]),
		),
		rs485=Rs485Config(
			enabled=rs485_enabled,
			device=str(rs485["device"]),
			baudrate=int(rs485["baudrate"]),
			bytesize=int(rs485["bytesize"]),
			parity=str(rs485["parity"]).upper(),
			stopbits=float(rs485["stopbits"]),
			modbus_id=int(rs485["modbus_id"]),
			timeout=float(rs485["timeout"]),
			reconnect_delay=int(rs485["reconnect_delay"]),
			polling=_parse_polling(rs485["polling"]),
		),
		mqtt=MqttConfig(
			host=mqtt_connection["host"],
			port=int(mqtt_connection["port"]),
			username=mqtt_connection.get("username",""),
			password=mqtt_connection.get("password",""),
			client_id=mqtt["client_id"],
			base_topic=mqtt["base_topic"].strip("/"),
			discovery_prefix=mqtt["discovery_prefix"].strip("/"),
			retain=bool(mqtt["retain"]),
			tls=bool(mqtt_connection.get("tls",mqtt.get("tls",False))),
			source="supervisor" if supervisor_mqtt else "manual",
		),
		inverter=InverterConfig(
			serial_number=str(inverter["serial_number"]),
			name=inverter["name"],
			manufacturer=inverter["manufacturer"],
			model=inverter["model"],
		),
		profiles=ProfilesConfig(
			default_profile=list(BUILTIN_SENSOR_PROFILES),
			overrides_file=profiles["overrides_file"],
			custom_sensors_file=profiles.get("custom_sensors_file","/config/custom_sensors.yaml"),
			state_file=profiles["state_file"],
			scan_report_file=profiles["scan_report_file"],
		),
		advanced=AdvancedConfig(
			emit_raw_topics=bool(advanced["emit_raw_topics"]),
			emit_scan_report=bool(advanced["emit_scan_report"]),
			detailed_logs=bool(advanced.get("detailed_logs",False)),
		),
		scan=ScanConfig(
			mode=scan["mode"],
			report_file=scan["report_file"],
			detected_sensors_file=scan["detected_sensors_file"],
			bms_pack_count=int(scan["bms_pack_count"]),
		),
		catalog=CatalogConfig(
			refresh_on_start=bool(catalog["refresh_on_start"]),
			url=str(catalog["url"]),
			cache_file=str(catalog["cache_file"]),
			timeout=int(catalog["timeout"]),
			control_url=str(catalog.get("control_url","")).strip(),
			control_cache_file=str(catalog.get("control_cache_file","/config/deye_solarman_control_catalog.yaml")),
		),
	)
