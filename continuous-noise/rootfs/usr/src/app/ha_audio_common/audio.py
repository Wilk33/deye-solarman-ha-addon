from __future__ import annotations

import logging
import math
import random
import struct
import subprocess
import threading
import wave
from pathlib import Path


LOGGER=logging.getLogger(__name__)


def generate_alarm_wav(path: Path,duration_seconds: int=8,sample_rate: int=22050) -> Path:
	frames=[]
	for index in range(duration_seconds*sample_rate):
		time=index/sample_rate
		phase=time%1.0
		if phase >= 0.72:
			sample=0.0
		else:
			frequency=880 if phase < 0.36 else 660
			sample=math.sin(2*math.pi*frequency*time)*0.72
		frames.append(struct.pack("<h",int(sample*32767)))
	with wave.open(str(path),"wb") as output:
		output.setnchannels(1)
		output.setsampwidth(2)
		output.setframerate(sample_rate)
		output.writeframes(b"".join(frames))
	return path


def generate_noise_wav(path: Path,noise_type: str,duration_seconds: int=20,sample_rate: int=22050) -> Path:
	if noise_type not in {"white","pink","brown","violet"}:
		raise ValueError(f"Nieobsługiwany rodzaj szumu: {noise_type}")
	randomizer=random.Random(f"continuous-noise:{noise_type}")
	count=duration_seconds*sample_rate
	white=[randomizer.uniform(-1,1) for _ in range(count)]
	values=[]
	if noise_type == "white":
		values=white
	elif noise_type == "brown":
		state=0.0
		for sample in white:
			state=(state+sample*0.02)/1.02
			values.append(state*3.5)
	elif noise_type == "violet":
		previous=0.0
		for sample in white:
			values.append((sample-previous)*0.55)
			previous=sample
	else:
		b0=b1=b2=0.0
		for sample in white:
			b0=0.99765*b0+sample*0.0990460
			b1=0.96300*b1+sample*0.2965164
			b2=0.57000*b2+sample*1.0526913
			values.append((b0+b1+b2+sample*0.1848)*0.05)
	peak=max(max(abs(value) for value in values),0.001)
	scale=0.72/peak
	frames=b"".join(struct.pack("<h",int(max(-1,min(1,value*scale))*32767)) for value in values)
	with wave.open(str(path),"wb") as output:
		output.setnchannels(1)
		output.setsampwidth(2)
		output.setframerate(sample_rate)
		output.writeframes(frames)
	return path


class LoopingAudioPlayer:
	def __init__(self,binary: str="paplay") -> None:
		self.binary=binary
		self._lock=threading.RLock()
		self._stop=threading.Event()
		self._thread: threading.Thread | None=None
		self._process: subprocess.Popen | None=None
		self._path: Path | None=None
		self._volume=100

	@property
	def active(self) -> bool:
		with self._lock:
			return self._thread is not None and self._thread.is_alive()

	def start(self,path: str | Path,volume_percent: int) -> None:
		path=Path(path)
		if not path.is_file():
			raise FileNotFoundError(path)
		volume=max(0,min(100,int(volume_percent)))
		with self._lock:
			if self.active and self._path == path and self._volume == volume:
				return
		self.stop()
		with self._lock:
			self._path=path
			self._volume=volume
			self._stop.clear()
			self._thread=threading.Thread(target=self._run,name="audio-loop",daemon=True)
			self._thread.start()
		LOGGER.info("Uruchomiono audio w pętli: %s, głośność=%s%%",path,volume)

	def stop(self) -> None:
		with self._lock:
			self._stop.set()
			process=self._process
			thread=self._thread
			if process is not None and process.poll() is None:
				process.terminate()
		if thread is not None and thread is not threading.current_thread():
			thread.join(timeout=3)
		with self._lock:
			self._process=None
			self._thread=None

	def _run(self) -> None:
		while not self._stop.is_set():
			with self._lock:
				path=self._path
				volume=int(65536*self._volume/100)
			try:
				process=subprocess.Popen(
					[self.binary,f"--volume={volume}",str(path)],
					stdout=subprocess.DEVNULL,
					stderr=subprocess.PIPE,
					text=True,
				)
				with self._lock:
					self._process=process
				_,error=process.communicate()
				if process.returncode not in {0,-15} and not self._stop.is_set():
					LOGGER.error("Odtwarzanie audio zakończone błędem %s: %s",process.returncode,error.strip())
					self._stop.wait(2)
			except OSError as error:
				LOGGER.error("Nie można uruchomić odtwarzania audio: %s",error)
				self._stop.wait(5)
		with self._lock:
			self._process=None
