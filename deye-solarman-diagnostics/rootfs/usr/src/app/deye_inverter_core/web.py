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
from urllib.parse import parse_qs
from urllib.parse import unquote
from urllib.parse import urlsplit

from .custom_sensors import delete_custom_sensor
from .custom_sensors import load_custom_sensors
from .custom_sensors import save_custom_sensors
from .configuration_coordinator import ConfigurationCoordinator
from .scanner import load_detected_sensors
from .scanner import update_detected_sensors
from .logging_utils import success


LOGGER=logging.getLogger(__name__)
MAX_REQUEST_BYTES=1_000_000
PANEL_SCRIPT=Path(__file__).with_name("panel.js").read_text(encoding="utf-8")
CUSTOM_PANEL_SCRIPT=Path(__file__).with_name("custom_panel.js").read_text(encoding="utf-8")
CONTROL_PANEL_SCRIPT=Path(__file__).with_name("control_panel.js").read_text(encoding="utf-8")
I18N_DIRECTORY=Path(__file__).with_name("i18n")
I18N_TRANSLATIONS={
	language:json.loads((I18N_DIRECTORY/f"{language}.json").read_text(encoding="utf-8"))
	for language in ("pl","en")
}
TRANSPORT_IDS=("solarman_tcp","modbus_rtu")


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
		control_service: Any=None,
		configuration_coordinator: ConfigurationCoordinator | None=None,
		transport_status_handler: Callable[[], dict[str,Any]] | None=None,
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
		self._controls=control_service
		self._transport_status_handler=transport_status_handler
		tracked=[Path(detected_sensors_file)]
		tracked.append(Path(detected_sensors_file).with_name("deye_solarman_discovery_removals.yaml"))
		if custom_sensors_file is not None:
			tracked.append(Path(custom_sensors_file))
			tracked.append(Path(custom_sensors_file).with_name("deye_solarman_discovery_removals.yaml"))
		if control_service is not None:
			tracked.append(control_service.path)
		self._configuration=configuration_coordinator or ConfigurationCoordinator(tracked)
		if self._controls is not None:
			self._controls.configuration_coordinator=self._configuration
			self._controls.configuration_action=self._configuration.apply
		self._job_lock=threading.Lock()
		self._job={
			"status": "idle",
			"message": "Nie uruchomiono jeszcze skanu z tego panelu.",
			"message_key": "scan.idle",
			"result": None,
		}
		self._server: ThreadingHTTPServer | None=None
		self._thread: threading.Thread | None=None
		self._scan_thread: threading.Thread | None=None

	def start(self) -> None:
		if self._server is not None:
			return
		handler=self._build_handler()
		server=ThreadingHTTPServer(("0.0.0.0",self._port),handler)
		server.daemon_threads=False
		self._server=server
		self._thread=threading.Thread(
			target=server.serve_forever,
			name="deye-solarman-ingress",
			daemon=True,
		)
		self._thread.start()
		success(LOGGER,"Ingress configuration panel listening on port %s",self._port)

	def stop(self) -> None:
		server=self._server
		server_thread=self._thread
		if server is not None:
			server.shutdown()
			server.server_close()
		if server_thread is not None and server_thread is not threading.current_thread():
			server_thread.join()
		scan_thread=self._scan_thread
		if scan_thread is not None and scan_thread is not threading.current_thread():
			scan_thread.join()
		if self._controls is not None:
			self._controls.wait_for_idle()
		self._server=None
		self._thread=None
		self._scan_thread=None

	def _build_handler(self) -> type[BaseHTTPRequestHandler]:
		panel=self

		class PanelHandler(BaseHTTPRequestHandler):
			def do_GET(self) -> None:
				self._get()

			def _get(self) -> None:
				path=urlsplit(self.path).path
				self._log_request(path)
				if path in {"/","/index.html"}:
					language=self._requested_language()
					body=PANEL_HTML.replace("__INGRESS_BASE__",self._ingress_base())
					body=body.replace("__DOCUMENT_LANGUAGE__",language or "pl").replace("__PANEL_LANGUAGE__",language)
					self._send_html(body)
					return
				if path.startswith("/api/i18n/"):
					requested=unquote(path.removeprefix("/api/i18n/"))
					if not requested or "/" in requested or "\\" in requested or requested in {".",".."}:
						self._send_json({"error":"Not found"},HTTPStatus.NOT_FOUND)
						return
					language=panel._normalize_language(requested)
					self._send_json({"language":language,"translations":I18N_TRANSLATIONS[language]})
					return
				if path == "/api/runtime":
					payload=panel._transport_status_handler() if panel._transport_status_handler is not None else {"transports":[]}
					self._send_json(payload)
					return
				if path == "/panel.js":
					self._send_script(PANEL_SCRIPT)
					return
				if path == "/control-panel.js":
					self._send_script(CONTROL_PANEL_SCRIPT)
					return
				if path in {"/api/controls","/api/controls/scan-status"} and panel._controls is not None:
					if path == "/api/controls":
						self._send_json(panel._view(panel._controls.load,controls=True))
					else:
						with panel._controls.lock:
							self._send_json(dict(panel._controls.job))
					return
				if path == "/custom-panel.js":
					self._send_script(CUSTOM_PANEL_SCRIPT)
					return
				if path == "/api/sensors":
					self._send_json(panel._view(lambda:load_detected_sensors(panel._detected_sensors_file)))
					return
				if path == "/api/scan-status":
					with panel._job_lock:
						self._send_json(dict(panel._job))
					return
				if path == "/api/custom-sensors":
					if panel._custom_sensors_file is None:
						self._send_json({"error": "Custom sensors are unavailable"},HTTPStatus.NOT_FOUND)
						return
					self._send_json(panel._view(lambda:load_custom_sensors(panel._custom_sensors_file),field="sensors"))
					return
				self._send_json({"error": "Not found"},HTTPStatus.NOT_FOUND)

			def do_POST(self) -> None:
				path=self.path.split("?",1)[0]
				self._log_request(path)
				try:
					if path.startswith("/api/controls") and panel._controls is not None:
						payload=self._read_json()
						if not isinstance(payload,dict):
							raise ValueError("Expected JSON object")
						if path == "/api/controls/scan":
							if not panel._controls.start_scan(panel._notify_configuration_changed):
								self._send_json({"error":"Scan already running"},HTTPStatus.CONFLICT)
							else:
								self._send_json({"status":"started"},HTTPStatus.ACCEPTED)
							return
						if path == "/api/controls/test":
							self._send_json(panel._controls.test(payload.get("key","")))
							return
						if path == "/api/controls":
							result=panel._configuration_action(lambda:panel._controls.update(payload.get("sensors")))
						elif path in {"/api/controls/reset","/api/controls/delete"}:
							result=panel._configuration_action(lambda:panel._controls.reset(clear=path.endswith("/delete")))
						else:
							self._send_json({"error":"Not found"},HTTPStatus.NOT_FOUND)
							return
						panel._notify_configuration_changed()
						self._send_json(panel._view(lambda:result,controls=True))
						return
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
						updated=panel._configuration_action(lambda:update_detected_sensors(panel._detected_sensors_file,updates))
						panel._notify_configuration_changed()
						self._send_json(panel._view(lambda:updated))
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
						updated=panel._configuration_action(lambda:(
							panel._custom_save_handler(entries)
							if panel._custom_save_handler is not None
							else save_custom_sensors(panel._custom_sensors_file,entries)
						))
						panel._notify_configuration_changed()
						self._send_json(panel._view(lambda:updated,field="sensors"))
						return
					if path == "/api/custom-sensors/test":
						if panel._custom_test_handler is None:
							self._send_json({"error": "Custom sensor test is unavailable"},HTTPStatus.NOT_FOUND)
							return
						payload=self._read_json()
						definition=payload.get("definition") if isinstance(payload,dict) else None
						if not isinstance(definition,dict):
							raise ValueError("Custom sensor definition must be an object")
						requested=payload.get("transports") if isinstance(payload,dict) else None
						if requested is None:
							self._send_json(panel._custom_test_handler(definition))
							return
						if not isinstance(requested,list) or not requested:
							raise ValueError("transports must be a non-empty list")
						allowed=definition.get("transports") or [definition.get("transport","solarman_tcp")]
						if len(set(requested)) != len(requested) or any(item not in TRANSPORT_IDS or item not in allowed for item in requested):
							raise ValueError("Requested custom sensor transport is not allowed")
						results=[]
						for transport in TRANSPORT_IDS:
							if transport not in requested:
								continue
							transport_definition={**definition,"transport":transport}
							try:
								result=panel._custom_test_handler(transport_definition)
								results.append({**result,"transport":transport,"status":"supported"})
							except Exception as error:
								results.append({"transport":transport,"status":"timeout","error":str(error)})
						self._send_json({"results":results})
						return
				except ValueError as error:
					self._send_json({"error": str(error)},HTTPStatus.BAD_REQUEST)
					return
				except Exception as error:
					LOGGER.exception("Ingress operation failed")
					self._send_json({"error":str(error)},HTTPStatus.BAD_GATEWAY)
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
					updated=panel._configuration_action(lambda:delete_custom_sensor(panel._custom_sensors_file,key))
					panel._notify_configuration_changed()
					self._send_json(panel._view(lambda:updated,field="sensors"))
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

			def _requested_language(self) -> str:
				query=parse_qs(urlsplit(self.path).query)
				for key in ("language","lang"):
					if query.get(key):
						return panel._normalize_language(query[key][0])
				for header in ("X-Home-Assistant-Language","X-Hass-Language","Accept-Language"):
					value=self.headers.get(header)
					if value:
						return panel._normalize_language(value)
				return ""

			def _log_request(self, path: str) -> None:
				LOGGER.info(
					"Ingress request method=%s path=%s ingress_path=%s",
					self.command,
					path,
					self.headers.get("X-Ingress-Path","missing"),
				)

		return PanelHandler

	@staticmethod
	def _normalize_language(value: str) -> str:
		primary=str(value).strip().lower().split(",",1)[0].split(";",1)[0].split("-",1)[0]
		return "en" if primary == "en" else "pl"

	def _start_scan(self) -> bool:
		with self._job_lock:
			if self._job["status"] == "running":
				return False
			self._job={
				"status": "running",
				"message": "Laczenie z loggerem Solarman i skanowanie kandydatow.",
				"message_key": "scan.running",
				"result": None,
			}
		thread=threading.Thread(target=self._run_scan,name="deye-solarman-scan")
		self._scan_thread=thread
		thread.start()
		return True

	def _run_scan(self) -> None:
		try:
			result=self._configuration.apply(self._scan_handler)
		except Exception as error:
			LOGGER.exception("Ingress scan failed")
			with self._job_lock:
				self._job={
					"status": "failed",
					"message": str(error),
					"message_key": None,
					"result": None,
				}
			return
		with self._job_lock:
			self._job={
				"status": "completed",
				"message": "Skan zakonczony. Wybierz wartosci do publikacji i zapisz konfiguracje.",
				"message_key": "scan.completed",
				"result": result,
			}
		self._notify_configuration_changed()

	def _run_configuration_action(self, handler: Callable[[], dict[str, Any]]) -> dict[str, Any]:
		with self._job_lock:
			if self._job["status"] == "running":
				raise ValueError("Poczekaj na zakonczenie aktualnego skanu")
			result=self._configuration_action(handler)
			self._notify_configuration_changed()
			return result

	def _configuration_action(self, action):
		return self._configuration.apply(action)

	def _view(self, loader, field="available_sensors", controls=False):
		with self._configuration.locked():
			return loader()

	def _notify_configuration_changed(self) -> None:
		if self._configuration_changed_handler is None:
			return
		self._configuration_changed_handler()
		LOGGER.info("Runtime configuration reload requested")


PANEL_HTML="""<!doctype html>
<html lang="__DOCUMENT_LANGUAGE__" data-language="__PANEL_LANGUAGE__">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<base href="__INGRESS_BASE__">
<title>SolarMan Diagnostics</title>
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
.status { min-width: 300px; border-left: 4px solid var(--sun); padding: 10px 0 10px 14px; font-family: "Courier New", monospace; font-size: .82rem; }
.status strong { display: block; margin-bottom: 5px; color: var(--green); }
.runtime-title { margin-top: 12px; color: var(--muted); text-transform: uppercase; }
.runtime-transports { display: grid; gap: 7px; margin-top: 7px; }
.runtime-transport { display: grid; gap: 2px; border-top: 1px solid var(--line); padding-top: 6px; }
.runtime-transport strong { margin: 0; }
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
.sensor-list-surface { margin-top: 28px; border: 1px solid var(--line); background: var(--panel); padding: 0 12px 12px; box-shadow: var(--shadow); }
.sensor-list-surface .group:first-child { margin-top: 12px; }
.sensor-list-surface .sensor { background: var(--field); }
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
.badge.supported, .badge.verified_local, .badge.online { border-color: var(--green); color: var(--green); }
.badge.timeout, .badge.unsupported, .badge.invalid_value, .badge.offline { border-color: var(--red); color: var(--red); }
.toggle { display: inline-flex; gap: 7px; align-items: center; white-space: nowrap; font-family: "Courier New", monospace; font-size: .72rem; }
.toggle input { accent-color: var(--green); width: 18px; height: 18px; }
details { border-top: 1px solid var(--line); padding: 0 15px 14px; }
summary { padding: 11px 0; color: var(--green); cursor: pointer; font-family: "Courier New", monospace; font-size: .75rem; }
.fields { display: grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap: 9px; }
.field { display: grid; gap: 4px; color: var(--muted); font-family: "Courier New", monospace; font-size: .68rem; text-transform: uppercase; }
.field input, .field select { min-width: 0; border: 1px solid var(--line); background: var(--field); padding: 7px; color: var(--ink); font-family: "Courier New", monospace; font-size: .8rem; text-transform: none; }
.field.wide { grid-column: 1 / -1; }
.transport-results { display: grid; grid-template-columns: repeat(auto-fit,minmax(220px,1fr)); gap: 8px; padding: 0 15px 15px; }
.transport-result { display: grid; gap: 5px; border: 1px solid var(--line); background: var(--field); padding: 9px; font: .72rem/1.4 "Courier New", monospace; }
.transport-result header { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.transport-result.supported { border-color: var(--green); }
.transport-error { color: var(--red); overflow-wrap: anywhere; }
.select-control { position: relative; min-width: 0; font-family: "Courier New", monospace; font-size: .8rem; text-transform: none; }
.select-trigger { display: flex; width: 100%; min-height: 34px; align-items: center; justify-content: space-between; gap: 8px; border: 1px solid var(--line); background: var(--field); color: var(--ink); padding: 7px; text-align: left; }
.filters .select-trigger { min-height: 44px; padding: 12px; font-family: inherit; font-size: 1rem; }
.select-trigger:hover, .select-control.open .select-trigger { border-color: var(--solar); }
.select-trigger:disabled { cursor: not-allowed; opacity: .65; }
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
      <p class="eyebrow" data-i18n="app.eyebrow">Home Assistant Ingress / diagnostyka transportów</p>
      <h1 data-i18n="app.heading">Konfigurator encji</h1>
      <p class="lede" data-i18n="app.lede">Odczytaj stan falownika Deye, porównaj oba transporty i wybierz sensory oraz encje sterowania udostępniane w Home Assistant przez MQTT.</p>
    </div>
    <div class="status"><strong id="scan-state" data-i18n="scan.loading">Ladowanie panelu</strong><span id="scan-message" data-i18n="scan.loading_message">Odczyt zapisanego wyniku skanu.</span><strong class="runtime-title" data-i18n="runtime.title">Aktywne transporty</strong><div id="transport-status-list" class="runtime-transports"></div></div>
  </header>

  <nav class="tabs" aria-label="Pulpity konfiguracji">
    <button class="tab active" type="button" data-tab="detected" data-i18n="tabs.sensors">Sensory</button>
    <button class="tab" type="button" data-tab="control" data-i18n="tabs.controls">Sterowanie</button>
    <button class="tab" type="button" data-tab="custom" data-i18n="tabs.custom">Własne sensory</button>
  </nav>

  <section id="detected-tab" class="tab-panel">
  <section class="actions">
    <button class="button" id="scan-button" type="button" data-i18n="actions.scan">Skanuj teraz</button>
    <button class="button secondary" id="reset-button" type="button" data-i18n="actions.reset">Reset konfiguracji</button>
    <button class="button danger" id="delete-button" type="button" data-i18n="actions.delete_sensors">Usun sensory</button>
    <button class="button secondary" id="save-button" type="button" data-i18n="actions.save_mqtt">Zapisz wybor MQTT</button>
    <span id="save-message"></span>
  </section>

  <section class="summary" aria-label="Scan summary">
    <div class="metric"><b id="count-total">0</b><span data-i18n="summary.candidates">dostepnych kandydatow</span></div>
    <div class="metric"><b id="count-supported">0</b><span data-i18n="summary.supported">poprawnych odpowiedzi</span></div>
    <div class="metric"><b id="count-selected">0</b><span data-i18n="summary.selected">wybranych do MQTT</span></div>
    <div class="metric"><b id="count-other">0</b><span data-i18n="summary.other">niedostepnych lub blednych</span></div>
  </section>

  <section class="filters">
    <input id="search" type="search" placeholder="Filtruj po nazwie, kluczu, kategorii, rejestrze lub jednostce" data-i18n-placeholder="filters.sensor_search">
    <div class="select-control" data-select-control>
      <input id="status-filter" type="hidden" value="all">
      <button class="select-trigger" type="button" data-select-trigger aria-haspopup="listbox" aria-expanded="false"><span class="select-value" data-i18n="filters.all">Wszystkie statusy</span><span class="select-chevron">&#9662;</span></button>
      <div class="select-options" role="listbox"><button class="select-option selected" type="button" data-select-option data-value="all" data-i18n="filters.all">Wszystkie statusy</button><button class="select-option" type="button" data-select-option data-value="supported" data-i18n="status.supported">Supported</button><button class="select-option" type="button" data-select-option data-value="unsupported" data-i18n="status.unsupported">Unsupported</button><button class="select-option" type="button" data-select-option data-value="timeout" data-i18n="status.timeout">Timeout</button><button class="select-option" type="button" data-select-option data-value="invalid_value" data-i18n="status.invalid_value">Invalid value</button></div>
    </div>
  </section>
  <p id="empty" hidden data-i18n="sensors.empty">Brak danych skanu. Uzyj Skanuj teraz po skonfigurowaniu polaczenia loggera w zakladce Konfiguracja dodatku.</p>
  <section id="sensor-groups" class="sensor-list-surface"></section>
  <p class="notice" data-i18n="sensors.notice">Zapis aktualizuje trwaly plik wyboru. Dodatek automatycznie przeladowuje odczyt i MQTT. Poprawny odczyt potwierdza dostep transportowy, ale niekoniecznie znaczenie rejestru.</p>
  </section>

  <section id="custom-tab" class="tab-panel" hidden>
    <p class="custom-intro" data-i18n="custom.intro">Dodaj zwykly sensor Modbus lub wlacz Wlasna formule, aby lokalnie odczytywac rejestry przez sensor(...) i RAW(...). Test zawsze tylko odczytuje rejestry.</p>
    <section class="custom-actions">
      <div><button class="button" id="custom-add-button" type="button" data-i18n="actions.add_sensor">+ Dodaj sensor</button><button class="button secondary" id="custom-save-button" type="button" data-i18n="actions.save_custom">Zapisz wlasne sensory</button></div>
      <span id="custom-save-message"></span>
    </section>
    <section id="custom-sensor-list" class="custom-grid"></section>
    <p id="custom-empty" hidden data-i18n="custom.empty">Nie utworzono jeszcze wlasnych sensorow. Uzyj przycisku + Dodaj sensor.</p>
  </section>
  <section id="control-tab" class="tab-panel" hidden>
    <p class="custom-intro" data-i18n="controls.intro">Skan pobiera aktualny stan. Zaznaczenie MQTT udostępnia sterowanie wybraną encją w Home Assistant. Pola UNKNOWN i niepotwierdzone definicje mają zablokowany zapis.</p>
    <section class="actions">
      <button class="button" id="control-scan" type="button" data-i18n="actions.scan">Skanuj teraz</button>
      <button class="button secondary" id="control-reset" type="button" data-i18n="actions.reset">Reset konfiguracji</button>
      <button class="button danger" id="control-delete" type="button" data-i18n="actions.delete_controls">Usuń encje</button>
      <button class="button secondary" id="control-save" type="button" data-i18n="actions.save_mqtt">Zapisz wybór MQTT</button>
      <span id="control-message" role="status"></span>
    </section>
    <section class="summary">
      <div class="metric"><b id="control-total">0</b><span data-i18n="summary.controls">encji sterowania</span></div>
      <div class="metric"><b id="control-supported">0</b><span data-i18n="summary.supported">poprawnych odpowiedzi</span></div>
      <div class="metric"><b id="control-selected">0</b><span data-i18n="summary.selected">wybranych do MQTT</span></div>
      <div class="metric"><b id="control-other">0</b><span data-i18n="summary.other">niedostępnych lub błędnych</span></div>
    </section>
    <section class="filters">
      <input id="control-search" type="search" placeholder="Filtruj po nazwie, kluczu, rejestrze lub metodzie sterowania" data-i18n-placeholder="filters.control_search">
      <div class="select-control" data-select-control>
        <input id="control-filter" type="hidden" value="all">
        <button class="select-trigger" type="button" data-select-trigger aria-haspopup="listbox" aria-expanded="false"><span class="select-value" data-i18n="filters.all">Wszystkie statusy</span><span class="select-chevron">&#9662;</span></button>
        <div class="select-options" role="listbox"><button class="select-option selected" type="button" data-select-option data-value="all" data-i18n="filters.all">Wszystkie statusy</button><button class="select-option" type="button" data-select-option data-value="supported" data-i18n="status.supported">Supported</button><button class="select-option" type="button" data-select-option data-value="unknown" data-i18n="status.unknown">UNKNOWN</button><button class="select-option" type="button" data-select-option data-value="timeout" data-i18n="status.timeout">Timeout</button><button class="select-option" type="button" data-select-option data-value="invalid_value" data-i18n="status.invalid_value">Invalid value</button></div>
      </div>
    </section>
    <p id="control-empty" data-i18n="controls.empty">Brak danych skanu. Użyj Skanuj teraz.</p>
    <section id="control-groups"></section>
  </section>
</main>
<section id="formula-modal" class="formula-modal" hidden aria-modal="true" role="dialog" aria-label="Edytor formuly" data-i18n-aria-label="common.formula_editor">
  <div class="formula-dialog">
    <header><div><h2 id="formula-modal-title" data-i18n="common.formula">Formula</h2><span id="formula-modal-key" class="key"></span></div><button class="button secondary" id="formula-minimize-button" type="button" data-i18n="actions.minimize">Minimalizuj</button></header>
    <textarea id="formula-modal-editor" spellcheck="false" aria-label="Formula"></textarea>
    <pre id="formula-modal-result" class="test-result" hidden></pre>
    <footer><button class="button secondary" id="formula-modal-test-button" type="button" data-i18n="actions.test_formula">Test formuly</button><button class="button" id="formula-apply-button" type="button" data-i18n="actions.apply">Zastosuj</button></footer>
  </div>
</section>
<script src="panel.js"></script>
<script>
let sensors=[];
let scanTimer=null;
let runtimeTimer=null;
const editable=["name","multiplier","offset","unit","type","word_order","byte_order","schedule","read_every","report_every","change_by","retain","device_class","state_class","icon","category","topic_suffix","transport"];
const esc=value=>String(value ?? "").replace(/[&<>'"]/g,char=>{
  if (char.charCodeAt(0) === 34) return "&quot;";
  return {"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;"}[char];
});
const numberValue=value=>Number.isFinite(Number(value)) ? Number(value) : "";
const byId=id=>document.getElementById(id);
const haThemeVariables=["--primary-background-color","--secondary-background-color","--card-background-color","--primary-text-color","--secondary-text-color","--divider-color","--primary-color","--accent-color","--error-color","--success-color","--input-fill-color","--ha-card-box-shadow","--text-primary-color","--paper-font-body1_-_font-family"];
let themeSynchronized=false;

console.info("[SolarMan Diagnostics] panel script started",{href:window.location.href,base:document.baseURI});
window.addEventListener("error",event=>console.error("[SolarMan Diagnostics] browser error",event.error || event.message));
window.addEventListener("unhandledrejection",event=>console.error("[SolarMan Diagnostics] unhandled promise rejection",event.reason));

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
      console.info("[SolarMan Diagnostics] Home Assistant theme synchronized",{variables:copied,dark:themeIsDark(background)});
      themeSynchronized=true;
    }
  } catch (error) {
    if (!themeSynchronized) console.info("[SolarMan Diagnostics] Home Assistant theme unavailable",error.message);
  }
}

function installHomeAssistantThemeSync() {
  syncHomeAssistantTheme();
  try {
    const observer=new MutationObserver(syncHomeAssistantTheme);
    observer.observe(window.parent.document.documentElement,{attributes:true,subtree:true,attributeFilter:["class","style","data-theme"]});
  } catch (error) {
    console.info("[SolarMan Diagnostics] Theme change observer unavailable",error.message);
  }
  window.setInterval(syncHomeAssistantTheme,10000);
}

async function request(path,options={}) {
  const url=new URL(path,document.baseURI).toString();
  console.info("[SolarMan Diagnostics] API request",{path,url,method:options.method || "GET"});
  const response=await fetch(url,{headers:{"Content-Type":"application/json"},...options});
  console.info("[SolarMan Diagnostics] API response",{url,status:response.status});
  const data=await response.json();
  if (!response.ok) throw new Error(data.error || "Request failed");
  return data;
}

function statusBadge(status) { const value=status || "not_scanned"; return `<span class="badge ${esc(value)}">${esc(t(`status.${value}`))}</span>`; }
function input(key,field,label,value,type="text",wide=false) {
  return `<label class="field ${wide ? "wide" : ""}">${label}<input data-field="${esc(field)}" data-key="${esc(key)}" type="${type}" value="${esc(value)}"></label>`;
}
function select(key,field,label,current,values) {
	const selected=values.includes(current) ? current : values[0];
	return `<label class="field">${label}<div class="select-control" data-select-control><input data-field="${esc(field)}" data-key="${esc(key)}" type="hidden" value="${esc(selected)}"><button class="select-trigger" type="button" data-select-trigger aria-haspopup="listbox" aria-expanded="false"><span class="select-value">${esc(selected)}</span><span class="select-chevron">&#9662;</span></button><div class="select-options" role="listbox">${values.map(value=>`<button class="select-option ${value === selected ? "selected" : ""}" type="button" data-select-option data-value="${esc(value)}">${esc(value)}</button>`).join("")}</div></div></label>`;
}

function asciiFromRaw(registers,byteOrder="high_low") {
	if (!Array.isArray(registers) || !registers.length) return "";
	return registers.flatMap(register=>{
		const bytes=[(register >> 8)&255,register&255];
		return byteOrder === "low_high" ? bytes.reverse() : bytes;
	}).map(byte=>byte >= 32 && byte <= 126 ? String.fromCharCode(byte) : ".").join("");
}

function sensorCard(entry) {
  const definition=entry.definition || {};
  const supported=transportBranches(entry).filter(([,result])=>result.status === "supported");
  return `<article class="sensor ${entry.monitor ? "selected" : ""}" data-sensor="${esc(entry.key)}">
    <div class="sensor-head">
      <div><h3>${esc(definition.name || entry.key)}</h3><span class="key">${esc(entry.key)} / R${esc((definition.registers || []).join(","))}</span>
        <div class="badges"><span class="badge">${esc(definition.type)}</span></div>
      </div>
      <label class="toggle"><input data-monitor="${esc(entry.key)}" type="checkbox" ${entry.monitor ? "checked" : ""} ${supported.length ? "" : "disabled"}> ${esc(t("common.mqtt"))}</label>
    </div>
    ${transportResultCards(entry)}
    <details><summary>${esc(t("sensors.configure"))}</summary><div class="fields">
      ${transportSelector(entry)}
      ${input(entry.key,"name",t("common.name"),definition.name,"text",true)}
      ${input(entry.key,"multiplier",t("common.multiplier"),definition.multiplier,"number")}
      ${input(entry.key,"offset",t("common.offset"),definition.offset,"number")}
      ${input(entry.key,"unit",t("common.unit"),definition.unit)}
      ${select(entry.key,"type",t("common.register_type"),definition.type,definition.formula ? ["auto"] : ["uint16","int16","uint32","int32","hex","ascii","enum","bitmask"])}
      ${select(entry.key,"word_order",t("common.word_order"),definition.word_order,["high_low","low_high"])}
      ${select(entry.key,"byte_order",t("common.byte_order"),definition.byte_order,["high_low","low_high"])}
      ${select(entry.key,"schedule",t("common.schedule"),definition.schedule,["default","slow"])}
      ${input(entry.key,"read_every",t("common.read_every"),definition.read_every,"number")}
      ${input(entry.key,"report_every",t("common.report_every"),definition.report_every,"number")}
      ${input(entry.key,"change_by",t("common.change_by"),definition.change_by,"number")}
      ${input(entry.key,"device_class",t("common.device_class"),definition.device_class)}
      ${input(entry.key,"state_class",t("common.state_class"),definition.state_class)}
      ${input(entry.key,"icon",t("common.icon"),definition.icon)}
      ${input(entry.key,"category",t("common.category"),definition.category)}
      ${input(entry.key,"topic_suffix",t("common.topic_suffix"),definition.topic_suffix,"text",true)}
      <label class="toggle"><input data-field="retain" data-key="${esc(entry.key)}" type="checkbox" ${definition.retain ? "checked" : ""}> ${esc(t("common.retain"))}</label>
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
  byId("sensor-groups").innerHTML=[...groups.entries()].sort(([a],[b])=>a.localeCompare(b)).map(([category,items])=>`<section class="group"><div class="group-title"><b>${esc(category)}</b><small>${esc(t("common.entries",{value:items.length}))}</small></div><div class="sensor-grid">${items.map(sensorCard).join("")}</div></section>`).join("");
  byId("empty").hidden=sensors.length !== 0;
  byId("count-total").textContent=sensors.length;
  byId("count-supported").textContent=sensors.filter(entry=>transportBranches(entry).some(([,result])=>result.status === "supported")).length;
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

async function refreshRuntimeStatus() {
  const transportChanged=renderTransportRuntime(await request("api/runtime"));
  if (!transportChanged) return;
  render();
  if (typeof renderCustomSensors === "function") renderCustomSensors();
}

function collectUpdates() {
  return sensors.map(entry=>{
    const key=entry.key;
    const definition={};
	for (const field of editable) {
	  const control=field === "transport" ? document.querySelector(`[data-transport="${CSS.escape(key)}"]`) : document.querySelector(`[data-field="${field}"][data-key="${CSS.escape(key)}"]`);
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
    message.textContent=t("messages.saved");
    render();
  } catch (error) { message.textContent=t("messages.save_error",{error:error.message}); message.style.color="var(--red)"; }
}

async function resetConfiguration() {
  if (!window.confirm(t("confirm.reset_sensors"))) return;
  const message=byId("save-message");
  try {
    const payload=await request("api/reset",{method:"POST",body:"{}"});
    sensors=payload.available_sensors || [];
    message.style.color="var(--green)";
    message.textContent=t("messages.reset");
    render();
  } catch (error) { message.style.color="var(--red)"; message.textContent=t("messages.save_error",{error:error.message}); }
}

async function deleteSensors() {
  if (!window.confirm(t("confirm.delete_sensors"))) return;
  const message=byId("save-message");
  try {
    const payload=await request("api/sensors/delete",{method:"POST",body:"{}"});
    sensors=payload.available_sensors || [];
    message.style.color="var(--green)";
    message.textContent=t("messages.deleted");
    render();
  } catch (error) { message.style.color="var(--red)"; message.textContent=t("messages.delete_error",{error:error.message}); }
}

async function refreshScanStatus() {
  const job=await request("api/scan-status");
  byId("scan-state").textContent=t(`status.${job.status}`);
  byId("scan-message").textContent=job.message_key ? t(job.message_key) : job.message;
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
  console.info("[SolarMan Diagnostics] Scan now clicked");
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
window.i18nReady.then(async()=>{
  await Promise.all([loadSensors(),refreshScanStatus(),refreshRuntimeStatus()]);
  if (!runtimeTimer) runtimeTimer=window.setInterval(()=>refreshRuntimeStatus().catch(error=>console.error("[SolarMan Diagnostics] runtime status refresh failed",error)),5000);
}).catch(error=>{
  console.error("[SolarMan Diagnostics] panel initialization failed",error);
  byId("scan-message").textContent=error.message;
});
</script>
<script src="custom-panel.js"></script>
<script src="control-panel.js"></script>
</body>
</html>
"""
