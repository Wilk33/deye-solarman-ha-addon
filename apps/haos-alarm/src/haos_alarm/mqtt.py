from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DiscoveryMessage:
	component: str
	object_id: str
	topic: str
	payload: dict[str,Any]


def discovery_messages(discovery_prefix: str,base_topic: str,device_name: str) -> list[DiscoveryMessage]:
	availability=f"{base_topic}/availability"
	device={
		"identifiers":["haos_alarm"],
		"name":device_name,
		"manufacturer":"Wilk33",
		"model":"HAOS Alarm",
		"sw_version":"1.0.1",
	}
	button=DiscoveryMessage(
		"button",
		"acknowledge",
		f"{discovery_prefix}/button/haos_alarm/acknowledge/config",
		{
			"name":"Potwierdź alarm",
			"unique_id":"haos_alarm_acknowledge",
			"object_id":"haos_alarm_acknowledge",
			"default_entity_id":"button.haos_alarm_acknowledge",
			"command_topic":f"{base_topic}/command/acknowledge",
			"payload_press":"PRESS",
			"availability_topic":availability,
			"icon":"mdi:alarm-light-off",
			"device":device,
		},
	)
	sensor=DiscoveryMessage(
		"sensor",
		"state",
		f"{discovery_prefix}/sensor/haos_alarm/state/config",
		{
			"name":"Stan alarmu",
			"unique_id":"haos_alarm_state",
			"object_id":"haos_alarm_state",
			"default_entity_id":"sensor.haos_alarm_state",
			"state_topic":f"{base_topic}/state/state",
			"json_attributes_topic":f"{base_topic}/state/attributes",
			"availability_topic":availability,
			"icon":"mdi:alarm-light-outline",
			"device":device,
		},
	)
	return [button,sensor]
