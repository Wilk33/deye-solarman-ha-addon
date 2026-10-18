from __future__ import annotations

import logging
import os
import signal
import threading
from typing import Any

from ha_audio_common.audio import LoopingAudioPlayer
from ha_audio_common.config import load_options
from ha_audio_common.logging_utils import configure_logging
from ha_audio_common.mqtt import MqttServiceClient
from ha_audio_common.supervisor import discover_mqtt_service

from .models import NoiseDefinition
from .mqtt import discovery_messages
from .runtime import NoiseApp
from .runtime import prepare_noise_files


LOGGER=logging.getLogger(__name__)


def main() -> None:
	options=load_options()
	configure_logging(str(options.get("log_level","INFO")))
	base_topic=str(options.get("mqtt_base_topic","continuous_noise")).rstrip("/")
	discovery_prefix=str(options.get("mqtt_discovery_prefix","homeassistant")).rstrip("/")
	device_name=str(options.get("device_name","Szum ciągły"))
	alarm_topic=str(options.get("alarm_coordination_topic","haos_alarm/active"))
	alarm_availability_topic=str(options.get("alarm_availability_topic","haos_alarm/availability"))
	definitions=[NoiseDefinition.from_dict(item) for item in options.get("noises",[])]
	paths=prepare_noise_files(definitions)
	stop=threading.Event()
	holder: dict[str,NoiseApp]={}

	def handle_message(topic: str,payload: str,retained: bool) -> None:
		app=holder["app"]
		if topic == alarm_topic:
			app.set_alarm_active(payload.upper() == "ON")
			return
		if topic == alarm_availability_topic:
			if payload.lower() != "online":
				app.set_alarm_active(False)
			return
		prefix=f"{base_topic}/command/"
		if retained or not topic.startswith(prefix):
			return
		key=topic.removeprefix(prefix)
		try:
			app.command(key,payload)
		except ValueError as error:
			LOGGER.warning("Odrzucono komendę MQTT: %s",error)

	service=discover_mqtt_service(os.environ.get("SUPERVISOR_TOKEN",""))
	mqtt=MqttServiceClient(service,"continuous-noise",handle_message)
	mqtt.set_last_will(f"{base_topic}/availability")
	app=NoiseApp(options,mqtt,LoopingAudioPlayer(),paths)
	holder["app"]=app

	def stop_handler(_signum: int,_frame: Any) -> None:
		stop.set()

	signal.signal(signal.SIGTERM,stop_handler)
	signal.signal(signal.SIGINT,stop_handler)

	try:
		mqtt.connect()
		mqtt.subscribe(f"{base_topic}/command/+")
		mqtt.subscribe(alarm_topic)
		mqtt.subscribe(alarm_availability_topic)
		for message in discovery_messages(discovery_prefix,base_topic,device_name,definitions):
			mqtt.publish(message.topic,message.payload)
		mqtt.publish(f"{base_topic}/availability","online")
		app.publish_states()
		LOGGER.info("Odtwarzacz szumów uruchomiony: szumy=%s, głośność=%s%%",len(definitions),app.volume_percent)
		stop.wait()
	finally:
		app.close()
		try:
			mqtt.publish_and_wait(f"{base_topic}/availability","offline")
		except Exception:
			LOGGER.exception("Nie udało się potwierdzić końcowego stanu MQTT odtwarzacza szumów")
		finally:
			mqtt.close()


if __name__ == "__main__":
	main()
