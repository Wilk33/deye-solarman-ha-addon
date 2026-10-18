from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

from ha_audio_common.audio import generate_noise_wav

from .models import NoiseDefinition
from .models import NoiseSelection


LOGGER=logging.getLogger(__name__)


def prepare_noise_files(definitions: list[NoiseDefinition],directory: str | Path="/tmp/continuous-noise") -> dict[str,Path]:
	root=Path(directory)
	root.mkdir(parents=True,exist_ok=True)
	paths={}
	by_type={}
	for definition in definitions:
		path=by_type.get(definition.noise_type)
		if path is None:
			path=generate_noise_wav(root/f"{definition.noise_type}.wav",definition.noise_type)
			by_type[definition.noise_type]=path
		paths[definition.key]=path
	return paths


class NoiseApp:
	def __init__(
		self,
		options: dict[str,Any],
		publisher: Any,
		player: Any,
		paths: dict[str,str | Path],
	) -> None:
		self.options=options
		self.publisher=publisher
		self.player=player
		self.base_topic=str(options.get("mqtt_base_topic","continuous_noise")).rstrip("/")
		self.volume_percent=int(options.get("volume_percent",50))
		self.definitions=[NoiseDefinition.from_dict(item) for item in options.get("noises",[])]
		if not self.definitions:
			raise ValueError("Skonfiguruj co najmniej jeden szum")
		self.selection=NoiseSelection(self.definitions)
		self.paths={key:Path(path) for key,path in paths.items()}
		self._lock=threading.RLock()

	def command(self,key: str,payload: str) -> None:
		with self._lock:
			before=self.selection.playing
			self.selection.command(key,payload)
			self._sync_playback(before)
			self.publish_states()
		LOGGER.info("Komenda szumu %s=%s, wybrany=%s",key,payload,self.selection.requested)

	def set_alarm_active(self,active: bool) -> None:
		with self._lock:
			before=self.selection.playing
			self.selection.set_alarm_active(active)
			self._sync_playback(before)
			self.publish_states()
		LOGGER.warning("Alarm audio %s - szum %s","aktywny" if active else "wyłączony","wstrzymany" if active else "wznowiony")

	def publish_states(self) -> None:
		for key,state in self.selection.states().items():
			self.publisher.publish(f"{self.base_topic}/state/{key}",state)
		self.publisher.publish(f"{self.base_topic}/state/active",self.selection.playing or "off")

	def close(self) -> None:
		with self._lock:
			self.player.stop()

	def _sync_playback(self,before: str | None) -> None:
		after=self.selection.playing
		if before == after:
			return
		if after is None:
			self.player.stop()
			return
		path=self.paths.get(after)
		if path is None:
			raise RuntimeError(f"Brak pliku dla szumu {after}")
		self.player.start(path,self.volume_percent)
