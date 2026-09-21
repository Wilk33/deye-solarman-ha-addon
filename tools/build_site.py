"""Build the static SolarMan Diagnostics project and register reference site."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
	sys.path.insert(0,str(ROOT))

from tools.catalog_integrity import CatalogModel,discover_catalog_models


TEXT_SUFFIXES={".html",".mjs",".css",".json",".xml",".txt"}


@dataclass(frozen=True)
class BuildConfig:
	root: Path
	models_root: Path
	site_root: Path
	output: Path
	base_path: str
	site_url: str
	repository_url: str


def validate_build_config(config: BuildConfig) -> None:
	root=config.root.resolve()
	models_root=config.models_root.resolve()
	site_root=config.site_root.resolve()
	output=config.output.resolve()
	if not config.base_path.startswith("/") or not config.base_path.endswith("/"):
		raise ValueError("base_path must start and end with /")
	if not models_root.is_dir():
		raise ValueError(f"models_root does not exist: {models_root}")
	if not site_root.is_dir():
		raise ValueError(f"site_root does not exist: {site_root}")
	if not output.is_relative_to(root):
		raise ValueError("output must be inside root")
	if output == root or output == site_root or site_root.is_relative_to(output) or output.is_relative_to(site_root):
		raise ValueError("output must be separate from root and site source")
	if not config.site_url.startswith(("https://","http://")) or not config.site_url.endswith("/"):
		raise ValueError("site_url must be an absolute URL ending with /")
	if not config.repository_url.startswith("https://"):
		raise ValueError("repository_url must be an HTTPS URL")


def reset_output(output: Path) -> None:
	resolved=output.resolve()
	if resolved.exists():
		shutil.rmtree(resolved)
	resolved.mkdir(parents=True)


def _replace_tokens(content: str,config: BuildConfig) -> str:
	return (
		content
		.replace("__BASE_PATH__",config.base_path)
		.replace("__SITE_URL__",config.site_url)
		.replace("__REPOSITORY_URL__",config.repository_url)
	)


def copy_site_sources(config: BuildConfig) -> None:
	for source in sorted(config.site_root.rglob("*")):
		if not source.is_file():
			continue
		target=config.output/source.relative_to(config.site_root)
		target.parent.mkdir(parents=True,exist_ok=True)
		if source.suffix.lower() in TEXT_SUFFIXES:
			target.write_text(_replace_tokens(source.read_text(encoding="utf-8"),config),encoding="utf-8",newline="\n")
		else:
			target.write_bytes(source.read_bytes())


def _source_url(config: BuildConfig,model: CatalogModel,file_name: str) -> str:
	return f"{config.repository_url}/blob/main/catalogs/models/{model.catalog_set}/{file_name}"


def build_manifest(models: tuple[CatalogModel,...],config: BuildConfig) -> dict[str,Any]:
	manifest_models=[]
	for model in models:
		map_items={}
		for map_id,catalog_map in model.maps.items():
			file_name=catalog_map.metadata["file"]
			map_items[map_id]={
				"map_id":map_id,
				"writable":catalog_map.metadata["writable"],
				"transports":catalog_map.metadata["transports"],
				"definition_count":len(catalog_map.definitions),
				"sha256":catalog_map.metadata["sha256"].lower(),
				"data_path":f"generated/models/{model.catalog_set}/{map_id}.json",
				"source_url":_source_url(config,model,file_name),
			}
		display_name=model.index.get("display_name",model.catalog_set)
		manufacturer=model.index.get("manufacturer","")
		model_families=model.index.get("model_families",[])
		manifest_models.append({
			"catalog_set":model.catalog_set,
			"display_name":display_name,
			"manufacturer":manufacturer,
			"model_families":model_families,
			"revision":model.index.get("revision",""),
			"source_url":_source_url(config,model,"catalog-index.yaml"),
			"maps":map_items,
		})
	return {
		"format":1,
		"base_path":config.base_path,
		"site_url":config.site_url,
		"repository_url":config.repository_url,
		"models":manifest_models,
	}


def _write_json(path: Path,payload: Any) -> None:
	path.parent.mkdir(parents=True,exist_ok=True)
	path.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8",newline="\n")


def write_catalog_data(models: tuple[CatalogModel,...],config: BuildConfig) -> None:
	for model in models:
		for map_id,catalog_map in model.maps.items():
			reference={
				"catalog_set":model.catalog_set,
				"map_id":map_id,
				"sha256":catalog_map.metadata["sha256"].lower(),
				"source_url":_source_url(config,model,catalog_map.metadata["file"]),
			}
			_write_json(
				config.output/f"generated/models/{model.catalog_set}/{map_id}.json",
				{"reference":reference,"catalog":catalog_map.payload},
			)


def write_generated_metadata(manifest: dict[str,Any],config: BuildConfig) -> None:
	_write_json(config.output/"generated/models.json",manifest)
	sitemap=(
		'<?xml version="1.0" encoding="UTF-8"?>\n'
		'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
		f"\t<url><loc>{config.site_url}</loc></url>\n"
		f"\t<url><loc>{config.site_url}reference/</loc></url>\n"
		"</urlset>\n"
	)
	(config.output/"sitemap.xml").write_text(sitemap,encoding="utf-8",newline="\n")
	(config.output/"robots.txt").write_text(
		f"User-agent: *\nAllow: /\nSitemap: {config.site_url}sitemap.xml\n",
		encoding="utf-8",
		newline="\n",
	)


def build_site(config: BuildConfig) -> dict[str,Any]:
	validate_build_config(config)
	models=discover_catalog_models(config.models_root)
	if not models:
		raise ValueError("no catalog models found")
	reset_output(config.output)
	copy_site_sources(config)
	manifest=build_manifest(models,config)
	write_catalog_data(models,config)
	write_generated_metadata(manifest,config)
	return manifest


def main() -> None:
	parser=argparse.ArgumentParser()
	parser.add_argument("--output",default=".site-dist")
	parser.add_argument("--base-path",default="/deye-solarman-ha-addon/")
	parser.add_argument("--site-url",default="https://wilk33.github.io/deye-solarman-ha-addon/")
	parser.add_argument("--repository-url",default="https://github.com/Wilk33/deye-solarman-ha-addon")
	args=parser.parse_args()
	config=BuildConfig(
		root=ROOT,
		models_root=ROOT/"catalogs/models",
		site_root=ROOT/"site",
		output=(ROOT/args.output).resolve(),
		base_path=args.base_path,
		site_url=args.site_url,
		repository_url=args.repository_url.rstrip("/"),
	)
	manifest=build_site(config)
	map_count=sum(len(model["maps"]) for model in manifest["models"])
	definition_count=sum(
		catalog_map["definition_count"]
		for model in manifest["models"]
		for catalog_map in model["maps"].values()
	)
	print(f"Built {len(manifest['models'])} models, {map_count} maps and {definition_count} definitions in {config.output}")


if __name__ == "__main__":
	main()
