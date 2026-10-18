from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import NoiseDefinition


@dataclass(frozen=True)
class DiscoveryMessage:
	component: str
	object_id: str
	topic: str
	payload: dict[str,Any]


def discovery_messages(
	discovery_prefix: str,
	base_topic: str,
	device_name: str,
	definitions: list[NoiseDefinition],
) -> list[DiscoveryMessage]:
	availability=f"{base_topic}/availability"
	device={
		"identifiers":["continuous_noise"],
		"name":device_name,
		"manufacturer":"Wilk33",
		"model":"Continuous Noise",
		"sw_version":"1.0.0",
	}
	messages=[]
	for definition in definitions:
		messages.append(DiscoveryMessage(
			"switch",
			definition.key,
			f"{discovery_prefix}/switch/continuous_noise/{definition.key}/config",
			{
				"name":definition.name,
				"unique_id":f"continuous_noise_{definition.key}",
				"object_id":f"continuous_noise_{definition.key}",
				"state_topic":f"{base_topic}/state/{definition.key}",
				"command_topic":f"{base_topic}/command/{definition.key}",
				"availability_topic":availability,
				"payload_on":"ON",
				"payload_off":"OFF",
				"icon":"mdi:waveform",
				"device":device,
			},
		))
	return messages
