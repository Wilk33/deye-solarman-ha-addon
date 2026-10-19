from __future__ import annotations

import logging
import os
import signal
import threading
import time
from typing import Any

from ha_audio_common.config import load_options
from ha_audio_common.logging_utils import configure_logging
from ha_audio_common.mqtt import MqttServiceClient
from ha_audio_common.supervisor import HomeAssistantClient
from ha_audio_common.supervisor import discover_mqtt_service

from .gpio import GpioOutput
from .mqtt import discovery_messages
from .outputs import AudioAlarmOutput
from .runtime import AlarmApp


LOGGER=logging.getLogger(__name__)


def build_output(options: dict[str,Any]) -> Any:
	mode=str(options.get("output_mode","audio"))
	if mode == "audio":
		return AudioAlarmOutput(
			str(options.get("audio_file","")),
			int(options.get("audio_volume_percent",95)),
		)
	if mode == "gpio":
		output=GpioOutput(
			int(options.get("gpio_pin",17)),
			bool(options.get("gpio_active_high",True)),
		)
		output.initialize()
		return output
	raise ValueError(f"Nieobsługiwany output_mode: {mode}")


def handle_command(
	app: AlarmApp,
	base_topic: str,
	topic: str,
	payload: str,
	retained: bool,
) -> None:
	if retained:
		return
	if topic == f"{base_topic}/command/acknowledge":
		if payload.upper() != "PRESS":
			LOGGER.warning("Odrzucono komendę potwierdzenia MQTT: %s",payload)
			return
		app.acknowledge_active_alarms()
		return
	if topic == f"{base_topic}/command/test_value":
		try:
			app.set_test_value(payload)
		except (TypeError,ValueError) as error:
			LOGGER.warning("Odrzucono testową wartość MQTT: %s",error)


def main() -> None:
	options=load_options()
	configure_logging(str(options.get("log_level","INFO")))
	base_topic=str(options.get("mqtt_base_topic","haos_alarm")).rstrip("/")
	discovery_prefix=str(options.get("mqtt_discovery_prefix","homeassistant")).rstrip("/")
	device_name=str(options.get("device_name","Alarm"))
	stop=threading.Event()
	holder: dict[str,AlarmApp]={}

	def handle_message(topic: str,payload: str,retained: bool) -> None:
		handle_command(holder["app"],base_topic,topic,payload,retained)

	token=os.environ.get("SUPERVISOR_TOKEN","")
	ha=HomeAssistantClient(token)
	service=discover_mqtt_service(token)
	mqtt=MqttServiceClient(service,"haos-alarm",handle_message)
	mqtt.set_last_will(f"{base_topic}/availability")
	output=build_output(options)
	app=AlarmApp(options,ha,mqtt,output)
	holder["app"]=app
	app.validate_notification_targets()

	def stop_handler(_signum: int,_frame: Any) -> None:
		stop.set()

	signal.signal(signal.SIGTERM,stop_handler)
	signal.signal(signal.SIGINT,stop_handler)

	try:
		mqtt.connect()
		mqtt.subscribe(f"{base_topic}/command/acknowledge")
		mqtt.subscribe(f"{base_topic}/command/test_value")
		mqtt.publish(f"{discovery_prefix}/switch/haos_alarm/enabled/config","")
		for message in discovery_messages(discovery_prefix,base_topic,device_name):
			mqtt.publish(message.topic,message.payload)
		mqtt.publish(f"{base_topic}/availability","online")
		LOGGER.info(
			"Alarm uruchomiony: tryb=%s, encje=%s, aktywne reguły=%s, cele powiadomień=%s",
			options.get("output_mode","audio"),
			len(app.monitors),
			sum(1 for monitor in app.monitors if monitor.enabled),
			len(app.notification_targets),
		)
		interval=max(1,int(options.get("poll_interval_seconds",5)))
		while not stop.is_set():
			started=time.monotonic()
			try:
				app.poll_once()
			except Exception:
				LOGGER.exception("Błąd cyklu monitorowania")
			remaining=max(0,interval-(time.monotonic()-started))
			stop.wait(remaining)
	finally:
		app.close()
		try:
			mqtt.publish_and_wait(str(options.get("alarm_coordination_topic","haos_alarm/active")),"OFF")
			mqtt.publish_and_wait(f"{base_topic}/availability","offline")
		except Exception:
			LOGGER.exception("Nie udało się potwierdzić końcowego stanu MQTT alarmu")
		finally:
			mqtt.close()


if __name__ == "__main__":
	main()
