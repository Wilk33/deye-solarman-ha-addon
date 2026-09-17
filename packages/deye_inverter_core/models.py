from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


TRANSPORT_IDS=("solarman_tcp","modbus_rtu")


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
	tls: bool=False
	source: str="manual"


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
	custom_sensors_file: str
	state_file: str
	scan_report_file: str


@dataclass(slots=True)
class TransportPollingConfig:
	default_interval: int
	slow_interval: int
	read_message_spacing: float
	batch_gap: int
	max_registers_per_request: int
	publish_unchanged_every: int
	startup_probe_register: int
	startup_probe_count: int
	allow_reconnect: bool


PollingConfig=TransportPollingConfig


@dataclass(slots=True)
class SolarmanConfig:
	enabled: bool
	host: str
	port: int
	serial_number: int
	modbus_id: int
	timeout: int
	reconnect_delay: int
	polling: TransportPollingConfig


@dataclass(slots=True)
class Rs485Config:
	enabled: bool
	device: str
	baudrate: int
	bytesize: int
	parity: str
	stopbits: float
	modbus_id: int
	timeout: float
	reconnect_delay: int
	polling: TransportPollingConfig


@dataclass(slots=True)
class AdvancedConfig:
	emit_raw_topics: bool
	emit_scan_report: bool
	detailed_logs: bool=False


@dataclass(slots=True)
class ScanConfig:
	mode: str
	report_file: str
	detected_sensors_file: str
	bms_pack_count: int


@dataclass(slots=True)
class CatalogConfig:
	refresh_on_start: bool
	url: str
	cache_file: str
	timeout: int
	control_url: str=""
	control_cache_file: str=""


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
	byte_order: str="high_low"
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
	formula: str=""
	attributes: dict[str, Any]=field(default_factory=dict)
	transport: str="solarman_tcp"
	transports: list[str]=field(default_factory=lambda:list(TRANSPORT_IDS))

	def __post_init__(self) -> None:
		if (
			not isinstance(self.transports,list)
			or not self.transports
			or any(transport not in TRANSPORT_IDS for transport in self.transports)
			or len(set(self.transports)) != len(self.transports)
		):
			raise ValueError("Sensor transports must be a non-empty list of unique known transport ids")
		if self.transport not in self.transports:
			raise ValueError("Sensor transport must be one of the allowed transports")


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
	solarman: SolarmanConfig
	rs485: Rs485Config
	mqtt: MqttConfig
	inverter: InverterConfig
	profiles: ProfilesConfig
	advanced: AdvancedConfig
	scan: ScanConfig
	catalog: CatalogConfig

	@property
	def logger(self) -> SolarmanConfig:
		return self.solarman

	@property
	def polling(self) -> TransportPollingConfig:
		return self.solarman.polling
