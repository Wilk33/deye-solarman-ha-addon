from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from html import escape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from .custom_sensors import delete_custom_sensor
from .custom_sensors import load_custom_sensors
from .custom_sensors import save_custom_sensors
from .scanner import load_detected_sensors
from .scanner import update_detected_sensors
from .logging_utils import success


LOGGER=logging.getLogger(__name__)
MAX_REQUEST_BYTES=1_000_000
PANEL_SCRIPT=Path(__file__).with_name("panel.js").read_text(encoding="utf-8")
CUSTOM_PANEL_SCRIPT=Path(__file__).with_name("custom_panel.js").read_text(encoding="utf-8")


class IngressPanel:
	def __init__(
		self,
		detected_sensors_file: str,
		scan_handler: Callable[[], dict[str, Any]],
		reset_handler: Callable[[], dict[str, Any]] | None=None,
		clear_handler: Callable[[], dict[str, Any]] | None=None,
		configuration_changed_handler: Callable[[], None] | None=None,
		custom_sensors_file: str | None=None,
		custom_test_handler: Callable[[dict[str, Any]], dict[str, Any]] | None=None,
		custom_save_handler: Callable[[list[dict[str, Any]]], dict[str, Any]] | None=None,
		port: int=8099,
	) -> None:
		self._detected_sensors_file=detected_sensors_file
		self._scan_handler=scan_handler
		self._reset_handler=reset_handler
		self._clear_handler=clear_handler
		self._configuration_changed_handler=configuration_changed_handler
		self._custom_sensors_file=custom_sensors_file
		self._custom_test_handler=custom_test_handler
		self._custom_save_handler=custom_save_handler
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
		success(LOGGER,"Ingress configuration panel listening on port %s",self._port)

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
				self._log_request(path)
				if path in {"/","/index.html"}:
					self._send_html(PANEL_HTML.replace("__INGRESS_BASE__",self._ingress_base()))
					return
				if path == "/panel.js":
					self._send_script(PANEL_SCRIPT)
					return
				if path == "/custom-panel.js":
					self._send_script(CUSTOM_PANEL_SCRIPT)
					return
				if path == "/api/sensors":
					self._send_json(load_detected_sensors(panel._detected_sensors_file))
					return
				if path == "/api/scan-status":
					with panel._job_lock:
						self._send_json(dict(panel._job))
					return
				if path == "/api/custom-sensors":
					if panel._custom_sensors_file is None:
						self._send_json({"error": "Custom sensors are unavailable"},HTTPStatus.NOT_FOUND)
						return
					self._send_json(load_custom_sensors(panel._custom_sensors_file))
					return
				self._send_json({"error": "Not found"},HTTPStatus.NOT_FOUND)

			def do_POST(self) -> None:
				path=self.path.split("?",1)[0]
				self._log_request(path)
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
						panel._notify_configuration_changed()
						self._send_json(updated)
						return
					if path == "/api/reset":
						if panel._reset_handler is None:
							self._send_json({"error": "Reset is unavailable"},HTTPStatus.NOT_FOUND)
							return
						self._read_json()
						self._send_json(panel._run_configuration_action(panel._reset_handler))
						return
					if path == "/api/sensors/delete":
						if panel._clear_handler is None:
							self._send_json({"error": "Delete is unavailable"},HTTPStatus.NOT_FOUND)
							return
						self._read_json()
						self._send_json(panel._run_configuration_action(panel._clear_handler))
						return
					if path == "/api/custom-sensors":
						if panel._custom_sensors_file is None:
							self._send_json({"error": "Custom sensors are unavailable"},HTTPStatus.NOT_FOUND)
							return
						payload=self._read_json()
						entries=payload.get("sensors") if isinstance(payload,dict) else None
						if not isinstance(entries,list):
							raise ValueError("custom sensors must be a list")
						updated=(
							panel._custom_save_handler(entries)
							if panel._custom_save_handler is not None
							else save_custom_sensors(panel._custom_sensors_file,entries)
						)
						panel._notify_configuration_changed()
						self._send_json(updated)
						return
					if path == "/api/custom-sensors/test":
						if panel._custom_test_handler is None:
							self._send_json({"error": "Custom sensor test is unavailable"},HTTPStatus.NOT_FOUND)
							return
						payload=self._read_json()
						definition=payload.get("definition") if isinstance(payload,dict) else None
						if not isinstance(definition,dict):
							raise ValueError("Custom sensor definition must be an object")
						self._send_json(panel._custom_test_handler(definition))
						return
				except ValueError as error:
					self._send_json({"error": str(error)},HTTPStatus.BAD_REQUEST)
					return
				self._send_json({"error": "Not found"},HTTPStatus.NOT_FOUND)

			def do_DELETE(self) -> None:
				path=self.path.split("?",1)[0]
				self._log_request(path)
				if not path.startswith("/api/custom-sensors/") or panel._custom_sensors_file is None:
					self._send_json({"error": "Not found"},HTTPStatus.NOT_FOUND)
					return
				key=unquote(path.removeprefix("/api/custom-sensors/"))
				if not key or "/" in key:
					self._send_json({"error": "Invalid custom sensor key"},HTTPStatus.BAD_REQUEST)
					return
				try:
					updated=delete_custom_sensor(panel._custom_sensors_file,key)
					panel._notify_configuration_changed()
					self._send_json(updated)
				except ValueError as error:
					self._send_json({"error": str(error)},HTTPStatus.BAD_REQUEST)

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

			def _send_script(self, body: str) -> None:
				content=body.encode("utf-8")
				self.send_response(HTTPStatus.OK)
				self.send_header("Content-Type","application/javascript; charset=utf-8")
				self.send_header("Cache-Control","no-store")
				self.send_header("Content-Length",str(len(content)))
				self.end_headers()
				self.wfile.write(content)

			def _ingress_base(self) -> str:
				path=self.headers.get("X-Ingress-Path","").strip().rstrip("/")
				if not path.startswith("/api/hassio_ingress/"):
					path=""
				return escape(f"{path}/",quote=True)

			def _log_request(self, path: str) -> None:
				LOGGER.info(
					"Ingress request method=%s path=%s ingress_path=%s",
					self.command,
					path,
					self.headers.get("X-Ingress-Path","missing"),
				)

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
		self._notify_configuration_changed()

	def _run_configuration_action(self, handler: Callable[[], dict[str, Any]]) -> dict[str, Any]:
		with self._job_lock:
			if self._job["status"] == "running":
				raise ValueError("Poczekaj na zakonczenie aktualnego skanu")
			result=handler()
			self._notify_configuration_changed()
			return result

	def _notify_configuration_changed(self) -> None:
		if self._configuration_changed_handler is None:
			return
		self._configuration_changed_handler()
		LOGGER.info("Runtime configuration reload requested")


PANEL_HTML="""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<base href="__INGRESS_BASE__">
<title>Deye Solarman - Konfigurator encji</title>
<style>
:root {
  color-scheme: light;
  --ink: var(--primary-text-color, #212121);
  --muted: var(--secondary-text-color, #727272);
  --paper: var(--primary-background-color, #fafafa);
  --panel: var(--card-background-color, #ffffff);
  --line: var(--divider-color, #e0e0e0);
  --sun: var(--accent-color, var(--primary-color, #03a9f4));
  --solar: var(--primary-color, #03a9f4);
  --green: var(--success-color, var(--primary-color, #03a9f4));
  --red: var(--error-color, #db4437);
  --field: var(--input-fill-color, var(--secondary-background-color, #f5f5f5));
  --shadow: var(--ha-card-box-shadow, 0 2px 4px rgba(0, 0, 0, .18));
}
* { box-sizing: border-box; }
body {
  margin: 0;
  min-width: 320px;
  color: var(--ink);
  background: var(--paper);
  font-family: var(--paper-font-body1_-_font-family, Roboto, sans-serif);
}
button, input, textarea { font: inherit; }
button { cursor: pointer; }
.shell { max-width: 1480px; margin: 0 auto; padding: 34px 28px 64px; }
.masthead { display: flex; justify-content: space-between; gap: 24px; align-items: end; border-bottom: 2px solid var(--ink); padding-bottom: 22px; }
.eyebrow { margin: 0 0 8px; font-family: "Courier New", monospace; color: var(--solar); font-size: .78rem; letter-spacing: .12em; text-transform: uppercase; }
h1 { margin: 0; font-size: clamp(2rem, 5vw, 4.2rem); letter-spacing: -.055em; line-height: .92; }
.lede { max-width: 650px; margin: 15px 0 0; color: var(--muted); font-size: 1.05rem; line-height: 1.45; }
.status { min-width: 250px; border-left: 4px solid var(--sun); padding: 10px 0 10px 14px; font-family: "Courier New", monospace; font-size: .82rem; }
.status strong { display: block; margin-bottom: 5px; color: var(--green); }
.actions { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin: 25px 0 14px; }
.tabs { display: flex; gap: 8px; margin: 24px 0 0; border-bottom: 1px solid var(--line); }
.tab { border: 0; border-bottom: 3px solid transparent; background: transparent; color: var(--muted); padding: 11px 15px; font-weight: bold; }
.tab.active { border-bottom-color: var(--solar); color: var(--ink); }
.tab-panel[hidden] { display: none; }
.button { border: 1px solid var(--solar); border-radius: 4px; padding: 11px 16px; background: var(--solar); color: var(--text-primary-color, #fff); font-weight: bold; }
.button:hover { background: var(--green); }
.button.secondary { background: var(--panel); color: var(--ink); }
.button.danger { border-color: var(--red); background: var(--panel); color: var(--red); }
.button.danger:hover { background: var(--red); color: var(--panel); }
.button:disabled { opacity: .55; cursor: progress; }
#save-message { color: var(--green); font-family: "Courier New", monospace; font-size: .82rem; }
.summary { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 1px; background: var(--line); border: 1px solid var(--line); box-shadow: var(--shadow); }
.metric { background: var(--panel); min-height: 94px; padding: 15px; }
.metric b { display: block; font-family: "Courier New", monospace; font-size: 1.8rem; color: var(--solar); }
.metric span { color: var(--muted); font-size: .85rem; }
.filters { margin-top: 28px; display: grid; grid-template-columns: minmax(0, 1fr) 180px; gap: 12px; }
.filters input { width: 100%; border: 1px solid var(--line); background: var(--field); padding: 12px; color: var(--ink); }
#empty { margin: 32px 0; color: var(--muted); font-style: italic; }
.group { margin-top: 34px; }
.group-title { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 10px; font-size: 1.25rem; }
.group-title small { color: var(--muted); font-family: "Courier New", monospace; }
.sensor-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(330px, 1fr)); gap: 12px; }
.sensor { border: 1px solid var(--line); background: var(--panel); box-shadow: var(--shadow); }
.sensor.selected { border-left: 5px solid var(--green); }
.sensor-head { display: grid; grid-template-columns: 1fr auto; gap: 10px; padding: 15px; }
.sensor h3 { margin: 0; font-size: 1.05rem; }
.key { display: block; margin-top: 5px; color: var(--muted); font-family: "Courier New", monospace; font-size: .72rem; overflow-wrap: anywhere; }
.reading { margin-top: 13px; font-family: "Courier New", monospace; font-size: .9rem; line-height: 1.45; }
.reading b { color: var(--solar); }
.raw-line { display: flex; gap: 8px; align-items: baseline; overflow-wrap: anywhere; }
.raw-label { min-width: 38px; color: var(--muted); font-size: .68rem; font-weight: bold; }
.raw-line code { color: var(--ink); font: inherit; }
.raw-line.ascii code { color: var(--sun); letter-spacing: .04em; }
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
.field input { min-width: 0; border: 1px solid var(--line); background: var(--field); padding: 7px; color: var(--ink); font-family: "Courier New", monospace; font-size: .8rem; text-transform: none; }
.field.wide { grid-column: 1 / -1; }
.select-control { position: relative; min-width: 0; font-family: "Courier New", monospace; font-size: .8rem; text-transform: none; }
.select-trigger { display: flex; width: 100%; min-height: 34px; align-items: center; justify-content: space-between; gap: 8px; border: 1px solid var(--line); background: var(--field); color: var(--ink); padding: 7px; text-align: left; }
.filters .select-trigger { min-height: 44px; padding: 12px; font-family: inherit; font-size: 1rem; }
.select-trigger:hover, .select-control.open .select-trigger { border-color: var(--solar); }
.select-chevron { color: var(--solar); font-size: .9rem; transition: transform .15s ease; }
.select-control.open .select-chevron { transform: rotate(180deg); }
.select-options { position: absolute; z-index: 20; top: calc(100% + 4px); right: 0; left: 0; display: none; max-height: 230px; overflow-y: auto; border: 1px solid var(--solar); background: var(--panel); box-shadow: var(--shadow); }
.select-control.open .select-options { display: grid; }
.select-option { border: 0; border-bottom: 1px solid var(--line); background: var(--panel); color: var(--ink); padding: 9px; text-align: left; font: inherit; }
.select-option:last-child { border-bottom: 0; }
.select-option:hover, .select-option:focus-visible, .select-option.selected { background: var(--solar); color: var(--text-primary-color, #fff); outline: 0; }
.sensor.select-open { position: relative; z-index: 4; }
.notice { margin-top: 34px; border-top: 1px solid var(--line); padding-top: 15px; color: var(--muted); line-height: 1.5; }
.custom-intro { margin: 24px 0 8px; max-width: 760px; color: var(--muted); line-height: 1.5; }
.custom-actions { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin: 22px 0; }
.custom-actions div { display: flex; flex-wrap: wrap; gap: 10px; }
.custom-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(360px, 1fr)); gap: 12px; }
.custom-sensor { position: relative; border: 1px solid var(--line); background: var(--panel); box-shadow: var(--shadow); }
.custom-sensor.enabled { border-left: 5px solid var(--green); }
.custom-sensor .sensor-head { padding-bottom: 9px; }
.custom-sensor .fields { padding: 0 15px 15px; }
.custom-sensor .field textarea { min-height: 148px; width: 100%; resize: vertical; border: 1px solid var(--line); background: var(--field); color: var(--ink); padding: 8px; font: .8rem/1.45 "Courier New", monospace; text-transform: none; white-space: pre; overflow: auto; }
.formula-toolbar { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; grid-column: 1 / -1; }
.formula-toolbar .button { padding: 7px 10px; font-size: .75rem; }
.test-result { grid-column: 1 / -1; margin: 0; max-height: 260px; overflow: auto; border: 1px solid var(--line); background: var(--field); color: var(--ink); padding: 10px; font: .75rem/1.45 "Courier New", monospace; white-space: pre-wrap; }
.test-result.error { border-color: var(--red); color: var(--red); }
.formula-modal[hidden] { display: none; }
.formula-modal { position: fixed; z-index: 100; inset: 0; display: grid; place-items: center; padding: 22px; background: rgba(0,0,0,.62); }
.formula-dialog { display: grid; grid-template-rows: auto minmax(0,1fr) auto auto; width: min(1040px,100%); height: min(760px,100%); border: 1px solid var(--line); background: var(--panel); box-shadow: var(--shadow); }
.formula-dialog header, .formula-dialog footer { display: flex; justify-content: space-between; align-items: center; gap: 12px; padding: 14px; border-bottom: 1px solid var(--line); }
.formula-dialog footer { border-top: 1px solid var(--line); border-bottom: 0; justify-content: flex-end; }
.formula-dialog h2 { margin: 0; font-size: 1.1rem; }
.formula-dialog textarea { min-height: 0; width: 100%; height: 100%; border: 0; background: var(--field); color: var(--ink); padding: 16px; resize: none; font: .9rem/1.55 "Courier New", monospace; white-space: pre; overflow: auto; }
@media (max-width: 760px) {
  .shell { padding: 22px 16px 44px; }
  .masthead { display: block; }
  .status { margin-top: 22px; }
  .summary { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .filters { grid-template-columns: 1fr; }
  .custom-actions { align-items: flex-start; flex-direction: column; }
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

  <nav class="tabs" aria-label="Pulpity konfiguracji">
    <button class="tab active" type="button" data-tab="detected">Wykryte sensory</button>
    <button class="tab" type="button" data-tab="custom">Wlasne sensory</button>
  </nav>

  <section id="detected-tab" class="tab-panel">
  <section class="actions">
    <button class="button" id="scan-button" type="button">Skanuj teraz</button>
    <button class="button secondary" id="reset-button" type="button">Reset konfiguracji</button>
    <button class="button danger" id="delete-button" type="button">Usun sensory</button>
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
    <div class="select-control" data-select-control>
      <input id="status-filter" type="hidden" value="all">
      <button class="select-trigger" type="button" data-select-trigger aria-haspopup="listbox" aria-expanded="false"><span class="select-value">Wszystkie statusy</span><span class="select-chevron">&#9662;</span></button>
      <div class="select-options" role="listbox"><button class="select-option selected" type="button" data-select-option data-value="all">Wszystkie statusy</button><button class="select-option" type="button" data-select-option data-value="supported">Supported</button><button class="select-option" type="button" data-select-option data-value="unsupported">Unsupported</button><button class="select-option" type="button" data-select-option data-value="timeout">Timeout</button><button class="select-option" type="button" data-select-option data-value="invalid_value">Invalid value</button></div>
    </div>
  </section>
  <p id="empty" hidden>Brak danych skanu. Uzyj Skanuj teraz po skonfigurowaniu polaczenia loggera w zakladce Konfiguracja dodatku.</p>
  <section id="sensor-groups"></section>
  <p class="notice"><b>Zastosowanie zmian:</b> zapis aktualizuje trwaly plik wyboru. Dodatek automatycznie przeladowuje tylko polaczenia Solarman i MQTT oraz odczyt wybranych czujnikow. Wiersz ASCII pokazuje dwa znaki z kazdego rejestru, a znaki niedrukowalne jako kropki. Poprawny odczyt BMS potwierdza dostep transportowy, ale niekoniecznie znaczenie rejestru.</p>
  </section>

  <section id="custom-tab" class="tab-panel" hidden>
    <p class="custom-intro">Dodaj zwykly sensor Modbus lub wlacz <b>Wlasna formula</b>, aby lokalnie odczytywac rejestry przez <code>sensor(...)</code> i <code>RAW(...)</code>. Zapis automatycznie przeladowuje tylko odczyt oraz MQTT.</p>
    <section class="custom-actions">
      <div><button class="button" id="custom-add-button" type="button">+ Dodaj sensor</button><button class="button secondary" id="custom-save-button" type="button">Zapisz wlasne sensory</button></div>
      <span id="custom-save-message"></span>
    </section>
    <section id="custom-sensor-list" class="custom-grid"></section>
    <p id="custom-empty" hidden>Nie utworzono jeszcze wlasnych sensorow. Uzyj przycisku + Dodaj sensor.</p>
  </section>
</main>
<section id="formula-modal" class="formula-modal" hidden aria-modal="true" role="dialog" aria-label="Edytor formuly">
  <div class="formula-dialog">
    <header><div><h2 id="formula-modal-title">Formula</h2><span id="formula-modal-key" class="key"></span></div><button class="button secondary" id="formula-minimize-button" type="button">Minimalizuj</button></header>
    <textarea id="formula-modal-editor" spellcheck="false" aria-label="Formula"></textarea>
    <pre id="formula-modal-result" class="test-result" hidden></pre>
    <footer><button class="button secondary" id="formula-modal-test-button" type="button">Test formuly</button><button class="button" id="formula-apply-button" type="button">Zastosuj</button></footer>
  </div>
</section>
<script src="panel.js"></script>
<script>
let sensors=[];
let scanTimer=null;
const editable=["name","multiplier","offset","unit","type","word_order","schedule","read_every","report_every","change_by","retain","device_class","state_class","icon","category","topic_suffix"];
const esc=value=>String(value ?? "").replace(/[&<>'"]/g,char=>{
  if (char.charCodeAt(0) === 34) return "&quot;";
  return {"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;"}[char];
});
const numberValue=value=>Number.isFinite(Number(value)) ? Number(value) : "";
const byId=id=>document.getElementById(id);
const haThemeVariables=["--primary-background-color","--secondary-background-color","--card-background-color","--primary-text-color","--secondary-text-color","--divider-color","--primary-color","--accent-color","--error-color","--success-color","--input-fill-color","--ha-card-box-shadow","--text-primary-color","--paper-font-body1_-_font-family"];
let themeSynchronized=false;

console.info("[Deye Solarman] panel script started",{href:window.location.href,base:document.baseURI});
window.addEventListener("error",event=>console.error("[Deye Solarman] browser error",event.error || event.message));
window.addEventListener("unhandledrejection",event=>console.error("[Deye Solarman] unhandled promise rejection",event.reason));

function themeIsDark(color) {
  const probe=document.createElement("span");
  probe.style.color=color;
  document.body.append(probe);
  const match=getComputedStyle(probe).color.match(/[0-9]+/g);
  probe.remove();
  if (!match || match.length < 3) return false;
  const [red,green,blue]=match.map(Number);
  return red*0.2126+green*0.7152+blue*0.0722 < 140;
}

function syncHomeAssistantTheme() {
  try {
    if (window.parent === window) return;
    const parentDocument=window.parent.document;
    const sources=[parentDocument.querySelector("home-assistant"),parentDocument.documentElement,parentDocument.body].filter(Boolean);
    let background="";
    let copied=0;
    for (const variable of haThemeVariables) {
      for (const source of sources) {
        const value=window.parent.getComputedStyle(source).getPropertyValue(variable).trim();
        if (!value) continue;
        document.documentElement.style.setProperty(variable,value);
        if (variable === "--primary-background-color") background=value;
        copied+=1;
        break;
      }
    }
    if (background) document.documentElement.style.colorScheme=themeIsDark(background) ? "dark" : "light";
    if (copied && !themeSynchronized) {
      console.info("[Deye Solarman] Home Assistant theme synchronized",{variables:copied,dark:themeIsDark(background)});
      themeSynchronized=true;
    }
  } catch (error) {
    if (!themeSynchronized) console.info("[Deye Solarman] Home Assistant theme unavailable",error.message);
  }
}

function installHomeAssistantThemeSync() {
  syncHomeAssistantTheme();
  try {
    const observer=new MutationObserver(syncHomeAssistantTheme);
    observer.observe(window.parent.document.documentElement,{attributes:true,subtree:true,attributeFilter:["class","style","data-theme"]});
  } catch (error) {
    console.info("[Deye Solarman] Theme change observer unavailable",error.message);
  }
  window.setInterval(syncHomeAssistantTheme,10000);
}

async function request(path,options={}) {
  const url=new URL(path,document.baseURI).toString();
  console.info("[Deye Solarman] API request",{path,url,method:options.method || "GET"});
  const response=await fetch(url,{headers:{"Content-Type":"application/json"},...options});
  console.info("[Deye Solarman] API response",{url,status:response.status});
  const data=await response.json();
  if (!response.ok) throw new Error(data.error || "Request failed");
  return data;
}

function statusBadge(status) { return `<span class="badge ${esc(status)}">${esc(status || "not_scanned")}</span>`; }
function input(key,field,label,value,type="text",wide=false) {
  return `<label class="field ${wide ? "wide" : ""}">${label}<input data-field="${esc(field)}" data-key="${esc(key)}" type="${type}" value="${esc(value)}"></label>`;
}
function select(key,field,label,current,values) {
	const selected=values.includes(current) ? current : values[0];
	return `<label class="field">${label}<div class="select-control" data-select-control><input data-field="${esc(field)}" data-key="${esc(key)}" type="hidden" value="${esc(selected)}"><button class="select-trigger" type="button" data-select-trigger aria-haspopup="listbox" aria-expanded="false"><span class="select-value">${esc(selected)}</span><span class="select-chevron">&#9662;</span></button><div class="select-options" role="listbox">${values.map(value=>`<button class="select-option ${value === selected ? "selected" : ""}" type="button" data-select-option data-value="${esc(value)}">${esc(value)}</button>`).join("")}</div></div></label>`;
}

function asciiFromRaw(registers) {
	if (!Array.isArray(registers) || !registers.length) return "";
	return registers.flatMap(register=>[(register >> 8)&255,register&255]).map(byte=>byte >= 32 && byte <= 126 ? String.fromCharCode(byte) : ".").join("");
}

function sensorCard(entry) {
  const definition=entry.definition || {};
  const scan=entry.last_scan || {};
  const value=scan.value === null || scan.value === undefined ? "-" : `${esc(scan.value)} ${esc(definition.unit)}`;
  const raw=(scan.raw_hex || []).join(", ") || "-";
  const rawAscii=scan.raw_ascii || asciiFromRaw(scan.raw_registers) || "-";
  return `<article class="sensor ${entry.monitor ? "selected" : ""}" data-sensor="${esc(entry.key)}">
    <div class="sensor-head">
      <div><h3>${esc(definition.name || entry.key)}</h3><span class="key">${esc(entry.key)} / R${esc((definition.registers || []).join(","))}</span>
        <div class="reading"><b>${value}</b><div class="raw-line"><span class="raw-label">HEX</span><code>${esc(raw)}</code></div><div class="raw-line ascii"><span class="raw-label">ASCII</span><code>${esc(rawAscii)}</code></div></div>
        <div class="badges">${statusBadge(scan.status)}<span class="badge ${esc(scan.verification)}">${esc(scan.verification || "unknown")}</span><span class="badge">${esc(definition.type)}</span></div>
      </div>
      <label class="toggle"><input data-monitor="${esc(entry.key)}" type="checkbox" ${entry.monitor ? "checked" : ""}> MQTT</label>
    </div>
    <details><summary>Konfiguruj dekodowanie i odpytywanie</summary><div class="fields">
      ${input(entry.key,"name","Nazwa",definition.name,"text",true)}
      ${input(entry.key,"multiplier","Mnoznik",definition.multiplier,"number")}
      ${input(entry.key,"offset","Offset",definition.offset,"number")}
      ${input(entry.key,"unit","Jednostka",definition.unit)}
      ${select(entry.key,"type","Typ rejestru",definition.type,["uint16","int16","uint32","int32","hex","ascii"])}
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

function closeSelectControls(except=null) {
  for (const control of document.querySelectorAll("[data-select-control].open")) {
    if (control === except) continue;
    control.classList.remove("open");
    control.querySelector("[data-select-trigger]").setAttribute("aria-expanded","false");
    control.closest(".sensor")?.classList.remove("select-open");
  }
}

function chooseSelectOption(option) {
  const control=option.closest("[data-select-control]");
  const input=control.querySelector("input");
  input.value=option.dataset.value || "";
  control.querySelector(".select-value").textContent=option.textContent;
  for (const candidate of control.querySelectorAll("[data-select-option]")) candidate.classList.toggle("selected",candidate === option);
  closeSelectControls();
  input.dispatchEvent(new Event("change",{bubbles:true}));
}

document.addEventListener("click",event=>{
  const option=event.target.closest("[data-select-option]");
  if (option) {
    chooseSelectOption(option);
    return;
  }
  const trigger=event.target.closest("[data-select-trigger]");
  if (!trigger) {
    closeSelectControls();
    return;
  }
  const control=trigger.closest("[data-select-control]");
  const opening=!control.classList.contains("open");
  closeSelectControls(control);
  control.classList.toggle("open",opening);
  trigger.setAttribute("aria-expanded",String(opening));
  control.closest(".sensor")?.classList.toggle("select-open",opening);
});

document.addEventListener("keydown",event=>{
  if (event.key === "Escape") closeSelectControls();
});

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
    message.style.color="var(--green)";
    message.textContent="Zapisano. Polaczenia Solarman i MQTT zostaly automatycznie przeladowane.";
    render();
  } catch (error) { message.textContent=`Blad zapisu: ${error.message}`; message.style.color="var(--red)"; }
}

async function resetConfiguration() {
  if (!window.confirm("Przywrocic domyslne ustawienia katalogowe dla znalezionych czujnikow? Wszystkie wyboru MQTT zostana wylaczone.")) return;
  const message=byId("save-message");
  try {
    const payload=await request("api/reset",{method:"POST",body:"{}"});
    sensors=payload.available_sensors || [];
    message.style.color="var(--green)";
    message.textContent="Przywrocono domyslna konfiguracje. Poprzednie encje MQTT Discovery zostana automatycznie usuniete.";
    render();
  } catch (error) { message.style.color="var(--red)"; message.textContent=`Blad resetu: ${error.message}`; }
}

async function deleteSensors() {
  if (!window.confirm("Usunac lokalna liste znalezionych czujnikow i ich konfiguracje? Katalog rejestrow zostanie odswiezony z GitHub.")) return;
  const message=byId("save-message");
  try {
    const payload=await request("api/sensors/delete",{method:"POST",body:"{}"});
    sensors=payload.available_sensors || [];
    message.style.color="var(--green)";
    message.textContent="Usunieto lokalna liste. Katalog zostal odswiezony, a poprzednie encje MQTT Discovery zostana automatycznie usuniete. Uruchom skan, aby utworzyc nowa liste.";
    render();
  } catch (error) { message.style.color="var(--red)"; message.textContent=`Blad usuwania: ${error.message}`; }
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
  console.info("[Deye Solarman] Scan now clicked");
  byId("save-message").textContent="";
  try { await request("api/scan",{method:"POST",body:"{}"}); await refreshScanStatus(); }
  catch (error) { byId("scan-message").textContent=error.message; }
});
byId("save-button").addEventListener("click",save);
byId("reset-button").addEventListener("click",resetConfiguration);
byId("delete-button").addEventListener("click",deleteSensors);
byId("search").addEventListener("input",render);
byId("status-filter").addEventListener("change",render);
installHomeAssistantThemeSync();
Promise.all([loadSensors(),refreshScanStatus()]).catch(error=>{
  console.error("[Deye Solarman] panel initialization failed",error);
  byId("scan-message").textContent=error.message;
});
</script>
<script src="custom-panel.js"></script>
</body>
</html>
"""
