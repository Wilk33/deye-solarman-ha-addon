from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"packages"))

from deye_inverter_core.controls import CONTROLS, ControlService, ControlRuntime, decode, encode, write_control
from deye_inverter_core.mqtt import MqttPublisher
from deye_inverter_core.models import InverterConfig, MqttConfig
from deye_inverter_core.web import IngressPanel
from deye_inverter_core.transport import TransportConnectionClosedError as SolarmanConnectionClosedError


class Registers:
	def __init__(self, values=None):
		self.values=values or {}
		self.reads=[]
		self.writes=[]
		self.fail_write=False
		self.mismatch=False

	def connect(self):
		pass

	def close(self):
		pass

	def read_holding_registers(self, start, count):
		self.reads.append((start,count))
		return [self.values.get(address,0) for address in range(start,start+count)]

	def write_holding_registers(self, start, values):
		self.writes.append((start,values))
		if self.fail_write:
			raise TimeoutError("timeout after send")
		if not self.mismatch:
			self.values.update({start+index:value for index,value in enumerate(values)})


class ControlTests(unittest.TestCase):
	def setUp(self):
		self.temp=tempfile.TemporaryDirectory()
		self.service=ControlService(str(Path(self.temp.name)/"controls.json"),None,threading.Lock(),0)

	def tearDown(self):
		self.temp.cleanup()

	def select(self, key):
		entry=self.service.entry(key)
		entry["last_scan"]={"status":"supported"}
		entry["monitor"]=True
		self.service.store({"available_sensors":[entry],"published":[]})
		return entry

	def test_catalog_profile_counts_and_unique_addresses(self):
		self.assertEqual(len(CONTROLS),119)
		self.assertEqual(CONTROLS["control_grid_charge_battery_current"]["registers"],[128])
		self.assertEqual(CONTROLS["control_battery_1_manufacturer"]["registers"],[229])
		self.assertEqual(CONTROLS["control_prog1_charge"]["bitmask"],3)
		self.assertEqual(CONTROLS["control_prog1_mode"]["bitmask"],28)

	def test_read_test_never_writes_and_updates_saved_scan(self):
		key="control_grid_charge_battery_current"
		self.select(key)
		client=Registers({128:37})
		with patch.object(self.service,"transport_factory",return_value=client):
			result=self.service.test(key)
		self.assertEqual(result["value"],37)
		self.assertEqual(client.writes,[])
		self.assertEqual(self.service.load()["available_sensors"][0]["last_scan"]["value"],37)

	def test_scan_is_read_only_and_preserves_selections(self):
		key="control_grid_charge_battery_current"
		self.select(key)
		client=Registers({128:45})
		with patch.object(self.service,"transport_factory",return_value=client):
			self.service._scan(lambda:None)
		self.assertEqual(self.service.job["status"],"completed")
		self.assertEqual(len(self.service.load()["available_sensors"]),119)
		self.assertTrue(next(e for e in self.service.load()["available_sensors"] if e["key"] == key)["monitor"])
		self.assertEqual(client.writes,[])

	def test_bitmask_preserves_other_controls(self):
		client=Registers({172:0xA5})
		result=write_control(client,CONTROLS["control_prog1_charge"],"Allow Gen")
		self.assertEqual(client.writes,[(172,[0xA6])])
		self.assertEqual(result["value"],"Allow Gen")

	def test_signed_value_and_factor(self):
		entry=CONTROLS["control_system_zero_export_power"]
		client=Registers({104:0})
		result=write_control(client,entry,"-12")
		self.assertEqual(client.writes,[(104,[65524])])
		self.assertEqual(result["value"],-12)

	def test_dynamic_limits_are_read_before_write(self):
		client=Registers({20:34464,21:1,143:0})
		entry=CONTROLS["control_export_limit_power"]
		with self.assertRaises(ValueError):
			write_control(client,entry,"11000")
		self.assertEqual(client.writes,[])
		write_control(client,entry,"9800")
		self.assertEqual(client.writes,[(143,[9800])])
		self.assertIn((20,2),client.reads)

	def test_invalid_values_never_write(self):
		client=Registers()
		for value in ("nan","inf","-1","241","1.5"):
			with self.subTest(value=value),self.assertRaises(ValueError):
				write_control(client,CONTROLS["control_battery_max_charge_current"],value)
		with self.assertRaises(ValueError):
			write_control(client,CONTROLS["control_load_limit"],"invalid")
		self.assertEqual(client.writes,[])

	def test_time_respects_adjacent_programs_and_midnight(self):
		client=Registers({148:2300,149:300,153:2200})
		entry=CONTROLS["control_prog1_time"]
		self.assertEqual(encode(entry,"01:30",client,[2300]),[130])
		with self.assertRaises(ValueError):
			encode(entry,"12:00",client,[2300])
		with self.assertRaises(ValueError):
			encode(entry,"24:00",client,[2300])

	def test_datetime_and_unknown_enum(self):
		entry=CONTROLS["control_date_time"]
		words=encode(entry,"2026-09-15 21:30:12",Registers(),[0,0,0])
		self.assertEqual(decode(entry,words),"2026-09-15 21:30:12")
		with self.assertRaises(ValueError):
			decode(CONTROLS["control_load_limit"],[99])

	def test_uncertain_write_is_not_retried(self):
		for failure in ("fail_write","mismatch"):
			client=Registers({128:20})
			setattr(client,failure,True)
			with self.assertRaises(RuntimeError):
				write_control(client,CONTROLS["control_grid_charge_battery_current"],"30")
			self.assertEqual(len(client.writes),1)

	def test_fixed_encoding_cannot_be_changed_by_panel(self):
		key="control_grid_charge_battery_current"
		self.select(key)
		for field in ("registers","factor","bitmask","method","options"):
			with self.subTest(field=field),self.assertRaises(ValueError):
				self.service.update([{"key":key,"monitor":True,"definition":{field:80}}])

	def test_filtered_updates_preserve_other_selection_and_reset(self):
		key="control_grid_charge_battery_current"
		self.select(key)
		self.service.update([])
		self.assertTrue(self.service.load()["available_sensors"][0]["monitor"])
		self.service.update([{"key":key,"monitor":True,"definition":{"read_every":120,"name":"Ładowanie"}}])
		self.assertEqual(self.service.load()["available_sensors"][0]["definition"]["read_every"],120)
		self.assertFalse(self.service.reset()["available_sensors"][0]["monitor"])
		self.assertEqual(self.service.reset(clear=True)["available_sensors"],[])

	def test_runtime_retained_unknown_and_deselected_commands_do_not_write(self):
		key="control_grid_charge_battery_current"
		self.select(key)
		client=Registers({128:10})
		runtime=ControlRuntime(self.service,Mock(),client)
		runtime.receive(key,"20",True)
		runtime.receive("arbitrary","20",False)
		runtime.tick()
		self.assertEqual(client.writes,[])
		runtime.receive(key,"20",False)
		self.service.reset()
		runtime.tick()
		self.assertEqual(client.writes,[])

	def test_runtime_write_failure_blocks_following_commands(self):
		key="control_grid_charge_battery_current"
		self.select(key)
		client=Registers({128:10})
		client.fail_write=True
		runtime=ControlRuntime(self.service,Mock(),client)
		runtime.receive(key,"20",False)
		runtime.tick()
		runtime.receive(key,"30",False)
		runtime.tick()
		self.assertTrue(runtime.blocked)
		self.assertEqual(len(client.writes),1)

	def test_runtime_removes_persisted_discovery(self):
		key="control_grid_charge_battery_current"
		self.service.store({"available_sensors":[],"published":[key]})
		mqtt=Mock()
		ControlRuntime(self.service,mqtt,Registers()).start()
		mqtt.remove_control_discovery.assert_called_once_with(CONTROLS[key])
		self.assertEqual(self.service.load()["published"],[])

	def test_transport_reconnect_preserves_write_block(self):
		key="control_grid_charge_battery_current"
		self.select(key)
		self.service.writes_blocked=True
		runtime=ControlRuntime(self.service,Mock(),Registers())
		self.assertTrue(runtime.blocked)
		self.service.update([{"key":key,"monitor":True,"definition":{}}])
		self.assertFalse(ControlRuntime(self.service,Mock(),Registers()).blocked)

	def test_closed_control_connection_requests_runtime_reconnect(self):
		self.select("control_grid_charge_battery_current")
		client=Mock()
		client.read_holding_registers.side_effect=SolarmanConnectionClosedError("Connection already closed")
		with self.assertRaises(SolarmanConnectionClosedError):
			ControlRuntime(self.service,Mock(),client).tick()

	def test_runtime_publishes_readback_after_command(self):
		key="control_grid_charge_battery_current"
		self.select(key)
		client=Registers({128:10})
		mqtt=Mock()
		runtime=ControlRuntime(self.service,mqtt,client)
		runtime.start()
		runtime.receive(key,"25",False)
		runtime.tick()
		self.assertEqual(client.writes,[(128,[25])])
		self.assertEqual(mqtt.publish_control_state.call_args.args[1]["value"],25)

	def test_mqtt_discovery_components_and_command_dispatch(self):
		config=MqttConfig("broker",1883,"","","test","deye","homeassistant",True)
		mqtt=MqttPublisher(config,InverterConfig("123","Inverter","Deye","SG05LP3"))
		mqtt._client=Mock()
		mqtt._publish_confirmed=Mock()
		keys={"control_grid_charge_battery_current":"number","control_load_limit":"select","control_inverter_enabled":"switch","control_date_time":"text","control_prog1_time":"select"}
		for key,kind in keys.items():
			mqtt.publish_control_discovery(self.service.entry(key),{"min":0,"max":100,"options":["01:00","02:00"]})
			topic,payload,*_=mqtt._publish_confirmed.call_args.args
			self.assertIn(f"/{kind}/",topic)
			self.assertFalse(json.loads(payload)["retain"])
			self.assertFalse(json.loads(payload)["optimistic"])
		callback=Mock()
		mqtt.configure_controls(callback,["control_load_limit"])
		mqtt._on_control_message(None,None,SimpleNamespace(topic=mqtt.control_base()+"/control_load_limit/set",payload=b"Essentials",retain=False))
		callback.assert_called_once_with("control_load_limit","Essentials",False)

	def test_ingress_control_routes_and_test_have_no_write_side_effect(self):
		key="control_grid_charge_battery_current"
		self.select(key)
		client=Registers({128:42})
		panel=IngressPanel(str(Path(self.temp.name)/"sensors.yaml"),lambda:{},port=0,control_service=self.service)
		panel.start()
		base=f"http://127.0.0.1:{panel._server.server_port}"
		try:
			with urlopen(base) as response:
				html=response.read().decode()
			self.assertIn("Własne sensory",html)
			self.assertIn('id="control-tab"',html)
			with patch.object(self.service,"transport_factory",return_value=client):
				with urlopen(Request(base+"/api/controls/test",data=json.dumps({"key":key,"value":200}).encode(),headers={"Content-Type":"application/json"})) as response:
					self.assertEqual(json.load(response)["value"],42)
			self.assertEqual(client.writes,[])
			with self.assertRaises(HTTPError) as caught:
				urlopen(Request(base+"/api/controls/write",data=b"{}"))
			self.assertEqual(caught.exception.code,404)
		finally:
			panel.stop()


if __name__ == "__main__":
	unittest.main()
