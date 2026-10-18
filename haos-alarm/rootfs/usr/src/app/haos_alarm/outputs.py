from __future__ import annotations

import logging
from pathlib import Path

from ha_audio_common.audio import LoopingAudioPlayer
from ha_audio_common.audio import generate_alarm_wav


LOGGER=logging.getLogger(__name__)


class AudioAlarmOutput:
	def __init__(self,audio_file: str,volume_percent: int,player: LoopingAudioPlayer | None=None) -> None:
		self.player=player or LoopingAudioPlayer()
		self.volume_percent=int(volume_percent)
		if str(audio_file).strip():
			self.path=Path(str(audio_file).strip())
		else:
			self.path=generate_alarm_wav(Path("/tmp/haos-alarm.wav"))
		if not self.path.is_file():
			raise FileNotFoundError(f"Nie znaleziono pliku alarmu: {self.path}")

	def set_active(self,active: bool) -> None:
		if active:
			self.player.start(self.path,self.volume_percent)
		else:
			self.player.stop()

	def close(self) -> None:
		self.player.stop()
