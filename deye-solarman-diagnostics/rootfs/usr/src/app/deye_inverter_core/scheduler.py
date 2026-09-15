from __future__ import annotations

from .models import PollingConfig
from .models import SensorDefinition


def group_sensors_for_read(sensors: list[SensorDefinition], config: PollingConfig) -> list[list[SensorDefinition]]:
	enabled=[sensor for sensor in sensors if sensor.enabled]
	sorted_sensors=sorted(enabled, key=lambda item: min(item.registers))
	groups: list[list[SensorDefinition]]=[]

	for sensor in sorted_sensors:
		if not groups:
			groups.append([sensor])
			continue
		group=groups[-1]
		group_start=min(register for member in group for register in member.registers)
		current_end=max(register for member in group for register in member.registers)
		next_start=min(sensor.registers)
		next_end=max(sensor.registers)
		new_count=max(current_end, next_end)-group_start+1
		if next_start-current_end <= config.batch_gap and new_count <= config.max_registers_per_request:
			group.append(sensor)
		else:
			groups.append([sensor])

	return groups
