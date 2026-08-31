from __future__ import annotations

from .models import PollingConfig
from .models import SensorDefinition


def group_sensors_for_read(sensors: list[SensorDefinition], config: PollingConfig) -> list[list[SensorDefinition]]:
	enabled=[sensor for sensor in sensors if sensor.enabled]
	sorted_sensors=sorted(enabled, key=lambda item: item.registers[0])
	groups: list[list[SensorDefinition]]=[]

	for sensor in sorted_sensors:
		if not groups:
			groups.append([sensor])
			continue
		group=groups[-1]
		current_end=max(member.registers[-1] for member in group)
		next_start=sensor.registers[0]
		new_count=sensor.registers[-1]-group[0].registers[0]+1
		if next_start-current_end <= config.batch_gap and new_count <= config.max_registers_per_request:
			group.append(sensor)
		else:
			groups.append([sensor])

	return groups
