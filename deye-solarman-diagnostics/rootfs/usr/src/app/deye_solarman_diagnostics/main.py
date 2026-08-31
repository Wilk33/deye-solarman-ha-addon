from __future__ import annotations

import logging
import time
from typing import Any

from .codec import apply_transform
from .codec import decode_registers
from .config import load_config
from .definitions import load_sensor_definitions
from .logging_utils import configure_logging
from .models import SensorDefinition
from .models import SensorState
from .models import PollingConfig
from .mqtt import MqttPublisher
from .scheduler import group_sensors_for_read
from .solarman import SolarmanClient
from .storage import load_state
from .storage import save_scan_report
from .storage import save_state


LOGGER=logging.getLogger(__name__)


def main() -> None:
	configure_logging()
	config=load_config()
	sensors=load_sensor_definitions(config.profiles.default_profile, config.profiles.overrides_file)
	state=load_state(config.profiles.state_file)

	for sensor in sensors:
		state.setdefault(sensor.key, SensorState())

	solarman=SolarmanClient(config.logger)
	mqtt=MqttPublisher(config.mqtt, config.inverter)

	try:
		solarman.connect()
		probe_values=solarman.probe(
			config.polling.startup_probe_register,
			config.polling.startup_probe_count,
		)
		LOGGER.info(
			"Startup probe ok register=%s count=%s values=%s",
			config.polling.startup_probe_register,
			config.polling.startup_probe_count,
			probe_values,
		)

		mqtt.connect()
		for sensor in sensors:
			if sensor.enabled:
				mqtt.publish_discovery(sensor)

		while True:
			iteration_report=run_iteration(
				sensors,
				state,
				solarman,
				mqtt,
				config.polling,
				config.advanced.emit_raw_topics,
			)
			save_state(config.profiles.state_file, state)
			if config.advanced.emit_scan_report:
				save_scan_report(config.profiles.scan_report_file, iteration_report)
			time.sleep(config.polling.default_interval)
	except KeyboardInterrupt:
		LOGGER.info("Stopping add-on")
	finally:
		mqtt.disconnect()
		solarman.disconnect()


def run_iteration(
	sensors: list[SensorDefinition],
	state: dict[str, SensorState],
	solarman: SolarmanClient,
	mqtt: MqttPublisher,
	polling: PollingConfig,
	emit_raw_topics: bool,
) -> list[dict[str, Any]]:
	report: list[dict[str, Any]]=[]
	due_sensors=[
		sensor
		for sensor in sensors
		if sensor.enabled and _is_due(sensor, state[sensor.key])
	]
	groups=group_sensors_for_read(due_sensors, polling)

	for group in groups:
		group_start=group[0].registers[0]
		group_end=max(sensor.registers[-1] for sensor in group)
		count=group_end-group_start+1

		try:
			start=time.perf_counter()
			values=solarman.read_holding_registers(group_start, count)
			latency_ms=(time.perf_counter()-start)*1000
		except Exception as exc:
			LOGGER.warning("Read failed start=%s count=%s error=%s", group_start, count, exc)
			for sensor in group:
				current_state=state[sensor.key]
				current_state.last_status="timeout"
				current_state.timeout_count+=1
				report.append(
					{
						"sensor": sensor.key,
						"status": "timeout",
						"error": str(exc),
					}
				)
			continue

		for sensor in group:
			report.append(_handle_sensor(sensor, values, group_start, latency_ms, state[sensor.key], mqtt, emit_raw_topics))

	return report


def _is_due(sensor: SensorDefinition, sensor_state: SensorState) -> bool:
	if sensor_state.last_read_at == 0:
		return True
	return time.time()-sensor_state.last_read_at >= sensor.read_every


def _handle_sensor(
	sensor: SensorDefinition,
	group_values: list[int],
	group_start: int,
	latency_ms: float,
	sensor_state: SensorState,
	mqtt: MqttPublisher,
	emit_raw_topics: bool,
) -> dict[str, Any]:
	offset_start=sensor.registers[0]-group_start
	offset_end=offset_start+len(sensor.registers)
	raw_values=group_values[offset_start:offset_end]
	decoded=decode_registers(raw_values, sensor.register_type, sensor.word_order)
	value=apply_transform(decoded, sensor.multiplier, sensor.offset)
	now=time.time()

	sensor_state.last_value=value
	sensor_state.last_read_at=now
	sensor_state.last_status="supported"
	sensor_state.raw_registers=raw_values
	sensor_state.latency_ms=latency_ms

	should_publish=_should_publish(sensor, sensor_state, now, value)
	if should_publish:
		attributes={
			"raw_registers": raw_values,
			"decoded": decoded,
			"registers": sensor.registers,
			"type": sensor.register_type,
			"multiplier": sensor.multiplier,
			"offset": sensor.offset,
			"unit": sensor.unit,
			"word_order": sensor.word_order,
			"read_every": sensor.read_every,
			"report_every": sensor.report_every,
			"latency_ms": round(latency_ms,2),
			"last_read_at": int(now),
			"timeout_count": sensor_state.timeout_count,
		}
		mqtt.publish_state(sensor, value, attributes)
		if emit_raw_topics:
			mqtt.publish_raw(sensor, raw_values)
		sensor_state.last_published_at=now
		sensor_state.last_published_value=value

	return {
		"sensor": sensor.key,
		"name": sensor.name,
		"registers": sensor.registers,
		"raw": raw_values,
		"decoded": decoded,
		"value": value,
		"status": "supported",
		"latency_ms": round(latency_ms,2),
	}


def _should_publish(
	sensor: SensorDefinition,
	sensor_state: SensorState,
	now: float,
	value: int | float | str,
) -> bool:
	if sensor_state.last_published_value is None:
		return True
	if isinstance(value, str):
		return value != sensor_state.last_published_value
	if abs(float(value)-float(sensor_state.last_published_value)) >= sensor.change_by:
		return True
	return now-sensor_state.last_published_at >= sensor.report_every
