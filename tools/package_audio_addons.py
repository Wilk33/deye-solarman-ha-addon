from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT=Path(__file__).resolve().parents[1]
PACKAGES=(
	(ROOT/"apps/haos-alarm/src/haos_alarm",ROOT/"haos-alarm/rootfs/usr/src/app/haos_alarm"),
	(ROOT/"packages/ha_audio_common",ROOT/"haos-alarm/rootfs/usr/src/app/ha_audio_common"),
	(ROOT/"apps/continuous-noise/src/continuous_noise",ROOT/"continuous-noise/rootfs/usr/src/app/continuous_noise"),
	(ROOT/"packages/ha_audio_common",ROOT/"continuous-noise/rootfs/usr/src/app/ha_audio_common"),
)


def package(check: bool) -> list[str]:
	drift=[]
	for source_root,target_root in PACKAGES:
		expected={}
		for source in source_root.rglob("*"):
			if source.is_file() and "__pycache__" not in source.parts and source.suffix in {".py",".json"}:
				expected[target_root/source.relative_to(source_root)]=source.read_bytes()
		for target,data in expected.items():
			if target.exists() and target.read_bytes() == data:
				continue
			drift.append(str(target.relative_to(ROOT)))
			if not check:
				target.parent.mkdir(parents=True,exist_ok=True)
				target.write_bytes(data)
		if target_root.exists():
			for target in target_root.rglob("*"):
				if target.is_file() and "__pycache__" not in target.parts and target not in expected:
					drift.append(str(target.relative_to(ROOT)))
					if not check:
						if not target.resolve().is_relative_to(target_root.resolve()):
							raise RuntimeError("Generated file escaped add-on rootfs")
						target.unlink()
	return drift


def main() -> None:
	parser=argparse.ArgumentParser()
	parser.add_argument("--check",action="store_true")
	args=parser.parse_args()
	drift=package(args.check)
	if args.check and drift:
		raise SystemExit("Generated audio add-ons differ from sources:\n"+"\n".join(drift))
	print(f"{'Verified' if args.check else 'Packaged'} audio add-ons ({len(drift)} changed files)")


if __name__ == "__main__":
	main()
