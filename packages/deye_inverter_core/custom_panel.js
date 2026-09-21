let customSensors=[];
let customSavedKeys=new Set();
let formulaModalKey=null;
let customActiveTransports=[];
if (typeof globalThis.t !== "function") globalThis.t=(key,variables={})=>Object.entries(variables).reduce((value,[name,replacement])=>value.replaceAll(`{${name}}`,String(replacement)),key);
if (typeof globalThis.transportName !== "function") globalThis.transportName=transport=>transport;
if (typeof globalThis.transportResultCards !== "function") globalThis.transportResultCards=()=>"";
if (typeof globalThis.transportSelector !== "function") globalThis.transportSelector=()=>"";
const customTransportIds=typeof TRANSPORT_IDS === "undefined" ? ["solarman_tcp","modbus_rtu"] : TRANSPORT_IDS;

function customEsc(value)
{
	return String(value ?? "").replace(/[&<>'"]/g,char=>{
		if (char.charCodeAt(0) === 34) return "&quot;";
		return {"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;"}[char];
	});
}

function customById(id)
{
	return document.getElementById(id);
}

async function customRequest(path,options={})
{
	const response=await fetch(new URL(path,document.baseURI).toString(),{headers:{"Content-Type":"application/json"},...options});
	const payload=await response.json();
	if (!response.ok) throw new Error(payload.error || t("messages.request_failed"));
	return payload;
}

function customDefaultDefinition(key)
{
	return {
		key,
		name:t("custom.default_name"),
		transport:"solarman_tcp",
		transports:["solarman_tcp","modbus_rtu"],
		registers:[10040],
		type:"uint16",
		multiplier:1,
		offset:0,
		unit:"",
		word_order:"high_low",
		byte_order:"high_low",
		schedule:"default",
		read_every:60,
		report_every:300,
		change_by:0,
		retain:true,
		device_class:"",
		state_class:"",
		icon:"",
		category:"",
		topic_suffix:key,
		formula:"",
		options:{},
		zero:"",
		unknown:"",
	};
}

function customReadSnapshot(definition,transport)
{
	const snapshot={
		registers:[...(definition.registers || [])],
		type:String(definition.type),
		formula:String(definition.formula || ""),
		multiplier:Number(definition.multiplier),
		offset:Number(definition.offset),
		word_order:String(definition.word_order),
		byte_order:String(definition.byte_order),
		transport,
	};
	if (definition.type === "enum" || definition.type === "bitmask") {
		snapshot.options={...(definition.options || {})};
		snapshot.zero=String(definition.zero || "");
		snapshot.unknown=String(definition.unknown || "");
	}
	return snapshot;
}

function customFrozenCopy(value)
{
	if (Array.isArray(value)) return Object.freeze(value.map(customFrozenCopy));
	if (value && typeof value === "object") {
		const copy={};
		for (const [key,item] of Object.entries(value)) copy[key]=customFrozenCopy(item);
		return Object.freeze(copy);
	}
	return value;
}

function customInput(key,field,label,value,type="text",wide=false)
{
	return `<label class="field ${wide ? "wide" : ""}">${label}<input data-custom-field="${customEsc(field)}" data-custom-key="${customEsc(key)}" type="${type}" value="${customEsc(value)}"></label>`;
}

function customTextarea(key,field,label,value,hint="")
{
	return `<label class="field wide">${label}<textarea data-custom-field="${customEsc(field)}" data-custom-key="${customEsc(key)}" spellcheck="false">${customEsc(value)}</textarea>${hint ? `<span class="key">${customEsc(hint)}</span>` : ""}</label>`;
}

function formatStatusOptions(options)
{
	return Object.entries(options || {}).sort(([left],[right])=>Number(left)-Number(right)).map(([value,label])=>`${value}=${label}`).join("\n");
}

function parseStatusOptions(value)
{
	const options={};
	for (const [index,line] of String(value || "").split(/\r?\n/).entries()) {
		if (!line.trim()) continue;
		const separator=line.indexOf("=");
		if (separator <= 0 || !line.slice(separator+1).trim()) throw new Error(t("messages.invalid_status_option",{line:index+1}));
		const key=Number(line.slice(0,separator).trim());
		if (!Number.isInteger(key) || key < 0) throw new Error(t("messages.invalid_status_option",{line:index+1}));
		options[key]=line.slice(separator+1).trim();
	}
	if (!Object.keys(options).length) throw new Error(t("messages.status_options_required"));
	return options;
}

function customSelect(key,field,label,current,values)
{
	const selected=values.includes(current) ? current : values[0];
	return `<label class="field">${label}<div class="select-control" data-select-control><input data-custom-field="${customEsc(field)}" data-custom-key="${customEsc(key)}" type="hidden" value="${customEsc(selected)}"><button class="select-trigger" type="button" data-select-trigger aria-haspopup="listbox" aria-expanded="false"><span class="select-value">${customEsc(selected === "auto" ? "-" : selected)}</span><span class="select-chevron">&#9662;</span></button><div class="select-options" role="listbox">${values.map(value=>`<button class="select-option ${value === selected ? "selected" : ""}" type="button" data-select-option data-value="${customEsc(value)}">${customEsc(value === "auto" ? "-" : value)}</button>`).join("")}</div></div></label>`;
}

function customResult(entry)
{
	if (!entry._test) return "";
	const lines=[];
	if (entry._test.error) return `<pre class="test-result error">${customEsc(t("messages.test_error",{error:entry._test.error}))}</pre>`;
	for (const result of entry._test.results || [entry._test.result || {}]) {
		if (result.transport) lines.push(`${transportName(result.transport)}: ${t(`status.${result.status || "supported"}`)}`);
		if (result.error) {
			lines.push(t("messages.test_error",{error:result.error}));
			continue;
		}
		for (const read of result.reads || []) lines.push(`R${read.register}: RAW ${(read.raw_hex || []).join(", ")} | ${read.type} x${read.multiplier} | ${read.value}`);
		if (result.raw_hex) lines.push(`RAW ${(result.raw_hex || []).join(", ")} | ${t("custom.test_value",{value:result.value})}`);
		else lines.push(t("custom.test_value",{value:result.value ?? t("custom.no_value")}));
	}
	return `<pre class="test-result">${customEsc(lines.join("\n"))}</pre>`;
}

function customTestSelector(entry)
{
	const allowed=entry.definition.transports || [entry.definition.transport || "solarman_tcp"];
	const online=Array.isArray(window.onlineTransportIds) ? window.onlineTransportIds : customActiveTransports;
	const available=customTransportIds.filter(transport=>allowed.includes(transport) && online.includes(transport));
	if (available.length === 1) {
		entry._testTransport=available[0];
		return `<input type="hidden" data-custom-test-transport="${customEsc(entry.key)}" value="${customEsc(available[0])}">`;
	}
	if (available.length === 2) {
		const testTransportSelection=entry._testTransport || entry.definition.transport || available[0];
		entry._testTransport=testTransportSelection;
		const choices=[...available,"both"];
		const label=testTransportSelection === "both" ? t("transport.both") : transportName(testTransportSelection);
		return `<label class="field wide">${customEsc(t("transport.test"))}<div class="select-control" data-select-control><input type="hidden" data-custom-test-transport="${customEsc(entry.key)}" value="${customEsc(testTransportSelection)}"><button class="select-trigger" type="button" data-select-trigger aria-haspopup="listbox" aria-expanded="false"><span class="select-value">${customEsc(label)}</span><span class="select-chevron">&#9662;</span></button><div class="select-options" role="listbox">${choices.map(transport=>`<button class="select-option ${testTransportSelection === transport ? "selected" : ""}" type="button" data-select-option data-value="${customEsc(transport)}">${customEsc(transport === "both" ? t("transport.both") : transportName(transport))}</button>`).join("")}</div></div></label>`;
	}
	return `<p class="notice wide">${customEsc(t("transport.unavailable"))}</p>`;
}

function customCard(entry)
{
	const definition=entry.definition;
	const formula=definition.type === "auto";
	const statusType=definition.type === "enum" || definition.type === "bitmask";
	const statusFields=statusType ? `
		${customTextarea(entry.key,"options",t("custom.status_options"),formatStatusOptions(definition.options),definition.type === "enum" ? t("custom.enum_hint") : t("custom.bitmask_hint"))}
		${customInput(entry.key,"zero",t("custom.zero_label"),definition.zero || "","text",true)}
		${customInput(entry.key,"unknown",t("custom.unknown_label"),definition.unknown || (definition.type === "enum" ? "Unknown ({value})" : "Bit {bit}"),"text",true)}` : "";
	const formulaFields=formula ? `
		<label class="field wide">${customEsc(t("common.formula"))}<textarea data-custom-formula data-custom-key="${customEsc(entry.key)}" spellcheck="false">${customEsc(definition.formula)}</textarea></label>
		<div class="formula-toolbar"><button class="button secondary" type="button" data-custom-test="${customEsc(entry.key)}">${customEsc(t("actions.test"))}</button><button class="button secondary" type="button" data-custom-expand="${customEsc(entry.key)}">${customEsc(t("actions.expand"))}</button><span class="key">${customEsc(t("custom.formula_hint"))}</span></div>` : `
		${customInput(entry.key,"registers",t("common.registers"),(definition.registers || []).join(","),"text",true)}
		${customSelect(entry.key,"type",t("common.register_type"),definition.type,["uint16","int16","uint32","int32","hex","ascii","enum","bitmask"])}
		${statusFields}
		${customInput(entry.key,"multiplier",t("common.multiplier"),definition.multiplier,"number")}
		${customInput(entry.key,"offset",t("common.offset"),definition.offset,"number")}
		${customSelect(entry.key,"word_order",t("common.word_order"),definition.word_order,["high_low","low_high"])}
		${customSelect(entry.key,"byte_order",t("common.byte_order"),definition.byte_order,["high_low","low_high"])}
		<div class="formula-toolbar"><button class="button secondary" type="button" data-custom-test="${customEsc(entry.key)}">${customEsc(t("actions.test_read"))}</button></div>`;
	return `<article class="custom-sensor ${entry.monitor ? "enabled" : ""}" data-custom-sensor="${customEsc(entry.key)}">
		<div class="sensor-head"><div><h3>${customEsc(definition.name || entry.key)}</h3><span class="key">${customEsc(entry.key)}${formula ? " / formula" : " / R"+customEsc((definition.registers || []).join(","))}</span></div><label class="toggle"><input data-custom-monitor="${customEsc(entry.key)}" type="checkbox" ${entry.monitor ? "checked" : ""}> ${customEsc(t("common.mqtt"))}</label></div>
		${transportResultCards(entry)}
		<div class="fields">
			${transportSelector(entry,"custom")}
			${customTestSelector(entry)}
			${customInput(entry.key,"name",t("common.name"),definition.name,"text",true)}
			${customInput(entry.key,"key",t("common.key"),entry.key,"text",true)}
			<label class="toggle wide"><input data-custom-formula-toggle="${customEsc(entry.key)}" type="checkbox" ${formula ? "checked" : ""}> ${customEsc(t("custom.formula"))}</label>
			${formulaFields}
			${customInput(entry.key,"unit",t("common.unit"),definition.unit)}
			${customSelect(entry.key,"schedule",t("common.schedule"),definition.schedule,["default","slow"])}
			${customInput(entry.key,"read_every",t("common.read_every"),definition.read_every,"number")}
			${customInput(entry.key,"report_every",t("common.report_every"),definition.report_every,"number")}
			${customInput(entry.key,"change_by",t("common.change_by"),definition.change_by,"number")}
			${customInput(entry.key,"device_class",t("common.device_class"),definition.device_class)}
			${customInput(entry.key,"state_class",t("common.state_class"),definition.state_class)}
			${customInput(entry.key,"icon",t("common.icon"),definition.icon)}
			${customInput(entry.key,"category",t("common.category"),definition.category)}
			${customInput(entry.key,"topic_suffix",t("common.topic_suffix"),definition.topic_suffix,"text",true)}
			<label class="toggle"><input data-custom-retain="${customEsc(entry.key)}" type="checkbox" ${definition.retain ? "checked" : ""}> ${customEsc(t("common.retain"))}</label>
			<div class="formula-toolbar"><button class="button danger" type="button" data-custom-delete="${customEsc(entry.key)}">${customEsc(t("common.delete"))}</button></div>
			${customResult(entry)}
		</div>
	</article>`;
}

function renderCustomSensors()
{
	customById("custom-sensor-list").innerHTML=customSensors.map(customCard).join("");
	customById("custom-empty").hidden=customSensors.length !== 0;
}

function parseRegisters(value)
{
	const text=String(value || "").trim();
	if (!text) return [];
	return text.split(/[\s,]+/).filter(Boolean).map(item=>{
		const parsed=Number(item);
		if (!Number.isInteger(parsed)) throw new Error(t("messages.invalid_register",{value:item}));
		return parsed;
	});
}

function collectCustomSensors()
{
	return customSensors.map(existing=>{
		const key=existing.key;
		const value=field=>document.querySelector(`[data-custom-field="${field}"][data-custom-key="${CSS.escape(key)}"]`)?.value ?? existing.definition[field];
		const formula=document.querySelector(`[data-custom-formula][data-custom-key="${CSS.escape(key)}"]`)?.value ?? existing.definition.formula;
		const formulaMode=document.querySelector(`[data-custom-formula-toggle="${CSS.escape(key)}"]`)?.checked ?? existing.definition.type === "auto";
		const selectedTransport=document.querySelector(`[data-custom-transport="${CSS.escape(key)}"]`)?.value || existing.definition.transport || "solarman_tcp";
		const testTransport=document.querySelector(`[data-custom-test-transport="${CSS.escape(key)}"]`)?.value || existing._testTransport || selectedTransport;
		const nextKey=String(value("key")).trim();
		const registerType=formulaMode ? "auto" : String(value("type"));
		const statusMode=registerType === "enum" || registerType === "bitmask";
		const optionsText=document.querySelector(`[data-custom-field="options"][data-custom-key="${CSS.escape(key)}"]`)?.value;
		const definition={
			...existing.definition,
			key:nextKey,
			transport:selectedTransport,
			name:String(value("name")).trim(),
			registers:formulaMode ? [] : parseRegisters(value("registers")),
			type:registerType,
			multiplier:formulaMode || statusMode ? 1 : Number(value("multiplier")),
			offset:formulaMode || statusMode ? 0 : Number(value("offset")),
			unit:String(value("unit")).trim(),
			word_order:formulaMode ? "high_low" : String(value("word_order")),
			byte_order:formulaMode ? "high_low" : String(value("byte_order")),
			schedule:String(value("schedule")),
			read_every:Number(value("read_every")),
			report_every:Number(value("report_every")),
			change_by:Number(value("change_by")),
			retain:document.querySelector(`[data-custom-retain="${CSS.escape(key)}"]`)?.checked ?? true,
			device_class:String(value("device_class")).trim(),
			state_class:String(value("state_class")).trim(),
			icon:String(value("icon")).trim(),
			category:String(value("category")).trim(),
			topic_suffix:String(value("topic_suffix")).trim() || nextKey,
			formula:formulaMode ? String(formula) : "",
			options:statusMode ? parseStatusOptions(optionsText ?? formatStatusOptions(existing.definition.options)) : {},
			zero:statusMode ? String(value("zero") || "").trim() : "",
			unknown:statusMode ? String(value("unknown") || "").trim() : "",
		};
		return {key:nextKey,monitor:document.querySelector(`[data-custom-monitor="${CSS.escape(key)}"]`)?.checked ?? true,definition,last_scan:existing.last_scan,_test:existing._test,_testTransport:testTransport};
	});
}

function captureCustomSensors()
{
	try {
		customSensors=collectCustomSensors();
	} catch (error) {
		throw error;
	}
}

async function loadCustomSensors()
{
	const payload=await customRequest("api/custom-sensors");
	customSensors=(payload.sensors || []).map(entry=>({...entry,_test:null,_testTransport:entry.definition.transport}));
	customSavedKeys=new Set(customSensors.map(entry=>entry.key));
	renderCustomSensors();
}

function addCustomSensor()
{
	try { captureCustomSensors(); } catch (error) { customMessage(error.message,true); return; }
	let index=customSensors.length+1;
	let key=`custom_sensor_${index}`;
	while (customSensors.some(entry=>entry.key === key)) {
		index+=1;
		key=`custom_sensor_${index}`;
	}
	customSensors.push({key,monitor:true,definition:customDefaultDefinition(key),_test:null,_testTransport:"solarman_tcp"});
	renderCustomSensors();
}

function customMessage(message,error=false)
{
	const target=customById("custom-save-message");
	target.style.color=error ? "var(--red)" : "var(--green)";
	target.textContent=message;
}

function customCurrentKey(key)
{
	return document.querySelector(`[data-custom-field="key"][data-custom-key="${CSS.escape(key)}"]`)?.value.trim() || key;
}

async function saveCustomSensors()
{
	try {
		captureCustomSensors();
		const payload=await customRequest("api/custom-sensors",{method:"POST",body:JSON.stringify({sensors:customSensors.map(({_test,_testTransport,...entry})=>entry)})});
		customSensors=(payload.sensors || []).map(entry=>({...entry,_test:null,_testTransport:entry.definition.transport}));
		customSavedKeys=new Set(customSensors.map(entry=>entry.key));
		customMessage(t("messages.saved"));
		renderCustomSensors();
	} catch (error) {
		customMessage(t("messages.save_error",{error:error.message}),true);
	}
}

async function testCustomSensor(key,formulaText=null)
{
	try {
		const currentKey=customCurrentKey(key);
		captureCustomSensors();
		const entry=customSensors.find(item=>item.key === currentKey);
		if (!entry) throw new Error(t("custom.no_sensor"));
		if (formulaText !== null) entry.definition.formula=formulaText;
		const selection=entry._testTransport || entry.definition.transport || "solarman_tcp";
		const transports=selection === "both" ? ["solarman_tcp","modbus_rtu"] : [selection];
		const testedDefinition=customFrozenCopy(entry.definition);
		const payload=await customRequest("api/custom-sensors/test",{method:"POST",body:JSON.stringify({definition:testedDefinition,transports})});
		const results=Array.isArray(payload.results) ? payload.results : [{...payload,transport:transports[0],status:"supported"}];
		for (const result of results) {
			const transport=result.transport;
			const definitionSnapshot=customFrozenCopy(customReadSnapshot(testedDefinition,transport));
			entry.last_scan={...(entry.last_scan || {}),[transport]:{...result,status:"supported",definition_snapshot:definitionSnapshot}};
			if (result.status !== "supported") entry.last_scan[transport].status=result.status;
		}
		entry._test={results};
		if (formulaModalKey === currentKey) {
			customById("formula-modal-result").textContent=customResult(entry).replace(/<[^>]+>/g,"");
			customById("formula-modal-result").hidden=false;
		}
		customMessage(t("custom.test_success"));
		renderCustomSensors();
	} catch (error) {
		const entry=customSensors.find(item=>item.key === customCurrentKey(key));
		if (entry) {
			const transport=entry._testTransport === "both" ? entry.definition.transport : entry._testTransport || entry.definition.transport || "solarman_tcp";
			const previousScan=entry.last_scan?.[transport] || {};
			entry.last_scan={...(entry.last_scan || {}),[transport]:{...previousScan,status:"timeout",error:error.message}};
			entry._test={error:error.message};
		}
		if (formulaModalKey === entry?.key) {
			customById("formula-modal-result").textContent=t("messages.test_error",{error:error.message});
			customById("formula-modal-result").hidden=false;
		}
		customMessage(t("messages.test_error",{error:error.message}),true);
		renderCustomSensors();
	}
}

async function deleteCustomSensor(key)
{
	if (!window.confirm(t("confirm.delete_custom"))) return;
	try {
		const currentKey=customCurrentKey(key);
		captureCustomSensors();
		if (customSavedKeys.has(key)) await customRequest(`api/custom-sensors/${encodeURIComponent(key)}`,{method:"DELETE"});
		customSensors=customSensors.filter(entry=>entry.key !== currentKey);
		customSavedKeys.delete(key);
		customMessage(t("messages.sensor_deleted"));
		renderCustomSensors();
	} catch (error) {
		customMessage(t("messages.delete_error",{error:error.message}),true);
	}
}

function toggleCustomFormula(key,enabled)
{
	try {
		const currentKey=customCurrentKey(key);
		captureCustomSensors();
		const entry=customSensors.find(item=>item.key === currentKey);
		if (!entry) return;
		if (enabled) {
			entry.definition.type="auto";
			entry.definition.registers=[];
			entry.definition.formula=entry.definition.formula || "value=sensor(R10040,uint16,0.1)\nreturn value";
		} else {
			entry.definition.type="uint16";
			entry.definition.registers=[10040];
			entry.definition.formula="";
		}
		renderCustomSensors();
	} catch (error) {
		customMessage(error.message,true);
	}
}

function expandFormula(key)
{
	try {
		const currentKey=customCurrentKey(key);
		captureCustomSensors();
		const entry=customSensors.find(item=>item.key === currentKey);
		if (!entry) return;
		formulaModalKey=currentKey;
		customById("formula-modal-title").textContent=entry.definition.name || t("common.formula");
		customById("formula-modal-key").textContent=entry.key;
		customById("formula-modal-editor").value=entry.definition.formula;
		customById("formula-modal-result").textContent=entry._test ? customResult(entry).replace(/<[^>]+>/g,"") : "";
		customById("formula-modal-result").hidden=!entry._test;
		customById("formula-modal").hidden=false;
		customById("formula-modal-editor").focus();
	} catch (error) {
		customMessage(error.message,true);
	}
}

function minimizeFormula()
{
	customById("formula-modal").hidden=true;
	formulaModalKey=null;
}

function applyFormula()
{
	if (!formulaModalKey) return;
	const entry=customSensors.find(item=>item.key === formulaModalKey);
	if (entry) entry.definition.formula=customById("formula-modal-editor").value;
	minimizeFormula();
	renderCustomSensors();
}

document.addEventListener("click",event=>{
	const tab=event.target.closest("[data-tab]");
	if (tab) {
		const custom=tab.dataset.tab === "custom";
		for (const panel of document.querySelectorAll(".tab-panel")) panel.hidden=panel.id !== `${tab.dataset.tab}-tab`;
		for (const item of document.querySelectorAll("[data-tab]")) item.classList.toggle("active",item === tab);
		if (custom && !customSensors.length) loadCustomSensors().catch(error=>customMessage(error.message,true));
	}
	const test=event.target.closest("[data-custom-test]");
	if (test) testCustomSensor(test.dataset.customTest);
	const expand=event.target.closest("[data-custom-expand]");
	if (expand) expandFormula(expand.dataset.customExpand);
	const remove=event.target.closest("[data-custom-delete]");
	if (remove) deleteCustomSensor(remove.dataset.customDelete);
});

document.addEventListener("change",event=>{
	const toggle=event.target.closest("[data-custom-formula-toggle]");
	if (toggle) toggleCustomFormula(toggle.dataset.customFormulaToggle,toggle.checked);
	const testTransport=event.target.closest("[data-custom-test-transport]");
	if (testTransport) {
		const entry=customSensors.find(item=>item.key === testTransport.dataset.customTestTransport);
		if (entry) entry._testTransport=testTransport.value;
	}
	const registerType=event.target.closest('[data-custom-field="type"]');
	if (registerType) {
		try { captureCustomSensors(); renderCustomSensors(); }
		catch (error) { customMessage(error.message,true); }
	}
});

customById("custom-add-button").addEventListener("click",addCustomSensor);
customById("custom-save-button").addEventListener("click",saveCustomSensors);
customById("formula-minimize-button").addEventListener("click",minimizeFormula);
customById("formula-apply-button").addEventListener("click",applyFormula);
customById("formula-modal-test-button").addEventListener("click",()=>{
	if (formulaModalKey) testCustomSensor(formulaModalKey,customById("formula-modal-editor").value);
});
if (window.i18nReady) window.i18nReady.then(async()=>{
	const runtime=await customRequest("api/runtime");
	customActiveTransports=(runtime.transports || []).filter(status=>status.online).map(status=>status.id);
	await loadCustomSensors();
}).catch(error=>customMessage(error.message,true));
