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

from deye_inverter_core.controls import CONTROLS, ControlService, ControlRuntime, decode, encode, set_controls, write_control
from deye_inverter_core.mqtt import MqttPublisher
from deye_inverter_core.models import InverterConfig, MqttConfig
from deye_inverter_core.web import IngressPanel
from deye_inverter_core.transport import TransportConnectionClosedError as SolarmanConnectionClosedError


class RecordingManager:
	_is_transport_manager=True

	def __init__(self, clients):
		self.clients=clients
		self.calls=[]

	def run(self, transport_id, operation, *, before_io=None):
		self.calls.append(transport_id)
		if before_io is not None:
			before_io()
		return operation(self.clients[transport_id])


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


class ManualClock:
	def __init__(self,value=0.0):
		self.value=value

	def __call__(self):
		return self.value


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
		self.assertEqual(len(CONTROLS),115)
		self.assertFalse(
			{"control_us_version_grounding_fault","control_grid_standard","control_configured_grid_phases","control_allow_remote"}
			& set(CONTROLS)
		)
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

	def test_read_test_uses_the_transport_selected_in_the_saved_definition(self):
		key="control_grid_charge_battery_current"
		entry=self.select(key)
		entry["definition"]["transport"]="modbus_rtu"
		entry["last_scan"]={
			"solarman_tcp":{"status":"supported","write_allowed":True},
			"modbus_rtu":{"status":"supported","write_allowed":True},
			"status":"supported",
		}
		self.service.store({"available_sensors":[entry],"published":[]})
		solarman=Registers({128:11})
		rs485=Registers({128:37})
		manager=RecordingManager({"solarman_tcp":solarman,"modbus_rtu":rs485})
		self.service.transport_manager=manager

		result=self.service.test(key)

		self.assertEqual(result["value"],37)
		self.assertEqual(manager.calls,["modbus_rtu"])
		self.assertEqual(solarman.reads,[])
		self.assertEqual(solarman.writes+rs485.writes,[])

	def test_scan_is_read_only_and_preserves_selections(self):
		key="control_grid_charge_battery_current"
		self.select(key)
		client=Registers({128:45})
		with patch.object(self.service,"transport_factory",return_value=client):
			self.service._scan(lambda:None)
		self.assertEqual(self.service.job["status"],"completed")
		self.assertEqual(len(self.service.load()["available_sensors"]),115)
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
		self.assertIn("UNKNOWN",decode(CONTROLS["control_load_limit"],[99]))

	def test_parallel_address_shifts_and_preserves_all_other_bits(self):
		entry=CONTROLS["control_parallel_modbus_sn"]
		self.assertEqual(decode(entry,[1024]),1)
		for address in (0,1,17,63):
			client=Registers({336:0x07AB})
			result=write_control(client,entry,str(address))
			self.assertEqual(client.values[336],(address<<10)|0x3AB)
			self.assertEqual(result["value"],address)
		with self.assertRaises(ValueError):
			write_control(Registers({336:1024}),entry,"64")

	def test_current_limits_follow_rated_power_and_reject_unknown_model(self):
		for key in ("control_battery_max_charge_current","control_battery_max_discharge_current"):
			entry=CONTROLS[key]
			for power,maximum in ((5000,120),(6000,150),(8000,190),(10000,210),(12000,240)):
				with self.subTest(key=key,power=power):
					raw=power*10
					client=Registers({20:raw&65535,21:raw>>16,entry["registers"][0]:100})
					result=self.service.read(client,key)
					self.assertEqual(result["max"],maximum)
					with self.assertRaises(ValueError):
						write_control(client,entry,str(maximum+1))
					self.assertEqual(client.writes,[])
					write_control(client,entry,str(maximum))
					self.assertEqual(client.writes[-1][1],[maximum])
			client=Registers({108:100,109:100})
			result=self.service.read(client,key)
			self.assertEqual(result["value"],100)
			self.assertFalse(result["write_allowed"])
			with self.assertRaises(ValueError):
				write_control(client,entry,"100")
			self.assertEqual(client.writes,[])

	def test_unverified_definitions_are_read_only_with_raw_preserved(self):
		for key,register,raw in (("control_min_pv_power_for_gen_start",139,500),):
			with self.subTest(key=key):
				client=Registers({register:raw})
				result=self.service.read(client,key)
				self.assertEqual(result["raw_registers"],[raw])
				self.assertFalse(result["write_allowed"])
				if register == 139:
					self.assertEqual(result["value"],500)
					self.assertNotIn("max",result)
				else:
					self.assertEqual(result["status"],"unknown")
					self.assertIn("UNKNOWN",result["value"])
				with self.assertRaises(ValueError):
					write_control(client,CONTROLS[key],"500" if register == 139 else next(iter(CONTROLS[key]["options"].values())))
				self.assertEqual(client.writes,[])

	def test_zero_enum_fields_are_unknown_and_cannot_be_written(self):
		for key,entry in CONTROLS.items():
			if entry["registers"] not in ([178],[228]):
				continue
			with self.subTest(key=key):
				client=Registers({entry["registers"][0]:65535^entry["bitmask"]})
				result=self.service.read(client,key)
				self.assertEqual(result["status"],"unknown")
				self.assertIn("UNKNOWN",result["value"])
				self.assertFalse(result["write_allowed"])
				for value in list(entry["options"].values())+[result["value"]]:
					with self.assertRaises(ValueError):
						write_control(client,entry,value)
				self.assertEqual(client.writes,[])
				# A known state still permits a masked write, preserving other fields.
				client.values[entry["registers"][0]]=65535
				option=next(iter(entry["options"].values()))
				write_control(client,entry,option)
				self.assertEqual(client.values[entry["registers"][0]]&(65535^entry["bitmask"]),65535^entry["bitmask"])

	def test_saved_catalog_migrates_without_losing_custom_settings(self):
		entry=self.service.entry("control_battery_capacity_current")
		entry["definition"].update(name="Battery Capacity current",unit="A",read_every=123)
		entry["last_scan"]={"status":"supported","value":100,"raw_registers":[100],"write_allowed":True}
		entry["monitor"]=True
		self.service.store({"available_sensors":[entry],"published":[]})
		updated=self.service.load()["available_sensors"][0]
		self.assertEqual(updated["definition"]["name"],"Battery Capacity")
		self.assertEqual(updated["definition"]["unit"],"Ah")
		self.assertEqual(updated["definition"]["read_every"],123)
		self.assertTrue(updated["monitor"])
		updated["definition"]["name"]="Moja bateria"
		self.service.store({"available_sensors":[updated],"published":[]})
		self.assertEqual(self.service.load()["available_sensors"][0]["definition"]["name"],"Moja bateria")

	def test_saved_unsafe_discovery_is_removed_and_cannot_receive_commands(self):
		key="control_configured_grid_phases"
		self.service.store({"available_sensors":[],"published":[key]})
		mqtt=Mock()
		client=Registers({184:1})
		runtime=ControlRuntime(self.service,mqtt,client)
		runtime.start()
		self.assertEqual(mqtt.remove_control_discovery.call_args.args[0]["key"],key)
		runtime.receive(key,"Three Phase",False)
		runtime.tick()
		self.assertEqual(client.writes,[])

	def test_control_service_waits_for_active_scan_thread(self):
		started=threading.Event()
		release=threading.Event()
		finished=threading.Event()
		def scan(changed):
			started.set()
			if not release.wait(5):
				raise TimeoutError("test did not release control scan")
		self.service._scan=scan
		self.assertTrue(self.service.start_scan(lambda:None))
		self.assertTrue(started.wait(5))
		waiter=threading.Thread(target=lambda:(self.service.wait_for_idle(),finished.set()))
		waiter.start()
		self.assertFalse(finished.wait(0.1))
		release.set()
		waiter.join(5)

		self.assertTrue(finished.is_set())

	def test_saved_parallel_scan_is_redecoded_after_upgrade(self):
		entry=self.service.entry("control_parallel_modbus_sn")
		entry["definition"].pop("shift",None)
		entry["last_scan"]={"status":"supported","value":1024,"raw_registers":[1024],"min":0,"max":63}
		self.service.store({"available_sensors":[entry],"published":[]})
		updated=self.service.load()["available_sensors"][0]
		self.assertEqual(updated["last_scan"]["value"],1)
		self.assertEqual(updated["last_scan"]["raw_hex"],["0x0400"])
		self.assertNotIn("max",updated["last_scan"])

	def test_unknown_mqtt_state_is_attributes_only(self):
		config=MqttConfig("broker",1883,"","","test","deye","homeassistant",True)
		mqtt=MqttPublisher(config,InverterConfig("123","Inverter","Deye","SG05LP3"))
		mqtt._client=Mock()
		key="control_beep"
		result=self.service.read(Registers({228:0}),key)
		mqtt.publish_control_state(self.service.entry(key),result)
		calls=mqtt._client.publish.call_args_list
		self.assertEqual(len(calls),1)
		self.assertTrue(calls[0].args[0].endswith("/attributes"))
		self.assertEqual(json.loads(calls[0].args[1])["raw_registers"],[0])

	def test_unknown_state_blocks_runtime_commands_until_known_state(self):
		key="control_beep"
		self.select(key)
		client=Registers({228:0})
		mqtt=Mock()
		runtime=ControlRuntime(self.service,mqtt,client)
		runtime.start()
		self.assertFalse(mqtt.control_availability.call_args.args[1])
		runtime.receive(key,"Enable",False)
		runtime.tick()
		self.assertEqual(client.writes,[])
		self.assertFalse(runtime.blocked)
		client.values[228]=8
		runtime.receive(key,"Enable",False)
		runtime.tick()
		self.assertEqual(client.writes,[(228,[12])])

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

	def test_runtime_removes_persisted_discovery_after_catalog_becomes_empty(self):
		key="control_grid_charge_battery_current"
		entry=self.service.entry(key)
		self.service.store({"available_sensors":[entry],"published":[key]})
		catalog=list(CONTROLS.values())
		set_controls([])
		try:
			mqtt=Mock()
			ControlRuntime(self.service,mqtt,Registers()).start()
			mqtt.remove_control_discovery.assert_called_once_with(entry["definition"])
			self.assertEqual(self.service.load()["published"],[])
		finally:
			set_controls(catalog)

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

	def test_runtime_routes_each_command_once_to_live_selected_transport_without_fallback(self):
		key="control_grid_charge_battery_current"
		entry=self.select(key)
		entry["definition"]["transport"]="modbus_rtu"
		entry["last_scan"]={
			"solarman_tcp":{"status":"supported","write_allowed":True},
			"modbus_rtu":{"status":"supported","write_allowed":True},
			"status":"supported",
		}
		self.service.store({"available_sensors":[entry],"published":[]})
		solarman=Registers({128:10})
		rs485=Registers({128:10})
		manager=RecordingManager({"solarman_tcp":solarman,"modbus_rtu":rs485})
		runtime=ControlRuntime(self.service,Mock(),manager)
		runtime.receive(key,"25",False)

		runtime.tick()

		self.assertEqual(manager.calls,["modbus_rtu"])
		self.assertEqual(solarman.writes,[])
		self.assertEqual(rs485.writes,[(128,[25])])

	def test_runtime_does_not_fallback_after_uncertain_selected_transport_write(self):
		key="control_grid_charge_battery_current"
		entry=self.select(key)
		entry["definition"]["transport"]="modbus_rtu"
		entry["last_scan"]={
			"solarman_tcp":{"status":"supported","write_allowed":True},
			"modbus_rtu":{"status":"supported","write_allowed":True},
			"status":"supported",
		}
		self.service.store({"available_sensors":[entry],"published":[]})
		solarman=Registers({128:10})
		rs485=Registers({128:10})
		rs485.fail_write=True
		manager=RecordingManager({"solarman_tcp":solarman,"modbus_rtu":rs485})
		runtime=ControlRuntime(self.service,Mock(),manager)
		runtime.receive(key,"25",False)

		runtime.tick()

		self.assertNotIn("solarman_tcp",manager.calls)
		self.assertEqual(solarman.writes,[])
		self.assertEqual(len(rs485.writes),1)
		self.assertGreaterEqual(len(rs485.reads),2)
		self.assertTrue(runtime.blocked)

	def test_command_ttl_is_rechecked_inside_selected_slot_before_register_io(self):
		key="control_grid_charge_battery_current"
		entry=self.select(key)
		entry["definition"]["transport"]="modbus_rtu"
		entry["last_scan"]={"modbus_rtu":{"status":"supported","write_allowed":True}}
		self.service.store({"available_sensors":[entry],"published":[]})
		clock=ManualClock(1.0)
		client=Registers({128:10})
		class DelayedManager(RecordingManager):
			def run(self,transport_id,operation, *, before_io=None):
				self.calls.append(transport_id)
				clock.value=11.1
				if before_io is not None:
					before_io()
				return operation(self.clients[transport_id])
		manager=DelayedManager({"modbus_rtu":client})
		runtime=ControlRuntime(self.service,Mock(),manager,clock=clock)
		runtime.last_read[key]=1.0
		runtime.receive(key,"25",False)

		runtime.tick()

		self.assertEqual(manager.calls,["modbus_rtu"])
		self.assertEqual(client.reads,[])
		self.assertEqual(client.writes,[])

	def test_command_configuration_load_failure_does_not_escape_or_block_transport(self):
		key="control_grid_charge_battery_current"
		entry=self.select(key)
		entry["definition"]["transport"]="modbus_rtu"
		entry["last_scan"]={"modbus_rtu":{"status":"supported","write_allowed":True}}
		self.service.store({"available_sensors":[entry],"published":[]})
		clock=ManualClock(1.0)
		runtime=ControlRuntime(
			self.service,
			Mock(),
			RecordingManager({"modbus_rtu":Registers({128:10})}),
			clock=clock,
		)
		runtime.last_read[key]=clock()
		runtime.receive(key,"25",False)

		with patch.object(self.service,"load",side_effect=OSError("configuration unavailable")):
			runtime.tick()

		self.assertFalse(runtime.blocked)

	def test_prewrite_transport_failure_does_not_block_future_writes(self):
		key="control_grid_charge_battery_current"
		entry=self.select(key)
		entry["definition"]["transport"]="modbus_rtu"
		entry["last_scan"]={"modbus_rtu":{"status":"supported","write_allowed":True}}
		self.service.store({"available_sensors":[entry],"published":[]})
		client=Registers({128:10})
		client.read_holding_registers=Mock(side_effect=SolarmanConnectionClosedError("offline before write"))
		clock=ManualClock(1.0)
		runtime=ControlRuntime(self.service,Mock(),RecordingManager({"modbus_rtu":client}),clock=clock)
		runtime.receive(key,"25",False)

		runtime.tick()

		self.assertFalse(runtime.blocked)
		self.assertEqual(client.writes,[])

	def test_uncertain_write_blocks_all_future_writes_but_keeps_control_reads_running(self):
		failed=self.service.entry("control_grid_charge_battery_current")
		failed["definition"]["transport"]="modbus_rtu"
		failed["last_scan"]={"modbus_rtu":{"status":"supported","write_allowed":True}}
		failed["monitor"]=True
		working=self.service.entry("control_inverter_enabled")
		working["definition"]["transport"]="solarman_tcp"
		working["last_scan"]={"solarman_tcp":{"status":"supported","write_allowed":True}}
		working["monitor"]=True
		self.service.store({"available_sensors":[failed,working],"published":[]})
		modbus=Registers({128:10})
		modbus.fail_write=True
		solarman=Registers({80:0})
		clock=ManualClock(1.0)
		runtime=ControlRuntime(
			self.service,
			Mock(),
			RecordingManager({"solarman_tcp":solarman,"modbus_rtu":modbus}),
			clock=clock,
		)
		runtime.receive(failed["key"],"25",False)
		runtime.tick()
		clock.value=2.1
		runtime.receive(working["key"],"ON",False)

		runtime.tick()

		self.assertTrue(runtime.blocked)
		self.assertEqual(len(modbus.writes),1)
		self.assertEqual(solarman.writes,[])
		self.assertGreaterEqual(len(modbus.reads),2)
		self.assertGreaterEqual(len(solarman.reads),1)

	def test_control_availability_is_isolated_by_selected_transport(self):
		failed=self.service.entry("control_grid_charge_battery_current")
		failed["definition"]["transport"]="modbus_rtu"
		failed["last_scan"]={"modbus_rtu":{"status":"supported","write_allowed":True}}
		failed["monitor"]=True
		working=self.service.entry("control_inverter_enabled")
		working["definition"]["transport"]="solarman_tcp"
		working["last_scan"]={"solarman_tcp":{"status":"supported","write_allowed":True}}
		working["monitor"]=True
		self.service.store({"available_sensors":[failed,working],"published":[]})
		modbus=Registers({128:10})
		modbus.read_holding_registers=Mock(side_effect=SolarmanConnectionClosedError("serial offline"))
		solarman=Registers({80:1})
		manager=RecordingManager({"solarman_tcp":solarman,"modbus_rtu":modbus})
		mqtt=Mock()

		ControlRuntime(self.service,mqtt,manager).tick()

		availability=[call.args for call in mqtt.control_availability.call_args_list]
		self.assertIn(("control_grid_charge_battery_current",False),availability)
		self.assertIn(("control_inverter_enabled",True),availability)
		published=mqtt.publish_control_state.call_args
		self.assertEqual(published.args[0]["key"],"control_inverter_enabled")
		self.assertEqual(published.args[1]["transport"],"solarman_tcp")

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
		mqtt._on_control_message(None,None,SimpleNamespace(topic=mqtt.control_command_topic("control_load_limit"),payload=b"Essentials",retain=False))
		callback.assert_called_once_with("control_load_limit","Essentials",False)
		mqtt._on_control_message(None,None,SimpleNamespace(topic="base/123/controls/unknown/set",payload=b"x",retain=False))
		mqtt._on_control_message(None,None,SimpleNamespace(topic=mqtt.control_command_topic("control_load_limit"),payload=b"x"*129,retain=False))
		mqtt._on_control_message(None,None,SimpleNamespace(topic=mqtt.control_command_topic("control_load_limit"),payload=b"\xff",retain=False))
		callback.assert_called_once_with("control_load_limit","Essentials",False)

	def test_failed_control_subscription_disables_the_stale_command_handler(self):
		config=MqttConfig("broker",1883,"","","test","deye","homeassistant",True)
		mqtt=MqttPublisher(config,InverterConfig("123","Inverter","Deye","SG05LP3"))
		mqtt._client=Mock()
		old_topic=mqtt.control_command_topic("control_load_limit")
		old_handler=Mock()
		mqtt._control_topics={old_topic:"control_load_limit"}
		mqtt._control_handler=old_handler
		mqtt._client.subscribe.side_effect=ConnectionError("subscribe failed")

		with self.assertRaisesRegex(ConnectionError,"subscribe failed"):
			mqtt.configure_controls(Mock(),["control_inverter_enabled"])

		self.assertIsNone(mqtt._control_handler)
		self.assertEqual(mqtt._control_topics,{old_topic:"control_load_limit"})
		mqtt._on_control_message(None,None,SimpleNamespace(topic=old_topic,payload=b"25",retain=False))
		old_handler.assert_not_called()

	def test_control_subscription_return_code_prevents_handler_activation(self):
		config=MqttConfig("broker",1883,"","","test","deye","homeassistant",True)
		mqtt=MqttPublisher(config,InverterConfig("123","Inverter","Deye","SG05LP3"))
		mqtt._client=Mock()
		mqtt._client.subscribe.return_value=(4,1)
		handler=Mock()

		with self.assertRaisesRegex(ConnectionError,"subscribe.*code=4"):
			mqtt.configure_controls(handler,["control_inverter_enabled"])

		self.assertIsNone(mqtt._control_handler)
		handler.assert_not_called()

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
