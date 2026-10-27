import logging
import unittest
import threading
from unittest.mock import Mock

from test_runtime import FakePahoClient,RuntimeTransport
from test_dual_transport import ManualClock,make_transport_slot,make_runtime_sensor
from test_dual_transport import RecordingModbusClientFactory,FakeModbusSerialClient,make_rs485_config

from deye_inverter_core.models import MqttConfig,InverterConfig,SensorDefinition
from deye_inverter_core.models import SensorState
from deye_inverter_core.main import SensorRuntime
from deye_inverter_core.mqtt import MqttPublisher
from deye_inverter_core.scheduler import PerEntityScheduler
from deye_inverter_core.transport import TransportConnectionClosedError
from deye_inverter_core.transport_manager import TransportManager
from deye_inverter_core.transport_runtime import TransportWorker
from deye_solarman_diagnostics.rs485 import ModbusRtuTransport
from deye_solarman_diagnostics.solarman import SolarmanClient
from test_dual_transport import make_solarman_config


def publisher() -> MqttPublisher:
	result=MqttPublisher(
		MqttConfig("host",1883,"","","test","base","homeassistant",True),
		InverterConfig("123","Deye","Deye","SG05LP3"),
		detailed_logs=True,
	)
	result._client=FakePahoClient()
	return result


def closed(_client):
	raise TransportConnectionClosedError("Connection closed on read")


class OperationalLoggingTests(unittest.TestCase):
	def test_confirmed_mqtt_messages_have_one_batch_summary_instead_of_topic_logs(self) -> None:
		mqtt=publisher()
		sensor=SensorDefinition("voltage","Voltage",[100],"uint16")
		with self.assertLogs("deye_inverter_core.mqtt",logging.DEBUG) as logs:
			with mqtt.publication_batch("sensors",transport="modbus_rtu"):
				mqtt.publish_state(sensor,52,{})
				mqtt.publish_raw(sensor,[520])
		self.assertEqual(len(mqtt._client.messages),3)
		self.assertEqual(len(logs.records),1)
		self.assertIn("confirmed=3",logs.output[0])
		self.assertIn("transport=modbus_rtu",logs.output[0])
		self.assertNotIn("topic=",logs.output[0])

	def test_failed_mqtt_batch_reports_failed_topic_without_success_or_traceback(self) -> None:
		mqtt=publisher()
		mqtt._client=Mock()
		mqtt._client.publish.side_effect=TimeoutError("broker did not acknowledge")
		with self.assertLogs("deye_inverter_core.mqtt",logging.DEBUG) as logs:
			with self.assertRaises(TimeoutError):
				with mqtt.publication_batch("sensors",transport="solarman_tcp"):
					mqtt.publish_raw(SensorDefinition("v","V",[100],"uint16"),[1])
		self.assertTrue(any("topic=base/123/v/raw" in item for item in logs.output))
		self.assertTrue(any("failed=1" in item and "confirmed=0" in item for item in logs.output))
		self.assertTrue(all(record.exc_info is None for record in logs.records))

	def test_nested_mqtt_batches_do_not_duplicate_summaries(self) -> None:
		mqtt=publisher()
		with self.assertLogs("deye_inverter_core.mqtt",logging.DEBUG) as logs:
			with mqtt.publication_batch("sensors",transport="solarman_tcp"):
				with mqtt.publication_batch("diagnostics"):
					mqtt.publish_raw(SensorDefinition("v","V",[100],"uint16"),[1])
		self.assertEqual(len(logs.records),1)
		self.assertIn("confirmed=1",logs.output[0])

	def test_sensor_runtime_groups_sensor_and_diagnostic_publications(self) -> None:
		mqtt=publisher()
		slot=make_transport_slot("solarman_tcp")
		slot.client=RuntimeTransport("solarman_tcp",{100:7})
		manager=TransportManager([slot])
		sensor=SensorDefinition("v","V",[100],"uint16")
		runtime=SensorRuntime(manager,mqtt,[sensor],{"v":SensorState()})
		with self.assertLogs("deye_inverter_core.mqtt",logging.DEBUG) as logs:
			runtime.run_once("solarman_tcp")
		self.assertEqual(len(logs.records),1)
		self.assertIn("kind=sensors transport=solarman_tcp",logs.output[0])
		self.assertTrue(any(topic == "base/123/v" and value == 7 for topic,value,_ in mqtt._client.messages))

	def test_mqtt_batches_from_parallel_workers_have_separate_counts(self) -> None:
		mqtt=publisher()
		barrier=threading.Barrier(2)
		def send(transport,count):
			with mqtt.publication_batch("sensors",transport=transport):
				barrier.wait(timeout=2)
				for index in range(count):
					mqtt.publish_raw(SensorDefinition(f"v{index}","V",[100],"uint16"),[1])
		with self.assertLogs("deye_inverter_core.mqtt",logging.DEBUG) as logs:
			threads=[threading.Thread(target=send,args=("solarman_tcp",2)),threading.Thread(target=send,args=("modbus_rtu",3))]
			for thread in threads:
				thread.start()
			for thread in threads:
				thread.join(timeout=3)
			self.assertTrue(all(not thread.is_alive() for thread in threads))
		self.assertEqual(len(logs.records),2)
		self.assertTrue(any("transport=solarman_tcp confirmed=2" in item for item in logs.output))
		self.assertTrue(any("transport=modbus_rtu confirmed=3" in item for item in logs.output))

	def test_connection_outage_logs_once_and_recovers_only_after_successful_io(self) -> None:
		clock=ManualClock(0)
		slot=make_transport_slot("solarman_tcp",reconnect_delay=10)
		manager=TransportManager([slot],clock=clock)
		manager.run("solarman_tcp",lambda client:None)
		clock.value=100
		with self.assertLogs("deye_inverter_core.transport_manager",logging.DEBUG) as logs:
			with self.assertRaises(TransportConnectionClosedError):
				manager.run("solarman_tcp",closed)
			clock.value=105
			with self.assertRaises(TransportConnectionClosedError):
				manager.run("solarman_tcp",closed)
			clock.value=110
			with self.assertRaises(TransportConnectionClosedError):
				manager.run("solarman_tcp",closed)
			self.assertFalse(any("restored" in item for item in logs.output))
			clock.value=120
			manager.run("solarman_tcp",lambda client:7)
		self.assertEqual(sum(record.levelno == logging.WARNING for record in logs.records),1)
		self.assertEqual(sum("restored" in item for item in logs.output),1)
		self.assertTrue(any("outage_seconds=20.00" in item for item in logs.output))
		self.assertEqual(slot.status.connection_losses,1)
		self.assertEqual(slot.status.error_count,0)
		self.assertEqual(slot.status.last_outage_seconds,20)

	def test_three_hour_tcp_pattern_is_observed_without_proactive_disconnect_or_masking_errors(self) -> None:
		clock=ManualClock(0)
		slot=make_transport_slot("solarman_tcp",reconnect_delay=10)
		manager=TransportManager([slot],clock=clock)
		manager.run("solarman_tcp",lambda client:None)
		for loss_time in (100,10900):
			clock.value=loss_time
			with self.assertRaises(TransportConnectionClosedError):
				manager.run("solarman_tcp",closed)
			self.assertEqual(slot.status.error_count,1)
			clock.value+=10
			manager.run("solarman_tcp",lambda client:None)
		self.assertEqual(slot.status.connection_losses,2)
		self.assertEqual(slot.status.last_disconnect_interval_seconds,10800)
		self.assertTrue(slot.status.periodic_reset_detected)
		self.assertEqual(slot.client.reconnect_calls,2)

	def test_connection_loss_retries_due_read_after_reconnect_delay_not_sensor_interval(self) -> None:
		clock=ManualClock(0)
		slot=make_transport_slot("solarman_tcp",reconnect_delay=10)
		manager=TransportManager([slot],clock=clock)
		sensor=make_runtime_sensor("v",read_every=60)
		scheduler=PerEntityScheduler([sensor],slot.polling,clock=clock)
		attempts=[]
		def read(client,sensors,mark_attempted):
			mark_attempted(["v"])
			attempts.append(clock())
			if len(attempts) == 1:
				raise TransportConnectionClosedError("logger reset")
			return 7
		worker=TransportWorker(manager,slot,scheduler,read,clock=clock)
		with self.assertRaises(TransportConnectionClosedError):
			worker.run_due()
		self.assertEqual(worker.wait_time(),10)
		clock.value=10
		self.assertEqual(worker.run_due(),7)
		self.assertEqual(attempts,[0,10])

	def test_long_outage_is_not_hidden_and_rs485_is_not_classified_as_logger_reset(self) -> None:
		clock=ManualClock(0)
		slot=make_transport_slot("modbus_rtu",reconnect_delay=10)
		manager=TransportManager([slot],clock=clock)
		with self.assertLogs("deye_inverter_core.transport_manager",logging.DEBUG) as logs:
			for timestamp in (0,10,20,60,70):
				clock.value=timestamp
				with self.assertRaises(TransportConnectionClosedError):
					manager.run("modbus_rtu",closed)
		self.assertEqual(sum(record.levelno == logging.WARNING for record in logs.records),2)
		self.assertEqual(slot.status.connection_losses,1)
		self.assertEqual(slot.status.error_count,5)
		self.assertFalse(slot.status.periodic_reset_detected)

	def test_rs485_request_logs_range_response_and_time_without_traceback(self) -> None:
		client=FakeModbusSerialClient()
		transport=ModbusRtuTransport(make_rs485_config(),RecordingModbusClientFactory([client]))
		transport.connect()
		with self.assertLogs("deye_solarman_diagnostics.rs485",logging.DEBUG) as logs:
			self.assertEqual(transport.read_holding_registers(100,2),[101,202])
		self.assertTrue(any("start=100" in item and "count=2" in item for item in logs.output))
		self.assertTrue(any("result=ok" in item and "latency_ms=" in item and "0x0065" in item for item in logs.output))
		self.assertTrue(all(record.exc_info is None for record in logs.records))

	def test_tcp_failed_request_has_range_and_reason_without_raw_traceback(self) -> None:
		transport=SolarmanClient(make_solarman_config())
		transport._client=Mock()
		transport._client.read_holding_registers.side_effect=ConnectionResetError("logger reset")
		with self.assertLogs("deye_solarman_diagnostics.solarman",logging.DEBUG) as logs:
			with self.assertRaises(TransportConnectionClosedError):
				transport.read_holding_registers(10040,6)
		self.assertTrue(any("result=error" in item and "start=10040 count=6" in item and "logger reset" in item for item in logs.output))
		self.assertTrue(all(record.exc_info is None for record in logs.records))
