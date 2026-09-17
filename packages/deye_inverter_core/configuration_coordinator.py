"""Atomic rollback boundary for related local configuration files."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import threading
from typing import Any
from typing import Callable


class ConfigurationCoordinator:
	def __init__(self,files: list[str | Path]) -> None:
		self.files={Path(path) for path in files}
		self._lock=threading.RLock()

	@contextmanager
	def locked(self):
		with self._lock:
			yield

	def apply(self,action: Callable[[],Any]) -> Any:
		with self._lock:
			before={path:path.read_bytes() if path.exists() else None for path in self.files}
			try:
				return action()
			except Exception:
				for path,content in before.items():
					if content is None:
						path.unlink(missing_ok=True)
					elif not path.exists() or path.read_bytes() != content:
						path.parent.mkdir(parents=True,exist_ok=True)
						temporary=path.with_name(f".{path.name}.configuration-rollback")
						temporary.write_bytes(content)
						temporary.replace(path)
				raise
