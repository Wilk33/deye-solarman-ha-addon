from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"packages"))

from deye_inverter_core.ownership import EntityOwnershipRegistry, EntityOwnership
from deye_inverter_core.ownership_config import OwnershipCoordinator
from deye_inverter_core.scanner import load_detected_sensors, update_detected_sensors, clear_detected_sensors
from deye_inverter_core.custom_sensors import load_custom_sensors
from deye_inverter_core.controls import ControlService, component
from deye_inverter_core.web import IngressPanel


class OwnershipApiTests(unittest.TestCase):
	def setUp(self):
		self.temp=tempfile.TemporaryDirectory()
		self.directory=Path(self.temp.name)
		self.registry=EntityOwnershipRegistry(self.directory/"owners.json")
		self.own=EntityOwnership(self.registry,"123","solarman_tcp","Logger")
		self.foreign=EntityOwnership(self.registry,"123","modbus_rtu","RS485")
		self.detected=self.directory/"detected.yaml"
		self.custom=self.directory/"custom.yaml"
		self.queue=self.directory/"deye_solarman_discovery_removals.yaml"
		self.definition={"key":"pv_power","name":"PV","registers":[672],"type":"uint16"}
		self.detected.write_text(json.dumps({"available_sensors":[{"key":"pv_power","definition":self.definition,"monitor":False}]}))
		self.controls=ControlService(str(self.directory/"controls.json"),None,threading.Lock())
		self.controls.ownership=self.own
		control=self.controls.entry("control_grid_charge_battery_current")
		control["last_scan"]={"status":"supported"}
		self.controls.store({"available_sensors":[control],"published":[]})
		self.coordinator=OwnershipCoordinator(self.own,[self.detected,self.custom,self.queue,self.controls.path],self.desired)
		self.panel=IngressPanel(str(self.detected),lambda:{},clear_handler=lambda:clear_detected_sensors(str(self.detected)),custom_sensors_file=str(self.custom),port=0,control_service=self.controls,ownership_coordinator=self.coordinator)
		self.panel.start()
		self.base=f"http://127.0.0.1:{self.panel._server.server_port}"

	def tearDown(self):
		self.panel.stop()
		self.temp.cleanup()

	def desired(self):
		return {("sensor",e["key"]) for e in load_detected_sensors(str(self.detected))["available_sensors"]+load_custom_sensors(str(self.custom))["sensors"] if e["monitor"]}|{(component(e["definition"]),e["key"]) for e in self.controls.load()["available_sensors"] if e["monitor"]}

	def request(self, path, payload=None, method=None):
		data=json.dumps(payload).encode() if payload is not None else None
		with urlopen(Request(self.base+path,data=data,method=method,headers={"Content-Type":"application/json"})) as response:
			return json.load(response)

	def test_panel_shows_foreign_owner_and_conflict_does_not_save(self):
		self.foreign.reconcile({("sensor","pv_power")})
		entry=self.request("/api/sensors")["available_sensors"][0]
		self.assertEqual(entry["ownership"]["owner"],"modbus_rtu")
		self.assertFalse(entry["ownership"]["editable"])
		before=self.detected.read_bytes()
		with self.assertRaises(HTTPError) as caught:
			self.request("/api/sensors",{"sensors":[{"key":"pv_power","monitor":True,"definition":{"name":"Changed"}}]})
		self.assertEqual(caught.exception.code,409)
		self.assertEqual(self.detected.read_bytes(),before)
		self.assertFalse(self.queue.exists())

	def test_selected_sensor_claims_and_delete_releases(self):
		self.request("/api/sensors",{"sensors":[{"key":"pv_power","monitor":True}]})
		self.assertTrue(self.own.owns("sensor","pv_power"))
		self.request("/api/sensors/delete",{})
		self.assertFalse(self.own.owns("sensor","pv_power"))
		self.assertEqual(load_detected_sensors(str(self.detected))["available_sensors"],[])

	def test_custom_sensor_conflict_and_release_on_delete(self):
		definition={**self.definition,"key":"custom_pv"}
		payload={"sensors":[{"key":"custom_pv","monitor":True,"definition":definition}]}
		self.foreign.reconcile({("sensor","custom_pv")})
		with self.assertRaises(HTTPError) as caught:
			self.request("/api/custom-sensors",payload)
		self.assertEqual(caught.exception.code,409)
		self.assertFalse(self.custom.exists())
		self.foreign.reconcile(set())
		self.request("/api/custom-sensors",payload)
		self.assertTrue(self.own.owns("sensor","custom_pv"))
		self.request("/api/custom-sensors/custom_pv",method="DELETE")
		self.assertFalse(self.own.owns("sensor","custom_pv"))

	def test_control_conflict_and_reset_releases_owner(self):
		key="control_grid_charge_battery_current"
		self.foreign.reconcile({("number",key)})
		entry=self.request("/api/controls")["available_sensors"][0]
		self.assertFalse(entry["ownership"]["editable"])
		with self.assertRaises(HTTPError) as caught:
			self.request("/api/controls",{"sensors":[{"key":key,"monitor":True,"definition":{}}]})
		self.assertEqual(caught.exception.code,409)
		self.assertFalse(self.controls.load()["available_sensors"][0]["monitor"])
		self.foreign.reconcile(set())
		self.request("/api/controls",{"sensors":[{"key":key,"monitor":True,"definition":{}}]})
		self.assertTrue(self.own.owns("number",key))
		self.request("/api/controls/reset",{})
		self.assertFalse(self.own.owns("number",key))

	def test_corrupt_registry_returns_503_for_view_and_save(self):
		self.registry.path.write_text('{broken')
		for payload in (None,{"sensors":[{"key":"pv_power","monitor":True}]}):
			with self.assertRaises(HTTPError) as caught:
				self.request("/api/sensors",payload)
			self.assertEqual(caught.exception.code,503)
		self.assertFalse(load_detected_sensors(str(self.detected))["available_sensors"][0]["monitor"])


if __name__ == "__main__":
	unittest.main()
