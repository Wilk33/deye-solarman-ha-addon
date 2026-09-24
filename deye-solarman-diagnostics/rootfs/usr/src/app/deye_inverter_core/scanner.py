from __future__ import annotations

import re
import time
from dataclasses import asdict
from dataclasses import replace
from datetime import UTC
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from .codec import apply_transform
from .codec import decode_registers
from .codec import registers_to_ascii
from .formula import FormulaError
from .formula import FormulaExecutor
from .models import PollingConfig
from .models import TRANSPORT_IDS
from .scan_catalog import ScanCandidate
from .scheduler import group_sensors_for_read
from .transport import RegisterTransport
from .transport import TransportConnectionClosedError


EDITABLE_DEFINITION_FIELDS={
	"name",
	"type",
	"multiplier",
	"offset",
	"unit",
	"word_order",
	"byte_order",
	"schedule",
	"read_every",
	"report_every",
	"change_by",
	"retain",
	"device_class",
	"state_class",
	"icon",
	"category",
	"topic_suffix",
	"transport",
}


class PartialScanConnectionError(TransportConnectionClosedError):
	def __init__(self, message: str, results: Any) -> None:
		super().__init__(message)
		self.results=results


class ScanBatchError(RuntimeError):
	def __init__(self, message: str, results: Any) -> None:
		super().__init__(message)
		self.results=results


def validate_transport_configuration(
	transport: Any,
	transports: Any,
	*,
	subject: str="Entity",
) -> list[str]:
	if (
		not isinstance(transports,list)
		or not transports
		or any(item not in TRANSPORT_IDS for item in transports)
		or len(set(transports)) != len(transports)
	):
		raise ValueError(f"{subject} transports must be a non-empty list of unique known transport ids")
	if transport not in transports:
		raise ValueError(f"{subject} transport must be one of the allowed transports")
	return list(transports)


def normalize_last_scan(last_scan: Any) -> dict[str,dict[str,Any]]:
	if not isinstance(last_scan,dict):
		return {}
	branches={
		transport_id: dict(last_scan[transport_id])
		for transport_id in TRANSPORT_IDS
		if isinstance(last_scan.get(transport_id),dict)
	}
	if not branches and last_scan:
		branches["solarman_tcp"]=dict(last_scan)
	return branches


def select_transport(
	transports: list[str],
	last_scan: dict[str,dict[str,Any]],
	previous: str | None=None,
) -> str:
	default="solarman_tcp" if "solarman_tcp" in transports else transports[0] if transports else None
	validate_transport_configuration(default,transports)
	supported=[
		transport_id
		for transport_id in TRANSPORT_IDS
		if transport_id in transports and last_scan.get(transport_id,{}).get("status") == "supported"
	]
	if previous in supported:
		return previous
	if len(supported) == 1:
		return supported[0]
	if supported:
		return "solarman_tcp" if "solarman_tcp" in supported else supported[0]
	if previous in transports:
		return previous
	return "solarman_tcp" if "solarman_tcp" in transports else transports[0]


def scan_status(last_scan: dict[str,dict[str,Any]],transports: list[str]) -> str:
	return "supported" if any(
		last_scan.get(transport_id,{}).get("status") == "supported"
		for transport_id in transports
	) else "unknown"


def last_scan_with_selected_alias(
	last_scan: dict[str,dict[str,Any]],
	transport: str,
) -> dict[str,Any]:
	payload={key:dict(value) for key,value in last_scan.items()}
	payload.update(last_scan.get(transport,{}))
	return payload


def scan_transports_sequentially(
	candidates: list[ScanCandidate],
	manager: Any,
	previous_entries: list[dict[str,Any]] | None=None,
) -> list[dict[str,Any]]:
	"""Scan SolarMan and then RS485, and merge their results per sensor."""
	previous_by_key={
		entry.get("key"):entry
		for entry in previous_entries or []
		if isinstance(entry,dict) and isinstance(entry.get("key"),str)
	}
	available={slot.transport_id:slot for slot in manager.available()}
	results: dict[str,dict[str,dict[str,Any]]]={candidate.sensor.key:{} for candidate in candidates}

	for transport_id in TRANSPORT_IDS:
		allowed=[candidate for candidate in candidates if transport_id in candidate.sensor.transports]
		for candidate in candidates:
			if transport_id not in candidate.sensor.transports:
				results[candidate.sensor.key][transport_id]=_scan_error(
					candidate,"unsupported",f"Transport {transport_id} is not allowed by the catalog",
				)
		if not allowed:
			continue
		slot=available.get(transport_id)
		if slot is None:
			for candidate in allowed:
				results[candidate.sensor.key][transport_id]=_scan_error(
					candidate,"unavailable",f"Transport {transport_id} is not active",
				)
			continue
		try:
			report=manager.run(
				transport_id,
				lambda client:scan_candidates(allowed,client,slot.polling,raise_on_all_failures=True),
			)
		except PartialScanConnectionError as error:
			for result in error.results:
				results[result["key"]][transport_id]=result
			for candidate in allowed:
				if transport_id in results[candidate.sensor.key]:
					continue
				results[candidate.sensor.key][transport_id]=_scan_error(
					candidate,"unavailable",str(error),
				)
		except TransportConnectionClosedError as error:
			for candidate in allowed:
				results[candidate.sensor.key][transport_id]=_scan_error(
					candidate,"unavailable",str(error),
				)
		except ScanBatchError as error:
			report=error.results
			for result in report:
				results[result["key"]][transport_id]=result
		else:
			for result in report:
				results[result["key"]][transport_id]=result

	merged=[]
	for candidate in candidates:
		key=candidate.sensor.key
		previous=previous_by_key.get(key,{})
		previous_definition=previous.get("definition",{})
		previous_transport=(
			previous_definition.get("transport")
			if isinstance(previous_definition,dict)
			else None
		)
		prior_scans=normalize_last_scan(previous.get("last_scan",{}))
		transport_results={}
		for transport_id,result in results[key].items():
			prior=prior_scans.get(transport_id,{})
			transport_results[transport_id]=merge_scan_result(prior,result)
		selected=select_transport(candidate.sensor.transports,transport_results,previous_transport)
		definition=_sensor_to_payload(replace(candidate.sensor,transport=selected))
		merged.append({
			"key":key,
			"name":candidate.sensor.name,
			"definition":definition,
			"transport":selected,
			"transports":list(candidate.sensor.transports),
			"status":scan_status(transport_results,candidate.sensor.transports),
			"last_scan":last_scan_with_selected_alias(transport_results,selected),
			"verification":candidate.verification,
			"description":candidate.description,
		})
	return merged


def scan_candidates(
	candidates: list[ScanCandidate],
	solarman: RegisterTransport,
	polling: PollingConfig,
	*,
	raise_on_all_failures: bool=False,
) -> list[dict[str, Any]]:
	by_key={candidate.sensor.key: candidate for candidate in candidates}
	readable=[replace(candidate.sensor, enabled=True) for candidate in candidates]
	direct=[sensor for sensor in readable if not sensor.formula]
	formula_candidates=[candidate for candidate in candidates if candidate.sensor.formula]
	report: list[dict[str, Any]]=[]
	groups=group_sensors_for_read(direct,polling)
	operation_count=len(groups)+len(formula_candidates)
	operation_index=0

	for group in groups:
		group_start=min(register for sensor in group for register in sensor.registers)
		group_end=max(register for sensor in group for register in sensor.registers)
		count=group_end-group_start+1

		try:
			start=time.perf_counter()
			values=solarman.read_holding_registers(group_start, count)
			latency_ms=(time.perf_counter()-start)*1000
		except TransportConnectionClosedError as error:
			raise PartialScanConnectionError(str(error),report) from error
		except Exception as error:
			status=_read_error_status(error)
			for sensor in group:
				report.append(_scan_error(by_key[sensor.key], status, str(error)))
		else:
			for sensor in group:
				report.append(_scan_value(by_key[sensor.key], values, group_start, latency_ms))

		operation_index+=1
		if operation_index < operation_count and polling.read_message_spacing > 0:
			time.sleep(polling.read_message_spacing)

	for candidate in formula_candidates:
		try:
			start=time.perf_counter()
			result=FormulaExecutor(solarman.read_holding_registers).execute(candidate.sensor.formula)
			latency_ms=(time.perf_counter()-start)*1000
		except TransportConnectionClosedError as error:
			raise PartialScanConnectionError(str(error),report) from error
		except (FormulaError,ArithmeticError,TypeError,ValueError) as error:
			report.append(_scan_error(candidate,"invalid_value",str(error)))
		except Exception as error:
			report.append(_scan_error(candidate,_read_error_status(error),str(error)))
		else:
			report.append(_scan_formula_value(candidate,result,latency_ms))
		operation_index+=1
		if operation_index < operation_count and polling.read_message_spacing > 0:
			time.sleep(polling.read_message_spacing)

	if raise_on_all_failures and report and all(result.get("status") in {"timeout","unsupported"} for result in report):
		raise ScanBatchError("All scan reads failed",report)
	return report


def _scan_formula_value(candidate: ScanCandidate,result: Any,latency_ms: float) -> dict[str,Any]:
	raw_values=[raw for read in result.reads for raw in read.raw_registers]
	return {
		"key":candidate.sensor.key,
		"name":candidate.sensor.name,
		"definition":_sensor_to_payload(candidate.sensor),
		"status":"supported",
		"raw_registers":raw_values,
		"raw_hex":[f"0x{value:04X}" for value in raw_values],
		"raw_ascii":registers_to_ascii(raw_values),
		"decoded":result.value,
		"value":result.value,
		"formula_reads":[asdict(read) for read in result.reads],
		"latency_ms":round(latency_ms,2),
		"verification":candidate.verification,
		"description":candidate.description,
	}


def _read_error_status(error: Exception) -> str:
	message=str(error).lower()
	if re.search(r"\billegal\s+(?:data\s+)?(?:address|function)\b",message):
		return "unsupported"
	match=re.search(r"\bexception(?:_|\s+)code\s*[=:]?\s*(\d+)\b",message)
	if match and int(match.group(1)) in {1,2}:
		return "unsupported"
	return "timeout"


def merge_scan_result(previous: Any, result: dict[str,Any]) -> dict[str,Any]:
	if result.get("status") not in {"timeout","unavailable","unsupported"} or not isinstance(previous,dict) or not previous:
		return result
	preserved=dict(previous)
	preserved.update({
		field:value
		for field,value in result.items()
		if field not in {"raw_registers","raw_hex","raw_ascii","decoded","value"}
	})
	return preserved


def save_detected_sensors(path: str, report: list[dict[str, Any]]) -> None:
	target=Path(path)
	target.parent.mkdir(parents=True, exist_ok=True)
	previous=_load_yaml_mapping(target)
	previous_entries={
		entry.get("key"): entry
		for entry in previous.get("available_sensors", [])
		if isinstance(entry, dict) and isinstance(entry.get("key"), str)
	}
	entries=[]

	for result in report:
		key=result["key"]
		previous_entry=previous_entries.get(key,{})
		definition=dict(result["definition"])
		previous_definition=previous_entry.get("definition")
		if isinstance(previous_definition, dict):
			definition.update(previous_definition)
			# Existing files predate byte_order, so retain user settings while applying the new BMS serial default.
			if key.endswith("_bms_serial") and "byte_order" not in previous_definition:
				definition["byte_order"]="low_high"
		definition["key"]=key
		definition["transports"]=list(result.get("transports",definition.get("transports",TRANSPORT_IDS)))
		definition["transport"]=result.get("transport",definition.get("transport","solarman_tcp"))
		validate_transport_configuration(definition["transport"],definition["transports"],subject=f"Sensor {key}")

		monitor=previous_entry.get("monitor",False)
		if not isinstance(monitor, bool):
			monitor=False
		if "last_scan" in result:
			last_scan=dict(result["last_scan"])
		else:
			legacy_scan={
				"status": result["status"],
				"raw_registers": result.get("raw_registers",[]),
				"raw_hex": result.get("raw_hex",[]),
				"raw_ascii": result.get("raw_ascii",""),
				"decoded": result.get("decoded"),
				"value": result.get("value"),
				"latency_ms": result.get("latency_ms"),
				"error": result.get("error"),
				"verification": result["verification"],
				"description": result["description"],
			}
			last_scan=last_scan_with_selected_alias({
				"solarman_tcp":legacy_scan,
				"modbus_rtu":{"status":"unavailable","error":"Transport modbus_rtu was not active during the legacy scan"},
			},definition["transport"])
		branches=normalize_last_scan(last_scan)
		if branches.get(definition["transport"],{}).get("status") != "supported":
			monitor=False
		entries.append(
			{
				"key": key,
				"monitor": monitor,
				"definition": definition,
				"status":result.get("status",scan_status(branches,definition["transports"])),
				"last_scan": last_scan,
			}
		)

	payload={
		"version": 1,
		"scanned_at": datetime.now(UTC).isoformat(),
		"available_sensors": entries,
	}
	_write_yaml(target, payload)


def reset_detected_sensors(path: str, candidates: list[ScanCandidate]) -> dict[str, Any]:
	"""Restore catalog defaults for sensors already found by a scan."""
	target=Path(path)
	payload=load_detected_sensors(path)
	entries=payload.get("available_sensors",[])
	if not isinstance(entries,list):
		raise ValueError("detected_sensors.yaml: available_sensors must be a list")

	_queue_discovery_removals(target,entries)
	defaults={candidate.sensor.key: _sensor_to_payload(candidate.sensor) for candidate in candidates}
	reset_entries=[]
	for entry in entries:
		if not isinstance(entry,dict):
			continue
		key=entry.get("key")
		if not isinstance(key,str) or key not in defaults:
			continue
		reset_entries.append(
			{
				"key": key,
				"monitor": False,
				"definition": defaults[key],
				"last_scan": last_scan_with_selected_alias(
					normalize_last_scan(entry.get("last_scan",{})),
					defaults[key].get("transport","solarman_tcp"),
				),
			}
		)

	payload["available_sensors"]=reset_entries
	_write_yaml(target,payload)
	return payload


def clear_detected_sensors(path: str) -> dict[str, Any]:
	"""Remove all local scan results and their per-sensor configuration."""
	target=Path(path)
	target.parent.mkdir(parents=True,exist_ok=True)
	previous=load_detected_sensors(path)
	entries=previous.get("available_sensors",[])
	if isinstance(entries,list):
		_queue_discovery_removals(target,entries)
	payload={
		"version": 1,
		"scanned_at": None,
		"available_sensors": [],
	}
	_write_yaml(target,payload)
	return payload


def load_pending_discovery_removals(path: str) -> list[str]:
	payload=_load_yaml_mapping(_discovery_removals_path(Path(path)))
	keys=payload.get("keys",[])
	if not isinstance(keys,list) or not all(isinstance(key,str) and key for key in keys):
		raise ValueError("discovery removal queue: keys must be a list of sensor keys")
	return keys


def clear_pending_discovery_removals(path: str) -> None:
	target=_discovery_removals_path(Path(path))
	if target.exists():
		target.unlink()


def load_monitored_definitions(path: str) -> list[dict[str, Any]]:
	target=Path(path)
	if not target.exists():
		return []
	payload=_load_yaml_mapping(target)
	entries=payload.get("available_sensors",[])
	if not isinstance(entries, list):
		raise ValueError("detected_sensors.yaml: available_sensors must be a list")

	definitions=[]
	for index, entry in enumerate(entries):
		if not isinstance(entry, dict):
			raise ValueError(f"detected_sensors.yaml: available_sensors[{index}] must be an object")
		monitor=entry.get("monitor",False)
		if not isinstance(monitor, bool):
			raise ValueError(f"detected_sensors.yaml: available_sensors[{index}].monitor must be a boolean")
		if not monitor:
			continue
		definition=entry.get("definition")
		if not isinstance(definition, dict):
			raise ValueError(f"detected_sensors.yaml: available_sensors[{index}].definition must be an object")
		if definition.get("key") != entry.get("key"):
			raise ValueError(f"detected_sensors.yaml: available_sensors[{index}] has inconsistent key")
		transport=definition.get("transport","solarman_tcp")
		transports=definition.get("transports",list(TRANSPORT_IDS))
		validate_transport_configuration(transport,transports,subject=f"Sensor {entry.get('key')}")
		if normalize_last_scan(entry.get("last_scan",{})).get(transport,{}).get("status") != "supported":
			continue
		selected=dict(definition)
		selected["transport"]=transport
		selected["transports"]=transports
		selected["enabled"]=True
		definitions.append(selected)

	return definitions


def load_detected_sensors(path: str) -> dict[str, Any]:
	target=Path(path)
	if not target.exists():
		return {
			"version": 1,
			"scanned_at": None,
			"available_sensors": [],
		}
	payload=_load_yaml_mapping(target)
	entries=payload.get("available_sensors",[])
	if not isinstance(entries,list):
		raise ValueError("detected_sensors.yaml: available_sensors must be a list")
	for entry in entries:
		if not isinstance(entry,dict) or not isinstance(entry.get("definition"),dict):
			continue
		definition=entry["definition"]
		definition.setdefault("transport","solarman_tcp")
		definition.setdefault("transports",list(TRANSPORT_IDS))
		validate_transport_configuration(definition["transport"],definition["transports"],subject=f"Sensor {entry.get('key')}")
		branches=normalize_last_scan(entry.get("last_scan",{}))
		entry["last_scan"]=last_scan_with_selected_alias(branches,definition["transport"])
		entry["status"]=scan_status(branches,definition["transports"])
		if entry.get("monitor") is True and branches.get(definition["transport"],{}).get("status") != "supported":
			entry["monitor"]=False
	return payload


def update_detected_sensors(path: str, updates: list[dict[str, Any]]) -> dict[str, Any]:
	target=Path(path)
	payload=load_detected_sensors(path)
	entries=payload.get("available_sensors")
	if not isinstance(entries, list):
		raise ValueError("detected_sensors.yaml: available_sensors must be a list")
	entries_by_key={
		entry.get("key"): entry
		for entry in entries
		if isinstance(entry, dict) and isinstance(entry.get("key"), str)
	}

	removed_keys: set[str]=set()
	for index, update in enumerate(updates):
		if not isinstance(update, dict):
			raise ValueError(f"Update {index} must be an object")
		key=update.get("key")
		if not isinstance(key, str) or key not in entries_by_key:
			raise ValueError(f"Update {index} has an unknown sensor key")
		entry=entries_by_key[key]
		monitor=update.get("monitor")
		if not isinstance(monitor, bool):
			raise ValueError(f"Update {key}: monitor must be a boolean")
		definition_update=update.get("definition",{})
		if not isinstance(definition_update, dict):
			raise ValueError(f"Update {key}: definition must be an object")
		definition=entry.get("definition")
		if not isinstance(definition, dict):
			raise ValueError(f"detected_sensors.yaml: {key} has no definition")

		transports=definition.get("transports",list(TRANSPORT_IDS))
		transport=definition.get("transport","solarman_tcp")
		validate_transport_configuration(transport,transports,subject=f"Sensor {key}")
		requested_transport=definition_update.get("transport",transport)
		validate_transport_configuration(requested_transport,transports,subject=f"Sensor {key}")
		branches=normalize_last_scan(entry.get("last_scan",{}))
		if requested_transport != transport and branches.get(requested_transport,{}).get("status") != "supported":
			raise ValueError(f"Sensor {key}: transport must have supported scan status")
		if monitor and branches.get(requested_transport,{}).get("status") != "supported":
			raise ValueError(f"Sensor {key}: selected transport must have supported scan status")

		if entry.get("monitor") is True and not monitor:
			removed_keys.add(key)
		entry["monitor"]=monitor
		for field, value in definition_update.items():
			if field not in EDITABLE_DEFINITION_FIELDS:
				continue
			if field == "type" and definition.get("formula"):
				if value != "auto":
					raise ValueError(f"Update {key}: formula type must remain auto")
				definition[field]="auto"
				continue
			definition[field]=_validate_definition_value(key, field, value)
		definition["transport"]=requested_transport
		definition["transports"]=transports
		entry["last_scan"]=last_scan_with_selected_alias(branches,requested_transport)

	_queue_discovery_removal_keys(target,removed_keys)
	_write_yaml(target, payload)
	return payload


def _scan_value(
	candidate: ScanCandidate,
	group_values: list[int],
	group_start: int,
	latency_ms: float,
) -> dict[str, Any]:
	sensor=candidate.sensor
	try:
		raw_values=[group_values[register-group_start] for register in sensor.registers]
		decoded=decode_registers(
			raw_values,sensor.register_type,sensor.word_order,sensor.byte_order,
			options=sensor.options,zero=sensor.zero,unknown=sensor.unknown,
		)
		value=apply_transform(decoded, sensor.multiplier, sensor.offset)
	except (IndexError, TypeError, ValueError) as error:
		return _scan_error(candidate, "invalid_value", str(error), latency_ms)

	return {
		"key": sensor.key,
		"name": sensor.name,
		"definition": _sensor_to_payload(sensor),
		"status": "supported",
		"raw_registers": raw_values,
		"raw_hex": [f"0x{value:04X}" for value in raw_values],
		"raw_ascii": registers_to_ascii(raw_values,sensor.byte_order),
		"decoded": decoded,
		"value": value,
		"latency_ms": round(latency_ms,2),
		"verification": candidate.verification,
		"description": candidate.description,
	}


def _scan_error(
	candidate: ScanCandidate,
	status: str,
	error: str,
	latency_ms: float | None=None,
) -> dict[str, Any]:
	sensor=candidate.sensor
	return {
		"key": sensor.key,
		"name": sensor.name,
		"definition": _sensor_to_payload(sensor),
		"status": status,
		"raw_registers": [],
		"raw_hex": [],
		"raw_ascii": "",
		"latency_ms": round(latency_ms,2) if latency_ms is not None else None,
		"error": error,
		"verification": candidate.verification,
		"description": candidate.description,
	}


def _sensor_to_payload(sensor: Any) -> dict[str, Any]:
	payload=asdict(sensor)
	payload["type"]=payload.pop("register_type")
	return payload


def _validate_definition_value(key: str, field: str, value: Any) -> Any:
	if field in {"name","unit","device_class","state_class","icon","category","topic_suffix","zero","unknown"}:
		if not isinstance(value, str):
			raise ValueError(f"Update {key}: {field} must be text")
		return value.strip()
	if field in {"multiplier","offset","change_by"}:
		if isinstance(value, bool):
			raise ValueError(f"Update {key}: {field} must be a number")
		try:
			parsed=float(value)
		except (TypeError, ValueError) as error:
			raise ValueError(f"Update {key}: {field} must be a number") from error
		if field == "change_by" and parsed < 0:
			raise ValueError(f"Update {key}: change_by cannot be negative")
		return parsed
	if field in {"read_every","report_every"}:
		if isinstance(value, bool):
			raise ValueError(f"Update {key}: {field} must be a positive integer")
		try:
			parsed=int(value)
		except (TypeError, ValueError) as error:
			raise ValueError(f"Update {key}: {field} must be a positive integer") from error
		if parsed <= 0:
			raise ValueError(f"Update {key}: {field} must be a positive integer")
		return parsed
	if field == "retain":
		if not isinstance(value, bool):
			raise ValueError(f"Update {key}: retain must be a boolean")
		return value
	if field == "transport":
		if value not in TRANSPORT_IDS:
			raise ValueError(f"Update {key}: unsupported transport")
		return value
	if field == "type":
		if value not in {"uint16","int16","uint32","int32","hex","ascii","enum","bitmask"}:
			raise ValueError(f"Update {key}: unsupported type")
		return value
	if field == "options":
		if not isinstance(value,dict):
			raise ValueError(f"Update {key}: options must be an object")
		try:
			return {int(option):str(label) for option,label in value.items()}
		except (TypeError,ValueError) as error:
			raise ValueError(f"Update {key}: option keys must be integers") from error
	if field == "word_order":
		if value not in {"high_low","low_high"}:
			raise ValueError(f"Update {key}: unsupported word order")
		return value
	if field == "byte_order":
		if value not in {"high_low","low_high"}:
			raise ValueError(f"Update {key}: unsupported byte order")
		return value
	if field == "schedule":
		if value not in {"default","slow"}:
			raise ValueError(f"Update {key}: unsupported schedule")
		return value
	raise ValueError(f"Update {key}: unsupported field {field}")


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
	if not path.exists():
		return {}
	try:
		with path.open("r", encoding="utf-8") as handle:
			payload=yaml.safe_load(handle) or {}
	except (OSError, yaml.YAMLError) as error:
		raise ValueError(f"Unable to read {path}: {error}") from error
	if not isinstance(payload, dict):
		raise ValueError(f"{path.name}: root value must be an object")
	return payload


def _write_yaml(target: Path, payload: dict[str, Any]) -> None:
	temporary=target.with_name(f".{target.name}.tmp")
	with temporary.open("w", encoding="utf-8") as handle:
		yaml.safe_dump(payload, handle, allow_unicode=False, sort_keys=False)
	temporary.replace(target)


def _queue_discovery_removals(target: Path, entries: list[Any]) -> None:
	keys={
		entry.get("key")
		for entry in entries
		if isinstance(entry,dict) and entry.get("monitor") is True and isinstance(entry.get("key"),str)
	}
	_queue_discovery_removal_keys(target,keys)


def _queue_discovery_removal_keys(target: Path, keys: set[str]) -> None:
	if not keys:
		return
	queue_path=_discovery_removals_path(target)
	payload=_load_yaml_mapping(queue_path)
	pending=payload.get("keys",[])
	if not isinstance(pending,list):
		pending=[]
	keys.update(key for key in pending if isinstance(key,str) and key)
	_write_yaml(queue_path,{"version": 1,"keys": sorted(keys)})


def _discovery_removals_path(target: Path) -> Path:
	return target.with_name("deye_solarman_discovery_removals.yaml")
