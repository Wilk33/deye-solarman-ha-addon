from __future__ import annotations

import json
import multiprocessing
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"packages"))

from deye_inverter_core.ownership import EntityOwnershipRegistry, EntityOwnership, OwnershipConflict, OwnershipUnavailable
from deye_inverter_core.ownership_config import OwnershipCoordinator
from deye_inverter_core.mqtt import MqttPublisher
from deye_inverter_core.models import MqttConfig, InverterConfig, SensorDefinition


def race_claim(path, source, start, results):
	owner=EntityOwnership(EntityOwnershipRegistry(path),"123",source,source)
	start.wait(10)
	try:
		owner.reconcile({("sensor","pv_power")},strict=True)
		results.put(source)
	except OwnershipConflict:
		results.put("conflict")


class OwnershipTests(unittest.TestCase):
	def setUp(self):
		self.temp=tempfile.TemporaryDirectory()
		self.path=Path(self.temp.name)/"entity_owners.json"
		self.registry=EntityOwnershipRegistry(self.path)
		self.logger=EntityOwnership(self.registry,"123","solarman_tcp","Deye Solarman Local")
		self.rs485=EntityOwnership(EntityOwnershipRegistry(self.path),"123","modbus_rtu","Deye RS485 Local")

	def tearDown(self):
		self.temp.cleanup()

	def test_two_processes_have_exactly_one_winner(self):
		ctx=multiprocessing.get_context("spawn")
		start=ctx.Event()
		results=ctx.Queue()
		processes=[ctx.Process(target=race_claim,args=(str(self.path),source,start,results)) for source in ("solarman_tcp","modbus_rtu")]
		for process in processes:
			process.start()
		start.set()
		outcomes=[results.get(timeout=15) for _ in processes]
		for process in processes:
			process.join(15)
			self.assertEqual(process.exitcode,0)
		self.assertEqual(outcomes.count("conflict"),1)
		winner=next(value for value in outcomes if value != "conflict")
		self.assertEqual(json.loads(self.path.read_text())["123:sensor:pv_power"]["owner"],winner)

	def test_release_handoff_and_stale_release_do_not_steal(self):
		self.logger.reconcile({("sensor","pv_power")})
		with self.assertRaises(OwnershipConflict):
			self.rs485.reconcile({("sensor","pv_power")},strict=True)
		self.logger.reconcile(set())
		self.rs485.reconcile({("sensor","pv_power")},strict=True)
		self.logger.reconcile(set())
		with self.logger.guard("sensor","pv_power") as allowed:
			self.assertFalse(allowed)
		with self.rs485.guard("sensor","pv_power") as allowed:
			self.assertTrue(allowed)

	def test_identity_includes_serial_and_component(self):
		self.logger.reconcile({("sensor","setting"),("number","setting")})
		other=EntityOwnership(self.registry,"456","modbus_rtu","RS485")
		other.reconcile({("sensor","setting")},strict=True)
		self.assertEqual(len(self.registry.snapshot()),3)

	def test_corrupt_registry_is_not_replaced_or_treated_as_free(self):
		for raw in ('{broken','[]','{"123:sensor:pv_power":{}}'):
			self.path.write_text(raw)
			with self.assertRaises(OwnershipUnavailable):
				self.logger.reconcile({("sensor","pv_power")})
			self.assertEqual(self.path.read_text(),raw)

	def test_strict_batch_conflict_does_not_partially_claim(self):
		self.logger.reconcile({("sensor","a")})
		with self.assertRaises(OwnershipConflict):
			self.rs485.reconcile({("sensor","a"),("sensor","b")},strict=True)
		self.assertNotIn("123:sensor:b",self.registry.snapshot())

	def test_restart_keeps_owner_and_non_strict_reconcile_skips_foreign(self):
		self.logger.reconcile({("sensor","a")})
		self.rs485.reconcile({("sensor","a"),("sensor","b")})
		self.assertEqual(self.registry.snapshot()["123:sensor:a"]["owner"],"solarman_tcp")
		self.assertEqual(self.registry.snapshot()["123:sensor:b"]["owner"],"modbus_rtu")

	def publisher(self, owner):
		mqtt=MqttPublisher(MqttConfig("broker",1883,"","","test","deye","homeassistant",True),InverterConfig("123","Inverter","Deye","SG04LP3"),ownership=owner)
		mqtt._client=Mock()
		mqtt._publish_confirmed=Mock()
		return mqtt

	def test_state_topic_and_discovery_identity_are_shared(self):
		sensor=SensorDefinition("pv_power","PV Power",[672],"uint16")
		logger=self.publisher(self.logger)
		rs485=self.publisher(self.rs485)
		self.logger.reconcile({("sensor","pv_power")})
		logger.publish_discovery(sensor)
		first=json.loads(logger._publish_confirmed.call_args.args[1])
		self.assertEqual(first["state_topic"],"deye/123/pv_power")
		self.assertEqual(first["origin"]["name"],"Deye Solarman Local")
		self.logger.reconcile(set())
		self.rs485.reconcile({("sensor","pv_power")})
		rs485.publish_discovery(sensor)
		second=json.loads(rs485._publish_confirmed.call_args.args[1])
		self.assertEqual(second["state_topic"],"deye/123/pv_power")
		self.assertEqual(first["unique_id"],second["unique_id"])
		self.assertEqual(logger.discovery_topic(sensor.key),rs485.discovery_topic(sensor.key))

	def test_old_publisher_cannot_publish_or_remove_new_owners_discovery(self):
		sensor=SensorDefinition("pv_power","PV Power",[672],"uint16")
		logger=self.publisher(self.logger)
		self.rs485.reconcile({("sensor","pv_power")})
		logger.publish_discovery(sensor)
		logger.publish_state(sensor,42,{})
		logger.publish_raw(sensor,[42])
		logger.remove_discovery("pv_power")
		logger._publish_confirmed.assert_not_called()
		logger._client.publish.assert_not_called()
		self.rs485.reconcile(set())
		logger.remove_discovery("pv_power")
		logger._publish_confirmed.assert_called_once()

	def test_pending_remove_cannot_delete_reenabled_own_entity(self):
		logger=self.publisher(self.logger)
		self.logger.reconcile({("sensor","pv_power")})
		logger.remove_discovery("pv_power")
		logger._publish_confirmed.assert_not_called()

	def test_control_commands_use_source_topics_with_canonical_discovery(self):
		from deye_inverter_core.controls import CONTROLS
		key="control_grid_charge_battery_current"
		self.logger.reconcile({("number",key)})
		logger=self.publisher(self.logger)
		entry={"key":key,"definition":{"name":"Grid charge","icon":"mdi:tune","retain":True}}
		logger.publish_control_discovery(entry,{"min":0,"max":210})
		payload=json.loads(logger._publish_confirmed.call_args.args[1])
		self.assertEqual(payload["command_topic"],f"deye/123/source/solarman_tcp/controls/{key}/set")
		self.assertEqual(payload["unique_id"],f"deye_solarman_123_{key}")
		self.logger.reconcile(set())
		self.rs485.reconcile({("number",key)})
		logger._publish_confirmed.reset_mock()
		logger.remove_control_discovery(CONTROLS[key])
		logger._publish_confirmed.assert_not_called()

	def test_selection_conflict_rolls_back_local_files_and_claims(self):
		local=Path(self.temp.name)/"selection.json"
		local.write_text('[]')
		coordinator=OwnershipCoordinator(self.rs485,[local],lambda:{("sensor",key) for key in json.loads(local.read_text())})
		self.logger.reconcile({("sensor","pv_power")})
		with self.assertRaises(OwnershipConflict):
			coordinator.apply(lambda:local.write_text('["pv_power","battery_soc"]'))
		self.assertEqual(local.read_text(),'[]')
		self.assertNotIn("123:sensor:battery_soc",self.registry.snapshot())
		coordinator.apply(lambda:local.write_text('["battery_soc"]'))
		self.assertEqual(self.registry.snapshot()["123:sensor:battery_soc"]["owner"],"modbus_rtu")
		coordinator.apply(lambda:local.write_text('[]'))
		self.assertNotIn("123:sensor:battery_soc",self.registry.snapshot())

	def test_passive_scan_preserves_foreign_owner_and_updates_results(self):
		local=Path(self.temp.name)/"selection.json"
		local.write_text('["pv_power"]')
		coordinator=OwnershipCoordinator(self.rs485,[local],lambda:{("sensor",key) for key in json.loads(local.read_text())})
		self.logger.reconcile({("sensor","pv_power")})
		coordinator.apply(lambda:local.write_text('["pv_power","battery_soc"]'),strict=False)
		self.assertEqual(json.loads(local.read_text()),["pv_power","battery_soc"])
		self.assertEqual(self.registry.snapshot()["123:sensor:pv_power"]["owner"],"solarman_tcp")
		self.assertEqual(self.registry.snapshot()["123:sensor:battery_soc"]["owner"],"modbus_rtu")

	def test_shared_state_publication_holds_lock_until_broker_ack(self):
		self.logger.reconcile({("sensor","pv_power")})
		logger=self.publisher(self.logger)
		started=threading.Event()
		ack=threading.Event()
		transferred=threading.Event()
		def publish(*args):
			started.set()
			self.assertTrue(ack.wait(5))
		logger._publish_confirmed.side_effect=publish
		writer=threading.Thread(target=lambda:logger.publish_state(SensorDefinition("pv_power","PV",[672],"uint16"),10,{}))
		def transfer():
			self.logger.reconcile(set())
			self.rs485.reconcile({("sensor","pv_power")},strict=True)
			transferred.set()
		writer.start()
		self.assertTrue(started.wait(5))
		mover=threading.Thread(target=transfer)
		mover.start()
		self.assertFalse(transferred.wait(0.1))
		ack.set()
		writer.join(5)
		mover.join(5)
		self.assertTrue(transferred.is_set())

	def test_queued_control_command_is_rejected_after_handoff(self):
		from test_controls import Registers
		from deye_inverter_core.controls import ControlService, ControlRuntime
		service=ControlService(str(Path(self.temp.name)/"controls.json"),None,threading.Lock())
		service.ownership=self.logger
		key="control_grid_charge_battery_current"
		entry=service.entry(key)
		entry["monitor"]=True
		service.store({"available_sensors":[entry],"published":[]})
		self.logger.reconcile({("number",key)})
		client=Registers({128:10})
		runtime=ControlRuntime(service,Mock(),client)
		runtime.receive(key,"25",False)
		self.logger.reconcile(set())
		self.rs485.reconcile({("number",key)})
		runtime.tick()
		self.assertEqual(client.writes,[])

	def test_registry_write_failure_rolls_back_selection(self):
		local=Path(self.temp.name)/"selection.json"
		local.write_text('[]')
		coordinator=OwnershipCoordinator(self.logger,[local],lambda:{("sensor",key) for key in json.loads(local.read_text())})
		with patch.object(self.registry,"_write",side_effect=OSError("disk full")):
			with self.assertRaises(OwnershipUnavailable):
				coordinator.apply(lambda:local.write_text('["pv_power"]'))
		self.assertEqual(local.read_text(),'[]')
		self.assertEqual(self.registry.snapshot(),{})

	def test_shared_publication_uses_qos_one_and_stops_failed_client(self):
		mqtt=MqttPublisher(MqttConfig("broker",1883,"","","test","deye","homeassistant",True),InverterConfig("123","Inv","Deye","SG04LP3"),ownership=self.logger)
		self.logger.reconcile({("sensor","pv_power")})
		mqtt._client=Mock()
		info=mqtt._client.publish.return_value
		info.is_published.return_value=False
		with self.assertRaises(ConnectionError):
			mqtt.publish_state(SensorDefinition("pv_power","PV",[672],"uint16"),42,{})
		self.assertEqual(mqtt._client.publish.call_args.kwargs["qos"],1)
		info.wait_for_publish.assert_called_once_with(timeout=10)
		mqtt._client.disconnect.assert_called_once()
		mqtt._client.loop_stop.assert_called_once()


if __name__ == "__main__":
	unittest.main()
