from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import AdvancedConfig
from .models import AppConfig
from .models import InverterConfig
from .models import LoggerConfig
from .models import MqttConfig
from .models import PollingConfig
from .models import ProfilesConfig


OPTIONS_PATH=Path("/data/options.json")


def _read_options(path: Path=OPTIONS_PATH) -> dict[str, Any]:
	with path.open("r", encoding="utf-8") as handle:
		return json.load(handle)


def load_config(path: Path=OPTIONS_PATH) -> AppConfig:
	options=_read_options(path)

	logger=options["logger"]
	mqtt=options["mqtt"]
	inverter=options["inverter"]
	profiles=options["profiles"]
	polling=options["polling"]
	advanced=options["advanced"]

	default_profile=profiles["default_profile"]
	if isinstance(default_profile, str):
		default_profile=[default_profile]

	return AppConfig(
		logger=LoggerConfig(
			host=logger["host"],
			port=int(logger["port"]),
			serial_number=int(logger["serial_number"]),
			modbus_id=int(logger["modbus_id"]),
			timeout=int(logger["timeout"]),
			reconnect_delay=int(logger["reconnect_delay"]),
		),
		mqtt=MqttConfig(
			host=mqtt["host"],
			port=int(mqtt["port"]),
			username=mqtt.get("username",""),
			password=mqtt.get("password",""),
			client_id=mqtt["client_id"],
			base_topic=mqtt["base_topic"].strip("/"),
			discovery_prefix=mqtt["discovery_prefix"].strip("/"),
			retain=bool(mqtt["retain"]),
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
	)
