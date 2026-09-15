import ast
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"packages"))
sys.path.insert(0,str(ROOT/"apps/deye-solarman/src"))

from deye_inverter_core.catalog_bundle import load_map
from deye_solarman_diagnostics.solarman import SolarmanClient
from deye_inverter_core.models import LoggerConfig


class ArchitectureTests(unittest.TestCase):
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

	def test_bundle_checks_transport_and_checksum(self):
		self.assertEqual(len(load_map("control","solarman_tcp")["commands"]),119)
		with self.assertRaises(ValueError):
			load_map("telemetry_plus","modbus_rtu")
		with tempfile.TemporaryDirectory() as directory:
			path=Path(directory)
			index={"format":1,"catalog_set":"deye_sg04_sg05_3ph_lv","maps":{"control":{"file":"control.yaml","sha256":"wrong","transports":["solarman_tcp"]}}}
			(path/"catalog-index.yaml").write_text(json.dumps(index))
			(path/"control.yaml").write_text("{}")
			with self.assertRaisesRegex(ValueError,"checksum"):
				load_map("control","solarman_tcp",path)

	def test_packaged_runtime_imports_without_repository_sources(self):
		app=str(ROOT/"deye-solarman-diagnostics/rootfs/usr/src/app")
		code="import sys; sys.path.insert(0,sys.argv[1]); from deye_solarman_diagnostics.solarman import SolarmanClient; from deye_inverter_core.main import main; from deye_inverter_core.controls import CONTROLS; from deye_inverter_core.catalog import build_live_telemetry; assert len(CONTROLS)==119; assert len(build_live_telemetry())==94"
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
