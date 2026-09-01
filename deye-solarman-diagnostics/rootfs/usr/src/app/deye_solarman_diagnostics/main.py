from __future__ import annotations

from contextlib import nullcontext
import logging
import threading
import time
from typing import Any

from .codec import apply_transform
from .codec import decode_registers
from .codec import registers_to_ascii
from .config import load_config
from .definitions import load_sensor_definitions
from .logging_utils import configure_logging
from .logging_utils import success
from .models import SensorDefinition
from .models import SensorState
from .models import PollingConfig
from .mqtt import MqttPublisher
from .scheduler import group_sensors_for_read
from .scan_catalog import load_scan_candidates
from .remote_catalog import RemoteCatalog
from .remote_catalog import load_remote_catalog
from .scanner import clear_detected_sensors
from .scanner import clear_pending_discovery_removals
from .scanner import load_pending_discovery_removals
from .scanner import reset_detected_sensors
from .scanner import save_detected_sensors
from .scanner import scan_candidates
from .solarman import SolarmanClient
from .solarman import SolarmanConnectionClosedError
from .storage import load_state
from .storage import save_scan_report
from .storage import save_state
from .web import IngressPanel


LOGGER=logging.getLogger(__name__)


def main() -> None:
	configure_logging()
	config=load_config()
	access_lock=threading.Lock()
	catalog_lock=threading.Lock()
	catalog_state={"current": load_remote_catalog(config.catalog)}

	def current_catalog() -> RemoteCatalog:
		with catalog_lock:
			return catalog_state["current"]

	def refresh_catalog() -> RemoteCatalog:
		catalog=load_remote_catalog(config.catalog,force_refresh=True)
		with catalog_lock:
			catalog_state["current"]=catalog
		return catalog

	panel=IngressPanel(
		config.scan.detected_sensors_file,
		lambda: _run_manual_scan(config,access_lock,current_catalog()),
		lambda: _reset_panel_configuration(config,current_catalog()),
		lambda: _clear_panel_sensors(config,refresh_catalog()),
	)
	panel.start()
	try:
		_run_addon(config,access_lock,current_catalog())
	finally:
		panel.stop()


def _run_addon(config: Any, access_lock: Any, remote_catalog: RemoteCatalog) -> None:
	sensors=load_sensor_definitions(
		config.profiles.default_profile,
		config.profiles.overrides_file,
		config.scan.detected_sensors_file,
	)
	state=load_state(config.profiles.state_file)

	for sensor in sensors:
		state.setdefault(sensor.key, SensorState())
	success(
		LOGGER,
		"Sensor configuration loaded total=%s enabled=%s selected_file=%s",
		len(sensors),
		sum(sensor.enabled for sensor in sensors),
		config.scan.detected_sensors_file,
	)

	while True:
		solarman=SolarmanClient(config.logger)
		mqtt=MqttPublisher(config.mqtt, config.inverter)
		try:
			with access_lock:
				solarman.connect()
				probe_values=solarman.probe(
					config.polling.startup_probe_register,
					config.polling.startup_probe_count,
				)
			success(
				LOGGER,
				"Startup probe ok register=%s count=%s values=%s",
				config.polling.startup_probe_register,
				config.polling.startup_probe_count,
				probe_values,
			)
			if config.scan.mode != "disabled":
				with access_lock:
					scan_report=scan_candidates(
						load_scan_candidates(config.scan.bms_pack_count,remote_catalog),
						solarman,
						config.polling,
					)
				save_scan_report(config.scan.report_file, scan_report)
				save_detected_sensors(config.scan.detected_sensors_file, scan_report)
				_log_scan_summary(scan_report, config.scan.detected_sensors_file)
				if config.scan.mode == "scan_only":
					LOGGER.info("Scan complete. MQTT publishing is disabled while the Ingress panel remains available.")
					_wait_for_stop()
				sensors=load_sensor_definitions(
					config.profiles.default_profile,
					config.profiles.overrides_file,
					config.scan.detected_sensors_file,
				)
				for sensor in sensors:
					state.setdefault(sensor.key, SensorState())

			mqtt.connect()
			pending_removals=load_pending_discovery_removals(config.scan.detected_sensors_file)
			for sensor_key in pending_removals:
				mqtt.remove_discovery(sensor_key)
			if pending_removals:
				clear_pending_discovery_removals(config.scan.detected_sensors_file)
				success(LOGGER,"Removed MQTT Discovery entities=%s",len(pending_removals))
			enabled_sensors=[sensor for sensor in sensors if sensor.enabled]
			LOGGER.info(
				"Publishing MQTT Discovery sensors=%s prefix=%s inverter_serial=%s",
				len(enabled_sensors),
				config.mqtt.discovery_prefix,
				config.inverter.serial_number,
			)
			for sensor in enabled_sensors:
				mqtt.publish_discovery(sensor)

			while True:
				iteration_report=run_iteration(
					sensors,
					state,
					solarman,
					mqtt,
					config.polling,
					config.advanced.emit_raw_topics,
					access_lock,
				)
				save_state(config.profiles.state_file, state)
				if config.advanced.emit_scan_report:
					save_scan_report(config.profiles.scan_report_file, iteration_report)
				time.sleep(config.polling.default_interval)
		except KeyboardInterrupt:
			LOGGER.info("Stopping add-on")
			return
		except Exception:
			LOGGER.exception("Add-on cycle failed")
			if not config.polling.allow_reconnect:
				raise
			LOGGER.info("Retrying connection in %s seconds", config.logger.reconnect_delay)
		finally:
			mqtt.disconnect()
			solarman.disconnect()

		if config.polling.allow_reconnect:
			time.sleep(config.logger.reconnect_delay)


def _run_manual_scan(config: Any, access_lock: Any, remote_catalog: RemoteCatalog) -> dict[str, Any]:
	solarman=SolarmanClient(config.logger)
	try:
		with access_lock:
			solarman.connect()
			probe_values=solarman.probe(
				config.polling.startup_probe_register,
				config.polling.startup_probe_count,
			)
			success(LOGGER,"Manual panel scan probe values=%s",probe_values)
			scan_report=scan_candidates(
				load_scan_candidates(config.scan.bms_pack_count,remote_catalog),
				solarman,
				config.polling,
			)
		save_scan_report(config.scan.report_file, scan_report)
		save_detected_sensors(config.scan.detected_sensors_file, scan_report)
		_log_scan_summary(scan_report,config.scan.detected_sensors_file)
		statuses: dict[str,int]={}
		for result in scan_report:
			status=str(result["status"])
			statuses[status]=statuses.get(status,0)+1
		return {"count": len(scan_report),"statuses": statuses}
	finally:
		solarman.disconnect()


def _reset_panel_configuration(config: Any, remote_catalog: RemoteCatalog) -> dict[str, Any]:
	payload=reset_detected_sensors(
		config.scan.detected_sensors_file,
		load_scan_candidates(config.scan.bms_pack_count,remote_catalog),
	)
	success(
		LOGGER,
		"Panel reset detected sensor configuration sensors=%s catalog_source=%s",
		len(payload["available_sensors"]),
		remote_catalog.source,
	)
	return payload


def _clear_panel_sensors(config: Any, remote_catalog: RemoteCatalog) -> dict[str, Any]:
	payload=clear_detected_sensors(config.scan.detected_sensors_file)
	success(LOGGER,"Panel cleared detected sensors catalog_source=%s",remote_catalog.source)
	return payload


def _wait_for_stop() -> None:
	while True:
		time.sleep(3600)


def _log_scan_summary(report: list[dict[str, Any]], detected_sensors_file: str) -> None:
	statuses: dict[str, int]={}
	for result in report:
		status=str(result["status"])
		statuses[status]=statuses.get(status,0)+1
	success(
		LOGGER,
		"Candidate scan complete results=%s file=%s",
		", ".join(f"{status}={count}" for status,count in sorted(statuses.items())),
		detected_sensors_file,
	)


def run_iteration(
	sensors: list[SensorDefinition],
	state: dict[str, SensorState],
	solarman: SolarmanClient,
	mqtt: MqttPublisher,
	polling: PollingConfig,
	emit_raw_topics: bool,
	read_lock: Any | None=None,
) -> list[dict[str, Any]]:
	report: list[dict[str, Any]]=[]
	failed_groups=0
	due_sensors=[
		sensor
		for sensor in sensors
		if sensor.enabled and _is_due(sensor, state[sensor.key], polling)
	]
	groups=group_sensors_for_read(due_sensors, polling)

	for index, group in enumerate(groups):
		group_start=min(register for sensor in group for register in sensor.registers)
		group_end=max(register for sensor in group for register in sensor.registers)
		count=group_end-group_start+1

		try:
			start=time.perf_counter()
			with read_lock if read_lock is not None else nullcontext():
				values=solarman.read_holding_registers(group_start, count)
			latency_ms=(time.perf_counter()-start)*1000
		except SolarmanConnectionClosedError as error:
			LOGGER.warning("Solarman TCP session closed start=%s count=%s; reconnecting",group_start,count)
			raise error
		except Exception as exc:
			LOGGER.warning("Read failed start=%s count=%s error=%s", group_start, count, exc)
			failed_groups+=1
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
			if index < len(groups)-1 and polling.read_message_spacing > 0:
				time.sleep(polling.read_message_spacing)
			continue

		for sensor in group:
			report.append(
				_handle_sensor(
					sensor,
					values,
					group_start,
					latency_ms,
					state[sensor.key],
					mqtt,
					emit_raw_topics,
					polling.publish_unchanged_every,
				)
			)

		if index < len(groups)-1 and polling.read_message_spacing > 0:
			time.sleep(polling.read_message_spacing)

	if groups and failed_groups == len(groups):
		raise ConnectionError("All due Solarman register groups failed; reconnecting")

	return report


def _is_due(sensor: SensorDefinition, sensor_state: SensorState, polling: PollingConfig) -> bool:
	if sensor_state.last_read_at == 0:
		return True
	interval=polling.slow_interval if sensor.schedule == "slow" else sensor.read_every
	return time.time()-sensor_state.last_read_at >= interval


def _handle_sensor(
	sensor: SensorDefinition,
	group_values: list[int],
	group_start: int,
	latency_ms: float,
	sensor_state: SensorState,
	mqtt: MqttPublisher,
	emit_raw_topics: bool,
	publish_unchanged_every: int,
) -> dict[str, Any]:
	raw_values=[group_values[register-group_start] for register in sensor.registers]
	decoded=decode_registers(raw_values, sensor.register_type, sensor.word_order)
	value=apply_transform(decoded, sensor.multiplier, sensor.offset)
	now=time.time()

	sensor_state.last_value=value
	sensor_state.last_read_at=now
	sensor_state.last_status="supported"
	sensor_state.raw_registers=raw_values
	sensor_state.latency_ms=latency_ms

	should_publish=_should_publish(sensor, sensor_state, now, value, publish_unchanged_every)
	if should_publish:
		attributes={
			"raw_registers": raw_values,
			"raw_ascii": registers_to_ascii(raw_values),
			"decoded": decoded,
			"registers": sensor.registers,
			"type": sensor.register_type,
			"multiplier": sensor.multiplier,
			"offset": sensor.offset,
			"unit": sensor.unit,
			"word_order": sensor.word_order,
			"schedule": sensor.schedule,
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
	publish_unchanged_every: int,
) -> bool:
	if sensor_state.last_published_value is None:
		return True
	if isinstance(value, str):
		return value != sensor_state.last_published_value
	if abs(float(value)-float(sensor_state.last_published_value)) >= sensor.change_by:
		return True
	report_interval=min(sensor.report_every, publish_unchanged_every)
	return now-sensor_state.last_published_at >= report_interval
