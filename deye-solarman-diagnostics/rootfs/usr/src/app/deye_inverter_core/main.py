from __future__ import annotations

from contextlib import nullcontext
from copy import deepcopy
from dataclasses import dataclass
import logging
import threading
import time
from typing import Any
from pathlib import Path

from .controls import ControlService, ControlRuntime, set_controls

from .codec import apply_transform
from .codec import decode_registers
from .codec import registers_to_ascii
from .config import load_config
from .configuration_coordinator import ConfigurationCoordinator
from .definitions import sensor_from_payload
from .definitions import load_sensor_definitions
from .formula import FormulaExecutor
from .formula import FormulaResult
from .logging_utils import configure_logging
from .logging_utils import success
from .models import SensorDefinition
from .models import SensorState
from .models import PollingConfig
from .mqtt import MqttPublisher
from .scheduler import group_sensors_for_read
from .scheduler import PerEntityScheduler
from .scan_catalog import load_scan_candidates
from .remote_catalog import RemoteCatalog
from .remote_catalog import load_remote_catalog
from .control_catalog import load_remote_control_catalog
from .scanner import clear_detected_sensors
from .scanner import clear_pending_discovery_removals
from .scanner import load_pending_discovery_removals
from .scanner import reset_detected_sensors
from .scanner import load_detected_sensors
from .scanner import save_detected_sensors
from .scanner import scan_transports_sequentially
from .transport import RegisterTransport, TransportFactory, TransportConnectionClosedError
from .transport_manager import TransportManager
from .transport_manager import TransportSlot
from .transport_runtime import TransportWorker
from .storage import load_state
from .storage import save_scan_report
from .storage import save_state
from .web import IngressPanel


LOGGER=logging.getLogger(__name__)


def build_transport_manager(
	config: Any,
	solarman_factory: TransportFactory,
	rs485_factory: TransportFactory,
) -> TransportManager:
	slots=[]
	if config.solarman.enabled:
		slots.append(TransportSlot(
			client=solarman_factory(config.solarman),
			polling=config.solarman.polling,
			reconnect_delay=config.solarman.reconnect_delay,
		))
	if config.rs485.enabled:
		slots.append(TransportSlot(
			client=rs485_factory(config.rs485),
			polling=config.rs485.polling,
			reconnect_delay=config.rs485.reconnect_delay,
		))
	return TransportManager(slots)


class SensorRuntime:
	"""Run one independently scheduled monitoring worker per active transport."""

	def __init__(
		self,
		manager: TransportManager,
		mqtt: Any,
		sensors: list[SensorDefinition],
		state: dict[str,SensorState],
		*,
		emit_raw_topics: bool=False,
		detailed_logs: bool=False,
		state_file: str | None=None,
		scan_report_file: str | None=None,
		emit_scan_report: bool=False,
		clock: Any=time.monotonic,
	) -> None:
		self.manager=manager
		self.mqtt=mqtt
		self.state=state
		self.emit_raw_topics=emit_raw_topics
		self.detailed_logs=detailed_logs
		self.state_file=state_file
		self.scan_report_file=scan_report_file
		self.emit_scan_report=emit_scan_report
		self.clock=clock
		self._configuration_lock=threading.RLock()
		self._state_lock=threading.RLock()
		self._generation=0
		self._stop=threading.Event()
		self._wake={slot.transport_id:threading.Event() for slot in manager.available()}
		self._threads: list[threading.Thread]=[]
		self._sensors: dict[str,tuple[SensorDefinition,...]]={}
		self._reports: dict[str,list[dict[str,Any]]]={}
		self._schedulers={}
		self._workers={}
		for slot in manager.available():
			transport_sensors=[sensor for sensor in sensors if sensor.enabled and sensor.transport == slot.transport_id]
			scheduler=PerEntityScheduler(transport_sensors,slot.polling,clock=clock)
			self._schedulers[slot.transport_id]=scheduler
			self._workers[slot.transport_id]=TransportWorker(
				manager,
				slot,
				scheduler,
				self._read_callback(slot),
				clock=clock,
			)
		self.reload(sensors)

	@property
	def worker_ids(self) -> tuple[str,...]:
		return tuple(slot.transport_id for slot in self.manager.available())

	def reload(self,sensors: list[SensorDefinition], *, reset_state: bool=False) -> None:
		with self._configuration_lock:
			self._generation+=1
			with self._state_lock:
				for sensor in sensors:
					current=self.state.setdefault(sensor.key,SensorState())
					if reset_state:
						current.last_read_at=0
						current.last_published_value=None
			for slot in self.manager.available():
				selected=tuple(sensor for sensor in sensors if sensor.enabled and sensor.transport == slot.transport_id)
				self._sensors[slot.transport_id]=selected
				self._schedulers[slot.transport_id].sync(selected,now=self.clock())
				self._wake[slot.transport_id].set()

	def start(self) -> None:
		if self._threads:
			return
		for transport_id in self.worker_ids:
			self._wake[transport_id].clear()
			thread=threading.Thread(
				target=self._worker_loop,
				args=(transport_id,),
				daemon=True,
				name=f"sensor-{transport_id}",
			)
			self._threads.append(thread)
			thread.start()

	def stop(self) -> None:
		self._stop.set()
		for event in self._wake.values():
			event.set()
		for thread in self._threads:
			thread.join()
		self._threads=[]

	def run_once(self,transport_id: str,now: float | None=None) -> list[dict[str,Any]] | None:
		try:
			batch=self._workers[transport_id].run_due(now)
		except (_SensorBatchFailure,_SensorBatchConnectionFailure) as failure:
			if not self._commit_batch(transport_id,failure.batch):
				self._schedulers[transport_id].make_due(
					(sensor.key for sensor in failure.batch.sensors),
					now=self.clock(),
				)
			error=failure.error
			for sensor in self._sensors.get(transport_id,()):
				self._safe_sensor_availability(sensor,False)
			if self.detailed_logs:
				LOGGER.exception("Transport worker failed transport=%s",transport_id)
			else:
				LOGGER.warning("Transport worker failed transport=%s error=%s",transport_id,error)
			return None
		except Exception as error:
			for sensor in self._sensors.get(transport_id,()):
				self._safe_sensor_availability(sensor,False)
			if self.detailed_logs:
				LOGGER.exception("Transport worker failed transport=%s",transport_id)
			else:
				LOGGER.warning("Transport worker failed transport=%s error=%s",transport_id,error)
			return None
		if batch is None:
			return None
		if not self._commit_batch(transport_id,batch):
			self._schedulers[transport_id].make_due((sensor.key for sensor in batch.sensors),now=self.clock())
			return None
		return batch.report

	def _read_callback(self,slot: TransportSlot):
		def read(client: RegisterTransport,sensors: tuple[SensorDefinition,...],mark_attempted: Any):
			with self._configuration_lock:
				generation=self._generation
				current={sensor.key:sensor for sensor in self._sensors.get(slot.transport_id,())}
				definitions_current=all(current.get(sensor.key) == sensor for sensor in sensors)
			with self._state_lock:
				local_state={sensor.key:deepcopy(self.state.setdefault(sensor.key,SensorState())) for sensor in sensors}
			if not definitions_current:
				return _SensorBatch(generation,sensors,[],local_state)
			mqtt=_GenerationMqtt(self,generation)
			report=[]
			try:
				run_iteration(
					list(sensors),
					local_state,
					client,
					mqtt,
					slot.polling,
					self.emit_raw_topics,
					detailed_logs=self.detailed_logs,
					force=True,
					mark_attempted=mark_attempted,
					should_stop=self._stop.is_set,
					report_sink=report,
				)
			except Exception as error:
				batch=_SensorBatch(generation,sensors,report,local_state)
				if isinstance(error,TransportConnectionClosedError):
					raise _SensorBatchConnectionFailure(error,batch) from error
				raise _SensorBatchFailure(error,batch) from error
			return _SensorBatch(generation,sensors,report,local_state)
		return read

	def _worker_loop(self,transport_id: str) -> None:
		wake=self._wake[transport_id]
		while not self._stop.is_set():
			wake.clear()
			try:
				self.run_once(transport_id)
			except Exception:
				LOGGER.exception("Unexpected sensor worker failure transport=%s",transport_id)
			if self._stop.is_set():
				break
			wait=self._workers[transport_id].wait_time()
			wake.wait(wait)

	def _safe_sensor_availability(self,sensor: SensorDefinition,available: bool) -> None:
		callback=getattr(self.mqtt,"sensor_availability",None)
		if callback is not None:
			try:
				callback(sensor,available)
			except Exception as error:
				LOGGER.warning("MQTT sensor availability failed sensor=%s error=%s",sensor.key,error)

	def _publish_if_current(self,generation: int,sensor: SensorDefinition,action: Any) -> bool:
		with self._configuration_lock:
			if generation != self._generation:
				return False
			current=next((item for item in self._sensors.get(sensor.transport,()) if item.key == sensor.key),None)
			if current != sensor:
				return False
			action()
			return True

	def _commit_batch(self,transport_id: str,batch: "_SensorBatch") -> bool:
		with self._configuration_lock:
			current={sensor.key:sensor for sensor in self._sensors.get(transport_id,())}
			if batch.generation != self._generation or any(current.get(sensor.key) != sensor for sensor in batch.sensors):
				return False
			with self._state_lock:
				self.state.update(batch.state)
				self._reports[transport_id]=deepcopy(batch.report)
				state_snapshot=deepcopy(self.state)
				report_snapshot=[
					deepcopy(item)
					for slot in self.manager.available()
					for item in self._reports.get(slot.transport_id,[])
				]
			if self.state_file:
				try:
					save_state(self.state_file,state_snapshot)
				except Exception as error:
					LOGGER.warning("Runtime state save failed file=%s error=%s",self.state_file,error)
			if self.emit_scan_report and self.scan_report_file:
				try:
					save_scan_report(self.scan_report_file,report_snapshot)
				except Exception as error:
					LOGGER.warning("Runtime scan report save failed file=%s error=%s",self.scan_report_file,error)
			return True


@dataclass(slots=True)
class _SensorBatch:
	generation: int
	sensors: tuple[SensorDefinition,...]
	report: list[dict[str,Any]]
	state: dict[str,SensorState]


class _SensorBatchFailure(RuntimeError):
	def __init__(self,error: Exception,batch: _SensorBatch) -> None:
		super().__init__(str(error))
		self.error=error
		self.batch=batch


class _SensorBatchConnectionFailure(TransportConnectionClosedError):
	def __init__(self,error: Exception,batch: _SensorBatch) -> None:
		super().__init__(str(error))
		self.error=error
		self.batch=batch


class _GenerationMqtt:
	def __init__(self,runtime: SensorRuntime,generation: int) -> None:
		self.runtime=runtime
		self.generation=generation

	def publish_state(self,sensor: SensorDefinition,value: Any,attributes: dict[str,Any]) -> None:
		self.runtime._publish_if_current(
			self.generation,
			sensor,
			lambda:self.runtime.mqtt.publish_state(sensor,value,attributes),
		)

	def publish_raw(self,sensor: SensorDefinition,raw_registers: list[int]) -> None:
		self.runtime._publish_if_current(
			self.generation,
			sensor,
			lambda:self.runtime.mqtt.publish_raw(sensor,raw_registers),
		)

	def sensor_availability(self,sensor: SensorDefinition,available: bool) -> None:
		self.runtime._publish_if_current(
			self.generation,
			sensor,
			lambda:self.runtime.mqtt.sensor_availability(sensor,available),
		)


def main(solarman_factory: TransportFactory,rs485_factory: TransportFactory) -> None:
	configure_logging()
	config=load_config()
	configure_logging(config.advanced.detailed_logs)
	control_catalog=load_remote_control_catalog(config.catalog)
	set_controls(control_catalog.commands)
	LOGGER.info("Control catalog loaded source=%s entries=%s",control_catalog.source,len(control_catalog.commands))
	manager=build_transport_manager(config,solarman_factory,rs485_factory)
	configuration_changed=threading.Event()
	catalog_lock=threading.Lock()
	catalog_state={"current": load_remote_catalog(config.catalog)}
	spacing=min(slot.polling.read_message_spacing for slot in manager.available())
	controls=ControlService(
		str(Path(config.scan.detected_sensors_file).with_name("control_sensors.json")),
		None,
		threading.RLock(),
		spacing,
		transport_manager=manager,
	)
	configuration=ConfigurationCoordinator(_configuration_paths(config,controls))
	controls.configuration_coordinator=configuration
	controls.configuration_action=configuration.apply

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
		lambda: _run_manual_scan(config,current_catalog(),manager),
		lambda: _reset_panel_configuration(config,current_catalog()),
		lambda: _clear_panel_sensors(config,refresh_catalog()),
		configuration_changed.set,
		config.profiles.custom_sensors_file,
		lambda definition: _test_custom_sensor(manager,definition),
		lambda entries: _save_custom_sensor_configuration(config,entries),
		control_service=controls,
		configuration_coordinator=configuration,
	)
	panel.start()
	try:
		_run_addon(config,manager,current_catalog(),configuration_changed,controls,configuration)
	finally:
		panel.stop()
		try:
			manager.close()
		except Exception as error:
			LOGGER.warning("Transport manager close failed error=%s",error)


def _run_addon(
	config: Any,
	manager: TransportManager,
	remote_catalog: RemoteCatalog,
	configuration_changed: threading.Event | None=None,
	control_service: ControlService | None=None,
	configuration_coordinator: ConfigurationCoordinator | None=None,
) -> None:
	state=load_state(config.profiles.state_file)
	change_event=configuration_changed or threading.Event()
	configuration=configuration_coordinator or ConfigurationCoordinator(_configuration_paths(config,control_service))
	if control_service is not None:
		control_service.configuration_coordinator=configuration
		control_service.configuration_action=configuration.apply
	_probe_transports(manager)
	if config.scan.mode != "disabled":
		configuration.apply(lambda:_run_scan(config,remote_catalog,manager))
		if config.scan.mode == "scan_only":
			LOGGER.info("Scan complete. MQTT publishing is disabled while the Ingress panel remains available.")
			_wait_for_stop()
	with configuration.locked():
		sensors=_load_runtime_sensors(config,state)
	mqtt=MqttPublisher(config.mqtt,config.inverter,detailed_logs=config.advanced.detailed_logs)
	sensor_runtime=None
	try:
		mqtt.connect()
		sensor_runtime=SensorRuntime(
			manager,
			mqtt,
			sensors,
			state,
			emit_raw_topics=config.advanced.emit_raw_topics,
			detailed_logs=config.advanced.detailed_logs,
			state_file=config.profiles.state_file,
			scan_report_file=config.profiles.scan_report_file,
			emit_scan_report=config.advanced.emit_scan_report,
		)
		control_runtime=_apply_runtime_configuration_until_success(
			config,
			mqtt,
			sensor_runtime,
			state,
			configuration,
			manager,
			control_service,
			reset_state=True,
		)
		sensor_runtime.start()
		while True:
			if change_event.wait(0.25):
				change_event.clear()
				control_runtime=_apply_runtime_configuration_until_success(
					config,
					mqtt,
					sensor_runtime,
					state,
					configuration,
					manager,
					control_service,
					reset_state=True,
				)
				success(LOGGER,"Applied updated panel configuration without reconnecting transports or MQTT")
			if control_runtime is not None:
				try:
					control_runtime.tick()
				except Exception as error:
					LOGGER.warning("Control runtime tick failed: %s",error)
	except KeyboardInterrupt:
		LOGGER.info("Stopping add-on")
	finally:
		if sensor_runtime is not None:
			sensor_runtime.stop()
		mqtt.disconnect()


def _configuration_paths(config: Any,control_service: ControlService | None) -> list[Path]:
	detected=Path(config.scan.detected_sensors_file)
	paths=[detected,detected.with_name("deye_solarman_discovery_removals.yaml")]
	custom_path=getattr(config.profiles,"custom_sensors_file",None)
	if custom_path:
		custom=Path(custom_path)
		paths.extend((custom,custom.with_name("deye_solarman_discovery_removals.yaml")))
	if control_service is not None:
		paths.append(control_service.path)
	return paths


def _apply_runtime_configuration_until_success(
	config: Any,
	mqtt: Any,
	sensor_runtime: SensorRuntime,
	state: dict[str,SensorState],
	configuration: ConfigurationCoordinator,
	manager: TransportManager,
	control_service: ControlService | None,
	*,
	reset_state: bool,
) -> ControlRuntime | None:
	while True:
		disable=getattr(type(mqtt),"disable_control_commands",None)
		if disable is not None:
			disable(mqtt)
		try:
			def apply() -> ControlRuntime | None:
				sensors=_load_runtime_sensors(config)
				_publish_sensor_configuration(config,mqtt,sensors,state,reset_state=False)
				control_runtime=ControlRuntime(control_service,mqtt,manager) if control_service is not None else None
				if control_runtime is not None:
					control_runtime.start(activate=False)
					control_runtime.activate()
				sensor_runtime.reload(sensors,reset_state=reset_state)
				return control_runtime
			with configuration.locked():
				return apply()
		except Exception as error:
			if disable is not None:
				disable(mqtt)
			LOGGER.warning("Runtime configuration apply failed; retrying: %s",error)
			time.sleep(0.25)


def _probe_transports(manager: TransportManager) -> None:
	for slot in manager.available():
		try:
			values=manager.run(
				slot.transport_id,
				lambda client:client.read_holding_registers(
					slot.polling.startup_probe_register,
					slot.polling.startup_probe_count,
				),
			)
			success(LOGGER,"Startup probe ok transport=%s values=%s",slot.transport_id,values)
		except Exception as error:
			LOGGER.warning("Startup probe failed transport=%s error=%s",slot.transport_id,error)


def _load_runtime_sensors(config: Any,state: dict[str,SensorState] | None=None) -> list[SensorDefinition]:
	sensors=load_sensor_definitions(
		config.profiles.default_profile,
		config.profiles.overrides_file,
		config.scan.detected_sensors_file,
		config.profiles.custom_sensors_file,
	)
	if state is not None:
		for sensor in sensors:
			state.setdefault(sensor.key,SensorState())
	success(
		LOGGER,
		"Sensor configuration loaded total=%s enabled=%s selected_file=%s",
		len(sensors),
		sum(sensor.enabled for sensor in sensors),
		config.scan.detected_sensors_file,
	)
	return sensors


def _publish_sensor_configuration(
	config: Any,
	mqtt: MqttPublisher,
	sensors: list[SensorDefinition],
	state: dict[str,SensorState],
	*,
	reset_state: bool=True,
	configuration_coordinator: ConfigurationCoordinator | None=None,
) -> None:
	configuration_context=(
		configuration_coordinator.locked()
		if configuration_coordinator is not None
		else nullcontext()
	)
	with configuration_context,mqtt.discovery_transaction():
		removal_paths={config.scan.detected_sensors_file,config.profiles.custom_sensors_file}
		pending=sorted({key for path in removal_paths for key in load_pending_discovery_removals(path)})
		for sensor_key in pending:
			mqtt.remove_discovery(sensor_key)
		if pending:
			for path in removal_paths:
				clear_pending_discovery_removals(path)
			success(LOGGER,"Removed MQTT Discovery entities=%s",len(pending))
		for sensor in (item for item in sensors if item.enabled):
			mqtt.publish_discovery(sensor)
			mqtt.sensor_availability(sensor,False)
			if reset_state:
				state[sensor.key].last_read_at=0
				state[sensor.key].last_published_value=None


def _run_scan(config: Any,remote_catalog: RemoteCatalog,manager: TransportManager) -> list[dict[str,Any]]:
	previous=load_detected_sensors(config.scan.detected_sensors_file).get("available_sensors",[])
	report=scan_transports_sequentially(
		load_scan_candidates(config.scan.bms_pack_count,remote_catalog),
		manager,
		previous,
	)
	save_scan_report(config.scan.report_file,report)
	save_detected_sensors(config.scan.detected_sensors_file,report)
	_log_scan_summary(report,config.scan.detected_sensors_file)
	return report


def _run_manual_scan(config: Any,remote_catalog: RemoteCatalog,manager: TransportManager) -> dict[str,Any]:
	report=_run_scan(config,remote_catalog,manager)
	statuses: dict[str,int]={}
	for result in report:
		status=str(result["status"])
		statuses[status]=statuses.get(status,0)+1
	return {"count":len(report),"statuses":statuses}


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


def _save_custom_sensor_configuration(config: Any, entries: list[dict[str, Any]]) -> dict[str, Any]:
	base_sensors=load_sensor_definitions(
		config.profiles.default_profile,
		config.profiles.overrides_file,
		config.scan.detected_sensors_file,
		None,
	)
	base_keys={sensor.key for sensor in base_sensors}
	for entry in entries:
		if not isinstance(entry,dict) or not isinstance(entry.get("key"),str):
			continue
		if entry["key"] in base_keys:
			raise ValueError(f"Custom sensor key is already used: {entry['key']}")
	from .custom_sensors import save_custom_sensors

	return save_custom_sensors(config.profiles.custom_sensors_file,entries)


def _test_custom_sensor(manager: TransportManager,definition: dict[str,Any]) -> dict[str,Any]:
	sensor=sensor_from_payload(definition,enabled=True)
	from .definitions import _validate_sensor_definitions

	_validate_sensor_definitions([sensor])
	def read(client: RegisterTransport) -> dict[str,Any]:
		if sensor.formula:
			result=_evaluate_formula_sensor(sensor,client)
			return {**_formula_result_payload(result),"transport":sensor.transport}
		start=time.perf_counter()
		start_register=min(sensor.registers)
		values=client.read_holding_registers(start_register,max(sensor.registers)-start_register+1)
		latency_ms=(time.perf_counter()-start)*1000
		raw_values=[values[register-start_register] for register in sensor.registers]
		decoded=decode_registers(raw_values,sensor.register_type,sensor.word_order,sensor.byte_order)
		value=apply_transform(decoded,sensor.multiplier,sensor.offset)
		return {
			"value":value,
			"raw_registers":raw_values,
			"raw_hex":[f"0x{raw:04X}" for raw in raw_values],
			"decoded":decoded,
			"latency_ms":round(latency_ms,2),
			"transport":sensor.transport,
		}
	return manager.run(sensor.transport,read)


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
	solarman: RegisterTransport,
	mqtt: MqttPublisher,
	polling: PollingConfig,
	emit_raw_topics: bool,
	read_lock: Any | None=None,
	detailed_logs: bool=False,
	*,
	force: bool=False,
	mark_attempted: Any | None=None,
	should_stop: Any | None=None,
	report_sink: list[dict[str,Any]] | None=None,
) -> list[dict[str, Any]]:
	report: list[dict[str, Any]]=[] if report_sink is None else report_sink
	failed_groups=0
	due_sensors=[sensor for sensor in sensors if sensor.enabled and (force or _is_due(sensor,state[sensor.key],polling))]
	direct_sensors=[sensor for sensor in due_sensors if not sensor.formula]
	formula_sensors=[sensor for sensor in due_sensors if sensor.formula]
	groups=group_sensors_for_read(direct_sensors, polling)

	for index, group in enumerate(groups):
		if should_stop is not None and should_stop():
			break
		group_start=min(register for sensor in group for register in sensor.registers)
		group_end=max(register for sensor in group for register in sensor.registers)
		count=group_end-group_start+1

		try:
			start=time.perf_counter()
			with read_lock if read_lock is not None else nullcontext():
				if mark_attempted is not None:
					mark_attempted(sensor.key for sensor in group)
				values=solarman.read_holding_registers(group_start, count)
			latency_ms=(time.perf_counter()-start)*1000
		except TransportConnectionClosedError as error:
			if detailed_logs:
				LOGGER.warning("Solarman TCP session closed start=%s count=%s; reconnecting",group_start,count)
			else:
				LOGGER.warning("Solarman TCP session closed; reconnecting")
			raise error
		except Exception as exc:
			LOGGER.warning("Read failed start=%s count=%s error=%s", group_start, count, exc)
			failed_groups+=1
			for sensor in group:
				_publish_sensor_availability(mqtt,sensor,False)
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
			_publish_sensor_availability(mqtt,sensor,True)

		if index < len(groups)-1 and polling.read_message_spacing > 0:
			time.sleep(polling.read_message_spacing)

	if groups and failed_groups == len(groups):
		raise ConnectionError("All due Solarman register groups failed; reconnecting")

	for sensor in formula_sensors:
		if should_stop is not None and should_stop():
			break
		try:
			start=time.perf_counter()
			with read_lock if read_lock is not None else nullcontext():
				if mark_attempted is not None:
					mark_attempted((sensor.key,))
				formula_result=_evaluate_formula_sensor(sensor,solarman)
			latency_ms=(time.perf_counter()-start)*1000
			report.append(
				_handle_formula_sensor(
					sensor,
					formula_result,
					latency_ms,
					state[sensor.key],
					mqtt,
					emit_raw_topics,
					polling.publish_unchanged_every,
				)
			)
			_publish_sensor_availability(mqtt,sensor,formula_result.value is not None)
		except TransportConnectionClosedError as error:
			if detailed_logs:
				LOGGER.warning("Solarman TCP session closed for formula sensor=%s; reconnecting",sensor.key)
			else:
				LOGGER.warning("Solarman TCP session closed; reconnecting")
			raise error
		except Exception as error:
			_publish_sensor_availability(mqtt,sensor,False)
			LOGGER.warning("Formula read failed sensor=%s error=%s",sensor.key,error)
			current_state=state[sensor.key]
			current_state.last_status="formula_error"
			current_state.timeout_count+=1
			report.append({"sensor": sensor.key,"status": "formula_error","error": str(error)})

	return report


def _publish_sensor_availability(mqtt: Any,sensor: SensorDefinition,available: bool) -> None:
	callback=getattr(mqtt,"sensor_availability",None)
	if callback is not None:
		callback(sensor,available)


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
	decoded=decode_registers(raw_values,sensor.register_type,sensor.word_order,sensor.byte_order)
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
			"transport": sensor.transport,
			"raw_registers": raw_values,
			"raw_ascii": registers_to_ascii(raw_values,sensor.byte_order),
			"decoded": decoded,
			"registers": sensor.registers,
			"type": sensor.register_type,
			"multiplier": sensor.multiplier,
			"offset": sensor.offset,
				"unit": sensor.unit,
				"word_order": sensor.word_order,
				"byte_order": sensor.byte_order,
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


def _evaluate_formula_sensor(sensor: SensorDefinition, solarman: RegisterTransport) -> FormulaResult:
	return FormulaExecutor(solarman.read_holding_registers).execute(sensor.formula)


def _formula_result_payload(result: FormulaResult) -> dict[str, Any]:
	return {
		"value": result.value,
		"reads": [
			{
				"register": read.address,
				"raw_registers": read.raw_registers,
				"raw_hex": [f"0x{raw:04X}" for raw in read.raw_registers],
				"type": read.register_type,
				"multiplier": read.multiplier,
				"offset": read.offset,
				"word_order": read.word_order,
				"byte_order": read.byte_order,
				"decoded": read.decoded,
				"value": read.value,
			}
			for read in result.reads
		],
	}


def _handle_formula_sensor(
	sensor: SensorDefinition,
	formula_result: FormulaResult,
	latency_ms: float,
	sensor_state: SensorState,
	mqtt: MqttPublisher,
	emit_raw_topics: bool,
	publish_unchanged_every: int,
) -> dict[str, Any]:
	now=time.time()
	value=formula_result.value
	raw_values=[raw for read in formula_result.reads for raw in read.raw_registers]
	sensor_state.last_read_at=now
	sensor_state.raw_registers=raw_values
	sensor_state.latency_ms=latency_ms
	if value is None:
		sensor_state.last_value=None
		sensor_state.last_status="unavailable"
		return {
			"sensor": sensor.key,
			"name": sensor.name,
			"status": "unavailable",
			"value": None,
			"formula_reads": _formula_result_payload(formula_result)["reads"],
		}

	sensor_state.last_value=value
	sensor_state.last_status="supported"
	if _should_publish(sensor,sensor_state,now,value,publish_unchanged_every):
		attributes={
			"transport": sensor.transport,
			"formula": sensor.formula,
			"type": "auto",
			"formula_reads": _formula_result_payload(formula_result)["reads"],
			"latency_ms": round(latency_ms,2),
			"last_read_at": int(now),
			"timeout_count": sensor_state.timeout_count,
		}
		mqtt.publish_state(sensor,value,attributes)
		if emit_raw_topics:
			mqtt.publish_raw(sensor,raw_values)
		sensor_state.last_published_at=now
		sensor_state.last_published_value=value

	return {
		"sensor": sensor.key,
		"name": sensor.name,
		"status": "supported",
		"value": value,
		"raw": raw_values,
		"formula_reads": _formula_result_payload(formula_result)["reads"],
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
