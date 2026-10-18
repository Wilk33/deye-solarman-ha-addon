from __future__ import annotations

import logging
import time
from pathlib import Path


LOGGER=logging.getLogger(__name__)


class GpioOutput:
	def __init__(self,pin: int,active_high: bool=True,sysfs_root: str | Path="/sys/class/gpio") -> None:
		if not 0 <= int(pin) <= 27:
			raise ValueError("Numer GPIO Raspberry Pi musi mieścić się w zakresie 0-27")
		self.pin=int(pin)
		self.active_high=bool(active_high)
		self.root=Path(sysfs_root)
		self.global_number=self._find_rp1_base()+self.pin
		self.line=self.root/f"gpio{self.global_number}"
		self._initialized=False

	def _find_rp1_base(self) -> int:
		fallback=[]
		for chip in sorted(self.root.glob("gpiochip*")):
			try:
				label=(chip/"label").read_text(encoding="utf-8").strip()
				base=int((chip/"base").read_text(encoding="utf-8").strip())
			except (OSError,ValueError):
				continue
			fallback.append((label,base))
			if label in {"pinctrl-rp1","pinctrl-bcm2712"}:
				return base
		raise RuntimeError(f"Nie znaleziono kontrolera GPIO Raspberry Pi 5 pinctrl-rp1: {fallback}")

	def initialize(self,export: bool=True) -> None:
		if export and not self.line.exists():
			(self.root/"export").write_text(str(self.global_number),encoding="utf-8")
			for _ in range(50):
				if self.line.exists():
					break
				time.sleep(0.02)
		if not self.line.exists():
			raise RuntimeError(f"Nie można udostępnić GPIO {self.pin} jako {self.global_number}")
		(self.line/"direction").write_text("out",encoding="utf-8")
		self._initialized=True
		self.set_active(False)
		LOGGER.info("GPIO gotowe: BCM=%s global=%s active_high=%s",self.pin,self.global_number,self.active_high)

	def set_active(self,active: bool) -> None:
		if not self._initialized:
			raise RuntimeError("GPIO nie zostało zainicjalizowane")
		value="1" if bool(active) == self.active_high else "0"
		(self.line/"value").write_text(value,encoding="utf-8")

	def close(self) -> None:
		if self._initialized:
			try:
				self.set_active(False)
			except OSError:
				LOGGER.exception("Nie udało się przywrócić bezpiecznego stanu GPIO")
		self._initialized=False
