from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class LoggerConfig:
	host: str
	port: int
	serial_number: int
	modbus_id: int
	timeout: int
	reconnect_delay: int


@dataclass(slots=True)
class MqttConfig:
	host: str
	port: int
	username: str
	password: str
	client_id: str
	base_topic: str
	discovery_prefix: str
	retain: bool


@dataclass(slots=True)
class InverterConfig:
	serial_number: str
	name: str
	manufacturer: str
	model: str


@dataclass(slots=True)
class ProfilesConfig:
	default_profile: list[str]
	overrides_file: str
	state_file: str
	scan_report_file: str


@dataclass(slots=True)
class PollingConfig:
	default_interval: int
	slow_interval: int
	read_message_spacing: float
	batch_gap: int
	max_registers_per_request: int
	publish_unchanged_every: int
	startup_probe_register: int
	startup_probe_count: int
	allow_reconnect: bool


@dataclass(slots=True)
class AdvancedConfig:
	emit_raw_topics: bool
	emit_scan_report: bool


@dataclass(slots=True)
class ScanConfig:
	mode: str
	report_file: str
	detected_sensors_file: str
	bms_pack_count: int


@dataclass(slots=True)
class SensorDefinition:
	key: str
	name: str
	registers: list[int]
	register_type: str
	multiplier: float=1.0
	offset: float=0.0
	unit: str=""
	word_order: str="high_low"
	schedule: str="default"
	read_every: int=60
	report_every: int=300
	change_by: float=0.0
	enabled: bool=True
	retain: bool=True
	device_class: str=""
	state_class: str=""
	icon: str=""
	category: str=""
	topic_suffix: str=""
	attributes: dict[str, Any]=field(default_factory=dict)


@dataclass(slots=True)
class SensorState:
	last_value: float | int | str | None=None
	last_published_value: float | int | str | None=None
	last_read_at: float=0.0
	last_published_at: float=0.0
	last_status: str="never_read"
	timeout_count: int=0
	raw_registers: list[int]=field(default_factory=list)
	latency_ms: float=0.0


@dataclass(slots=True)
class AppConfig:
	logger: LoggerConfig
	mqtt: MqttConfig
	inverter: InverterConfig
	profiles: ProfilesConfig
	polling: PollingConfig
	advanced: AdvancedConfig
	scan: ScanConfig
