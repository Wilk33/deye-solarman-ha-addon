from __future__ import annotations

import logging
import os


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


def configure_logging() -> None:
	color=os.environ.get("DEYE_LOG_COLOR","true").lower() not in {"0","false","no"}
	handler=logging.StreamHandler()
	handler.setFormatter(AddonLogFormatter(color))
	logging.basicConfig(level=logging.INFO,handlers=[handler],force=True)
