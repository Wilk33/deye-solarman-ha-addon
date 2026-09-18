"""Build/check the self-contained HAOS compatibility add-on from canonical sources."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import yaml

ROOT=Path(__file__).resolve().parents[1]
MODEL=ROOT/"catalogs/models/deye_sg04_sg05_3ph_lv"
APP=ROOT/"deye-solarman-diagnostics/rootfs/usr/src/app"


def main() -> None:
	parser=argparse.ArgumentParser()
	parser.add_argument("--check",action="store_true")
	args=parser.parse_args()
	expected={}
	index={"format":1,"catalog_set":"deye_sg04_sg05_3ph_lv","revision":"2.0.3","maps":{}}
	for map_id in ("telemetry","control"):
		name=map_id.replace("_","-")+".yaml"
		content=(MODEL/name).read_bytes()
		data=yaml.safe_load(content)
		index["maps"][map_id]={"file":name,"sha256":hashlib.sha256(content).hexdigest(),"transports":data["transports"],"writable":data["writable"]}
		expected[APP/"deye_inverter_core/data"/name]=content
	index_bytes=(json.dumps(index,indent=2)+"\n").encode()
	expected[MODEL/"catalog-index.yaml"]=index_bytes
	expected[APP/"deye_inverter_core/data/catalog-index.yaml"]=index_bytes
	for source in MODEL.glob("SUNSYNK_*"):
		expected[APP/"deye_inverter_core/data"/source.name]=source.read_bytes()
	for source_root,target_root in [(ROOT/"packages/deye_inverter_core",APP/"deye_inverter_core"),(ROOT/"apps/deye-solarman/src/deye_solarman_diagnostics",APP/"deye_solarman_diagnostics")]:
		for source in source_root.rglob("*"):
			if source.is_file() and "__pycache__" not in source.parts and source.suffix in {".py",".js",".json"}:
				expected[target_root/source.relative_to(source_root)]=source.read_bytes()
	# The old URL remains an exact mirror for installed clients.
	telemetry=(MODEL/"telemetry.yaml").read_bytes()
	expected[ROOT/"deye-solarman-diagnostics/deye_sg04_sg05_3ph_lv_catalog.yaml"]=telemetry
	drift=[]
	for target,content in expected.items():
		if target.exists() and target.read_bytes() == content:
			continue
		drift.append(str(target.relative_to(ROOT)))
		if not args.check:
			target.parent.mkdir(parents=True,exist_ok=True)
			target.write_bytes(content)
	for directory in (APP/"deye_inverter_core",APP/"deye_solarman_diagnostics"):
		if not directory.exists():
			continue
		for target in directory.rglob("*"):
			if target.is_file() and "__pycache__" not in target.parts and target not in expected:
				drift.append(str(target.relative_to(ROOT)))
				if not args.check:
					if not target.resolve().is_relative_to(APP.resolve()):
						raise ValueError("Generated file escaped build context")
					target.unlink()
	if args.check and drift:
		raise SystemExit("Generated add-on differs from sources:\n"+"\n".join(drift))
	print(f"{'Verified' if args.check else 'Packaged'} {len(expected)} files")


if __name__ == "__main__":
	main()
