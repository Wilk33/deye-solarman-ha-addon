from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

import yaml


ROOT=Path(__file__).resolve().parents[1]


class AudioAddonPackagingTests(unittest.TestCase):
	def test_repository_exposes_three_installable_addons(self) -> None:
		self.assertEqual(
			sorted(path.parent.name for path in ROOT.glob("*/config.yaml")),
			["continuous-noise","deye-solarman-diagnostics","haos-alarm"],
		)

	def test_alarm_manifest_has_exclusive_mode_and_dynamic_monitor_list(self) -> None:
		config=yaml.safe_load((ROOT/"haos-alarm/config.yaml").read_text(encoding="utf-8"))

		self.assertTrue(config["audio"])
		self.assertTrue(config["gpio"])
		self.assertTrue(config["homeassistant_api"])
		self.assertTrue(config["tmpfs"])
		self.assertNotIn("hassio_api",config)
		self.assertEqual(config["services"],["mqtt:need"])
		self.assertEqual(config["schema"]["output_mode"],"list(audio|gpio)")
		monitor_schema=config["schema"]["monitored_entities"][0]
		self.assertEqual(set(monitor_schema),{
			"entity_id","name","alarm_low","warning_low","warning_high","alarm_high",
		})
		self.assertEqual(config["schema"]["notification_targets"],["str"])
		self.assertFalse((ROOT/"haos-alarm/build.yaml").exists())
		self.assertIn(
			"ARG BUILD_FROM=ghcr.io/home-assistant/base:3.23",
			(ROOT/"haos-alarm/Dockerfile").read_text(encoding="utf-8"),
		)

	def test_noise_manifest_uses_audio_and_configurable_noise_list(self) -> None:
		config=yaml.safe_load((ROOT/"continuous-noise/config.yaml").read_text(encoding="utf-8"))

		self.assertTrue(config["audio"])
		self.assertTrue(config["tmpfs"])
		self.assertNotIn("hassio_api",config)
		self.assertEqual(config["services"],["mqtt:need"])
		self.assertEqual(set(config["schema"]["noises"][0]),{"key","name","type"})
		self.assertFalse((ROOT/"continuous-noise/build.yaml").exists())
		self.assertIn(
			"ARG BUILD_FROM=ghcr.io/home-assistant/base:3.23",
			(ROOT/"continuous-noise/Dockerfile").read_text(encoding="utf-8"),
		)

	def test_generated_audio_addon_runtime_matches_sources(self) -> None:
		result=subprocess.run(
			[sys.executable,str(ROOT/"tools/package_audio_addons.py"),"--check"],
			capture_output=True,
			text=True,
		)

		self.assertEqual(result.returncode,0,result.stdout+result.stderr)


if __name__ == "__main__":
	unittest.main()
