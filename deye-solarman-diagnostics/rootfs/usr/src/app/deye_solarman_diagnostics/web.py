from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer
from typing import Any

from .scanner import load_detected_sensors
from .scanner import update_detected_sensors


LOGGER=logging.getLogger(__name__)
MAX_REQUEST_BYTES=1_000_000


class IngressPanel:
	def __init__(
		self,
		detected_sensors_file: str,
		scan_handler: Callable[[], dict[str, Any]],
		port: int=8099,
	) -> None:
		self._detected_sensors_file=detected_sensors_file
		self._scan_handler=scan_handler
		self._port=port
		self._job_lock=threading.Lock()
		self._job={
			"status": "idle",
			"message": "Nie uruchomiono jeszcze skanu z tego panelu.",
			"result": None,
		}
		self._server: ThreadingHTTPServer | None=None
		self._thread: threading.Thread | None=None

	def start(self) -> None:
		if self._server is not None:
			return
		handler=self._build_handler()
		server=ThreadingHTTPServer(("0.0.0.0",self._port),handler)
		server.daemon_threads=True
		self._server=server
		self._thread=threading.Thread(
			target=server.serve_forever,
			name="deye-solarman-ingress",
			daemon=True,
		)
		self._thread.start()
		LOGGER.info("Ingress configuration panel listening on port %s",self._port)

	def stop(self) -> None:
		if self._server is None:
			return
		self._server.shutdown()
		self._server.server_close()
		self._server=None
		self._thread=None

	def _build_handler(self) -> type[BaseHTTPRequestHandler]:
		panel=self

		class PanelHandler(BaseHTTPRequestHandler):
			def do_GET(self) -> None:
				path=self.path.split("?",1)[0]
				if path in {"/","/index.html"}:
					self._send_html(PANEL_HTML)
					return
				if path == "/api/sensors":
					self._send_json(load_detected_sensors(panel._detected_sensors_file))
					return
				if path == "/api/scan-status":
					with panel._job_lock:
						self._send_json(dict(panel._job))
					return
				self._send_json({"error": "Not found"},HTTPStatus.NOT_FOUND)

			def do_POST(self) -> None:
				path=self.path.split("?",1)[0]
				try:
					if path == "/api/scan":
						if not panel._start_scan():
							self._send_json({"error": "A scan is already running"},HTTPStatus.CONFLICT)
							return
						self._send_json({"status": "started"},HTTPStatus.ACCEPTED)
						return
					if path == "/api/sensors":
						payload=self._read_json()
						updates=payload.get("sensors") if isinstance(payload,dict) else None
						if not isinstance(updates,list):
							raise ValueError("sensors must be a list")
						updated=update_detected_sensors(panel._detected_sensors_file,updates)
						self._send_json(updated)
						return
				except ValueError as error:
					self._send_json({"error": str(error)},HTTPStatus.BAD_REQUEST)
					return
				self._send_json({"error": "Not found"},HTTPStatus.NOT_FOUND)

			def log_message(self, format: str, *args: Any) -> None:
				LOGGER.debug("Ingress request: "+format,*args)

			def _read_json(self) -> Any:
				content_length=self.headers.get("Content-Length")
				if content_length is None:
					raise ValueError("Content-Length is required")
				try:
					length=int(content_length)
				except ValueError as error:
					raise ValueError("Invalid Content-Length") from error
				if length < 0 or length > MAX_REQUEST_BYTES:
					raise ValueError("Request body is too large")
				try:
					return json.loads(self.rfile.read(length).decode("utf-8"))
				except (UnicodeDecodeError,json.JSONDecodeError) as error:
					raise ValueError("Request body must be valid JSON") from error

			def _send_json(self, payload: Any, status: HTTPStatus=HTTPStatus.OK) -> None:
				body=json.dumps(payload,ensure_ascii=True).encode("utf-8")
				self.send_response(status)
				self.send_header("Content-Type","application/json; charset=utf-8")
				self.send_header("Cache-Control","no-store")
				self.send_header("Content-Length",str(len(body)))
				self.end_headers()
				self.wfile.write(body)

			def _send_html(self, body: str) -> None:
				content=body.encode("utf-8")
				self.send_response(HTTPStatus.OK)
				self.send_header("Content-Type","text/html; charset=utf-8")
				self.send_header("Cache-Control","no-store")
				self.send_header("Content-Length",str(len(content)))
				self.end_headers()
				self.wfile.write(content)

		return PanelHandler

	def _start_scan(self) -> bool:
		with self._job_lock:
			if self._job["status"] == "running":
				return False
			self._job={
				"status": "running",
				"message": "Laczenie z loggerem Solarman i skanowanie kandydatow.",
				"result": None,
			}
		threading.Thread(target=self._run_scan,name="deye-solarman-scan",daemon=True).start()
		return True

	def _run_scan(self) -> None:
		try:
			result=self._scan_handler()
		except Exception as error:
			LOGGER.exception("Ingress scan failed")
			with self._job_lock:
				self._job={
					"status": "failed",
					"message": str(error),
					"result": None,
				}
			return
		with self._job_lock:
			self._job={
				"status": "completed",
				"message": "Skan zakonczony. Wybierz wartosci do publikacji i zapisz konfiguracje.",
				"result": result,
			}


PANEL_HTML="""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Deye Solarman - Konfigurator encji</title>
<style>
:root {
  color-scheme: light;
  --ink: #16231f;
  --muted: #5f7168;
  --paper: #f5f0e6;
  --panel: #fffdf8;
  --line: #c9c0ad;
  --sun: #e8a719;
  --solar: #cf6c22;
  --green: #17644e;
  --red: #a54332;
  --shadow: 0 18px 55px rgba(45, 44, 32, .14);
}
* { box-sizing: border-box; }
body {
  margin: 0;
  min-width: 320px;
  color: var(--ink);
  background:
    radial-gradient(circle at 10% 0%, rgba(232, 167, 25, .22), transparent 30rem),
    linear-gradient(135deg, #ebe4d4, var(--paper) 46%, #e6eee5);
  font-family: Georgia, "Times New Roman", serif;
}
button, input, select { font: inherit; }
button { cursor: pointer; }
.shell { max-width: 1480px; margin: 0 auto; padding: 34px 28px 64px; }
.masthead { display: flex; justify-content: space-between; gap: 24px; align-items: end; border-bottom: 2px solid var(--ink); padding-bottom: 22px; }
.eyebrow { margin: 0 0 8px; font-family: "Courier New", monospace; color: var(--solar); font-size: .78rem; letter-spacing: .12em; text-transform: uppercase; }
h1 { margin: 0; font-size: clamp(2rem, 5vw, 4.2rem); letter-spacing: -.055em; line-height: .92; }
.lede { max-width: 650px; margin: 15px 0 0; color: var(--muted); font-size: 1.05rem; line-height: 1.45; }
.status { min-width: 250px; border-left: 4px solid var(--sun); padding: 10px 0 10px 14px; font-family: "Courier New", monospace; font-size: .82rem; }
.status strong { display: block; margin-bottom: 5px; color: var(--green); }
.actions { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin: 25px 0 14px; }
.button { border: 1px solid var(--ink); border-radius: 0; padding: 11px 16px; background: var(--ink); color: #fffdf8; font-weight: bold; }
.button:hover { background: var(--green); }
.button.secondary { background: var(--panel); color: var(--ink); }
.button:disabled { opacity: .55; cursor: progress; }
#save-message { color: var(--green); font-family: "Courier New", monospace; font-size: .82rem; }
.summary { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 1px; background: var(--line); border: 1px solid var(--line); box-shadow: var(--shadow); }
.metric { background: var(--panel); min-height: 94px; padding: 15px; }
.metric b { display: block; font-family: "Courier New", monospace; font-size: 1.8rem; color: var(--solar); }
.metric span { color: var(--muted); font-size: .85rem; }
.filters { margin-top: 28px; display: grid; grid-template-columns: minmax(0, 1fr) 180px; gap: 12px; }
.filters input, .filters select { width: 100%; border: 1px solid var(--line); background: rgba(255,253,248,.82); padding: 12px; color: var(--ink); }
#empty { margin: 32px 0; color: var(--muted); font-style: italic; }
.group { margin-top: 34px; }
.group-title { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 10px; font-size: 1.25rem; }
.group-title small { color: var(--muted); font-family: "Courier New", monospace; }
.sensor-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(330px, 1fr)); gap: 12px; }
.sensor { border: 1px solid var(--line); background: rgba(255,253,248,.93); box-shadow: 0 5px 19px rgba(45,44,32,.07); }
.sensor.selected { border-left: 5px solid var(--green); }
.sensor-head { display: grid; grid-template-columns: 1fr auto; gap: 10px; padding: 15px; }
.sensor h3 { margin: 0; font-size: 1.05rem; }
.key { display: block; margin-top: 5px; color: var(--muted); font-family: "Courier New", monospace; font-size: .72rem; overflow-wrap: anywhere; }
.reading { margin-top: 13px; font-family: "Courier New", monospace; font-size: .9rem; }
.reading b { color: var(--solar); }
.badges { display: flex; gap: 5px; flex-wrap: wrap; margin-top: 11px; }
.badge { padding: 3px 6px; border: 1px solid var(--line); color: var(--muted); font-family: "Courier New", monospace; font-size: .66rem; text-transform: uppercase; }
.badge.supported, .badge.verified_local { border-color: var(--green); color: var(--green); }
.badge.timeout, .badge.unsupported, .badge.invalid_value { border-color: var(--red); color: var(--red); }
.toggle { display: inline-flex; gap: 7px; align-items: center; white-space: nowrap; font-family: "Courier New", monospace; font-size: .72rem; }
.toggle input { accent-color: var(--green); width: 18px; height: 18px; }
details { border-top: 1px solid var(--line); padding: 0 15px 14px; }
summary { padding: 11px 0; color: var(--green); cursor: pointer; font-family: "Courier New", monospace; font-size: .75rem; }
.fields { display: grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap: 9px; }
.field { display: grid; gap: 4px; color: var(--muted); font-family: "Courier New", monospace; font-size: .68rem; text-transform: uppercase; }
.field input, .field select { min-width: 0; border: 1px solid var(--line); background: #fffdf8; padding: 7px; color: var(--ink); font-family: "Courier New", monospace; font-size: .8rem; text-transform: none; }
.field.wide { grid-column: 1 / -1; }
.notice { margin-top: 34px; border-top: 1px solid var(--line); padding-top: 15px; color: var(--muted); line-height: 1.5; }
@media (max-width: 760px) {
  .shell { padding: 22px 16px 44px; }
  .masthead { display: block; }
  .status { margin-top: 22px; }
  .summary { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .filters { grid-template-columns: 1fr; }
}
</style>
</head>
<body>
<main class="shell">
  <header class="masthead">
    <div>
      <p class="eyebrow">Home Assistant Ingress / local Solarman TCP</p>
      <h1>Konfigurator encji</h1>
      <p class="lede">Skanuj tylko-do-odczytu telemetrie Deye, porownaj zwrocone wartosci i wybierz dokladnie to, co Home Assistant ma otrzymywac przez MQTT.</p>
    </div>
    <div class="status"><strong id="scan-state">Ladowanie panelu</strong><span id="scan-message">Odczyt zapisanego wyniku skanu.</span></div>
  </header>

  <section class="actions">
    <button class="button" id="scan-button" type="button">Skanuj teraz</button>
    <button class="button secondary" id="save-button" type="button">Zapisz wybor MQTT</button>
    <span id="save-message"></span>
  </section>

  <section class="summary" aria-label="Scan summary">
    <div class="metric"><b id="count-total">0</b><span>dostepnych kandydatow</span></div>
    <div class="metric"><b id="count-supported">0</b><span>poprawnych odpowiedzi</span></div>
    <div class="metric"><b id="count-selected">0</b><span>wybranych do MQTT</span></div>
    <div class="metric"><b id="count-other">0</b><span>niedostepnych lub blednych</span></div>
  </section>

  <section class="filters">
    <input id="search" type="search" placeholder="Filtruj po nazwie, kluczu, kategorii, rejestrze lub jednostce">
    <select id="status-filter"><option value="all">Wszystkie statusy</option><option value="supported">Supported</option><option value="unsupported">Unsupported</option><option value="timeout">Timeout</option><option value="invalid_value">Invalid value</option></select>
  </section>
  <p id="empty" hidden>Brak danych skanu. Uzyj Skanuj teraz po skonfigurowaniu polaczenia loggera w zakladce Konfiguracja dodatku.</p>
  <section id="sensor-groups"></section>
  <p class="notice"><b>Zastosowanie zmian:</b> zapis aktualizuje trwaly plik wyboru. Po zapisie zrestartuj dodatek w Home Assistant, aby petla MQTT zaladowala wybrane czujniki. Poprawny odczyt BMS potwierdza dostep transportowy, ale niekoniecznie znaczenie rejestru.</p>
</main>
<script>
let sensors=[];
let scanTimer=null;
const editable=["name","multiplier","offset","unit","type","word_order","schedule","read_every","report_every","change_by","retain","device_class","state_class","icon","category","topic_suffix"];
const esc=value=>String(value ?? "").replace(/[&<>'"]/g,char=>({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;","\"":"&quot;"}[char]));
const numberValue=value=>Number.isFinite(Number(value)) ? Number(value) : "";
const byId=id=>document.getElementById(id);

async function request(path,options={}) {
  const response=await fetch(path,{headers:{"Content-Type":"application/json"},...options});
  const data=await response.json();
  if (!response.ok) throw new Error(data.error || "Request failed");
  return data;
}

function statusBadge(status) { return `<span class="badge ${esc(status)}">${esc(status || "not_scanned")}</span>`; }
function option(value,current) { return `<option value="${esc(value)}"${value === current ? " selected" : ""}>${esc(value)}</option>`; }
function input(key,field,label,value,type="text",wide=false) {
  return `<label class="field ${wide ? "wide" : ""}">${label}<input data-field="${esc(field)}" data-key="${esc(key)}" type="${type}" value="${esc(value)}"></label>`;
}
function select(key,field,label,current,values) {
  return `<label class="field">${label}<select data-field="${esc(field)}" data-key="${esc(key)}">${values.map(value=>option(value,current)).join("")}</select></label>`;
}

function sensorCard(entry) {
  const definition=entry.definition || {};
  const scan=entry.last_scan || {};
  const value=scan.value === null || scan.value === undefined ? "-" : `${esc(scan.value)} ${esc(definition.unit)}`;
  const raw=(scan.raw_hex || []).join(", ") || "-";
  return `<article class="sensor ${entry.monitor ? "selected" : ""}" data-sensor="${esc(entry.key)}">
    <div class="sensor-head">
      <div><h3>${esc(definition.name || entry.key)}</h3><span class="key">${esc(entry.key)} / R${esc((definition.registers || []).join(","))}</span>
        <div class="reading"><b>${value}</b><br><span>RAW ${esc(raw)}</span></div>
        <div class="badges">${statusBadge(scan.status)}<span class="badge ${esc(scan.verification)}">${esc(scan.verification || "unknown")}</span><span class="badge">${esc(definition.type)}</span></div>
      </div>
      <label class="toggle"><input data-monitor="${esc(entry.key)}" type="checkbox" ${entry.monitor ? "checked" : ""}> MQTT</label>
    </div>
    <details><summary>Konfiguruj dekodowanie i odpytywanie</summary><div class="fields">
      ${input(entry.key,"name","Nazwa",definition.name,"text",true)}
      ${input(entry.key,"multiplier","Mnoznik",definition.multiplier,"number")}
      ${input(entry.key,"offset","Offset",definition.offset,"number")}
      ${input(entry.key,"unit","Jednostka",definition.unit)}
      ${select(entry.key,"type","Typ rejestru",definition.type,["uint16","int16","uint32","int32","hex"])}
      ${select(entry.key,"word_order","Kolejnosc slow",definition.word_order,["high_low","low_high"])}
      ${select(entry.key,"schedule","Harmonogram",definition.schedule,["default","slow"])}
      ${input(entry.key,"read_every","Odczyt co sekundy",definition.read_every,"number")}
      ${input(entry.key,"report_every","Ponowna publikacja co sekundy",definition.report_every,"number")}
      ${input(entry.key,"change_by","Prog zmiany",definition.change_by,"number")}
      ${input(entry.key,"device_class","Klasa urzadzenia HA",definition.device_class)}
      ${input(entry.key,"state_class","Klasa stanu HA",definition.state_class)}
      ${input(entry.key,"icon","Ikona",definition.icon)}
      ${input(entry.key,"category","Kategoria",definition.category)}
      ${input(entry.key,"topic_suffix","Sufiks MQTT",definition.topic_suffix,"text",true)}
      <label class="toggle"><input data-field="retain" data-key="${esc(entry.key)}" type="checkbox" ${definition.retain ? "checked" : ""}> Zachowaj stan MQTT</label>
    </div></details>
  </article>`;
}

function render() {
  const search=byId("search").value.trim().toLowerCase();
  const wantedStatus=byId("status-filter").value;
  const filtered=sensors.filter(entry=>{
    const definition=entry.definition || {};
    const text=[entry.key,definition.name,definition.category,definition.unit,(definition.registers || []).join(",")].join(" ").toLowerCase();
    return (!search || text.includes(search)) && (wantedStatus === "all" || entry.last_scan?.status === wantedStatus);
  });
  const groups=new Map();
  for (const entry of filtered) {
    const category=entry.definition?.category || "other";
    if (!groups.has(category)) groups.set(category,[]);
    groups.get(category).push(entry);
  }
  byId("sensor-groups").innerHTML=[...groups.entries()].sort(([a],[b])=>a.localeCompare(b)).map(([category,items])=>`<section class="group"><div class="group-title"><b>${esc(category)}</b><small>${items.length} entries</small></div><div class="sensor-grid">${items.map(sensorCard).join("")}</div></section>`).join("");
  byId("empty").hidden=sensors.length !== 0;
  byId("count-total").textContent=sensors.length;
  byId("count-supported").textContent=sensors.filter(entry=>entry.last_scan?.status === "supported").length;
  byId("count-selected").textContent=sensors.filter(entry=>entry.monitor).length;
  byId("count-other").textContent=sensors.filter(entry=>entry.last_scan?.status && entry.last_scan.status !== "supported").length;
}

async function loadSensors() {
  const payload=await request("api/sensors");
  sensors=payload.available_sensors || [];
  render();
}

function collectUpdates() {
  return sensors.map(entry=>{
    const key=entry.key;
    const definition={};
    for (const field of editable) {
      const control=document.querySelector(`[data-field="${field}"][data-key="${CSS.escape(key)}"]`);
      if (!control) continue;
      definition[field]=field === "retain" ? control.checked : control.value;
    }
    for (const field of ["multiplier","offset","read_every","report_every","change_by"]) definition[field]=numberValue(definition[field]);
    return {key,monitor:document.querySelector(`[data-monitor="${CSS.escape(key)}"]`).checked,definition};
  });
}

async function save() {
  const message=byId("save-message");
  try {
    const payload=await request("api/sensors",{method:"POST",body:JSON.stringify({sensors:collectUpdates()})});
    sensors=payload.available_sensors || [];
    message.textContent="Zapisano. Zrestartuj dodatek, aby zastosowac zmiany odpytywania MQTT.";
    render();
  } catch (error) { message.textContent=`Blad zapisu: ${error.message}`; message.style.color="var(--red)"; }
}

async function refreshScanStatus() {
  const job=await request("api/scan-status");
  byId("scan-state").textContent=job.status.toUpperCase();
  byId("scan-message").textContent=job.message;
  const button=byId("scan-button");
  button.disabled=job.status === "running";
  if (job.status === "running") {
    if (!scanTimer) scanTimer=setInterval(refreshScanStatus,2000);
    return;
  }
  if (scanTimer) { clearInterval(scanTimer); scanTimer=null; }
  if (job.status === "completed") await loadSensors();
}

byId("scan-button").addEventListener("click",async()=>{
  byId("save-message").textContent="";
  try { await request("api/scan",{method:"POST",body:"{}"}); await refreshScanStatus(); }
  catch (error) { byId("scan-message").textContent=error.message; }
});
byId("save-button").addEventListener("click",save);
byId("search").addEventListener("input",render);
byId("status-filter").addEventListener("change",render);
Promise.all([loadSensors(),refreshScanStatus()]).catch(error=>{ byId("scan-message").textContent=error.message; });
</script>
</body>
</html>
"""
