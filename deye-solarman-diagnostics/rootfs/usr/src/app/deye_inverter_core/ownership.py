"""Cross-process entity ownership shared by transport applications on one HAOS host."""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import time
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path

DEFAULT_REGISTRY="/share/entity_owners.json"
_states={}
_states_lock=threading.Lock()


class OwnershipConflict(ValueError):
	pass


class OwnershipUnavailable(RuntimeError):
	pass


class EntityOwnershipRegistry:
	def __init__(self, path: str | Path=DEFAULT_REGISTRY):
		self.path=Path(path).resolve()
		with _states_lock:
			self._mutex,self._local=_states.setdefault(str(self.path),(threading.RLock(),threading.local()))

	@contextmanager
	def locked(self):
		with self._mutex:
			if hasattr(self._local,"data"):
				yield self._local.data
				return
			body_error=False
			try:
				self.path.parent.mkdir(parents=True,exist_ok=True)
				# The lock inode is never replaced with the JSON data file.
				with self.path.with_suffix(self.path.suffix+".lock").open("a+b") as handle:
					self._acquire(handle)
					try:
						data=self._read()
						self._local.before=deepcopy(data)
						self._local.data=data
						try:
							try:
								yield data
							except OSError:
								body_error=True
								raise
							if data != self._local.before:
								self._write(data)
						finally:
							del self._local.data
							del self._local.before
					finally:
						self._release(handle)
			except OSError as error:
				if body_error:
					raise
				raise OwnershipUnavailable(f"Rejestr właścicieli niedostępny: {error}") from error

	def _read(self):
		if not self.path.exists():
			return {}
		try:
			data=json.loads(self.path.read_text(encoding="utf-8"))
		except (ValueError,UnicodeError) as error:
			raise OwnershipUnavailable("Uszkodzony rejestr właścicieli; operacja zablokowana") from error
		if not isinstance(data,dict) or any(not isinstance(key,str) or len(key.split(":")) != 3 or not isinstance(value,dict) or not isinstance(value.get("owner"),str) or not value["owner"] for key,value in data.items()):
			raise OwnershipUnavailable("Niepoprawny format rejestru właścicieli")
		return data

	def _write(self, data):
		fd,name=tempfile.mkstemp(prefix=self.path.name+".",suffix=".tmp",dir=self.path.parent)
		try:
			with os.fdopen(fd,"w",encoding="utf-8",newline="\n") as handle:
				json.dump(data,handle,ensure_ascii=False,indent=2,sort_keys=True)
				handle.flush()
				os.fsync(handle.fileno())
			os.replace(name,self.path)
		finally:
			if os.path.exists(name):
				os.unlink(name)

	def snapshot(self):
		with self.locked() as data:
			return deepcopy(data)

	def commit_locked(self):
		"""Persist while still inside a caller's rollback boundary."""
		if self._local.data != self._local.before:
			try:
				self._write(self._local.data)
			except OSError as error:
				raise OwnershipUnavailable(f"Nie można zapisać rejestru właścicieli: {error}") from error
			self._local.before=deepcopy(self._local.data)

	@staticmethod
	def _acquire(handle):
		if os.name == "nt":
			import msvcrt
			if handle.seek(0,2) == 0:
				handle.write(b"0")
				handle.flush()
			deadline=time.monotonic()+30
			while True:
				handle.seek(0)
				try:
					msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
					return
				except OSError:
					if time.monotonic() >= deadline:
						raise
					time.sleep(0.02)
		else:
			import fcntl
			fcntl.flock(handle.fileno(),fcntl.LOCK_EX)

	@staticmethod
	def _release(handle):
		if os.name == "nt":
			import msvcrt
			handle.seek(0)
			msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
		else:
			import fcntl
			fcntl.flock(handle.fileno(),fcntl.LOCK_UN)


class EntityOwnership:
	def __init__(self, registry: EntityOwnershipRegistry, serial: str, source: str, name: str):
		if not re.fullmatch(r"[a-z0-9_]+",source) or not serial or ":" in serial:
			raise ValueError("Invalid ownership identity")
		self.registry=registry
		self.serial=serial
		self.source=source
		self.name=name

	def entity_id(self, component: str, key: str):
		if not component or not key or ":" in component or ":" in key:
			raise ValueError("Invalid entity ownership key")
		return f"{self.serial}:{component}:{key}"

	def reconcile(self, desired: set[tuple[str,str]], strict: bool=False):
		identities={self.entity_id(component,key) for component,key in desired}
		with self.registry.locked() as data:
			conflicts={key: data[key]["owner"] for key in identities if key in data and data[key]["owner"] != self.source}
			if conflicts and strict:
				raise OwnershipConflict("Encje używane przez inną aplikację: "+", ".join(f"{key}: {owner}" for key,owner in sorted(conflicts.items())))
			for key in list(data):
				if key.startswith(self.serial+":") and data[key]["owner"] == self.source and key not in identities:
					del data[key]
			for key in identities-conflicts.keys():
				data[key]={"owner":self.source,"name":self.name}
			return conflicts

	@contextmanager
	def guard(self, component: str, key: str, unowned: bool=False):
		with self.registry.locked() as data:
			owner=data.get(self.entity_id(component,key),{}).get("owner")
			yield owner is None if unowned else owner == self.source

	def owns(self, component: str, key: str):
		with self.guard(component,key) as allowed:
			return allowed

	def annotate(self, payload: dict, field: str="available_sensors", controls: bool=False):
		from .controls import component
		result=deepcopy(payload)
		with self.registry.locked() as data:
			for entry in result.get(field,[]):
				kind=component(entry["definition"]) if controls else "sensor"
				record=data.get(self.entity_id(kind,entry["key"]),{})
				owner=record.get("owner")
				entry["ownership"]={"owner":owner,"name":record.get("name",owner),"editable":owner in (None,self.source)}
				if not entry["ownership"]["editable"]:
					entry["monitor"]=False
		return result
