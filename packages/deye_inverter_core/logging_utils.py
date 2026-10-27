from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager,nullcontext


SUCCESS=25
logging.addLevelName(SUCCESS,"OK")


class AddonLogFormatter(logging.Formatter):
	"""Compact add-on log rows with visible severity markers and ANSI color."""

	_COLORS={
		SUCCESS: "\033[32m",
		logging.WARNING: "\033[33m",
		logging.ERROR: "\033[31m",
		logging.CRITICAL: "\033[31m",
	}
	_MARKERS={
		logging.DEBUG: "DEBUG",
		logging.INFO: "INFO",
		SUCCESS: "OK",
		logging.WARNING: "WARN",
		logging.ERROR: "ERROR",
		logging.CRITICAL: "ERROR",
	}

	def __init__(self, color: bool) -> None:
		super().__init__()
		self._color=color

	def format(self, record: logging.LogRecord) -> str:
		marker=self._MARKERS.get(record.levelno,record.levelname)
		module=record.name.rsplit(".",1)[-1]
		message=record.getMessage()
		line=f"{self.formatTime(record,'%Y-%m-%d %H:%M:%S')} [{marker:^5}] {module:<12} | {message}"
		if record.exc_info:
			line=f"{line}\n{self.formatException(record.exc_info)}"
		color=self._COLORS.get(record.levelno,"") if self._color else ""
		return f"{color}{line}\033[0m" if color else line


def success(logger: logging.Logger, message: str, *args: object) -> None:
	logger.log(SUCCESS,message,*args)


def mqtt_publication_batch(publisher: object,kind: str,transport: str="shared"):
	factory=getattr(type(publisher),"publication_batch",None)
	return nullcontext() if factory is None else factory(publisher,kind,transport=transport)


@contextmanager
def register_operation(logger: logging.Logger,transport: str,operation: str,start: int,count: int,modbus_id: int):
	details={}
	started_at=time.perf_counter()
	logger.debug("Register request transport=%s operation=%s start=%s count=%s modbus_id=%s",transport,operation,start,count,modbus_id)
	try:
		yield details
	except Exception as error:
		logger.debug("Register response transport=%s operation=%s start=%s count=%s result=error latency_ms=%.2f error=%s",transport,operation,start,count,(time.perf_counter()-started_at)*1000,error)
		raise
	else:
		words=" ".join(f"0x{word:04X}" for word in details.get("registers",[]))
		logger.debug("Register response transport=%s operation=%s start=%s count=%s result=ok latency_ms=%.2f registers=[%s]",transport,operation,start,count,(time.perf_counter()-started_at)*1000,words)


def configure_logging(detailed: bool=False) -> None:
	color=os.environ.get("DEYE_LOG_COLOR","true").lower() not in {"0","false","no"}
	handler=logging.StreamHandler()
	handler.setFormatter(AddonLogFormatter(color))
	logging.basicConfig(level=logging.DEBUG if detailed else logging.INFO,handlers=[handler],force=True)
	for dependency in ("pymodbus","pysolarmanv5"):
		logging.getLogger(dependency).setLevel(logging.WARNING)
