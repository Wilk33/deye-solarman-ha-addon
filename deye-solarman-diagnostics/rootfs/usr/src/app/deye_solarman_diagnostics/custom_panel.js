let customSensors=[];
let customSavedKeys=new Set();
let formulaModalKey=null;

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
	if (!response.ok) throw new Error(payload.error || "Request failed");
	return payload;
}

function customDefaultDefinition(key)
{
	return {
		key,
		name:"Custom sensor",
		registers:[10040],
		type:"uint16",
		multiplier:1,
		offset:0,
		unit:"",
		word_order:"high_low",
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
	};
}

function customInput(key,field,label,value,type="text",wide=false)
{
	return `<label class="field ${wide ? "wide" : ""}">${label}<input data-custom-field="${customEsc(field)}" data-custom-key="${customEsc(key)}" type="${type}" value="${customEsc(value)}"></label>`;
}

function customSelect(key,field,label,current,values)
{
	const selected=values.includes(current) ? current : values[0];
	return `<label class="field">${label}<div class="select-control" data-select-control><input data-custom-field="${customEsc(field)}" data-custom-key="${customEsc(key)}" type="hidden" value="${customEsc(selected)}"><button class="select-trigger" type="button" data-select-trigger aria-haspopup="listbox" aria-expanded="false"><span class="select-value">${customEsc(selected === "auto" ? "-" : selected)}</span><span class="select-chevron">&#9662;</span></button><div class="select-options" role="listbox">${values.map(value=>`<button class="select-option ${value === selected ? "selected" : ""}" type="button" data-select-option data-value="${customEsc(value)}">${customEsc(value === "auto" ? "-" : value)}</button>`).join("")}</div></div></label>`;
}

function customResult(entry)
{
	if (!entry._test) return "";
	if (entry._test.error) return `<pre class="test-result error">Blad testu: ${customEsc(entry._test.error)}</pre>`;
	const result=entry._test.result || {};
	const reads=result.reads || [];
	const lines=[];
	for (const read of reads) {
		lines.push(`R${read.register}: RAW ${(read.raw_hex || []).join(", ")} | ${read.type} x${read.multiplier} | ${read.value}`);
	}
	if (result.raw_hex) lines.push(`RAW ${(result.raw_hex || []).join(", ")} | wynik ${result.value}`);
	else lines.push(`Wynik: ${result.value ?? "brak wartosci"}`);
	return `<pre class="test-result">${customEsc(lines.join("\n"))}</pre>`;
}

function customCard(entry)
{
	const definition=entry.definition;
	const formula=definition.type === "auto";
	const formulaFields=formula ? `
		<label class="field wide">Formula<textarea data-custom-formula data-custom-key="${customEsc(entry.key)}" spellcheck="false">${customEsc(definition.formula)}</textarea></label>
		<div class="formula-toolbar"><button class="button secondary" type="button" data-custom-test="${customEsc(entry.key)}">Test</button><button class="button secondary" type="button" data-custom-expand="${customEsc(entry.key)}">Powieksz</button><span class="key">Typ - oznacza wynik return bez dodatkowego dekodowania.</span></div>` : `
		${customInput(entry.key,"registers","Rejestry, rozdziel przecinkami",(definition.registers || []).join(","),"text",true)}
		${customSelect(entry.key,"type","Typ rejestru",definition.type,["uint16","int16","uint32","int32","hex","ascii"])}
		${customInput(entry.key,"multiplier","Mnoznik",definition.multiplier,"number")}
		${customInput(entry.key,"offset","Offset",definition.offset,"number")}
		${customSelect(entry.key,"word_order","Kolejnosc slow",definition.word_order,["high_low","low_high"])}`;
	return `<article class="custom-sensor ${entry.monitor ? "enabled" : ""}" data-custom-sensor="${customEsc(entry.key)}">
		<div class="sensor-head"><div><h3>${customEsc(definition.name || entry.key)}</h3><span class="key">${customEsc(entry.key)}${formula ? " / formula" : " / R"+customEsc((definition.registers || []).join(","))}</span></div><label class="toggle"><input data-custom-monitor="${customEsc(entry.key)}" type="checkbox" ${entry.monitor ? "checked" : ""}> MQTT</label></div>
		<div class="fields">
			${customInput(entry.key,"name","Nazwa",definition.name,"text",true)}
			${customInput(entry.key,"key","Klucz MQTT",entry.key,"text",true)}
			<label class="toggle wide"><input data-custom-formula-toggle="${customEsc(entry.key)}" type="checkbox" ${formula ? "checked" : ""}> Wlasna formula</label>
			${formulaFields}
			${customInput(entry.key,"unit","Jednostka",definition.unit)}
			${customSelect(entry.key,"schedule","Harmonogram",definition.schedule,["default","slow"])}
			${customInput(entry.key,"read_every","Odczyt co sekundy",definition.read_every,"number")}
			${customInput(entry.key,"report_every","Ponowna publikacja co sekundy",definition.report_every,"number")}
			${customInput(entry.key,"change_by","Prog zmiany",definition.change_by,"number")}
			${customInput(entry.key,"device_class","Klasa urzadzenia HA",definition.device_class)}
			${customInput(entry.key,"state_class","Klasa stanu HA",definition.state_class)}
			${customInput(entry.key,"icon","Ikona",definition.icon)}
			${customInput(entry.key,"category","Kategoria",definition.category)}
			${customInput(entry.key,"topic_suffix","Sufiks MQTT",definition.topic_suffix,"text",true)}
			<label class="toggle"><input data-custom-retain="${customEsc(entry.key)}" type="checkbox" ${definition.retain ? "checked" : ""}> Zachowaj stan MQTT</label>
			<div class="formula-toolbar"><button class="button danger" type="button" data-custom-delete="${customEsc(entry.key)}">Usun</button></div>
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
		if (!Number.isInteger(parsed)) throw new Error(`Nieprawidlowy rejestr: ${item}`);
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
		const nextKey=String(value("key")).trim();
		const definition={
			...existing.definition,
			key:nextKey,
			name:String(value("name")).trim(),
			registers:formulaMode ? [] : parseRegisters(value("registers")),
			type:formulaMode ? "auto" : String(value("type")),
			multiplier:formulaMode ? 1 : Number(value("multiplier")),
			offset:formulaMode ? 0 : Number(value("offset")),
			unit:String(value("unit")).trim(),
			word_order:formulaMode ? "high_low" : String(value("word_order")),
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
		};
		return {key:nextKey,monitor:document.querySelector(`[data-custom-monitor="${CSS.escape(key)}"]`)?.checked ?? true,definition,_test:existing._test};
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
	customSensors=(payload.sensors || []).map(entry=>({...entry,_test:null}));
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
	customSensors.push({key,monitor:true,definition:customDefaultDefinition(key),_test:null});
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
		const payload=await customRequest("api/custom-sensors",{method:"POST",body:JSON.stringify({sensors:customSensors.map(({_test,...entry})=>entry)})});
		customSensors=(payload.sensors || []).map(entry=>({...entry,_test:null}));
		customSavedKeys=new Set(customSensors.map(entry=>entry.key));
		customMessage("Zapisano. Polaczenia Solarman i MQTT zostaly automatycznie przeladowane.");
		renderCustomSensors();
	} catch (error) {
		customMessage(`Blad zapisu: ${error.message}`,true);
	}
}

async function testCustomSensor(key,formulaText=null)
{
	try {
		const currentKey=customCurrentKey(key);
		captureCustomSensors();
		const entry=customSensors.find(item=>item.key === currentKey);
		if (!entry) throw new Error("Nie znaleziono sensora");
		if (formulaText !== null) entry.definition.formula=formulaText;
		const result=await customRequest("api/custom-sensors/test",{method:"POST",body:JSON.stringify({definition:entry.definition})});
		entry._test={result};
		if (formulaModalKey === currentKey) {
			customById("formula-modal-result").textContent=customResult(entry).replace(/<[^>]+>/g,"");
			customById("formula-modal-result").hidden=false;
		}
		customMessage("Test zakonczony pomyslnie.");
		renderCustomSensors();
	} catch (error) {
		const entry=customSensors.find(item=>item.key === customCurrentKey(key));
		if (entry) entry._test={error:error.message};
		if (formulaModalKey === entry?.key) {
			customById("formula-modal-result").textContent=`Blad testu: ${error.message}`;
			customById("formula-modal-result").hidden=false;
		}
		customMessage(`Blad testu: ${error.message}`,true);
		renderCustomSensors();
	}
}

async function deleteCustomSensor(key)
{
	if (!window.confirm("Usunac ten wlasny sensor i jego MQTT Discovery?")) return;
	try {
		const currentKey=customCurrentKey(key);
		captureCustomSensors();
		if (customSavedKeys.has(key)) await customRequest(`api/custom-sensors/${encodeURIComponent(key)}`,{method:"DELETE"});
		customSensors=customSensors.filter(entry=>entry.key !== currentKey);
		customSavedKeys.delete(key);
		customMessage("Usunieto sensor. MQTT Discovery zostanie automatycznie zaktualizowane.");
		renderCustomSensors();
	} catch (error) {
		customMessage(`Blad usuwania: ${error.message}`,true);
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
		customById("formula-modal-title").textContent=entry.definition.name || "Formula";
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
		customById("detected-tab").hidden=custom;
		customById("custom-tab").hidden=!custom;
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
});

customById("custom-add-button").addEventListener("click",addCustomSensor);
customById("custom-save-button").addEventListener("click",saveCustomSensors);
customById("formula-minimize-button").addEventListener("click",minimizeFormula);
customById("formula-apply-button").addEventListener("click",applyFormula);
customById("formula-modal-test-button").addEventListener("click",()=>{
	if (formulaModalKey) testCustomSensor(formulaModalKey,customById("formula-modal-editor").value);
});
loadCustomSensors().catch(error=>customMessage(error.message,true));
