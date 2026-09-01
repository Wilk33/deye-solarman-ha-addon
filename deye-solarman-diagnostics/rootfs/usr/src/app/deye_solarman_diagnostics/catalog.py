from __future__ import annotations

from .models import SensorDefinition


LIVE_TELEMETRY_DATA=[
	("run_state","Run State",500,"uint16",1.0,0.0,"","","","slow"),
	("pv1_voltage","PV1 Voltage",676,"uint16",0.1,0.0,"V","voltage","measurement","default"),
	("pv1_current","PV1 Current",677,"uint16",0.1,0.0,"A","current","measurement","default"),
	("pv1_power","PV1 Power",672,"uint16",1.0,0.0,"W","power","measurement","default"),
	("pv2_voltage","PV2 Voltage",678,"uint16",0.1,0.0,"V","voltage","measurement","default"),
	("pv2_current","PV2 Current",679,"uint16",0.1,0.0,"A","current","measurement","default"),
	("pv2_power","PV2 Power",673,"uint16",1.0,0.0,"W","power","measurement","default"),
	("pv3_voltage","PV3 Voltage",680,"uint16",0.1,0.0,"V","voltage","measurement","default"),
	("pv3_current","PV3 Current",681,"uint16",0.1,0.0,"A","current","measurement","default"),
	("pv3_power","PV3 Power",674,"uint16",1.0,0.0,"W","power","measurement","default"),
	("pv4_voltage","PV4 Voltage",682,"uint16",0.1,0.0,"V","voltage","measurement","default"),
	("pv4_current","PV4 Current",683,"uint16",0.1,0.0,"A","current","measurement","default"),
	("pv4_power","PV4 Power",675,"uint16",1.0,0.0,"W","power","measurement","default"),
	("battery_soc","Battery SOC",588,"uint16",1.0,0.0,"%","battery","measurement","slow"),
	("battery_voltage","Battery Voltage",587,"uint16",0.01,0.0,"V","voltage","measurement","default"),
	("battery_current","Battery Current",591,"int16",0.01,0.0,"A","current","measurement","default"),
	("battery_power","Battery Power",590,"int16",1.0,0.0,"W","power","measurement","default"),
	("battery_temperature","Battery Temperature",586,"uint16",0.1,-100.0,"°C","temperature","measurement","default"),
	("battery_corrected_ah","Battery Corrected Capacity",592,"uint16",1.0,0.0,"Ah","","measurement","slow"),
	("grid_voltage_l1","Grid Voltage L1",598,"uint16",0.1,0.0,"V","voltage","measurement","default"),
	("grid_voltage_l2","Grid Voltage L2",599,"uint16",0.1,0.0,"V","voltage","measurement","default"),
	("grid_voltage_l3","Grid Voltage L3",600,"uint16",0.1,0.0,"V","voltage","measurement","default"),
	("grid_frequency","Grid Frequency",609,"uint16",0.01,0.0,"Hz","frequency","measurement","default"),
	("grid_power_l1","Grid Power L1",616,"int16",1.0,0.0,"W","power","measurement","default"),
	("grid_power_l2","Grid Power L2",617,"int16",1.0,0.0,"W","power","measurement","default"),
	("grid_power_l3","Grid Power L3",618,"int16",1.0,0.0,"W","power","measurement","default"),
	("grid_current_l1","Grid Current L1",613,"int16",0.01,0.0,"A","current","measurement","default"),
	("grid_current_l2","Grid Current L2",614,"int16",0.01,0.0,"A","current","measurement","default"),
	("grid_current_l3","Grid Current L3",615,"int16",0.01,0.0,"A","current","measurement","default"),
	("grid_power_total","Grid Power",619,"int16",1.0,0.0,"W","power","measurement","default"),
	("grid_internal_power","Grid Internal Total Power",607,"int16",1.0,0.0,"W","power","measurement","default"),
	("inverter_voltage_l1","Inverter Voltage L1",627,"uint16",0.1,0.0,"V","voltage","measurement","default"),
	("inverter_voltage_l2","Inverter Voltage L2",628,"uint16",0.1,0.0,"V","voltage","measurement","default"),
	("inverter_voltage_l3","Inverter Voltage L3",629,"uint16",0.1,0.0,"V","voltage","measurement","default"),
	("inverter_current_l1","Inverter Current L1",630,"int16",0.01,0.0,"A","current","measurement","default"),
	("inverter_current_l2","Inverter Current L2",631,"int16",0.01,0.0,"A","current","measurement","default"),
	("inverter_current_l3","Inverter Current L3",632,"int16",0.01,0.0,"A","current","measurement","default"),
	("inverter_power_total","Inverter Power",636,"int16",1.0,0.0,"W","power","measurement","default"),
	("inverter_frequency","Inverter Frequency",638,"uint16",0.01,0.0,"Hz","frequency","measurement","default"),
	("load_voltage_l1","Load Voltage L1",644,"uint16",0.1,0.0,"V","voltage","measurement","default"),
	("load_voltage_l2","Load Voltage L2",645,"uint16",0.1,0.0,"V","voltage","measurement","default"),
	("load_voltage_l3","Load Voltage L3",646,"uint16",0.1,0.0,"V","voltage","measurement","default"),
	("load_power_l1","Load Power L1",650,"int16",1.0,0.0,"W","power","measurement","default"),
	("load_power_l2","Load Power L2",651,"int16",1.0,0.0,"W","power","measurement","default"),
	("load_power_l3","Load Power L3",652,"int16",1.0,0.0,"W","power","measurement","default"),
	("load_power_total","Load Power",653,"int16",1.0,0.0,"W","power","measurement","default"),
	("load_frequency","Load Frequency",655,"uint16",0.01,0.0,"Hz","frequency","measurement","default"),
	("ups_power_total","Backup Power",643,"uint16",1.0,0.0,"W","power","measurement","default"),
	("gen_voltage_l1","Generator Voltage L1",661,"uint16",0.1,0.0,"V","voltage","measurement","default"),
	("gen_power_total","Generator Power",667,"int16",1.0,0.0,"W","power","measurement","default"),
	("ac_temperature","AC Temperature",541,"uint16",0.1,-100.0,"°C","temperature","measurement","default"),
	("dc_temperature","DC Temperature",540,"uint16",0.1,-100.0,"°C","temperature","measurement","default"),
	("energy_gen_today","Grid Generation Today",501,"int16",0.1,0.0,"kWh","energy","total","slow"),
	("pv_energy_today","PV Production Today",529,"uint16",0.1,0.0,"kWh","energy","total","slow"),
	("pv1_energy_today","PV1 Production Today",530,"uint16",0.1,0.0,"kWh","energy","total","slow"),
	("pv2_energy_today","PV2 Production Today",531,"uint16",0.1,0.0,"kWh","energy","total","slow"),
	("battery_charge_today","Battery Charge Today",514,"uint16",0.1,0.0,"kWh","energy","total","slow"),
	("battery_discharge_today","Battery Discharge Today",515,"uint16",0.1,0.0,"kWh","energy","total","slow"),
	("grid_import_today","Grid Import Today",520,"uint16",0.1,0.0,"kWh","energy","total","slow"),
	("grid_export_today","Grid Export Today",521,"uint16",0.1,0.0,"kWh","energy","total","slow"),
	("load_energy_today","Load Consumption Today",526,"uint16",0.1,0.0,"kWh","energy","total","slow"),
]


TOTAL_ENERGY_DATA=[
	("energy_gen_total","Grid Generation Total",504),
	("pv_energy_total","PV Production Total",534),
	("battery_charge_total","Battery Charge Total",516),
	("battery_discharge_total","Battery Discharge Total",518),
	("grid_import_total","Grid Import Total",522),
	("grid_export_total","Grid Export Total",524),
	("load_energy_total","Load Consumption Total",527),
]


def build_live_telemetry() -> list[SensorDefinition]:
	sensors=[
		SensorDefinition(
			key=key,
			name=name,
			registers=[address],
			register_type=register_type,
			multiplier=multiplier,
			offset=offset,
			unit=unit,
			device_class=device_class,
			state_class=state_class,
			schedule=schedule,
			read_every=60,
			report_every=300,
		)
		for key,name,address,register_type,multiplier,offset,unit,device_class,state_class,schedule in LIVE_TELEMETRY_DATA
	]
	for key,name,address in TOTAL_ENERGY_DATA:
		sensors.append(
			SensorDefinition(
				key=key,
				name=name,
				registers=[address,address+1],
				register_type="uint32",
				multiplier=0.1,
				unit="kWh",
				word_order="low_high",
				schedule="slow",
				read_every=600,
				report_every=900,
				device_class="energy",
				state_class="total_increasing",
			)
		)
	return sensors


def build_bms_pack_sensors(pack_count: int) -> list[SensorDefinition]:
	sensors: list[SensorDefinition]=[]
	for pack in range(1,pack_count+1):
		base=10032+(pack-1)*38
		prefix=f"battery_{pack}"
		name_prefix=f"Battery {pack}"
		sensors.extend(
			[
				SensorDefinition(f"{prefix}_bms_serial",f"{name_prefix} BMS Serial",list(range(base,base+8)),"hex",schedule="slow",read_every=3600,report_every=3600),
				SensorDefinition(f"{prefix}_voltage",f"{name_prefix} Voltage",[base+8],"uint16",0.1,unit="V",device_class="voltage",state_class="measurement",topic_suffix=f"battery_{pack}/voltage"),
				SensorDefinition(f"{prefix}_current",f"{name_prefix} Current",[base+9],"int16",0.1,unit="A",device_class="current",state_class="measurement",topic_suffix=f"battery_{pack}/current"),
				SensorDefinition(f"{prefix}_temperature",f"{name_prefix} Temperature",[base+10],"uint16",0.1,-100.0,"°C",device_class="temperature",state_class="measurement",topic_suffix=f"battery_{pack}/temperature"),
				SensorDefinition(f"{prefix}_soc",f"{name_prefix} SOC",[base+15],"uint16",0.1,unit="%",schedule="slow",read_every=600,report_every=600,change_by=0.1,device_class="battery",state_class="measurement",topic_suffix=f"battery_{pack}/soc"),
				SensorDefinition(f"{prefix}_soh",f"{name_prefix} SOH",[base+16],"uint16",0.1,unit="%",schedule="slow",read_every=600,report_every=900,device_class="battery",state_class="measurement",topic_suffix=f"battery_{pack}/soh"),
				SensorDefinition(f"{prefix}_capacity",f"{name_prefix} Capacity",[base+18],"uint16",0.1,unit="Ah",schedule="slow",read_every=600,report_every=900,topic_suffix=f"battery_{pack}/capacity"),
				SensorDefinition(f"{prefix}_max_cell_voltage",f"{name_prefix} Max Cell Voltage",[base+22],"uint16",0.001,unit="V",schedule="slow",read_every=600,report_every=900,device_class="voltage",state_class="measurement",topic_suffix=f"battery_{pack}/max_cell_voltage"),
				SensorDefinition(f"{prefix}_min_cell_voltage",f"{name_prefix} Min Cell Voltage",[base+23],"uint16",0.001,unit="V",schedule="slow",read_every=600,report_every=900,device_class="voltage",state_class="measurement",topic_suffix=f"battery_{pack}/min_cell_voltage"),
				SensorDefinition(f"{prefix}_cycles",f"{name_prefix} Cycles",[base+24],"uint16",schedule="slow",read_every=3600,report_every=3600,state_class="total_increasing",topic_suffix=f"battery_{pack}/cycles"),
				SensorDefinition(f"{prefix}_mos",f"{name_prefix} BMS MOS",[base+25],"hex",schedule="slow",read_every=600,report_every=900,topic_suffix=f"battery_{pack}/mos"),
				SensorDefinition(f"{prefix}_alarm",f"{name_prefix} BMS Alarm",list(range(base+26,base+30)),"hex",schedule="slow",read_every=600,report_every=900,topic_suffix=f"battery_{pack}/alarm"),
				SensorDefinition(f"{prefix}_software_version",f"{name_prefix} BMS Software Version",[base+30],"hex",schedule="slow",read_every=3600,report_every=3600,topic_suffix=f"battery_{pack}/software_version"),
				SensorDefinition(f"{prefix}_hardware_version",f"{name_prefix} BMS Hardware Version",[base+31],"hex",schedule="slow",read_every=3600,report_every=3600,topic_suffix=f"battery_{pack}/hardware_version"),
			]
		)
	return sensors
