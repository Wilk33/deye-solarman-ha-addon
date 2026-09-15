"""Export the installed, pinned Sunsynk three-phase LV definitions as data only."""
import json
import subprocess
import sys
from pathlib import Path

REVISION="e2466b6505c1990aced1f18c12a42ded638aee9b"
CHECKOUT=Path(sys.argv[1] if len(sys.argv) > 1 else ".work/sunsynk").resolve()
actual=subprocess.check_output(["git","-C",str(CHECKOUT),"rev-parse","HEAD"],text=True).strip()
if actual != REVISION:
	raise SystemExit(f"Expected source revision {REVISION}, got {actual}")
sys.path.insert(0,str(CHECKOUT/"src"))

from sunsynk.definitions.three_phase_lv import SENSORS
from sunsynk.rwsensors import RWSensor
from sunsynk.sensors import Constant, Sensor, ensure_slugs

TARGET=Path(__file__).resolve().parents[1]/"catalogs/models/deye_sg04_sg05_3ph_lv/control.yaml"


def reference(value):
	if isinstance(value,Constant):
		return value.value
	if isinstance(value,Sensor):
		return {"registers": list(value.address),"factor": value.factor,"name": value.name}
	return value


aliases={alias for sensor in SENSORS.all.values() for alias in ensure_slugs(sensor.alias)}
entries=[]
for key,sensor in SENSORS.all.items():
	if not isinstance(sensor,RWSensor) or key in aliases:
		continue
	entry={"key": "control_"+key,"name": sensor.name,"registers": list(sensor.address),"method": type(sensor).__name__,"factor": sensor.factor,"unit": sensor.unit,"bitmask": sensor.bitmask}
	for field in ("min","max","options","on","off","year_offset"):
		if hasattr(sensor,field):
			entry[field]=reference(getattr(sensor,field))
	entries.append(entry)
TARGET.write_bytes((json.dumps({"version": 1,"source_revision": REVISION,"source": f"https://github.com/kellerza/sunsynk/tree/{REVISION}/src/sunsynk","profile": "three_phase_lv","commands": entries,"format":1,"map_id":"control","catalog_set":"deye_sg04_sg05_3ph_lv","purpose":"control","writable":True,"transports":["solarman_tcp"]},ensure_ascii=False,indent=2)+"\n").encode("utf-8"))
print(f"Exported {len(entries)} controls to {TARGET}")
