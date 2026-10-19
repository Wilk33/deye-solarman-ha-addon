from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"packages"))
sys.path.insert(0,str(ROOT/"apps/haos-alarm/src"))

from haos_alarm.gpio import GpioOutput
from haos_alarm.models import AlarmLevel
from haos_alarm.models import MonitorDefinition
from haos_alarm.models import aggregate_level
from haos_alarm.mqtt import discovery_messages


class AlarmModelTests(unittest.TestCase):
	def test_monitor_with_empty_thresholds_is_registered_but_disabled(self) -> None:
		monitor=MonitorDefinition.from_dict({
			"entity_id":"sensor.test",
			"name":"Test",
			"alarm_low":"",
			"warning_low":None,
			"warning_high":" ",
			"alarm_high":"",
		})

		self.assertFalse(monitor.enabled)
		self.assertEqual(monitor.evaluate(42),AlarmLevel.DISABLED)

	def test_monitor_evaluates_all_four_optional_thresholds(self) -> None:
		monitor=MonitorDefinition.from_dict({
			"entity_id":"sensor.temperature",
			"name":"Temperatura",
			"alarm_low":"5",
			"warning_low":"10",
			"warning_high":"70",
			"alarm_high":"85",
		})

		cases=(
			(4.9,AlarmLevel.ALARM_LOW),
			(5,AlarmLevel.ALARM_LOW),
			(9,AlarmLevel.WARNING_LOW),
			(10,AlarmLevel.WARNING_LOW),
			(11,AlarmLevel.OK),
			(69,AlarmLevel.OK),
			(70,AlarmLevel.WARNING_HIGH),
			(84,AlarmLevel.WARNING_HIGH),
			(85,AlarmLevel.ALARM_HIGH),
		)
		for value,expected in cases:
			with self.subTest(value=value):
				self.assertEqual(monitor.evaluate(value),expected)

	def test_alarm_has_priority_when_levels_are_aggregated(self) -> None:
		self.assertEqual(
			aggregate_level([AlarmLevel.OK,AlarmLevel.WARNING_HIGH,AlarmLevel.ALARM_LOW]),
			AlarmLevel.ALARM_LOW,
		)
		self.assertEqual(
			aggregate_level([AlarmLevel.DISABLED,AlarmLevel.WARNING_LOW]),
			AlarmLevel.WARNING_LOW,
		)
		self.assertEqual(
			aggregate_level([AlarmLevel.OK,AlarmLevel.UNAVAILABLE]),
			AlarmLevel.UNAVAILABLE,
		)

	def test_invalid_threshold_order_is_rejected(self) -> None:
		with self.assertRaisesRegex(ValueError,"alarm_low"):
			MonitorDefinition.from_dict({
				"entity_id":"sensor.temperature",
				"alarm_low":"15",
				"warning_low":"10",
				"warning_high":"70",
				"alarm_high":"85",
			})


	def test_acknowledged_high_alarm_rearms_below_warning_hysteresis(self) -> None:
		monitor=MonitorDefinition.from_dict({
			"entity_id":"sensor.temperature",
			"warning_high":"50",
			"alarm_high":"60",
			"hysteresis":"5",
		})

		self.assertEqual(monitor.rearm_threshold(AlarmLevel.ALARM_HIGH),45)
		self.assertFalse(monitor.should_rearm(AlarmLevel.ALARM_HIGH,46))
		self.assertTrue(monitor.should_rearm(AlarmLevel.ALARM_HIGH,45))

	def test_acknowledged_low_alarm_rearms_above_warning_hysteresis(self) -> None:
		monitor=MonitorDefinition.from_dict({
			"entity_id":"sensor.temperature",
			"alarm_low":"10",
			"warning_low":"20",
			"hysteresis":"3",
		})

		self.assertEqual(monitor.rearm_threshold(AlarmLevel.ALARM_LOW),23)
		self.assertFalse(monitor.should_rearm(AlarmLevel.ALARM_LOW,22))
		self.assertTrue(monitor.should_rearm(AlarmLevel.ALARM_LOW,23))

	def test_negative_hysteresis_is_rejected(self) -> None:
		with self.assertRaisesRegex(ValueError,"Histereza"):
			MonitorDefinition.from_dict({
				"entity_id":"sensor.temperature",
				"warning_high":"50",
				"alarm_high":"60",
				"hysteresis":"-1",
			})

class AlarmMqttTests(unittest.TestCase):
	def test_discovery_contains_only_acknowledge_button_and_state_sensor(self) -> None:
		messages=discovery_messages("homeassistant","haos_alarm","Alarm")

		self.assertEqual([message.component for message in messages],["button","sensor"])
		self.assertEqual([message.object_id for message in messages],["acknowledge","state"])
		self.assertEqual(messages[0].payload["default_entity_id"],"button.haos_alarm_acknowledge")
		self.assertEqual(messages[1].payload["default_entity_id"],"sensor.haos_alarm_state")
		encoded="\n".join(json.dumps(message.payload) for message in messages)
		self.assertNotIn("temperature",encoded)
		self.assertIn("command/acknowledge",encoded)
		self.assertNotIn("command/enabled",encoded)
		self.assertNotIn("state/enabled",encoded)
		self.assertIn("state/state",encoded)


class AlarmGpioTests(unittest.TestCase):
	def test_gpio_finds_raspberry_pi_5_rp1_chip_and_returns_to_safe_state(self) -> None:
		with tempfile.TemporaryDirectory() as directory:
			root=Path(directory)
			chip=root/"gpiochip571"
			chip.mkdir()
			(chip/"label").write_text("pinctrl-rp1\n",encoding="utf-8")
			(chip/"base").write_text("571\n",encoding="utf-8")
			(root/"export").write_text("",encoding="utf-8")
			(root/"unexport").write_text("",encoding="utf-8")

			output=GpioOutput(17,active_high=True,sysfs_root=root)
			self.assertEqual(output.global_number,588)

			line=root/"gpio588"
			line.mkdir()
			(line/"direction").write_text("in",encoding="utf-8")
			(line/"value").write_text("0",encoding="utf-8")
			output.initialize(export=False)
			output.set_active(True)
			self.assertEqual((line/"value").read_text(encoding="utf-8"),"1")
			output.close()
			self.assertEqual((line/"value").read_text(encoding="utf-8"),"0")

class FakeHomeAssistant:
	def __init__(self,states: dict[str,str]) -> None:
		self.states=states
		self.reads=[]
		self.persistent=[]
		self.notifications=[]

	def get_state(self,entity_id: str) -> dict:
		self.reads.append(entity_id)
		return {"state":self.states[entity_id],"attributes":{"unit_of_measurement":"°C"}}

	def persistent_notification(self,title: str,message: str,notification_id: str) -> None:
		self.persistent.append((title,message,notification_id))

	def dismiss_persistent_notification(self,notification_id: str) -> None:
		return None

	def send_notification(self,target: str,title: str,message: str) -> None:
		self.notifications.append((target,title,message))


class FakePublisher:
	def __init__(self) -> None:
		self.messages=[]

	def publish(self,topic: str,payload,retain: bool=True) -> None:
		self.messages.append((topic,payload,retain))


class FakeOutput:
	def __init__(self) -> None:
		self.active=[]

	def set_active(self,active: bool) -> None:
		self.active.append(active)

	def close(self) -> None:
		return None


class AlarmRuntimeTests(unittest.TestCase):
	def test_poll_skips_thresholdless_entry_and_notifies_only_on_transition(self) -> None:
		from haos_alarm.runtime import AlarmApp

		options={
			"monitored_entities":[
				{"entity_id":"sensor.hot","name":"Gorący","warning_high":"70","alarm_high":"85"},
				{"entity_id":"sensor.registered","name":"Tylko zapis"},
			],
			"notification_targets":["notify.mobile_app_phone"],
			"mqtt_base_topic":"haos_alarm",
		}
		ha=FakeHomeAssistant({"sensor.hot":"90"})
		mqtt=FakePublisher()
		output=FakeOutput()
		app=AlarmApp(options,ha,mqtt,output)

		app.poll_once()
		app.poll_once()

		self.assertEqual(ha.reads,["sensor.hot","sensor.hot"])
		self.assertEqual(len(ha.persistent),1)
		self.assertEqual(len(ha.notifications),1)
		self.assertEqual(output.active,[True])
		self.assertEqual(app.state,"alarm")

	def test_non_finite_sensor_value_is_unavailable(self) -> None:
		from haos_alarm.runtime import AlarmApp

		options={
			"monitored_entities":[{"entity_id":"sensor.hot","alarm_high":"85"}],
			"notification_targets":[],
			"mqtt_base_topic":"haos_alarm",
		}
		app=AlarmApp(options,FakeHomeAssistant({"sensor.hot":"nan"}),FakePublisher(),FakeOutput())

		app.poll_once()

		self.assertEqual(app.state,"unavailable")

	def test_acknowledged_sensor_stays_silent_until_rearm_threshold(self) -> None:
		from haos_alarm.runtime import AlarmApp

		options={
			"monitored_entities":[{
				"entity_id":"sensor.hot",
				"warning_high":"50",
				"alarm_high":"60",
				"hysteresis":"5",
			}],
			"notification_targets":[],
			"mqtt_base_topic":"haos_alarm",
		}
		ha=FakeHomeAssistant({"sensor.hot":"30"})
		output=FakeOutput()
		app=AlarmApp(options,ha,FakePublisher(),output)
		app.poll_once()

		ha.states["sensor.hot"]="63"
		app.poll_once()
		self.assertEqual(output.active,[True])
		self.assertEqual(app.state,"alarm")

		app.acknowledge_active_alarms()
		self.assertEqual(output.active,[True,False])
		self.assertEqual(app.state,"acknowledged")

		app.poll_once()
		self.assertEqual(output.active,[True,False])
		self.assertEqual(app.state,"acknowledged")

		ha.states["sensor.hot"]="46"
		app.poll_once()
		self.assertEqual(output.active,[True,False])
		self.assertEqual(app.state,"acknowledged")

		ha.states["sensor.hot"]="45"
		app.poll_once()
		self.assertEqual(app.state,"ok")

		ha.states["sensor.hot"]="63"
		app.poll_once()
		self.assertEqual(output.active,[True,False,True])
		self.assertEqual(app.state,"alarm")

	def test_other_sensor_can_activate_alarm_while_first_is_acknowledged(self) -> None:
		from haos_alarm.runtime import AlarmApp

		options={
			"monitored_entities":[
				{
					"entity_id":"sensor.first",
					"warning_high":"50",
					"alarm_high":"60",
					"hysteresis":"5",
				},
				{
					"entity_id":"sensor.second",
					"warning_high":"50",
					"alarm_high":"60",
					"hysteresis":"5",
				},
			],
			"notification_targets":[],
			"mqtt_base_topic":"haos_alarm",
		}
		ha=FakeHomeAssistant({"sensor.first":"63","sensor.second":"30"})
		output=FakeOutput()
		app=AlarmApp(options,ha,FakePublisher(),output)
		app.poll_once()
		app.acknowledge_active_alarms()

		ha.states["sensor.second"]="63"
		app.poll_once()

		self.assertEqual(output.active,[True,False,True])
		self.assertEqual(app.state,"alarm")
		self.assertEqual(app.acknowledged_levels["sensor.first"],AlarmLevel.ALARM_HIGH)
		self.assertIsNone(app.acknowledged_levels["sensor.second"])

	def test_one_acknowledgement_silences_all_current_alarm_sensors(self) -> None:
		from haos_alarm.runtime import AlarmApp

		options={
			"monitored_entities":[
				{"entity_id":"sensor.first","warning_high":"50","alarm_high":"60","hysteresis":"5"},
				{"entity_id":"sensor.second","warning_high":"50","alarm_high":"60","hysteresis":"5"},
			],
			"notification_targets":[],
			"mqtt_base_topic":"haos_alarm",
		}
		output=FakeOutput()
		app=AlarmApp(
			options,
			FakeHomeAssistant({"sensor.first":"63","sensor.second":"70"}),
			FakePublisher(),
			output,
		)
		app.poll_once()

		acknowledged=app.acknowledge_active_alarms()

		self.assertEqual(acknowledged,2)
		self.assertEqual(output.active,[True,False])
		self.assertEqual(app.state,"acknowledged")

if __name__ == "__main__":
	unittest.main()
