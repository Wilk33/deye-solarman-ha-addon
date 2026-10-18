from __future__ import annotations

import logging
import math
import re
import threading
from typing import Any

from .models import AlarmLevel
from .models import MonitorDefinition
from .models import aggregate_level


LOGGER=logging.getLogger(__name__)
ACTIVE_LEVELS={AlarmLevel.ALARM_LOW,AlarmLevel.ALARM_HIGH}
NOTIFY_LEVELS={AlarmLevel.WARNING_LOW,AlarmLevel.WARNING_HIGH,*ACTIVE_LEVELS}


class AlarmApp:
	def __init__(self,options: dict[str,Any],home_assistant: Any,publisher: Any,output: Any) -> None:
		self.options=options
		self.home_assistant=home_assistant
		self.publisher=publisher
		self.output=output
		self.base_topic=str(options.get("mqtt_base_topic","haos_alarm")).rstrip("/")
		self.notification_targets=[str(value).strip() for value in options.get("notification_targets",[]) if str(value).strip()]
		self.notify_recovery=bool(options.get("notify_recovery",True))
		self.monitors=[MonitorDefinition.from_dict(item) for item in options.get("monitored_entities",[])]
		self.levels={monitor.entity_id:AlarmLevel.DISABLED for monitor in self.monitors}
		self.values: dict[str,float | None]={monitor.entity_id:None for monitor in self.monitors}
		self.enabled=True
		self.state="initializing"
		self._output_active=False
		self._lock=threading.RLock()

	def set_enabled(self,enabled: bool) -> None:
		with self._lock:
			self.enabled=bool(enabled)
			if not self.enabled:
				self._set_output(False)
				self.state="disabled"
			else:
				self._apply_global_level()
			self._publish_state()
		LOGGER.info("Alarm %s", "włączony" if self.enabled else "wyłączony")

	def poll_once(self) -> None:
		with self._lock:
			if not self.enabled:
				self.state="disabled"
				self._publish_state()
				return
			for monitor in self.monitors:
				if not monitor.enabled:
					self.levels[monitor.entity_id]=AlarmLevel.DISABLED
					continue
				previous=self.levels.get(monitor.entity_id,AlarmLevel.UNAVAILABLE)
				try:
					payload=self.home_assistant.get_state(monitor.entity_id)
					value=float(str(payload.get("state","")).replace(",","."))
					if not math.isfinite(value):
						raise ValueError("wartość nie jest skończona")
					level=monitor.evaluate(value)
				except (KeyError,TypeError,ValueError,OSError) as error:
					LOGGER.warning("Nie można odczytać %s: %s",monitor.entity_id,error)
					value=None
					level=AlarmLevel.UNAVAILABLE
				self.values[monitor.entity_id]=value
				self.levels[monitor.entity_id]=level
				if level != previous:
					LOGGER.info("Zmiana %s: %s -> %s, wartość=%s",monitor.entity_id,previous.value,level.value,value)
					self._notify_transition(monitor,previous,level,value)
			self._apply_global_level()
			self._publish_state()

	def close(self) -> None:
		with self._lock:
			self._set_output(False)
			self.output.close()

	def _apply_global_level(self) -> None:
		level=aggregate_level(list(self.levels.values()))
		active=level in ACTIVE_LEVELS
		self._set_output(active)
		if level == AlarmLevel.DISABLED:
			self.state="ok"
		else:
			self.state=level.state

	def _set_output(self,active: bool) -> None:
		if self._output_active == active:
			return
		self.output.set_active(active)
		self._output_active=active
		LOGGER.warning("Wyjście alarmu: %s","AKTYWNE" if active else "wyłączone")

	def _notify_transition(self,monitor: MonitorDefinition,previous: AlarmLevel,level: AlarmLevel,value: float | None) -> None:
		notification_id="haos_alarm_"+re.sub(r"[^a-zA-Z0-9_]","_",monitor.entity_id)
		if level in NOTIFY_LEVELS:
			kind="ALARM" if level in ACTIVE_LEVELS else "Ostrzeżenie"
			direction="poniżej" if level in {AlarmLevel.ALARM_LOW,AlarmLevel.WARNING_LOW} else "powyżej"
			threshold=monitor.threshold_for(level)
			title=f"{kind} - {monitor.name}"
			message=f"{monitor.entity_id}: wartość {value:g} jest {direction} progu {threshold:g}."
			self._send_notifications(title,message,notification_id)
		elif self.notify_recovery and previous in NOTIFY_LEVELS and level == AlarmLevel.OK:
			title=f"Powrót do normy - {monitor.name}"
			message=f"{monitor.entity_id}: wartość wróciła do prawidłowego zakresu ({value:g})."
			self._send_notifications(title,message,notification_id)
		elif level == AlarmLevel.OK:
			try:
				self.home_assistant.dismiss_persistent_notification(notification_id)
			except OSError:
				LOGGER.debug("Nie udało się usunąć starego powiadomienia %s",notification_id,exc_info=True)

	def _send_notifications(self,title: str,message: str,notification_id: str) -> None:
		try:
			self.home_assistant.persistent_notification(title,message,notification_id)
		except OSError:
			LOGGER.exception("Nie udało się utworzyć trwałego powiadomienia Home Assistant")
		for target in self.notification_targets:
			try:
				self.home_assistant.send_notification(target,title,message)
			except (OSError,ValueError):
				LOGGER.exception("Nie udało się wysłać powiadomienia do %s",target)

	def _publish_state(self) -> None:
		self.publisher.publish(f"{self.base_topic}/state/enabled","ON" if self.enabled else "OFF")
		self.publisher.publish(f"{self.base_topic}/state/state",self.state)
		self.publisher.publish(f"{self.base_topic}/state/attributes",{
			"output_active":self._output_active,
			"output_mode":self.options.get("output_mode","audio"),
			"monitors":[
				{
					"entity_id":monitor.entity_id,
					"name":monitor.name,
					"level":self.levels[monitor.entity_id].value,
					"value":self.values[monitor.entity_id],
					"configured":monitor.enabled,
				}
				for monitor in self.monitors
			],
		})
		self.publisher.publish(str(self.options.get("alarm_coordination_topic","haos_alarm/active")),"ON" if self._output_active else "OFF")
