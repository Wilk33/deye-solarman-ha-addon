import tempfile
import unittest
from pathlib import Path

import yaml

from tools.catalog_integrity import (
	CatalogValidationError,
	discover_catalog_models,
	load_catalog_model,
	normalized_sha256,
)


class CatalogIntegrityTests(unittest.TestCase):
	def setUp(self):
		self.temporary=tempfile.TemporaryDirectory()
		self.addCleanup(self.temporary.cleanup)
		self.models_root=Path(self.temporary.name)/"models"
		self.models_root.mkdir()

	def write_model(self,name: str,map_ids: tuple[str,...],definitions: dict[str,list[dict]] | None=None) -> Path:
		model_dir=self.models_root/name
		model_dir.mkdir()
		maps={}
		for map_id in map_ids:
			definition_key="sensors" if map_id == "telemetry" else "commands"
			items=(definitions or {}).get(map_id,[{"key":f"{map_id}_entry","registers":[100]}])
			payload={
				"format":1,
				"map_id":map_id,
				"catalog_set":name,
				"purpose":map_id,
				"writable":map_id == "control",
				"transports":["solarman_tcp","modbus_rtu"],
				definition_key:items,
			}
			map_path=model_dir/f"{map_id}.yaml"
			map_path.write_text(yaml.safe_dump(payload,sort_keys=False),encoding="utf-8")
			maps[map_id]={
				"file":map_path.name,
				"sha256":normalized_sha256(map_path),
				"transports":payload["transports"],
				"writable":payload["writable"],
			}
		index={"format":1,"catalog_set":name,"revision":"test","maps":maps}
		(model_dir/"catalog-index.yaml").write_text(yaml.safe_dump(index,sort_keys=False),encoding="utf-8")
		return model_dir

	def test_normalized_sha256_is_identical_for_lf_and_crlf(self):
		root=Path(self.temporary.name)
		lf=root/"lf.yaml"
		crlf=root/"crlf.yaml"
		lf.write_bytes(b"format: 1\nmap_id: telemetry\n")
		crlf.write_bytes(b"format: 1\r\nmap_id: telemetry\r\n")

		self.assertEqual(normalized_sha256(lf),normalized_sha256(crlf))

	def test_discovers_models_with_independent_maps(self):
		self.write_model("telemetry_only",("telemetry",))
		self.write_model("control_only",("control",))
		self.write_model("full",("telemetry","control"))

		models=discover_catalog_models(self.models_root)

		self.assertEqual([model.catalog_set for model in models],["control_only","full","telemetry_only"])
		self.assertEqual(set(models[0].maps),{"control"})
		self.assertEqual(set(models[1].maps),{"telemetry","control"})
		self.assertEqual(set(models[2].maps),{"telemetry"})

	def test_rejects_map_path_outside_model_directory(self):
		outside=self.models_root/"outside.yaml"
		outside.write_text("map_id: telemetry\n",encoding="utf-8")
		model_dir=self.models_root/"unsafe"
		model_dir.mkdir()
		index={
			"format":1,
			"catalog_set":"unsafe",
			"revision":"test",
			"maps":{
				"telemetry":{
					"file":"../outside.yaml",
					"sha256":normalized_sha256(outside),
					"transports":["solarman_tcp"],
					"writable":False,
				},
			},
		}
		(model_dir/"catalog-index.yaml").write_text(yaml.safe_dump(index,sort_keys=False),encoding="utf-8")

		with self.assertRaisesRegex(CatalogValidationError,"outside model directory"):
			load_catalog_model(model_dir)

	def test_rejects_duplicate_definition_keys(self):
		model_dir=self.write_model(
			"duplicate",
			("telemetry",),
			{"telemetry":[{"key":"same","registers":[100]},{"key":"same","registers":[101]}]},
		)

		with self.assertRaisesRegex(CatalogValidationError,"duplicate key"):
			load_catalog_model(model_dir)

	def test_rejects_checksum_mismatch_with_model_and_map_context(self):
		model_dir=self.write_model("broken",("control",))
		index=yaml.safe_load((model_dir/"catalog-index.yaml").read_text(encoding="utf-8"))
		index["maps"]["control"]["sha256"]="0"*64
		(model_dir/"catalog-index.yaml").write_text(yaml.safe_dump(index,sort_keys=False),encoding="utf-8")

		with self.assertRaisesRegex(CatalogValidationError,"broken.*control.*checksum"):
			load_catalog_model(model_dir)


if __name__ == "__main__":
	unittest.main()
