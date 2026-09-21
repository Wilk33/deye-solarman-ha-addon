import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import yaml

from tools.build_site import BuildConfig,build_site
from tools.catalog_integrity import normalized_sha256

ROOT=Path(__file__).resolve().parents[1]


def flatten_keys(value,base="") -> set[str]:
	result=set()
	for key,item in value.items():
		path=f"{base}.{key}" if base else key
		if isinstance(item,dict):
			result.update(flatten_keys(item,path))
		else:
			result.add(path)
	return result


class SiteBuildTests(unittest.TestCase):
	def setUp(self):
		self.temporary=tempfile.TemporaryDirectory()
		self.addCleanup(self.temporary.cleanup)
		self.root=Path(self.temporary.name)
		self.models_root=self.root/"catalogs/models"
		self.site_root=self.root/"site"
		self.output=self.root/"dist"
		self.models_root.mkdir(parents=True)
		(self.site_root/"reference").mkdir(parents=True)
		(self.site_root/"assets").mkdir()
		(self.site_root/"index.html").write_text(
			'<link rel="stylesheet" href="__BASE_PATH__assets/site.css">'
			'<a href="__REPOSITORY_URL__">Repository</a>',
			encoding="utf-8",
		)
		(self.site_root/"reference/index.html").write_text(
			'<a href="__BASE_PATH__">Home</a>',
			encoding="utf-8",
		)
		(self.site_root/"assets/site.css").write_text("/* __SITE_URL__ */\n",encoding="utf-8")
		(self.site_root/"assets/image.bin").write_bytes(b"\x00__BASE_PATH__\xff")
		self.write_model("telemetry_only",("telemetry",))
		self.write_model("control_only",("control",))
		self.write_model("full",("telemetry","control"),display_name="Full model")
		self.config=BuildConfig(
			root=self.root,
			models_root=self.models_root,
			site_root=self.site_root,
			output=self.output,
			base_path="/deye-solarman-ha-addon/",
			site_url="https://wilk33.github.io/deye-solarman-ha-addon/",
			repository_url="https://github.com/Wilk33/deye-solarman-ha-addon",
		)

	def write_model(self,name: str,map_ids: tuple[str,...],display_name: str | None=None) -> None:
		model_dir=self.models_root/name
		model_dir.mkdir()
		maps={}
		for offset,map_id in enumerate(map_ids):
			definition_key="sensors" if map_id == "telemetry" else "commands"
			payload={
				"format":1,
				"map_id":map_id,
				"catalog_set":name,
				"purpose":map_id,
				"writable":map_id == "control",
				"transports":["solarman_tcp"],
				definition_key:[{
					"key":f"{map_id}_{name}",
					"name":f"{map_id.title()} {name}",
					"registers":[100+offset],
					"custom_field":{"preserved":True},
				}],
			}
			path=model_dir/f"{map_id}.yaml"
			path.write_text(yaml.safe_dump(payload,sort_keys=False),encoding="utf-8",newline="\n")
			maps[map_id]={
				"file":path.name,
				"sha256":normalized_sha256(path),
				"transports":payload["transports"],
				"writable":payload["writable"],
			}
		index={"format":1,"catalog_set":name,"revision":"test","maps":maps}
		if display_name is not None:
			index["display_name"]=display_name
		(model_dir/"catalog-index.yaml").write_text(yaml.safe_dump(index,sort_keys=False),encoding="utf-8",newline="\n")

	def test_builds_manifest_and_lazy_map_files_for_every_model(self):
		manifest=build_site(self.config)

		self.assertEqual([item["catalog_set"] for item in manifest["models"]],["control_only","full","telemetry_only"])
		self.assertTrue((self.output/"generated/models/full/telemetry.json").is_file())
		self.assertTrue((self.output/"generated/models/full/control.json").is_file())
		self.assertFalse((self.output/"generated/models/telemetry_only/control.json").exists())
		self.assertEqual(manifest["models"][1]["display_name"],"Full model")
		self.assertEqual(manifest["models"][2]["display_name"],"telemetry_only")
		data=json.loads((self.output/"generated/models/full/telemetry.json").read_text(encoding="utf-8"))
		self.assertTrue(data["catalog"]["sensors"][0]["custom_field"]["preserved"])

	def test_build_is_deterministic(self):
		first=build_site(self.config)
		first_bytes=(self.output/"generated/models.json").read_bytes()
		second=build_site(self.config)

		self.assertEqual(first,second)
		self.assertEqual(first_bytes,(self.output/"generated/models.json").read_bytes())

	def test_build_writes_pages_metadata_files(self):
		build_site(self.config)

		sitemap=(self.output/"sitemap.xml").read_text(encoding="utf-8")
		robots=(self.output/"robots.txt").read_text(encoding="utf-8")
		self.assertIn("https://wilk33.github.io/deye-solarman-ha-addon/",sitemap)
		self.assertIn("https://wilk33.github.io/deye-solarman-ha-addon/reference/",sitemap)
		self.assertIn("Sitemap: https://wilk33.github.io/deye-solarman-ha-addon/sitemap.xml",robots)

	def test_manifest_is_identical_for_lf_and_crlf_catalog_files(self):
		map_path=self.models_root/"full/telemetry.yaml"
		lf_manifest=build_site(self.config)
		map_path.write_bytes(map_path.read_bytes().replace(b"\n",b"\r\n"))
		crlf_manifest=build_site(self.config)

		self.assertEqual(lf_manifest,crlf_manifest)

	def test_replaces_base_path_without_absolute_root_links(self):
		build_site(self.config)

		html=(self.output/"index.html").read_text(encoding="utf-8")
		self.assertIn("/deye-solarman-ha-addon/assets/site.css",html)
		self.assertNotIn('href="/assets/',html)
		self.assertEqual((self.output/"assets/image.bin").read_bytes(),b"\x00__BASE_PATH__\xff")

	def test_supports_root_base_path_for_local_preview(self):
		config=replace(self.config,base_path="/",site_url="http://127.0.0.1:8765/")
		build_site(config)

		html=(self.output/"index.html").read_text(encoding="utf-8")
		self.assertIn('href="/assets/site.css"',html)
		self.assertNotIn("/deye-solarman-ha-addon/",html)

	def test_rejects_base_path_without_both_slashes(self):
		for base_path in ("deye/","/deye","deye"):
			with self.subTest(base_path=base_path):
				with self.assertRaisesRegex(ValueError,"base_path"):
					build_site(replace(self.config,base_path=base_path))

	def test_rejects_output_outside_root_or_equal_to_site_source(self):
		with self.assertRaisesRegex(ValueError,"output"):
			build_site(replace(self.config,output=self.root.parent/"outside"))
		with self.assertRaisesRegex(ValueError,"output"):
			build_site(replace(self.config,output=self.site_root))

	def test_polish_and_english_translations_have_identical_keys(self):
		pl=json.loads((ROOT/"site/i18n/pl.json").read_text(encoding="utf-8"))
		en=json.loads((ROOT/"site/i18n/en.json").read_text(encoding="utf-8"))

		self.assertEqual(flatten_keys(pl),flatten_keys(en))

	def test_landing_page_has_required_sections_and_no_inline_scripts(self):
		html=(ROOT/"site/index.html").read_text(encoding="utf-8")

		for section in ("hero","transports","telemetry","controls","custom-sensors","catalogs","install"):
			self.assertIn(f'id="{section}"',html)
		self.assertNotIn("<script>",html)
		self.assertIn('type="module"',html)

	def test_styles_define_required_theme_and_accessibility_contract(self):
		css=(ROOT/"site/assets/site.css").read_text(encoding="utf-8")

		for token in ("--color-bg","--color-surface","--color-cyan","--color-green","--color-orange","--color-red","--color-text","--color-muted"):
			self.assertIn(token,css)
		for required in (":focus-visible","min-height:44px","prefers-reduced-motion","max-width:720px","max-width:1100px"):
			self.assertIn(required,css)

	def test_reference_module_avoids_unsafe_html_execution_apis(self):
		source=(ROOT/"site/assets/reference.mjs").read_text(encoding="utf-8")

		for forbidden in ("innerHTML","outerHTML","insertAdjacentHTML","document.write","eval("):
			self.assertNotIn(forbidden,source)

	def test_every_html_page_declares_content_security_policy(self):
		for path in (ROOT/"site").rglob("*.html"):
			with self.subTest(path=path):
				html=path.read_text(encoding="utf-8")
				self.assertIn('http-equiv="Content-Security-Policy"',html)


if __name__ == "__main__":
	unittest.main()
