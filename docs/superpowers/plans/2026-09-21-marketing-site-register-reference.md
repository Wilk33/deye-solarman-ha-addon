# SolarMan Diagnostics Marketing Site and Register Reference Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Zbudować i opublikować dwujęzyczną stronę SolarMan Diagnostics z wielomodelową przeglądarką telemetrii i sterowania generowaną z `catalogs/models/*`.

**Architecture:** Python waliduje wszystkie katalogi modeli, współdzieli reguły integralności z pakowaniem dodatku i buduje statyczny artefakt GitHub Pages. Strona używa HTML, CSS i modułów JavaScript bez frameworka, pobiera mały manifest modeli, a następnie tylko wybraną mapę. Obecny workflow walidacji buduje stronę dla każdego pull requestu i wdraża ją wyłącznie po poprawnym pushu do `main`.

**Tech Stack:** Python 3.13, PyYAML 6.0.3, `unittest`, HTML5, CSS, JavaScript ES modules, Node.js built-in test runner, GitHub Actions, GitHub Pages.

**Spec:** `docs/superpowers/specs/2026-09-21-marketing-site-register-reference-design.md`

## Global Constraints

- Publiczny adres ma postać `https://wilk33.github.io/deye-solarman-ha-addon/`.
- Modele są wykrywane wyłącznie przez `catalogs/models/*/catalog-index.yaml`; lista nazw modeli nie może znajdować się w kodzie strony ani generatora.
- Model może mieć tylko `telemetry`, tylko `control` albo obie mapy.
- Strona ma działać po polsku i angielsku.
- Dane techniczne katalogów pozostają niezmienione i nie są automatycznie tłumaczone.
- Strona używa HTML, CSS i JavaScript bez frameworka oraz bez zewnętrznych CDN.
- Nie wolno dodawać analityki, reklam, trackerów ani zewnętrznych fontów.
- Dane katalogu są wstawiane do DOM jako tekst i nie mogą być wykonywane jako HTML lub JavaScript.
- Pakowanie dodatku i generator strony muszą korzystać z tej samej normalizacji linii oraz SHA-256.
- Oryginalne zrzuty ekranu nie mogą trafić do repozytorium; publikowane kopie nie mogą zawierać danych prywatnych.
- Zmiana nie podbija wersji dodatku i nie zmienia runtime, Modbusa, MQTT ani definicji encji.
- Kontrola końcowa ma dokładnie dwie tury ograniczone do błędów istotnych i krytycznych.
- Kod Python i JavaScript zachowuje styl repozytorium: tabulatory, klamry JavaScript w nowej linii i brak niepowiązanego formatowania.

## Review Focus

1. Model zawierający tylko jedną mapę ma się zbudować, a brakująca zakładka ma być niedostępna bez błędu całej strony. Test przypisany do zadań 1, 2 i 4.
2. Te same katalogi zapisane z LF albo CRLF mają dawać ten sam SHA-256 i identyczny manifest. Test przypisany do zadań 1 i 2.
3. Ścieżka `../` w indeksie oraz tekst katalogu zawierający HTML lub skrypt nie mogą prowadzić do odczytu poza modelem ani wykonania treści. Test przypisany do zadań 1 i 4.
4. Wszystkie zasoby, zapytania i linki bezpośrednie muszą działać pod prefiksem `/deye-solarman-ha-addon/`, także po odświeżeniu widoku definicji. Test przypisany do zadań 2, 4 i 7.
5. Publiczne materiały nie mogą ujawniać adresów IP, numerów seryjnych, urządzeń USB, ścieżek Ingress ani avatara. Kontrola przypisana do zadań 5 i 7.

---

## Mapa plików

### Nowe pliki

- `tools/catalog_integrity.py` - wspólny odczyt, normalizacja, SHA-256, wykrywanie i walidacja modeli.
- `tools/build_site.py` - budowanie statycznego artefaktu i manifestu modeli.
- `tests/test_catalog_integrity.py` - testy wielomodelowej walidacji katalogów.
- `tests/test_site_build.py` - testy generatora, i18n, artefaktu i danych prywatnych.
- `tests/site_reference.test.mjs` - testy czystych funkcji wyszukiwania, filtrowania i URL.
- `site/index.html` - strona produktu.
- `site/404.html` - bezpieczna strona błędu z przejściem do strony głównej.
- `site/reference/index.html` - szkielet przeglądarki definicji.
- `site/assets/site.css` - wspólne style, responsywność i dostępność.
- `site/assets/app.mjs` - język, motyw, nawigacja i statystyki strony produktu.
- `site/assets/reference.mjs` - ładowanie manifestu, wyszukiwanie, filtry, tabela, karty i szczegóły.
- `site/assets/brand.svg` - kodowe logo projektu bez zewnętrznych zależności.
- `site/assets/screenshots/sensors.png` - publiczny widok telemetrii bez danych prywatnych.
- `site/assets/screenshots/controls.png` - publiczny widok sterowania bez danych prywatnych.
- `site/assets/screenshots/custom-sensors.png` - publiczny widok Własnych sensorów bez danych prywatnych.
- `site/assets/screenshots/catalog-sources.png` - publiczny widok źródeł katalogów bez danych prywatnych.
- `site/i18n/pl.json` - polskie teksty strony.
- `site/i18n/en.json` - angielskie teksty strony.

### Zmieniane pliki

- `tools/package_addon.py:1-34` - użycie wspólnego modułu integralności i zachowanie metadanych modelu.
- `tests/test_architecture.py:1-215` - nowy import normalizacji, kontrola metadanych i workflow Pages.
- `catalogs/models/deye_sg04_sg05_3ph_lv/catalog-index.yaml:1-26` - czytelne metadane modelu.
- `deye-solarman-diagnostics/rootfs/usr/src/app/deye_inverter_core/data/catalog-index.yaml` - wygenerowana kopia indeksu.
- `.gitignore` - śledzenie źródeł `site/` i ignorowanie `.site-dist/` oraz `.site-preview/`.
- `.github/workflows/validate.yml` - testy strony, artefakt i wdrożenie Pages.
- `README.md` - marketingowe wejście, status strony i odnośniki.
- `deye-solarman-diagnostics/README.md` - odnośnik do strony i definicji.
- `deye-solarman-diagnostics/DOCS.md` - odnośnik do przeglądarki modeli.
- `catalogs/README.md` - opis automatycznej publikacji wszystkich modeli.
- `catalogs/models/README.md` - kontrakt opcjonalnych metadanych i wykrywania modeli.

---

### Task 1: Wspólna integralność i wykrywanie katalogów

**Files:**
- Create: `tools/catalog_integrity.py`
- Create: `tests/test_catalog_integrity.py`
- Modify: `tools/package_addon.py:1-34`
- Modify: `tests/test_architecture.py:1-215`
- Modify: `catalogs/models/deye_sg04_sg05_3ph_lv/catalog-index.yaml:1-26`
- Modify: `deye-solarman-diagnostics/rootfs/usr/src/app/deye_inverter_core/data/catalog-index.yaml`

**Interfaces:**
- Produces: `normalized_text_bytes(path: Path) -> bytes`.
- Produces: `normalized_sha256(path: Path) -> str`.
- Produces: `load_catalog_model(model_dir: Path) -> CatalogModel`.
- Produces: `discover_catalog_models(models_root: Path) -> tuple[CatalogModel,...]`.
- Produces: immutable `CatalogMap` and `CatalogModel` dataclasses consumed by `tools/build_site.py`.

- [ ] **Step 1: Napisz testy normalizacji i wykrywania modeli**

Utwórz `tests/test_catalog_integrity.py` z pomocnikami zapisującymi syntetyczne mapy oraz z testami o dokładnych nazwach:

```python
class CatalogIntegrityTests(unittest.TestCase):
	def test_normalized_sha256_is_identical_for_lf_and_crlf(self):
		with tempfile.TemporaryDirectory() as directory:
			root=Path(directory)
			lf=root/"lf.yaml"
			crlf=root/"crlf.yaml"
			lf.write_bytes(b"format: 1\nmap_id: telemetry\n")
			crlf.write_bytes(b"format: 1\r\nmap_id: telemetry\r\n")
			self.assertEqual(normalized_sha256(lf),normalized_sha256(crlf))

	def test_discovers_models_with_independent_maps(self):
		models=discover_catalog_models(self.models_root)
		self.assertEqual([model.catalog_set for model in models],["control_only","full","telemetry_only"])
		self.assertEqual(set(models[0].maps),{"control"})
		self.assertEqual(set(models[1].maps),{"telemetry","control"})
		self.assertEqual(set(models[2].maps),{"telemetry"})

	def test_rejects_map_path_outside_model_directory(self):
		with self.assertRaisesRegex(CatalogValidationError,"outside model directory"):
			load_catalog_model(self.models_root/"unsafe")

	def test_rejects_duplicate_definition_keys(self):
		with self.assertRaisesRegex(CatalogValidationError,"duplicate key"):
			load_catalog_model(self.models_root/"duplicate")
```

Pomocnik testu ma liczyć SHA przez `normalized_sha256`, a nie powielać implementację hashowania.

- [ ] **Step 2: Uruchom testy i potwierdź kontrolowaną porażkę**

Run:

```powershell
.work/venv/Scripts/python.exe -m unittest tests.test_catalog_integrity -v
```

Expected: FAIL z `ModuleNotFoundError: No module named 'tools.catalog_integrity'`.

- [ ] **Step 3: Zaimplementuj model katalogu i walidację**

W `tools/catalog_integrity.py` dodaj dokładne typy publiczne:

```python
@dataclass(frozen=True)
class CatalogMap:
	map_id: str
	path: Path
	metadata: dict[str,Any]
	payload: dict[str,Any]
	definition_key: str
	definitions: tuple[dict[str,Any],...]


@dataclass(frozen=True)
class CatalogModel:
	path: Path
	catalog_set: str
	index: dict[str,Any]
	maps: dict[str,CatalogMap]
```

Zaimplementuj:

```python
def normalized_text_bytes(path: Path) -> bytes:
	return path.read_text(encoding="utf-8").replace("\r\n","\n").replace("\r","\n").encode("utf-8")


def normalized_sha256(path: Path) -> str:
	return hashlib.sha256(normalized_text_bytes(path)).hexdigest()


def discover_catalog_models(models_root: Path) -> tuple[CatalogModel,...]:
	return tuple(
		load_catalog_model(path)
		for path in sorted(models_root.iterdir(),key=lambda item:item.name)
		if path.is_dir() and (path/"catalog-index.yaml").is_file()
	)
```

`load_catalog_model` ma wykonywać komplet walidacji ze specyfikacji. Dozwolone mapy to `telemetry` i `control`, a odpowiadające listy definicji to `sensors` i `commands`. Rozwiązana ścieżka mapy musi przejść `resolved.is_relative_to(model_dir.resolve())`.

- [ ] **Step 4: Przenieś pakowanie na wspólną normalizację**

Usuń lokalne `normalized_text_bytes` i import `hashlib` z `tools/package_addon.py`. Zaimportuj:

```python
from tools.catalog_integrity import normalized_sha256,normalized_text_bytes
```

Podczas budowania indeksu zachowaj tylko opcjonalne pola:

```python
PRESENTATION_FIELDS=("display_name","manufacturer","model_families")
source_index=yaml.safe_load((MODEL/"catalog-index.yaml").read_text(encoding="utf-8"))
index={"format":1,"catalog_set":source_index["catalog_set"],"revision":"2.0.5","maps":{}}
for field in PRESENTATION_FIELDS:
	if field in source_index:
		index[field]=source_index[field]
```

Użyj `normalized_sha256(MODEL/name)` przy zapisie pola `sha256`.

- [ ] **Step 5: Dodaj metadane obecnego modelu i odśwież artefakt**

Dodaj do źródłowego indeksu:

```json
"display_name": "Deye SG04/SG05 3PH LV",
"manufacturer": "Deye",
"model_families": ["SG04LP3", "SG05LP3"]
```

Następnie uruchom:

```powershell
.work/venv/Scripts/python.exe tools/package_addon.py
```

Expected: wygenerowany indeks dodatku zawiera te same trzy pola, a sumy map nie zmieniają się.

- [ ] **Step 6: Zaktualizuj test architektury i uruchom walidację**

Zmień import na:

```python
from tools.catalog_integrity import normalized_text_bytes
```

W `test_release_metadata_and_bundle_match_version_2_contract` dodaj:

```python
self.assertEqual(index["display_name"],"Deye SG04/SG05 3PH LV")
self.assertEqual(index["manufacturer"],"Deye")
self.assertEqual(index["model_families"],["SG04LP3","SG05LP3"])
```

Run:

```powershell
.work/venv/Scripts/python.exe -m unittest tests.test_catalog_integrity tests.test_architecture -v
.work/venv/Scripts/python.exe tools/package_addon.py --check
```

Expected: PASS i `Verified ... files`.

- [ ] **Step 7: Commit**

```powershell
git add tools/catalog_integrity.py tools/package_addon.py tests/test_catalog_integrity.py tests/test_architecture.py catalogs/models/deye_sg04_sg05_3ph_lv/catalog-index.yaml deye-solarman-diagnostics/rootfs/usr/src/app/deye_inverter_core/data/catalog-index.yaml
git commit -m "Add generic catalog discovery and integrity validation"
```

---

### Task 2: Deterministyczny generator statycznej strony

**Files:**
- Create: `tools/build_site.py`
- Create: `tests/test_site_build.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: `discover_catalog_models(models_root)` z zadania 1.
- Produces: `BuildConfig` dataclass.
- Produces: `build_site(config: BuildConfig) -> dict[str,Any]` zwracające manifest zapisany również jako `generated/models.json`.
- Produces: CLI `python tools/build_site.py --output .site-dist --base-path /deye-solarman-ha-addon/ --site-url https://wilk33.github.io/deye-solarman-ha-addon/`.

- [ ] **Step 1: Napisz testy budowania wielu modeli**

W `tests/test_site_build.py` utwórz tymczasowe katalogi modeli i minimalny katalog źródeł strony. Dodaj testy:

```python
class SiteBuildTests(unittest.TestCase):
	def test_builds_manifest_and_lazy_map_files_for_every_model(self):
		manifest=build_site(self.config)
		self.assertEqual([item["catalog_set"] for item in manifest["models"]],["control_only","full","telemetry_only"])
		self.assertTrue((self.output/"generated/models/full/telemetry.json").is_file())
		self.assertTrue((self.output/"generated/models/full/control.json").is_file())
		self.assertFalse((self.output/"generated/models/telemetry_only/control.json").exists())

	def test_build_is_deterministic(self):
		first=build_site(self.config)
		first_bytes=(self.output/"generated/models.json").read_bytes()
		second=build_site(self.config)
		self.assertEqual(first,second)
		self.assertEqual(first_bytes,(self.output/"generated/models.json").read_bytes())

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

	def test_supports_root_base_path_for_local_preview(self):
		config=replace(self.config,base_path="/",site_url="http://127.0.0.1:8765/")
		build_site(config)
		html=(self.output/"index.html").read_text(encoding="utf-8")
		self.assertIn('href="/assets/site.css"',html)
		self.assertNotIn("/deye-solarman-ha-addon/",html)
```

Dodaj również test odrzucenia `base_path` bez początkowego i końcowego `/`.

- [ ] **Step 2: Uruchom test i potwierdź brak generatora**

Run:

```powershell
.work/venv/Scripts/python.exe -m unittest tests.test_site_build -v
```

Expected: FAIL z brakiem `tools.build_site`.

- [ ] **Step 3: Zaimplementuj konfigurację i manifest**

W `tools/build_site.py` dodaj:

```python
@dataclass(frozen=True)
class BuildConfig:
	root: Path
	models_root: Path
	site_root: Path
	output: Path
	base_path: str
	site_url: str
	repository_url: str


def build_site(config: BuildConfig) -> dict[str,Any]:
	validate_build_config(config)
	models=discover_catalog_models(config.models_root)
	reset_output(config.output)
	copy_site_sources(config)
	manifest=build_manifest(models,config)
	write_catalog_data(models,manifest,config)
	write_generated_metadata(manifest,config)
	return manifest
```

Manifest ma `format: 1` i posortowaną listę `models`. Nie dodawaj czasu budowy, ponieważ psuje deterministyczność.

Plik mapy ma strukturę:

```json
{
  "reference": {
    "catalog_set": "deye_sg04_sg05_3ph_lv",
    "map_id": "telemetry",
    "sha256": "...",
    "source_url": "https://github.com/Wilk33/deye-solarman-ha-addon/blob/main/catalogs/models/deye_sg04_sg05_3ph_lv/telemetry.yaml"
  },
  "catalog": {}
}
```

Pole `catalog` zawiera pełny payload źródłowy, aby nie utracić nieznanych pól.

- [ ] **Step 4: Dodaj kopiowanie źródeł i tokeny ścieżek**

Obsłuż tokeny tekstowe:

```text
__BASE_PATH__
__SITE_URL__
__REPOSITORY_URL__
```

Zamieniaj je po skopiowaniu plików tekstowych `.html`, `.mjs`, `.css`, `.json`, `.xml` i `.txt`. Pliki binarne kopiuj bez zmian.

Przed budową usuń tylko dokładny `config.output` po potwierdzeniu, że znajduje się wewnątrz repozytorium albo tymczasowego katalogu testowego. Nie używaj globu i nie usuwaj katalogu źródeł.

- [ ] **Step 5: Popraw `.gitignore`**

Usuń wpis:

```gitignore
/site
```

Dodaj:

```gitignore
/.site-dist/
/.site-preview/
```

- [ ] **Step 6: Uruchom testy generatora**

Run:

```powershell
.work/venv/Scripts/python.exe -m unittest tests.test_catalog_integrity tests.test_site_build -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add .gitignore tools/build_site.py tests/test_site_build.py
git commit -m "Add deterministic multi-model site generator"
```

---

### Task 3: Dwujęzyczna strona produktu i system wizualny

**Files:**
- Create: `site/index.html`
- Create: `site/404.html`
- Create: `site/assets/site.css`
- Create: `site/assets/app.mjs`
- Create: `site/assets/brand.svg`
- Create: `site/i18n/pl.json`
- Create: `site/i18n/en.json`
- Modify: `tests/test_site_build.py`

**Interfaces:**
- Produces: `window.solarmanSite` z aktywnym językiem i funkcją `setLanguage(language)`.
- Produces: elementy `data-i18n`, `data-i18n-aria` i `data-i18n-meta` używane przez `app.mjs`.
- Consumes: `__BASE_PATH__`, `__SITE_URL__` i `__REPOSITORY_URL__` z generatora.

- [ ] **Step 1: Dodaj test parytetu tłumaczeń i struktury strony**

Rozszerz `tests/test_site_build.py`:

```python
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
```

- [ ] **Step 2: Uruchom test i potwierdź brak plików strony**

Run:

```powershell
.work/venv/Scripts/python.exe -m unittest tests.test_site_build -v
```

Expected: FAIL z brakiem `site/i18n/pl.json` albo `site/index.html`.

- [ ] **Step 3: Zbuduj semantyczny landing page**

`site/index.html` ma zawierać:

```html
<header class="site-header">
	<a class="brand" href="__BASE_PATH__" aria-label="SolarMan Diagnostics">
		<img src="__BASE_PATH__assets/brand.svg" alt="">
		<span>SolarMan Diagnostics</span>
	</a>
	<nav aria-label="Primary navigation">...</nav>
	<div class="site-actions">...</div>
</header>
<main>
	<section id="hero">...</section>
	<section id="transports">...</section>
	<section id="telemetry">...</section>
	<section id="controls">...</section>
	<section id="custom-sensors">...</section>
	<section id="catalogs">...</section>
	<section id="install">...</section>
</main>
```

Każdy tekst zmienny ma klucz `data-i18n`. Nie dodawaj danych ze zrzutów ani liczby definicji na stałe. Miejsca na liczby używają `data-catalog-stat` i zostaną wypełnione z `generated/models.json`.

- [ ] **Step 4: Dodaj język, motyw i statystyki**

W `site/assets/app.mjs` zaimplementuj:

```javascript
export function chooseLanguage(url,navigatorLanguage,storedLanguage)
{
	const requested=new URL(url).searchParams.get("lang");
	if (requested === "pl" || requested === "en") return requested;
	if (storedLanguage === "pl" || storedLanguage === "en") return storedLanguage;
	return String(navigatorLanguage).toLowerCase().startsWith("pl") ? "pl" : "en";
}

export async function loadTranslations(language,basePath)
{
	const response=await fetch(`${basePath}i18n/${language}.json`);
	if (!response.ok) throw new Error(`Translation request failed: ${response.status}`);
	return response.json();
}
```

Aktualizuj treść wyłącznie przez `textContent` albo bezpieczne atrybuty `aria-label`, `title`, `content`. Zapisuj `solarman-site-language` i `solarman-site-theme` w `localStorage`. Respektuj `prefers-color-scheme` oraz `prefers-reduced-motion`.

- [ ] **Step 5: Zaimplementuj responsywny system wizualny**

W `site/assets/site.css` zdefiniuj tokeny `--color-bg`, `--color-surface`, `--color-cyan`, `--color-green`, `--color-orange`, `--color-red`, `--color-text` i `--color-muted`. Dodaj punkty układu dla 720 px i 1100 px, widoczny `:focus-visible`, minimalny rozmiar celu dotykowego 44 px oraz wyłączenie animacji przez `prefers-reduced-motion`.

Logo `brand.svg` ma być prostym, własnym znakiem łączącym słońce, dwie linie transportu i jeden węzeł wyjściowy. Nie kopiuj logo Deye, Home Assistant ani Sunsynk.

- [ ] **Step 6: Uruchom testy i lokalny build**

Run:

```powershell
.work/venv/Scripts/python.exe -m unittest tests.test_site_build -v
node --check site/assets/app.mjs
.work/venv/Scripts/python.exe tools/build_site.py --output .site-dist --base-path /deye-solarman-ha-addon/ --site-url https://wilk33.github.io/deye-solarman-ha-addon/
```

Expected: PASS i komplet strony w `.site-dist/`.

- [ ] **Step 7: Commit**

```powershell
git add site/index.html site/404.html site/assets/site.css site/assets/app.mjs site/assets/brand.svg site/i18n/pl.json site/i18n/en.json tests/test_site_build.py
git commit -m "Build bilingual SolarMan Diagnostics landing page"
```

---

### Task 4: Interaktywna przeglądarka definicji

**Files:**
- Create: `site/reference/index.html`
- Create: `site/assets/reference.mjs`
- Create: `tests/site_reference.test.mjs`
- Modify: `site/assets/site.css`
- Modify: `site/i18n/pl.json`
- Modify: `site/i18n/en.json`
- Modify: `tests/test_site_build.py`

**Interfaces:**
- Consumes: `generated/models.json` i pliki wskazane przez `maps.<map_id>.data_path`.
- Produces: `normalizeSearchValue(value) -> string`.
- Produces: `extractDefinitions(document) -> Array<object>`.
- Produces: `filterDefinitions(definitions,filters) -> Array<object>`.
- Produces: `parseReferenceState(url) -> object`.
- Produces: `updateReferenceUrl(url,state) -> string`.
- Produces: `selectAvailableMap(model,requestedMap) -> string`.
- Produces: `describeDefinition(definition,mapMetadata) -> object`.

- [ ] **Step 1: Napisz testy czystych funkcji JavaScript**

Utwórz `tests/site_reference.test.mjs`:

```javascript
import test from "node:test";
import assert from "node:assert/strict";
import {
	filterDefinitions,
	parseReferenceState,
	selectAvailableMap,
	updateReferenceUrl,
} from "../site/assets/reference.mjs";

const definitions=[
	{key:"run_state",name:"<img src=x onerror=alert(1)>",registers:[500],type:"enum",options:{"2":"Normal"}},
	{key:"pv1_voltage",name:"PV1 Voltage",registers:[676],type:"uint16",unit:"V",category:"pv"},
];

test("searches by register and enum option",()=>
{
	assert.deepEqual(filterDefinitions(definitions,{query:"500"}).map(item=>item.key),["run_state"]);
	assert.deepEqual(filterDefinitions(definitions,{query:"normal"}).map(item=>item.key),["run_state"]);
});

test("round trips model map query and hash",()=>
{
	const source=new URL("https://example.test/reference/?model=sample&map=telemetry&q=battery#run_state");
	const state=parseReferenceState(source);
	assert.equal(state.model,"sample");
	assert.equal(state.map,"telemetry");
	assert.equal(state.definition,"run_state");
	assert.equal(parseReferenceState(new URL(updateReferenceUrl(source,state))).definition,"run_state");
});

test("falls back to the only map exposed by a model",()=>
{
	const model={maps:{control:{data_path:"generated/models/sample/control.json"}}};
	assert.equal(selectAvailableMap(model,"telemetry"),"control");
});
```

Dodaj test filtrów kategorii, transportu, typu, zapisu, wielu rejestrów i dynamicznego zakresu.

Rozszerz `tests/test_site_build.py` o test źródła modułu, który odrzuca użycie `innerHTML`, `outerHTML`, `insertAdjacentHTML`, `document.write` i `eval` w `site/assets/reference.mjs`.

- [ ] **Step 2: Uruchom test i potwierdź brak modułu**

Run:

```powershell
node --test tests/site_reference.test.mjs
```

Expected: FAIL z `ERR_MODULE_NOT_FOUND`.

- [ ] **Step 3: Zaimplementuj czyste funkcje danych**

`extractDefinitions` wybiera `catalog.sensors` dla telemetrii i `catalog.commands` dla sterowania. Każdej definicji dodaje wyłącznie obliczone pola z prefiksem `_reference`, bez mutowania oryginału.

`filterDefinitions` przyjmuje obiekt:

```javascript
{
	query:"",
	category:"all",
	transport:"all",
	type:"all",
	access:"all",
	registerCount:"all",
	range:"all",
}
```

Wyszukiwanie obejmuje `name`, `key`, `registers`, `unit`, `category`, `type`, `method`, `options`, `zero` i `unknown`.

- [ ] **Step 4: Zbuduj semantyczny interfejs przeglądarki**

`site/reference/index.html` ma zawierać:

- `select#model-select`;
- przyciski zakładek z `role="tab"`;
- `input#definition-search`;
- rozwijane filtry z etykietami;
- `output#result-count` z `aria-live="polite"`;
- `table#definition-table`;
- `section#definition-cards`;
- `dialog#definition-details`;
- lokalizowany `section#error-state`.

Każdy wiersz i karta są przyciskiem otwierającym szczegóły. Wszystkie dane katalogu twórz przez `document.createElement` oraz `textContent`. Nie używaj `innerHTML` dla danych katalogu.

- [ ] **Step 5: Obsłuż modele z jedną mapą i błędy pobierania**

Po wczytaniu manifestu:

- wybierz model z URL albo pierwszy model;
- włącz tylko zakładki obecne w `model.maps`;
- jeżeli żądana mapa nie istnieje, wybierz pierwszą dostępną i popraw URL;
- pobierz tylko `data_path` wybranej mapy;
- pokaż lokalizowany błąd z linkiem do `source_url`, gdy pobranie nie powiedzie się;
- pozostaw nawigację i landing page sprawne.

- [ ] **Step 6: Dodaj tabelę, karty i panel szczegółów**

Tabela pokazuje nazwę, klucz, rejestry, typ, jednostkę, dostęp, transporty i kategorię. Na ekranie poniżej 720 px ukryj tabelę i pokaż karty.

Panel szczegółów pokazuje wszystkie pola znane ze specyfikacji. Obiektowe `min` albo `max` przedstaw jako zależność od wskazanych rejestrów i wartości, bez spłaszczania do nieprawdziwej liczby.

- [ ] **Step 7: Uruchom testy JavaScript i build**

Run:

```powershell
node --test tests/site_reference.test.mjs
node --check site/assets/reference.mjs
.work/venv/Scripts/python.exe -m unittest tests.test_site_build -v
.work/venv/Scripts/python.exe tools/build_site.py --output .site-dist --base-path /deye-solarman-ha-addon/ --site-url https://wilk33.github.io/deye-solarman-ha-addon/
```

Expected: PASS. Wygenerowane odnośniki strony definicji i manifestu zaczynają się od `/deye-solarman-ha-addon/`. Lokalny podgląd z prefiksem `/` jest wykonywany w zadaniu 7.

- [ ] **Step 8: Commit**

```powershell
git add site/reference/index.html site/assets/reference.mjs site/assets/site.css site/i18n/pl.json site/i18n/en.json tests/site_reference.test.mjs tests/test_site_build.py
git commit -m "Add searchable multi-model register reference"
```

---

### Task 5: Bezpieczne materiały marketingowe i dokumentacja

**Files:**
- Create: `site/assets/screenshots/sensors.png`
- Create: `site/assets/screenshots/controls.png`
- Create: `site/assets/screenshots/custom-sensors.png`
- Create: `site/assets/screenshots/catalog-sources.png`
- Modify: `site/index.html`
- Modify: `site/i18n/pl.json`
- Modify: `site/i18n/en.json`
- Modify: `README.md`
- Modify: `deye-solarman-diagnostics/README.md`
- Modify: `deye-solarman-diagnostics/DOCS.md`
- Modify: `catalogs/README.md`
- Modify: `catalogs/models/README.md`
- Modify: `tests/test_site_build.py`

**Interfaces:**
- Produces: cztery publiczne obrazy używane przez landing page.
- Produces: stabilne linki do strony i `/reference/` we wszystkich dokumentach wejściowych.

- [ ] **Step 1: Dodaj test zakazanych danych i wymaganych linków**

Rozszerz `tests/test_site_build.py`:

```python
	def test_public_text_does_not_contain_private_installation_values(self):
		forbidden=(
			"192.168.177.144",
			"3556142832",
			"2502092014",
			"/api/hassio_ingress/",
			"usb-FTDI_FT232R_USB_UART_BG02YHGK-if00-port0",
		)
		public_files=list((ROOT/"site").rglob("*.html"))+list((ROOT/"site/i18n").glob("*.json"))
		for path in public_files:
			content=path.read_text(encoding="utf-8")
			for value in forbidden:
				self.assertNotIn(value,content,path)

	def test_marketing_documents_link_to_site_and_reference(self):
		for relative in ("README.md","deye-solarman-diagnostics/README.md","deye-solarman-diagnostics/DOCS.md","catalogs/README.md"):
			content=(ROOT/relative).read_text(encoding="utf-8")
			self.assertIn("https://wilk33.github.io/deye-solarman-ha-addon/",content,relative)
			self.assertIn("https://wilk33.github.io/deye-solarman-ha-addon/reference/",content,relative)
```

- [ ] **Step 2: Przygotuj zanonimizowane obrazy**

Użyj narzędzia do edycji obrazu zgodnego z zasadami środowiska. Źródła:

```text
C:\Users\mskip\AppData\Local\Temp\codex-clipboard-c2862987-104f-4748-8eac-ce262557a755.png
C:\Users\mskip\AppData\Local\Temp\codex-clipboard-094cc98c-e930-4700-a3ec-c3b9d87048c6.png
C:\Users\mskip\AppData\Local\Temp\codex-clipboard-332c945d-a2c1-4cfc-ac8e-9d9096a511be.png
C:\Users\mskip\AppData\Local\Temp\codex-clipboard-858a4d82-6793-497d-b112-136c8d3957f3.png
```

Dla każdego obrazu:

- usuń cały lewy panel Home Assistant z avatarem;
- usuń górny pasek konta, jeżeli znajduje się w kadrze;
- zachowaj rzeczywisty interfejs dodatku bez syntetyzowania nowych wartości;
- nie publikuj pól tożsamości falownika ani danych transportu;
- zapisz tylko gotową kopię pod nazwą docelową;
- nie kopiuj źródła do repozytorium.

- [ ] **Step 3: Wykonaj wizualną kontrolę prywatności**

Otwórz każdy gotowy obraz w pełnej rozdzielczości i potwierdź brak adresu IP, numeru seryjnego, ścieżki urządzenia, tokenu Ingress, avatara i prywatnych logów. Jeżeli choć jeden element pozostaje widoczny, popraw obraz przed kolejnym krokiem.

- [ ] **Step 4: Dodaj galerię do landing page**

Użyj `figure`, `img`, `figcaption`, `loading="lazy"`, `decoding="async"` oraz tłumaczonych opisów alternatywnych. Nie ładuj wszystkich obrazów przed sekcją hero.

- [ ] **Step 5: Odśwież wejście marketingowe README**

Na początku `README.md` dodaj:

- jednozdaniową propozycję wartości;
- badge workflow walidacji;
- link `Strona projektu / Project site`;
- link `Definicje rejestrów / Register reference`;
- trzy krótkie filary: dwa transporty, niezależne katalogi, jedno MQTT;
- szybką instalację;
- galerię albo jeden reprezentatywny obraz;
- odnośniki do istniejących szczegółów technicznych.

Nie usuwaj granic walidacji sprzętowej ani opisu bezpiecznych zapisów.

- [ ] **Step 6: Zaktualizuj dokumentację katalogów**

W `catalogs/models/README.md` opisz wymagane `catalog-index.yaml`, opcjonalne `display_name`, `manufacturer`, `model_families` oraz automatyczne wykrywanie. W `catalogs/README.md` wyjaśnij, że publiczna przeglądarka jest generowana ze wszystkich poprawnych katalogów i że telemetria oraz sterowanie pozostają niezależne.

- [ ] **Step 7: Uruchom testy i build**

Run:

```powershell
.work/venv/Scripts/python.exe -m unittest tests.test_site_build tests.test_architecture -v
.work/venv/Scripts/python.exe tools/build_site.py --output .site-dist --base-path /deye-solarman-ha-addon/ --site-url https://wilk33.github.io/deye-solarman-ha-addon/
```

Expected: PASS, a galeria zawiera wyłącznie cztery gotowe kopie.

- [ ] **Step 8: Commit**

```powershell
git add site/assets/screenshots site/index.html site/i18n/pl.json site/i18n/en.json README.md deye-solarman-diagnostics/README.md deye-solarman-diagnostics/DOCS.md catalogs/README.md catalogs/models/README.md tests/test_site_build.py
git commit -m "Refresh project marketing and public documentation"
```

---

### Task 6: Walidacja CI i wdrożenie GitHub Pages

**Files:**
- Modify: `.github/workflows/validate.yml`
- Modify: `tests/test_architecture.py`

**Interfaces:**
- Consumes: CLI `tools/build_site.py` z zadania 2.
- Produces: artefakt `github-pages` z `.site-dist/`.
- Produces: job `deploy` zależny od `validate`, uruchamiany wyłącznie dla pushu do `main`.

- [ ] **Step 1: Napisz test kontraktu workflow**

Dodaj do `tests/test_architecture.py`:

```python
	def test_validation_workflow_builds_and_deploys_pages_after_validation(self):
		workflow=(ROOT/".github/workflows/validate.yml").read_text(encoding="utf-8")
		for required in (
			"python tools/build_site.py",
			"node --test tests/site_reference.test.mjs",
			"actions/configure-pages@v5",
			"actions/upload-pages-artifact@v4",
			"actions/deploy-pages@v4",
			"needs: validate",
			"environment:",
			"name: github-pages",
			"actions: read",
			"pages: write",
			"id-token: write",
		):
			self.assertIn(required,workflow,required)
```

- [ ] **Step 2: Uruchom test i potwierdź brak kroków Pages**

Run:

```powershell
.work/venv/Scripts/python.exe -m unittest tests.test_architecture.ArchitectureTests.test_validation_workflow_builds_and_deploys_pages_after_validation -v
```

Expected: FAIL na pierwszym brakującym wpisie.

- [ ] **Step 3: Rozszerz job `validate`**

Po istniejących testach dodaj kroki:

```yaml
      - run: node --check site/assets/app.mjs
      - run: node --check site/assets/reference.mjs
      - run: node --test tests/site_reference.test.mjs
      - run: python tools/build_site.py --output .site-dist --base-path /deye-solarman-ha-addon/ --site-url https://wilk33.github.io/deye-solarman-ha-addon/
      - name: Configure GitHub Pages
        if: github.event_name == 'push' && github.ref == 'refs/heads/main'
        uses: actions/configure-pages@v5
      - name: Upload GitHub Pages artifact
        if: github.event_name == 'push' && github.ref == 'refs/heads/main'
        uses: actions/upload-pages-artifact@v4
        with:
          path: .site-dist
```

W YAML użyj spacji, ponieważ tabulatory są niedozwolone przez składnię YAML.

- [ ] **Step 4: Dodaj job wdrożeniowy**

Dodaj:

```yaml
  deploy:
    if: github.event_name == 'push' && github.ref == 'refs/heads/main'
    needs: validate
    runs-on: ubuntu-latest
    permissions:
      contents: read
      actions: read
      pages: write
      id-token: write
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - name: Deploy GitHub Pages
        id: deployment
        uses: actions/deploy-pages@v4
```

Dodaj `workflow_dispatch` oraz concurrency dla grupy `pages-${{ github.ref }}` z `cancel-in-progress: true`.

- [ ] **Step 5: Uruchom pełną lokalną walidację workflow**

Run:

```powershell
.work/venv/Scripts/python.exe tools/package_addon.py --check
.work/venv/Scripts/python.exe -m unittest discover -s tests -v
.work/venv/Scripts/python.exe -W error::SyntaxWarning -m compileall -q packages apps/deye-solarman/src deye-solarman-diagnostics/rootfs/usr/src/app tools
node --check packages/deye_inverter_core/control_panel.js
node --check packages/deye_inverter_core/custom_panel.js
node --check packages/deye_inverter_core/panel.js
node --check site/assets/app.mjs
node --check site/assets/reference.mjs
node --test tests/site_reference.test.mjs
```

Expected: wszystkie komendy kończą się kodem 0.

- [ ] **Step 6: Commit**

```powershell
git add .github/workflows/validate.yml tests/test_architecture.py
git commit -m "Deploy validated reference site with GitHub Pages"
```

---

### Task 7: Dwie tury kontroli, publikacja i potwierdzenie działania

**Files:**
- Modify only when a significant or critical defect is found in the owning file.

**Interfaces:**
- Consumes: complete `.site-dist/` artifact and GitHub Actions workflow.
- Produces: successful public deployment at `https://wilk33.github.io/deye-solarman-ha-addon/`.

- [ ] **Step 1: Tura 1 - integralność, prywatność, bezpieczeństwo i wdrożenie**

Uruchom pełny zestaw z zadania 6 oraz:

```powershell
git diff --check
git status --short
```

Sprawdź krytyczne warunki:

- katalog z niezgodnym SHA zatrzymuje build;
- LF i CRLF dają tę samą sumę;
- ścieżka `../` jest odrzucana;
- dane zawierające `<script>` pozostają tekstem;
- `.site-dist/` nie zawiera oryginalnych zrzutów ani prywatnych wartości;
- artefakt ma wszystkie zasoby pod poprawnym prefiksem.

Napraw wyłącznie błąd istotny albo krytyczny, uruchom powiązany test i commituj poprawkę osobno.

- [ ] **Step 2: Uruchom lokalny serwer i kontrolę wizualną**

Zbuduj osobny artefakt lokalnego podglądu z prefiksem `/`, aby adresy zasobów odpowiadały katalogowi udostępnianemu przez prosty serwer HTTP:

```powershell
.work/venv/Scripts/python.exe tools/build_site.py --output .site-preview --base-path / --site-url http://127.0.0.1:8765/
```

Następnie uruchom serwer w ukrytym procesie:

```powershell
$server=Start-Process -FilePath ".work/venv/Scripts/python.exe" -ArgumentList "-m","http.server","8765","--directory",".site-preview" -WindowStyle Hidden -PassThru
```

Otwórz `http://127.0.0.1:8765/` przez dostępne narzędzie przeglądarki. Sprawdź stronę główną, `/reference/`, PL/EN, jasny i ciemny motyw, szerokość 1440 px oraz 390 px. Po kontroli zakończ wyłącznie proces wskazany przez `$server.Id`:

```powershell
Stop-Process -Id $server.Id
```

- [ ] **Step 3: Tura 2 - funkcje użytkownika i czytelność**

Sprawdź:

- wyszukiwanie po nazwie, kluczu, rejestrze i opcji enum;
- filtry typu, transportu, dostępu i dynamicznego zakresu;
- model z brakującą mapą w danych testowych;
- bezpośredni URL z query i hash po odświeżeniu;
- szczegóły `enum`, `bitmask`, maski, przesunięcia i zakresu obiektowego;
- klawiaturę, fokus, dialog i zamknięcie klawiszem Escape;
- układ mobilny bez poziomego przewijania;
- poprawność czterech publicznych obrazów.

Napraw wyłącznie błąd istotny albo krytyczny i powtór test właściciela.

- [ ] **Step 4: Skonfiguruj GitHub Pages jako workflow**

Najpierw sprawdź stan:

```powershell
gh api repos/Wilk33/deye-solarman-ha-addon/pages
```

Jeżeli endpoint zwróci 404, utwórz witrynę:

```powershell
gh api --method POST repos/Wilk33/deye-solarman-ha-addon/pages -f build_type=workflow
```

Jeżeli witryna istnieje z innym `build_type`, zaktualizuj ją:

```powershell
gh api --method PUT repos/Wilk33/deye-solarman-ha-addon/pages -f build_type=workflow
```

Expected: `build_type` ma wartość `workflow`.

- [ ] **Step 5: Sprawdź historię i wypchnij `main`**

```powershell
git status --short --branch
git log --oneline origin/main..HEAD
git push origin main
```

Expected: czysty katalog roboczy i poprawne wypchnięcie wszystkich commitów od specyfikacji do wdrożenia.

- [ ] **Step 6: Poczekaj na workflow i sprawdź wdrożenie**

```powershell
gh run list --workflow validate.yml --limit 1
gh run watch --exit-status
gh api repos/Wilk33/deye-solarman-ha-addon/pages
```

Otwórz publicznie:

```text
https://wilk33.github.io/deye-solarman-ha-addon/
https://wilk33.github.io/deye-solarman-ha-addon/reference/
```

Potwierdź kod HTTP 200, załadowanie `generated/models.json`, oba języki i bezpośredni link do `run_state`.

- [ ] **Step 7: Raport końcowy**

Podaj:

- publiczny adres strony;
- publiczny adres definicji;
- liczbę automatycznie wykrytych modeli;
- liczbę map i definicji wyliczoną z manifestu;
- wynik testów Python i JavaScript;
- adres udanego GitHub Actions run;
- listę plików odpowiedzialnych za generator, przeglądarkę i wdrożenie;
- ograniczenie, że witryna dokumentuje mapy, ale nie potwierdza fizycznych zapisów do falownika.

---

## Źródła wykonawcze

- Specyfikacja: `docs/superpowers/specs/2026-09-21-marketing-site-register-reference-design.md`
- [Sunsynk - Sensor definitions](https://kellerza.github.io/sunsynk/reference/definitions)
- [GitHub Docs - Using custom workflows with GitHub Pages](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)
- [GitHub Docs - REST API endpoints for GitHub Pages](https://docs.github.com/en/rest/pages/pages)
- [GitHub - actions/deploy-pages](https://github.com/actions/deploy-pages)
- [GitHub - actions/upload-pages-artifact](https://github.com/actions/upload-pages-artifact)
