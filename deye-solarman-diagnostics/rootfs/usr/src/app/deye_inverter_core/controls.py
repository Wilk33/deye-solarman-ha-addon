from __future__ import annotations

import json
import logging
import math
import queue
import re
import threading
import time
from copy import deepcopy
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path
from typing import Any

from .transport import TransportFactory, TransportConnectionClosedError
from .catalog_bundle import load_map

LOGGER=logging.getLogger(__name__)
CATALOG=load_map("control","solarman_tcp")
CONTROLS={entry["key"]: entry for entry in CATALOG["commands"]}
RETIRED_CONTROLS={
	"control_us_version_grounding_fault":{"key":"control_us_version_grounding_fault","method":"SelectRWSensor"},
	"control_grid_standard":{"key":"control_grid_standard","method":"SelectRWSensor"},
	"control_configured_grid_phases":{"key":"control_configured_grid_phases","method":"SelectRWSensor"},
	"control_allow_remote":{"key":"control_allow_remote","method":"SelectRWSensor"},
}


def set_controls(entries: list[dict]) -> None:
	keys=[entry["key"] for entry in entries]
	if len(keys) != len(set(keys)):
		raise ValueError("Control catalog has duplicate keys")
	CONTROLS.clear()
	CONTROLS.update({entry["key"]:entry for entry in entries})


def component(entry: dict) -> str:
	return {"NumberRWSensor": "number","SelectRWSensor": "select","SwitchRWSensor": "switch","TimeRWSensor": "select","SystemTimeRWSensor": "text"}[entry["method"]]


def read_words(client: Any, registers: list[int]) -> list[int]:
	values=client.read_holding_registers(min(registers),max(registers)-min(registers)+1)
	if len(values) != max(registers)-min(registers)+1 or any(type(v) is not int or not 0 <= v <= 65535 for v in values):
		raise ValueError("Invalid register response")
	return [values[address-min(registers)] for address in registers]


def numeric(words: list[int], factor: float) -> float:
	value=sum(word<<(16*index) for index,word in enumerate(words))
	bits=16*len(words)
	if factor < 0 and value&(1<<(bits-1)):
		value-=1<<bits
	return round(value*abs(factor),6)


def unknown_value(entry: dict, words: list[int]) -> bool:
	value=words[0]&entry["bitmask"] if entry["bitmask"] else words[0]
	return entry.get("raw_only",False) or (entry["method"] == "SelectRWSensor" and str(value) not in entry["options"])


def decode(entry: dict, words: list[int]) -> Any:
	masked=[word&entry["bitmask"] if entry["bitmask"] else word for word in words]
	if unknown_value(entry,words):
		return f"UNKNOWN / Not applicable (RAW={masked[0]})"
	method=entry["method"]
	if method == "SelectRWSensor":
		return entry["options"][str(masked[0])]
	if method == "SwitchRWSensor":
		active=masked[0] == entry["on"] if entry["on"] is not None else masked[0] != entry["off"]
		return "ON" if active else "OFF"
	if method == "TimeRWSensor":
		hour,minute=divmod(masked[0],100)
		if hour > 23 or minute > 59:
			raise ValueError("Invalid program time")
		return f"{hour:02}:{minute:02}"
	if method == "SystemTimeRWSensor":
		value=datetime((words[0]>>8)+entry["year_offset"],words[0]&255,words[1]>>8,words[1]&255,words[2]>>8,words[2]&255)
		return value.strftime("%Y-%m-%d %H:%M:%S")
	return numeric([word>>entry.get("shift",0) for word in masked],entry["factor"])


def read_result(entry: dict, words: list[int]) -> dict:
	unknown=unknown_value(entry,words)
	result={"status":"unknown" if unknown else "supported","value":decode(entry,words),"raw_registers":words,"raw_hex":[f"0x{word:04X}" for word in words],"verification":"transport_verified","write_allowed":not (unknown or entry.get("read_only",False))}
	if not result["write_allowed"]:
		result["write_reason"]=entry.get("read_only_reason","Nieznany stan pola. Zapis zablokowany do czasu rozpoznania wartości.")
	return result


def resolve_bound(bound: Any, client: Any) -> float:
	if isinstance(bound,dict):
		value=numeric(read_words(client,bound["registers"]),bound["factor"])
		if "values" in bound:
			key=str(int(value)) if float(value).is_integer() else str(value)
			if key not in bound["values"]:
				raise ValueError(f"Niepotwierdzony limit dla mocy znamionowej {value} W. Zapis zablokowany.")
			return float(bound["values"][key])
		return value
	return float(bound)


def limits(entry: dict, client: Any) -> tuple[float,float]:
	bits=16*len(entry["registers"])
	factor=abs(entry["factor"])
	signed=entry["factor"] < 0
	low=-(1<<(bits-1))*factor if signed else 0
	high=((1<<(bits-int(signed)))-1)*factor
	return max(low,resolve_bound(entry["min"],client)),min(high,resolve_bound(entry["max"],client))


def time_options(entry: dict, client: Any) -> list[str]:
	def minutes(bound: Any) -> int:
		if not bound:
			return 0
		word=read_words(client,bound["registers"])[0]
		hour,minute=divmod(word,100)
		if hour > 23 or minute > 59:
			raise ValueError("Invalid adjacent program time")
		return hour*60+minute
	low=minutes(entry.get("min"))
	high=minutes(entry.get("max"))
	if low >= high:
		high+=1440
	return [f"{(minute%1440)//60:02}:{minute%60:02}" for minute in range(low,high+1)]


def encode(entry: dict, value: Any, client: Any, current: list[int]) -> list[int]:
	if entry.get("read_only") or unknown_value(entry,current):
		raise ValueError(entry.get("read_only_reason","Cannot write a field with UNKNOWN current state"))
	method=entry["method"]
	if method == "NumberRWSensor":
		value=float(value)
		low,high=limits(entry,client)
		if not math.isfinite(value) or not low <= value <= high:
			raise ValueError(f"Value must be within {low}..{high}")
		scaled=value/abs(entry["factor"])
		if not math.isclose(scaled,round(scaled),abs_tol=1e-6,rel_tol=0):
			raise ValueError(f"Value must use step {abs(entry['factor'])}")
		integer=round(scaled)<<entry.get("shift",0)
		words=[(integer>>(16*index))&65535 for index in range(len(current))]
	elif method == "SelectRWSensor":
		choices={label:int(raw) for raw,label in entry["options"].items()}
		if value not in choices:
			raise ValueError("Unknown control option")
		words=[choices[value]]
	elif method == "SwitchRWSensor":
		if value not in {"ON","OFF"}:
			raise ValueError("ON or OFF required")
		words=[(entry["on"] or (255&(entry["bitmask"] or 65535))) if value == "ON" else entry["off"]]
	elif method == "TimeRWSensor":
		if not re.fullmatch(r"\d{2}:\d{2}",str(value)) or value not in time_options(entry,client):
			raise ValueError("Time must be HH:MM within adjacent program times")
		hour,minute=map(int,value.split(":"))
		words=[hour*100+minute]
	elif method == "SystemTimeRWSensor":
		if not re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}",str(value)):
			raise ValueError("Expected YYYY-MM-DD HH:MM:SS")
		date=datetime.strptime(value,"%Y-%m-%d %H:%M:%S")
		year=date.year-entry["year_offset"]
		if not 0 <= year <= 99:
			raise ValueError("Year outside 2000..2099")
		words=[(year<<8)|date.month,(date.day<<8)|date.hour,(date.minute<<8)|date.second]
	else:
		raise ValueError("Unsupported control method")
	if entry["bitmask"]:
		words=[(current[0]&(65535^entry["bitmask"]))|(words[0]&entry["bitmask"])]
	return words


def write_control(client: Any, entry: dict, value: Any) -> dict:
	current=read_words(client,entry["registers"])
	words=encode(entry,value,client,current)
	if entry["registers"] != list(range(min(entry["registers"]),max(entry["registers"])+1)):
		raise ValueError("Non-contiguous write rejected")
	if words != current:
		# No automatic retry: a timeout may follow an accepted write.
		try:
			client.write_holding_registers(entry["registers"][0],words)
			readback=read_words(client,entry["registers"])
			mask=entry["bitmask"] or 65535
			if entry["method"] == "SystemTimeRWSensor":
				if abs((datetime.fromisoformat(decode(entry,readback))-datetime.fromisoformat(str(value))).total_seconds()) > 5:
					raise RuntimeError("Clock read-back mismatch")
			elif [word&mask for word in readback] != [word&mask for word in words]:
				raise RuntimeError("Control read-back mismatch")
		except Exception as error:
			raise RuntimeError(f"Write outcome uncertain: {error}") from error
	else:
		readback=current
	LOGGER.info("Control write key=%s before=%s requested=%s readback=%s",entry["key"],current,value,readback)
	return {"value":decode(entry,readback),"raw_registers":readback,"raw_hex":[f"0x{word:04X}" for word in readback]}


class ControlService:
	def __init__(self, path: str, logger: Any, access_lock: Any, spacing: float=0.05, transport_factory: TransportFactory | None=None) -> None:
		self.path=Path(path)
		self.transport_factory=transport_factory
		self.logger=logger
		self.access_lock=access_lock
		self.spacing=spacing
		self.lock=threading.RLock()
		self.writes_blocked=False
		self.ownership=None
		self.configuration_action=lambda action:action()
		self.job={"status":"idle","message":"Skan odczytuje aktualny stan."}

	def load(self) -> dict:
		with self.lock:
			if not self.path.exists():
				return {"available_sensors":[],"published":[]}
			data=json.loads(self.path.read_text(encoding="utf-8"))
			# Reapply canonical encoding after upgrades; retain only user-editable settings.
			data["available_sensors"]=[self.entry(entry["key"],entry) for entry in data["available_sensors"] if entry["key"] in CONTROLS]
			return data

	def published_definitions(self) -> dict[str,dict]:
		with self.lock:
			if not self.path.exists():
				return {}
			data=json.loads(self.path.read_text(encoding="utf-8"))
			published=set(data.get("published",[]))
			return {
				entry["key"]:entry["definition"]
				for entry in data.get("available_sensors",[])
				if entry.get("key") in published and isinstance(entry.get("definition"),dict)
			}

	def store(self, data: dict) -> None:
		with self.lock:
			self.path.parent.mkdir(parents=True,exist_ok=True)
			temporary=self.path.with_suffix(".tmp")
			temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
			temporary.replace(self.path)

	def entry(self, key: str, previous: dict | None=None) -> dict:
		catalog=deepcopy(CONTROLS[key])
		definition={**catalog,"name":catalog["name"],"read_every":60,"report_every":300,"change_by":0,"retain":True,"category":"config","icon":"mdi:tune"}
		if previous:
			definition.update({field:previous["definition"][field] for field in ("name","read_every","report_every","change_by","retain","icon") if field in previous["definition"]})
			if definition["name"] in catalog.get("legacy_names",[]):
				definition["name"]=catalog["name"]
		last_scan=deepcopy(previous.get("last_scan",{})) if previous else {}
		if previous and any(previous["definition"].get(field) != catalog.get(field) for field in ("factor","bitmask","shift","min","max","options","read_only","raw_only","unit")):
			words=last_scan.get("raw_registers",[])
			last_scan=read_result(catalog,words) if len(words) == len(catalog["registers"]) else {}
		return {"key":key,"definition":definition,"monitor":bool(previous and previous.get("monitor",False) and not catalog.get("read_only")),"last_scan":last_scan}

	def update(self, updates: list) -> dict:
		if not isinstance(updates,list):
			raise ValueError("sensors must be a list")
		with self.lock:
			if self.job["status"] == "running":
				raise ValueError("Poczekaj na zakończenie skanu")
			data=self.load()
			by_key={entry["key"]:entry for entry in data["available_sensors"]}
			seen=set()
			for update in updates:
				key=update.get("key")
				if key not in by_key or key in seen:
					raise ValueError("Unknown or duplicate control key")
				seen.add(key)
				entry=by_key[key]
				if type(update.get("monitor")) is not bool:
					raise ValueError("monitor must be boolean")
				if update["monitor"] and (CONTROLS[key].get("read_only") or (not entry["monitor"] and (entry["last_scan"].get("status") != "supported" or entry["last_scan"].get("write_allowed") is False))):
					raise ValueError("Najpierw wykonaj poprawny odczyt encji")
				entry["monitor"]=update["monitor"]
				for field,value in update.get("definition",{}).items():
					if field not in {"name","read_every","report_every","change_by","retain","icon"}:
						raise ValueError(f"Control encoding is fixed by catalog: {field}")
					if field in {"read_every","report_every","change_by"}:
						value=float(value)
						if not math.isfinite(value) or value < (1 if field != "change_by" else 0):
							raise ValueError("Invalid polling value")
					elif field == "retain":
						if type(value) is not bool:
							raise ValueError("retain must be boolean")
					elif not isinstance(value,str) or not value.strip() or len(value) > 200:
						raise ValueError("Invalid text setting")
					entry["definition"][field]=value
			self.store(data)
			self.writes_blocked=False
			return data

	def reset(self, clear: bool=False) -> dict:
		with self.lock:
			if self.job["status"] == "running":
				raise ValueError("Poczekaj na zakończenie skanu")
			data=self.load()
			data["available_sensors"]=[] if clear else [{**self.entry(entry["key"]),"last_scan":entry["last_scan"]} for entry in data["available_sensors"]]
			self.store(data)
			self.writes_blocked=False
			return data

	def read(self, client: Any, key: str) -> dict:
		entry=CONTROLS[key]
		words=read_words(client,entry["registers"])
		result=read_result(entry,words)
		if entry["method"] == "NumberRWSensor" and not entry.get("read_only"):
			try:
				result["min"],result["max"]=limits(entry,client)
			except ValueError as error:
				result.update(write_allowed=False,write_reason=str(error))
		if entry["method"] == "TimeRWSensor":
			result["options"]=time_options(entry,client)
		return result

	def test(self, key: str) -> dict:
		if key not in CONTROLS:
			raise ValueError("Unknown control key")
		with self.access_lock:
			client=self.transport_factory(self.logger)
			try:
				client.connect()
				result=self.read(client,key)
			finally:
				client.close()
		def save_result():
			with self.lock:
				data=self.load()
				for entry in data["available_sensors"]:
					if entry["key"] == key:
						entry["last_scan"]=result
				self.store(data)
		self.configuration_action(save_result)
		return result

	def start_scan(self, changed: Any) -> bool:
		with self.lock:
			if self.job["status"] == "running":
				return False
			self.job={"status":"running","message":"Odczyt aktualnych ustawień falownika."}
		threading.Thread(target=self._scan,args=(changed,),daemon=True,name="control-scan").start()
		return True

	def _scan(self, changed: Any) -> None:
		try:
			data=self.load()
			previous={entry["key"]:entry for entry in data["available_sensors"]}
			entries=[]
			with self.access_lock:
				client=self.transport_factory(self.logger)
				try:
					client.connect()
					for key in CONTROLS:
						entry=self.entry(key,previous.get(key))
						try:
							entry["last_scan"]=self.read(client,key)
						except Exception as error:
							entry["last_scan"]={"status":"invalid_value" if isinstance(error,ValueError) else "timeout","error":str(error)}
						entries.append(entry)
						time.sleep(self.spacing)
				finally:
					client.close()
			def save_scan():
				with self.lock:
					data=self.load()
					data["available_sensors"]=entries
					self.store(data)
					self.job={"status":"completed","message":"Odczyt zakończony. Wybierz encje sterowania MQTT."}
			self.configuration_action(save_scan)
			changed()
		except Exception as error:
			LOGGER.exception("Control scan failed")
			with self.lock:
				self.job={"status":"failed","message":str(error)}


class ControlRuntime:
	def __init__(self, service: ControlService, mqtt: Any, client: Any) -> None:
		self.service=service
		self.ownership=service.ownership
		self.mqtt=mqtt
		self.client=client
		self.queue=queue.Queue(maxsize=32)
		self.enabled={entry["key"]:entry for entry in service.load()["available_sensors"] if entry["monitor"]}
		self.last_read={}
		self.last_publish={}
		self.last_value={}
		self.blocked=service.writes_blocked
		self.last_command=0.0

	def receive(self, key: str, value: str, retained: bool) -> None:
		if retained or key not in self.enabled or self.blocked:
			return
		try:
			self.queue.put_nowait((time.monotonic(),key,value))
		except queue.Full:
			LOGGER.warning("Control command queue full")

	def start(self) -> None:
		previous_definitions=self.service.published_definitions()
		data=self.service.load()
		for key in data.get("published",[]):
			definition=CONTROLS.get(key) or RETIRED_CONTROLS.get(key) or previous_definitions.get(key)
			if key not in self.enabled and definition:
				self.mqtt.remove_control_discovery(definition)
		self.mqtt.configure_controls(self.receive,list(self.enabled))
		# Persist before publication so interrupted starts can remove retained entries later.
		with self.ownership.registry.locked() if self.ownership else nullcontext():
			with self.service.lock:
				data=self.service.load()
				data["published"]=list(self.enabled)
				self.service.store(data)
		self.tick()

	def tick(self) -> None:
		now=time.monotonic()
		if now-self.last_command >= 1:
			try:
				created,key,value=self.queue.get_nowait()
			except queue.Empty:
				pass
			else:
				if not self.blocked and now-created <= 10:
					try:
						# Shared lock covers dependency reads, read-modify-write and read-back.
						with self.service.access_lock:
							if time.monotonic()-created > 10:
								raise ValueError("Control command expired while waiting for transport")
							live=self.service.load()
							if not any(e["key"] == key and e["monitor"] for e in live["available_sensors"]):
								raise ValueError("Control deselected")
							with self.ownership.guard(component(CONTROLS[key]),key) if self.ownership else nullcontext(True) as owned:
								if not owned:
									raise ValueError("Control belongs to another application")
								if time.monotonic()-created > 10:
									raise ValueError("Control command expired while waiting for ownership")
								# Reload selection while holding ownership through the physical write.
								if not any(e["key"] == key and e["monitor"] for e in self.service.load()["available_sensors"]):
									raise ValueError("Control deselected")
								write_control(self.client,CONTROLS[key],value)
						self.last_read.pop(key,None)
						self.last_value.pop(key,None)
						self.last_command=now
					except ValueError as error:
						LOGGER.warning("Control command rejected key=%s: %s",key,error)
					except Exception:
						self.blocked=True
						self.service.writes_blocked=True
						for control_key in self.enabled:
							self.mqtt.control_availability(control_key,False)
						LOGGER.exception("Control writes blocked until configuration reload")
		for key,entry in self.enabled.items():
			if self.ownership and not self.ownership.owns(component(CONTROLS[key]),key):
				continue
			if now-self.last_read.get(key,-math.inf) < entry["definition"]["read_every"]:
				continue
			self.last_read[key]=now
			try:
				with self.service.access_lock:
					result=self.service.read(self.client,key)
				if result["write_allowed"]:
					self.mqtt.publish_control_discovery(entry,result)
				value=result["value"]
				previous=self.last_value.get(key)
				changed=value != previous
				if isinstance(value,(int,float)) and isinstance(previous,(int,float)):
					changed=changed and abs(value-previous) >= entry["definition"]["change_by"]
				if changed or now-self.last_publish.get(key,-math.inf) >= entry["definition"]["report_every"]:
					self.mqtt.publish_control_state(entry,result)
					self.last_value[key]=value
					self.last_publish[key]=now
				self.mqtt.control_availability(key,not self.blocked and result["write_allowed"])
			except TransportConnectionClosedError:
				self.mqtt.control_availability(key,False)
				raise
			except Exception as error:
				self.mqtt.control_availability(key,False)
				LOGGER.warning("Control read failed key=%s: %s",key,error)
			time.sleep(self.service.spacing)
