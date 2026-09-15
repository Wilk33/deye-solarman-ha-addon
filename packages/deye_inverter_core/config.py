from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import AdvancedConfig
from .models import AppConfig
from .models import CatalogConfig
from .models import InverterConfig
from .models import LoggerConfig
from .models import MqttConfig
from .models import PollingConfig
from .models import ProfilesConfig
from .models import ScanConfig
from .supervisor import discover_mqtt_service


OPTIONS_PATH=Path("/data/options.json")


def _read_options(path: Path=OPTIONS_PATH) -> dict[str, Any]:
	with path.open("r", encoding="utf-8") as handle:
		return json.load(handle)


def load_config(path: Path=OPTIONS_PATH) -> AppConfig:
	options=_read_options(path)

	logger=options["logger"]
	mqtt=options["mqtt"]
	supervisor_mqtt=discover_mqtt_service() if mqtt.get("use_supervisor",True) else None
	mqtt_connection=supervisor_mqtt or mqtt
	inverter=options["inverter"]
	profiles=options["profiles"]
	polling=options["polling"]
	advanced=options["advanced"]
	scan=options.get(
		"scan",
		{
			"mode": "disabled",
			"report_file": "/share/deye_solarman_candidate_scan.json",
			"detected_sensors_file": "/config/detected_sensors.yaml",
			"bms_pack_count": 4,
		},
	)
	catalog=options.get(
		"catalog",
		{
			"refresh_on_start": True,
			"url": "https://raw.githubusercontent.com/Wilk33/deye-solarman-ha-addon/main/deye-solarman-diagnostics/deye_sg04_sg05_3ph_lv_catalog.yaml",
			"cache_file": "/config/deye_solarman_catalog.yaml",
			"timeout": 5,
		},
	)

	default_profile=profiles["default_profile"]
	if isinstance(default_profile, str):
		default_profile=[default_profile]
	logger_serial_number=int(logger["serial_number"])
	if logger_serial_number <= 0:
		raise ValueError("logger.serial_number must be the positive serial number of the Solarman logger")
	if scan["mode"] not in {"disabled","scan_only","scan_and_monitor"}:
		raise ValueError("scan.mode must be disabled, scan_only, or scan_and_monitor")
	if not 1 <= int(scan["bms_pack_count"]) <= 10:
		raise ValueError("scan.bms_pack_count must be between 1 and 10")
	if not 1 <= int(catalog["timeout"]) <= 30:
		raise ValueError("catalog.timeout must be between 1 and 30")

	return AppConfig(
		logger=LoggerConfig(
			host=logger["host"],
			port=int(logger["port"]),
			serial_number=logger_serial_number,
			modbus_id=int(logger["modbus_id"]),
			timeout=int(logger["timeout"]),
			reconnect_delay=int(logger["reconnect_delay"]),
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
			default_profile=list(default_profile),
			overrides_file=profiles["overrides_file"],
			custom_sensors_file=profiles.get("custom_sensors_file","/config/custom_sensors.yaml"),
			state_file=profiles["state_file"],
			scan_report_file=profiles["scan_report_file"],
		),
		polling=PollingConfig(
			default_interval=int(polling["default_interval"]),
			slow_interval=int(polling["slow_interval"]),
			read_message_spacing=float(polling["read_message_spacing"]),
			batch_gap=int(polling["batch_gap"]),
			max_registers_per_request=int(polling["max_registers_per_request"]),
			publish_unchanged_every=int(polling["publish_unchanged_every"]),
			startup_probe_register=int(polling["startup_probe_register"]),
			startup_probe_count=int(polling["startup_probe_count"]),
			allow_reconnect=bool(polling["allow_reconnect"]),
		),
		advanced=AdvancedConfig(
			emit_raw_topics=bool(advanced["emit_raw_topics"]),
			emit_scan_report=bool(advanced["emit_scan_report"]),
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
		),
	)
