import test from "node:test";
import assert from "node:assert/strict";

import {
	describeDefinition,
	extractDefinitions,
	filterDefinitions,
	normalizeSearchValue,
	parseReferenceState,
	selectAvailableMap,
	updateReferenceUrl,
} from "../site/assets/reference.mjs";


const definitions=[
	{
		key:"run_state",
		name:"<img src=x onerror=alert(1)>",
		registers:[500],
		type:"enum",
		options:{"2":"Normal"},
		category:"diagnostic",
		_referenceTransports:["solarman_tcp","modbus_rtu"],
		_referenceWritable:false,
		_referenceRegisterCount:1,
		_referenceRange:"none",
	},
	{
		key:"warning_flags",
		name:"Warning Flags",
		registers:[553,554],
		type:"bitmask",
		zero:"No warnings",
		unknown:"W{code:02d}",
		category:"diagnostic",
		_referenceTransports:["modbus_rtu"],
		_referenceWritable:false,
		_referenceRegisterCount:2,
		_referenceRange:"none",
	},
	{
		key:"control_battery_current",
		name:"Battery Current",
		registers:[108],
		method:"NumberRWSensor",
		type:"uint16",
		unit:"A",
		min:0,
		max:{registers:[20,21],name:"Rated power",values:{"10000":210}},
		category:"battery",
		_referenceTransports:["solarman_tcp"],
		_referenceWritable:true,
		_referenceRegisterCount:1,
		_referenceRange:"dynamic",
	},
];


test("normalizes diacritics and case for search",()=>
{
	assert.equal(normalizeSearchValue("  Napięcie ŁÓDŹ  "),"napiecie lodz");
});


test("searches by register, enum option, zero and unknown labels",()=>
{
	assert.deepEqual(filterDefinitions(definitions,{query:"500"}).map(item=>item.key),["run_state"]);
	assert.deepEqual(filterDefinitions(definitions,{query:"normal"}).map(item=>item.key),["run_state"]);
	assert.deepEqual(filterDefinitions(definitions,{query:"no warnings"}).map(item=>item.key),["warning_flags"]);
	assert.deepEqual(filterDefinitions(definitions,{query:"code:02d"}).map(item=>item.key),["warning_flags"]);
});


test("applies category transport type access count and range filters",()=>
{
	assert.deepEqual(filterDefinitions(definitions,{category:"battery"}).map(item=>item.key),["control_battery_current"]);
	assert.deepEqual(filterDefinitions(definitions,{transport:"modbus_rtu"}).map(item=>item.key),["run_state","warning_flags"]);
	assert.deepEqual(filterDefinitions(definitions,{type:"bitmask"}).map(item=>item.key),["warning_flags"]);
	assert.deepEqual(filterDefinitions(definitions,{access:"write"}).map(item=>item.key),["control_battery_current"]);
	assert.deepEqual(filterDefinitions(definitions,{access:"read"}).map(item=>item.key),["run_state","warning_flags"]);
	assert.deepEqual(filterDefinitions(definitions,{registerCount:"multiple"}).map(item=>item.key),["warning_flags"]);
	assert.deepEqual(filterDefinitions(definitions,{range:"dynamic"}).map(item=>item.key),["control_battery_current"]);
	assert.deepEqual(filterDefinitions(definitions,{type:"enum"}).map(item=>item.key),["run_state"]);
});


test("extracts telemetry and control definitions without mutating catalogs",()=>
{
	const telemetry={catalog:{map_id:"telemetry",writable:false,transports:["solarman_tcp"],sensors:[{key:"a",registers:[1]}]}};
	const control={catalog:{map_id:"control",writable:true,transports:["modbus_rtu"],commands:[
		{key:"b",registers:[2],min:0,max:100},
		{key:"c",registers:[3],read_only:true},
	]}};
	const sensor=extractDefinitions(telemetry)[0];
	const [command,readOnlyCommand]=extractDefinitions(control);
	assert.equal(sensor._referenceWritable,false);
	assert.deepEqual(sensor._referenceTransports,["solarman_tcp"]);
	assert.equal(command._referenceWritable,true);
	assert.equal(readOnlyCommand._referenceWritable,false);
	assert.equal(command._referenceRange,"fixed");
	assert.equal("_referenceWritable" in telemetry.catalog.sensors[0],false);
});


test("round trips model map filters query and hash",()=>
{
	const source=new URL("https://example.test/reference/?model=sample&map=telemetry&q=battery&category=pv&transport=modbus_rtu&type=uint16&access=read&count=multiple&range=dynamic#run_state");
	const state=parseReferenceState(source);
	assert.deepEqual(state,{
		model:"sample",map:"telemetry",query:"battery",category:"pv",transport:"modbus_rtu",
		type:"uint16",access:"read",registerCount:"multiple",range:"dynamic",definition:"run_state",
	});
	assert.deepEqual(parseReferenceState(new URL(updateReferenceUrl(source,state))),state);
});


test("falls back to the first available map exposed by a model",()=>
{
	assert.equal(selectAvailableMap({maps:{control:{data_path:"control.json"}}},"telemetry"),"control");
	assert.equal(selectAvailableMap({maps:{telemetry:{},control:{}}},"control"),"control");
	assert.equal(selectAvailableMap({maps:{}},"telemetry"),null);
});


test("describes dynamic range without flattening it to a false number",()=>
{
	const description=describeDefinition(definitions[2],{map_id:"control",writable:true});
	assert.equal(description.range.kind,"dynamic");
	assert.deepEqual(description.range.maximum.registers,[20,21]);
	assert.equal(description.range.maximum.values["10000"],210);
	assert.equal(description.access,"write");
});
