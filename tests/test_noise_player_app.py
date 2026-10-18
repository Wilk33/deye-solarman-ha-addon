from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"packages"))
sys.path.insert(0,str(ROOT/"apps/continuous-noise/src"))

from continuous_noise.models import NoiseDefinition
from continuous_noise.models import NoiseSelection
from continuous_noise.mqtt import discovery_messages


class NoiseSelectionTests(unittest.TestCase):
	def setUp(self) -> None:
		self.selection=NoiseSelection([
			NoiseDefinition("pink","Szum różowy","pink"),
			NoiseDefinition("violet","Szum fioletowy","violet"),
		])

	def test_enabling_noise_turns_every_other_noise_off(self) -> None:
		self.selection.command("pink","ON")
		self.selection.command("violet","ON")

		self.assertEqual(self.selection.requested,"violet")
		self.assertEqual(self.selection.playing,"violet")
		self.assertEqual(self.selection.states(),{"pink":"OFF","violet":"ON"})

	def test_disabling_inactive_noise_does_not_stop_active_noise(self) -> None:
		self.selection.command("pink","ON")
		self.selection.command("violet","OFF")

		self.assertEqual(self.selection.playing,"pink")

	def test_alarm_pauses_and_then_resumes_requested_noise(self) -> None:
		self.selection.command("pink","ON")
		self.selection.set_alarm_active(True)
		self.assertIsNone(self.selection.playing)
		self.assertEqual(self.selection.states(),{"pink":"ON","violet":"OFF"})

		self.selection.set_alarm_active(False)
		self.assertEqual(self.selection.playing,"pink")

	def test_unknown_noise_command_is_rejected(self) -> None:
		with self.assertRaisesRegex(ValueError,"Nieznany szum"):
			self.selection.command("blue","ON")


class NoiseMqttTests(unittest.TestCase):
	def test_discovery_exposes_one_switch_per_configured_noise(self) -> None:
		definitions=[
			NoiseDefinition("pink","Szum różowy","pink"),
			NoiseDefinition("violet","Szum fioletowy","violet"),
		]

		messages=discovery_messages("homeassistant","continuous_noise","Szum ciągły",definitions)

		self.assertEqual([message.component for message in messages],["switch","switch"])
		self.assertEqual([message.object_id for message in messages],["pink","violet"])
		self.assertTrue(all("command_topic" in message.payload for message in messages))

class FakePublisher:
	def __init__(self) -> None:
		self.messages=[]

	def publish(self,topic: str,payload,retain: bool=True) -> None:
		self.messages.append((topic,payload,retain))


class FakePlayer:
	def __init__(self) -> None:
		self.starts=[]
		self.stops=0

	def start(self,path,volume_percent: int) -> None:
		self.starts.append((str(path),volume_percent))

	def stop(self) -> None:
		self.stops+=1


class NoiseRuntimeTests(unittest.TestCase):
	def test_alarm_preempts_and_clearing_alarm_resumes_selected_noise(self) -> None:
		from continuous_noise.runtime import NoiseApp

		publisher=FakePublisher()
		player=FakePlayer()
		app=NoiseApp(
			{
				"noises":[{"key":"pink","name":"Szum różowy","type":"pink"}],
				"volume_percent":50,
				"mqtt_base_topic":"continuous_noise",
			},
			publisher,
			player,
			{"pink":"C:/tmp/pink.wav"},
		)

		app.command("pink","ON")
		app.set_alarm_active(True)
		app.set_alarm_active(False)

		expected=str(Path("C:/tmp/pink.wav"))
		self.assertEqual(player.starts,[(expected,50),(expected,50)])
		self.assertEqual(player.stops,1)
		self.assertEqual(app.selection.requested,"pink")

if __name__ == "__main__":
	unittest.main()
