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
TEST_ENTITY_ID="number.haos_alarm_test_value"


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
		self.test_monitor=MonitorDefinition(
			entity_id=TEST_ENTITY_ID,
			name="Test alarmu",
			alarm_low=-20,
			warning_low=-10,
			warning_high=10,
			alarm_high=20,
			hysteresis=5,
		)
		self.all_monitors=[*self.monitors,self.test_monitor]
		self.levels={monitor.entity_id:AlarmLevel.DISABLED for monitor in self.all_monitors}
		self.values: dict[str,float | None]={monitor.entity_id:None for monitor in self.all_monitors}
		self.acknowledged_levels: dict[str,AlarmLevel | None]={monitor.entity_id:None for monitor in self.all_monitors}
		self.levels[TEST_ENTITY_ID]=AlarmLevel.OK
		self.values[TEST_ENTITY_ID]=0.0
		self.state="initializing"
		self._output_active=False
		self._lock=threading.RLock()

	def validate_notification_targets(self) -> list[str]:
		invalid=[]
		for target in self.notification_targets:
			if not target.startswith("notify."):
				invalid.append(target)
				LOGGER.error("Nieprawidłowy cel powiadomień: %s. Wymagana jest encja notify.*",target)
				continue
			try:
				self.home_assistant.get_state(target)
			except (KeyError,OSError,RuntimeError,ValueError):
				invalid.append(target)
				LOGGER.error(
					"Cel powiadomień %s nie istnieje jako encja Home Assistant. "
					"Użyj identyfikatora ze strony Narzędzia -> Stany, a nie nazwy starej akcji notify.mobile_app_*.",
					target,
				)
		return invalid

	def acknowledge_active_alarms(self) -> int:
		with self._lock:
			acknowledged=0
			for monitor in self.all_monitors:
				level=self.levels[monitor.entity_id]
				if level not in ACTIVE_LEVELS:
					continue
				if self.acknowledged_levels[monitor.entity_id] == level:
					continue
				self.acknowledged_levels[monitor.entity_id]=level
				acknowledged+=1
				LOGGER.warning(
					"Potwierdzono alarm %s dla %s, ponowne uzbrojenie przy wartości %s",
					level.value,
					monitor.entity_id,
					monitor.rearm_threshold(level),
				)
			self._apply_global_level()
			self._publish_state()
		if acknowledged == 0:
			LOGGER.info("Polecenie potwierdzenia nie znalazło aktywnego alarmu")
		return acknowledged

	def poll_once(self) -> None:
		with self._lock:
			for monitor in self.monitors:
				if not monitor.enabled:
					self.levels[monitor.entity_id]=AlarmLevel.DISABLED
					continue
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
				self._record_monitor_value(monitor,value,level)
			self._apply_global_level()
			self._publish_state()

	def set_test_value(self,value: Any) -> float:
		number=float(str(value).replace(",","."))
		if not math.isfinite(number) or number < -30 or number > 30:
			raise ValueError(f"Wartość testowa musi być liczbą od -30 do 30: {value}")
		with self._lock:
			level=self.test_monitor.evaluate(number)
			self._record_monitor_value(self.test_monitor,number,level)
			self._apply_global_level()
			self._publish_state()
		LOGGER.info("Ustawiono wartość testową alarmu: %s",number)
		return number

	def _record_monitor_value(
		self,
		monitor: MonitorDefinition,
		value: float | None,
		level: AlarmLevel,
	) -> None:
		previous=self.levels.get(monitor.entity_id,AlarmLevel.UNAVAILABLE)
		previous_acknowledgement=self.acknowledged_levels[monitor.entity_id]
		self.values[monitor.entity_id]=value
		self.levels[monitor.entity_id]=level
		rearmed=self._update_acknowledgement(monitor,level,value)
		current_acknowledgement=self.acknowledged_levels[monitor.entity_id]
		if level != previous:
			LOGGER.info("Zmiana %s: %s -> %s, wartość=%s",monitor.entity_id,previous.value,level.value,value)
		if rearmed:
			self._notify_transition(
				monitor,
				previous_acknowledgement or previous,
				level,
				value,
			)
		elif level != previous and current_acknowledgement is None:
			self._notify_transition(monitor,previous,level,value)

	def close(self) -> None:
		with self._lock:
			self._set_output(False)
			self.output.close()

	def _update_acknowledgement(
		self,
		monitor: MonitorDefinition,
		level: AlarmLevel,
		value: float | None,
	) -> bool:
		acknowledged=self.acknowledged_levels[monitor.entity_id]
		if acknowledged is None:
			return False
		opposite=(
			acknowledged == AlarmLevel.ALARM_HIGH and level == AlarmLevel.ALARM_LOW
		) or (
			acknowledged == AlarmLevel.ALARM_LOW and level == AlarmLevel.ALARM_HIGH
		)
		if opposite:
			self.acknowledged_levels[monitor.entity_id]=None
			LOGGER.warning(
				"Nowy alarm w przeciwnym kierunku dla %s: %s",
				monitor.entity_id,
				level.value,
			)
			return False
		if value is None or not monitor.should_rearm(acknowledged,value):
			return False
		self.acknowledged_levels[monitor.entity_id]=None
		LOGGER.info(
			"Ponownie uzbrojono %s po alarmie %s przy wartości %s",
			monitor.entity_id,
			acknowledged.value,
			value,
		)
		return True

	def _apply_global_level(self) -> None:
		active=any(
			self.levels[monitor.entity_id] in ACTIVE_LEVELS
			and self.acknowledged_levels[monitor.entity_id] != self.levels[monitor.entity_id]
			for monitor in self.all_monitors
		)
		self._set_output(active)
		if active:
			self.state="alarm"
			return
		if any(level is not None for level in self.acknowledged_levels.values()):
			self.state="acknowledged"
			return
		level=aggregate_level(list(self.levels.values()))
		self.state="ok" if level == AlarmLevel.DISABLED else level.state

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
		self.publisher.publish(f"{self.base_topic}/state/test_value",self.values[TEST_ENTITY_ID])
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
					"acknowledged":self.acknowledged_levels[monitor.entity_id] is not None,
					"armed":self.acknowledged_levels[monitor.entity_id] is None,
					"hysteresis":monitor.hysteresis,
					"rearm_threshold":monitor.rearm_threshold(self.acknowledged_levels[monitor.entity_id]) if self.acknowledged_levels[monitor.entity_id] is not None else None,
				}
				for monitor in self.all_monitors
			],
		})
		self.publisher.publish(str(self.options.get("alarm_coordination_topic","haos_alarm/active")),"ON" if self._output_active else "OFF")
