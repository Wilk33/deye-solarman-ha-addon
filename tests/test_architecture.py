import ast
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"packages"))
sys.path.insert(0,str(ROOT/"apps/deye-solarman/src"))

from deye_inverter_core.catalog_bundle import load_map
from deye_solarman_diagnostics.solarman import SolarmanClient
from deye_inverter_core.models import LoggerConfig
from tools.package_addon import normalized_text_bytes


class ArchitectureTests(unittest.TestCase):
	def test_release_metadata_and_bundle_match_version_2_contract(self):
		config=yaml.safe_load((ROOT/"deye-solarman-diagnostics/config.yaml").read_text(encoding="utf-8"))
		repository=yaml.safe_load((ROOT/"repository.yaml").read_text(encoding="utf-8"))
		index=json.loads((ROOT/"catalogs/models/deye_sg04_sg05_3ph_lv/catalog-index.yaml").read_text(encoding="utf-8"))
		requirements=(ROOT/"deye-solarman-diagnostics/rootfs/requirements.txt").read_text(encoding="utf-8").splitlines()

		self.assertEqual(config["name"],"SolarMan Diagnostics")
		self.assertEqual(config["version"],"2.0.5")
		self.assertTrue(config["uart"])
		self.assertIn("solarman",config["options"])
		self.assertIn("rs485",config["options"])
		self.assertIn("solarman",config["schema"])
		self.assertIn("rs485",config["schema"])
		self.assertEqual(repository["name"],"SolarMan Diagnostics")
		self.assertEqual(index["revision"],"2.0.5")
		self.assertIn("pymodbus==3.14.0",requirements)
		self.assertEqual([path.parent.name for path in ROOT.glob("*/config.yaml")],["deye-solarman-diagnostics"])
		for relative in (
			"deye-solarman-diagnostics/rootfs/usr/src/app/deye_solarman_diagnostics/solarman.py",
			"deye-solarman-diagnostics/rootfs/usr/src/app/deye_solarman_diagnostics/rs485.py",
			"deye-solarman-diagnostics/rootfs/usr/src/app/deye_inverter_core/transport_manager.py",
			"deye-solarman-diagnostics/rootfs/usr/src/app/deye_inverter_core/i18n/pl.json",
			"deye-solarman-diagnostics/rootfs/usr/src/app/deye_inverter_core/i18n/en.json",
			"deye-solarman-diagnostics/rootfs/usr/src/app/deye_inverter_core/data/catalog-index.yaml",
		):
			self.assertTrue((ROOT/relative).is_file(),relative)

	def test_current_documentation_describes_the_dual_transport_release(self):
		documents=(
			"README.md",
			"deye-solarman-diagnostics/README.md",
			"deye-solarman-diagnostics/DOCS.md",
			"deye-solarman-diagnostics/CONTROL_ENTITIES.md",
			"docs/architecture/MULTI_ADDON_AND_CATALOGS.md",
		)
		contents={relative:(ROOT/relative).read_text(encoding="utf-8") for relative in documents}
		all_current="\n".join(contents.values())
		all_lower=all_current.lower()

		for relative,content in contents.items():
			self.assertIn("2.0.5",content,relative)
			self.assertIn("SolarMan Diagnostics",content,relative)
		for forbidden in ("entityownership","entity_owners.json","/source/solarman","/source/modbus"):
			self.assertNotIn(forbidden,all_lower)
		self.assertFalse((ROOT/"docs/architecture/ENTITY_OWNERSHIP.md").exists())
		for required in (
			"solarman-only",
			"rs485-only",
			"dual",
			"read-before-write",
			"read-back",
			"fc16",
			"/dev/ttyusb0",
			"9600 8n1",
			"client_id: solarman",
			"base_topic: solarman_diagnostics",
			"sensory",
			"sterowanie",
			"własne sensory",
		):
			self.assertIn(required,all_lower,required)

	def test_supporting_architecture_readmes_describe_current_runtime(self):
		documents=(
			"apps/README.md",
			"catalogs/README.md",
			"catalogs/schemas/README.md",
			"catalogs/models/README.md",
			"catalogs/models/deye_sg04_sg05_3ph_lv/README.md",
		)
		for relative in documents:
			content=(ROOT/relative).read_text(encoding="utf-8").lower()
			self.assertIn("2.0.5",content,relative)
			self.assertNotIn("future",content,relative)
			self.assertNotIn("planned",content,relative)
			self.assertNotIn("reserved",content,relative)
		self.assertFalse((ROOT/"apps/deye-rs485/README.md").exists())

	def test_user_documentation_covers_migration_safety_and_validation_limits(self):
		docs=(ROOT/"deye-solarman-diagnostics/DOCS.md").read_text(encoding="utf-8").lower()
		controls=(ROOT/"deye-solarman-diagnostics/CONTROL_ENTITIES.md").read_text(encoding="utf-8").lower()

		for required in (
			"logger",
			"polling",
			"solarman",
			"rs485",
			"detailed_logs",
			"catalog.url",
			"catalog.control_url",
			"testy automatyczne",
			"fizycznego portu usb",
			"timingu rs485",
			"konkretnego firmware",
			"rzeczywistego fc16",
		):
			self.assertIn(required,docs,required)
		for required in (
			"bez fallbacku",
			"brak ponowienia",
			"global",
			"niepewn",
			"tylko do odczytu",
		):
			self.assertIn(required,controls,required)

	def test_ownership_modules_are_removed_from_sources_and_generated_bundle(self):
		for relative in (
			"packages/deye_inverter_core/ownership.py",
			"packages/deye_inverter_core/ownership_config.py",
			"packages/deye_inverter_core/ownership_panel.js",
			"deye-solarman-diagnostics/rootfs/usr/src/app/deye_inverter_core/ownership.py",
			"deye-solarman-diagnostics/rootfs/usr/src/app/deye_inverter_core/ownership_config.py",
			"deye-solarman-diagnostics/rootfs/usr/src/app/deye_inverter_core/ownership_panel.js",
		):
			self.assertFalse((ROOT/relative).exists(),relative)

	def test_validation_workflow_checks_only_existing_javascript_files(self):
		workflow=(ROOT/".github/workflows/validate.yml").read_text(encoding="utf-8")
		self.assertNotIn("ownership_panel.js",workflow)
		for line in workflow.splitlines():
			marker="node --check "
			if marker not in line:
				continue
			relative=line.split(marker,1)[1].strip()
			self.assertTrue((ROOT/relative).is_file(),relative)

	def test_configuration_defaults_are_minimal_and_name_catalog_sources(self):
		config=yaml.safe_load((ROOT/"deye-solarman-diagnostics/config.yaml").read_text(encoding="utf-8"))

		self.assertEqual(config["name"],"SolarMan Diagnostics")
		self.assertEqual(config["options"]["mqtt"]["client_id"],"solarman")
		self.assertEqual(config["options"]["mqtt"]["base_topic"],"solarman_diagnostics")
		self.assertEqual(config["options"]["inverter_name"],"SolarMan Diagnostics")
		self.assertNotIn("default_profile",config["options"])
		self.assertNotIn("default_profile",config["schema"])
		self.assertIn("control_url",config["options"]["catalog"])
		self.assertEqual(config["schema"]["detailed_logs"],"bool")
		for section in ("inverter","profiles","advanced","scan"):
			self.assertNotIn(section,config["schema"])
		for field in (
			"inverter_serial_number","inverter_name","inverter_manufacturer","inverter_model",
			"overrides_file","custom_sensors_file","state_file","scan_report_file",
			"emit_raw_topics","emit_scan_report","detailed_logs",
			"scan_mode","scan_candidate_report_file","detected_sensors_file","bms_pack_count",
		):
			self.assertIn(field,config["schema"])

	def test_builtin_battery_profile_is_not_exposed_as_a_configuration_choice(self):
		config=yaml.safe_load((ROOT/"deye-solarman-diagnostics/config.yaml").read_text(encoding="utf-8"))

		self.assertNotIn("default_profile",config["options"])
		self.assertNotIn("default_profile",config["schema"])

	def test_sensor_list_uses_a_theme_backed_surface(self):
		web_source=(ROOT/"packages/deye_inverter_core/web.py").read_text(encoding="utf-8")

		self.assertIn(".sensor-list-surface",web_source)
		self.assertIn('id="sensor-groups" class="sensor-list-surface"',web_source)
		self.assertIn("const transportChanged=renderTransportRuntime",web_source)
		self.assertIn("if (!transportChanged) return;",web_source)

	def test_core_does_not_import_concrete_transports(self):
		for source in (ROOT/"packages/deye_inverter_core").glob("*.py"):
			for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
				if isinstance(node,ast.Import):
					names=[item.name for item in node.names]
				elif isinstance(node,ast.ImportFrom):
					names=[node.module or ""]
				else:
					continue
				for name in names:
					self.assertFalse(any(part in name for part in ("pysolarman","pymodbus","solarman","serial")),(source,name))

	def test_generated_package_matches_sources(self):
		result=subprocess.run([sys.executable,str(ROOT/"tools/package_addon.py"),"--check"],capture_output=True,text=True)
		self.assertEqual(result.returncode,0,result.stdout+result.stderr)

	def test_packaged_catalog_checksum_is_independent_of_checkout_line_endings(self):
		with tempfile.TemporaryDirectory() as directory:
			path=Path(directory)/"catalog.yaml"
			path.write_bytes(b"format: 1\r\nmap_id: telemetry\r\n")

			self.assertEqual(normalized_text_bytes(path),b"format: 1\nmap_id: telemetry\n")

	def test_bundle_checks_transport_and_checksum(self):
		controls=load_map("control","solarman_tcp")["commands"]
		self.assertEqual(len(controls),115)
		self.assertFalse(
			{"control_us_version_grounding_fault","control_grid_standard","control_configured_grid_phases","control_allow_remote"}
			& {entry["key"] for entry in controls}
		)
		for map_id in ("telemetry","control"):
			for transport_id in ("solarman_tcp","modbus_rtu"):
				self.assertEqual(load_map(map_id,transport_id)["map_id"],map_id)
		self.assertIn("bms_pack",load_map("telemetry","solarman_tcp"))
		with tempfile.TemporaryDirectory() as directory:
			path=Path(directory)
			index={"format":1,"catalog_set":"deye_sg04_sg05_3ph_lv","maps":{"control":{"file":"control.yaml","sha256":"wrong","transports":["solarman_tcp"]}}}
			(path/"catalog-index.yaml").write_text(json.dumps(index))
			(path/"control.yaml").write_text("{}")
			with self.assertRaisesRegex(ValueError,"checksum"):
				load_map("control","solarman_tcp",path)

	def test_catalog_configuration_uses_independent_canonical_sources_without_cache_fields(self):
		config=yaml.safe_load((ROOT/"deye-solarman-diagnostics/config.yaml").read_text(encoding="utf-8"))
		catalog=config["options"]["catalog"]
		schema=config["schema"]["catalog"]

		self.assertEqual(catalog["url"],"https://raw.githubusercontent.com/Wilk33/deye-solarman-ha-addon/main/catalogs/models/deye_sg04_sg05_3ph_lv/telemetry.yaml")
		self.assertEqual(catalog["control_url"],"https://raw.githubusercontent.com/Wilk33/deye-solarman-ha-addon/main/catalogs/models/deye_sg04_sg05_3ph_lv/control.yaml")
		self.assertNotIn("cache_file",catalog)
		self.assertNotIn("control_cache_file",catalog)
		self.assertNotIn("cache_file",schema)
		self.assertNotIn("control_cache_file",schema)
		self.assertEqual(schema["url"],"str?")
		self.assertEqual(schema["control_url"],"str?")

	def test_legacy_telemetry_url_is_an_exact_copy_of_the_canonical_map(self):
		canonical=ROOT/"catalogs/models/deye_sg04_sg05_3ph_lv/telemetry.yaml"
		legacy=ROOT/"deye-solarman-diagnostics/deye_sg04_sg05_3ph_lv_catalog.yaml"

		self.assertEqual(legacy.read_bytes(),canonical.read_bytes())

	def test_obsolete_catalog_files_are_removed(self):
		self.assertFalse((ROOT/"catalogs/models/deye_sg04_sg05_3ph_lv/telemetry-plus.yaml").exists())
		self.assertFalse((ROOT/"deye-solarman-diagnostics/catalog-overrides.yaml").exists())
		self.assertFalse((ROOT/"docs/superpowers/plans/2026-09-17-entity-ownership.md").exists())

	def test_packaged_runtime_imports_without_repository_sources(self):
		app=str(ROOT/"deye-solarman-diagnostics/rootfs/usr/src/app")
		code="import sys; sys.path.insert(0,sys.argv[1]); import deye_solarman_diagnostics.__main__; from deye_solarman_diagnostics.solarman import SolarmanClient; from deye_solarman_diagnostics.rs485 import ModbusRtuTransport; from deye_inverter_core.main import main; from deye_inverter_core.controls import CONTROLS; from deye_inverter_core.catalog import build_live_telemetry; assert len(CONTROLS)==115; assert len(build_live_telemetry())==94"
		with tempfile.TemporaryDirectory() as directory:
			result=subprocess.run([sys.executable,"-I","-c",code,app],cwd=directory,capture_output=True,text=True)
		self.assertEqual(result.returncode,0,result.stdout+result.stderr)

	def test_solarman_adapter_implements_shared_write_contract(self):
		client=SolarmanClient(LoggerConfig("localhost",8899,1,1,3,10))
		with patch("deye_solarman_diagnostics.solarman.PySolarmanV5") as library:
			client.connect()
			client.write_holding_registers(128,[25])
			library.return_value.write_multiple_holding_registers.assert_called_once_with(128,[25])
			self.assertFalse(library.call_args.kwargs["auto_reconnect"])
			self.assertEqual(client.transport_id,"solarman_tcp")
			client.close()
