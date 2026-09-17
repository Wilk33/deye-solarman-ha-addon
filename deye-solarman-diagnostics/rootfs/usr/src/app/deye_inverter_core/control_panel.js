let controlSensors=[];
let controlTimer=null;
let controlBusy=false;

function controlMethodName(method)
{
	return t({
		NumberRWSensor:"controls.number",
		SelectRWSensor:"controls.select",
		SwitchRWSensor:"controls.switch",
		TimeRWSensor:"controls.time",
		SystemTimeRWSensor:"controls.system_time",
	}[method] || "status.unknown");
}

function controlMessage(message,error=false)
{
	byId("control-message").textContent=message;
	byId("control-message").style.color=error ? "var(--red)" : "var(--green)";
}

function controlField(entry,field,label,type="text")
{
	return `<label class="field">${esc(label)}<input data-control-key="${esc(entry.key)}" data-control-field="${field}" type="${type}" value="${esc(entry.definition[field])}"></label>`;
}

function controlCard(entry)
{
	const definition=entry.definition;
	const selector=transportSelector(entry,"control");
	const selectedScan=entry.last_scan?.[definition.transport] || entry.last_scan || {};
	const supported=transportBranches(entry).filter(([,result])=>result.status === "supported");
	const choices=definition.options && !definition.raw_only ? Object.entries(definition.options).map(([raw,label])=>`${raw}: ${label}`).join("; ") : "";
	const bounds=definition.method === "NumberRWSensor" ? (definition.max === null ? t("controls.range_unknown") : t("controls.range",{min:selectedScan.min ?? "?",max:selectedScan.max ?? "?",step:Math.abs(definition.factor)})) : "";
	const writeReason=definition.read_only_reason || selectedScan.write_reason;
	const selectedWritable=selectedScan.status === "supported" && selectedScan.write_allowed !== false && !definition.read_only;
	return `<article class="sensor ${entry.monitor ? "selected" : ""}">
		<div class="sensor-head"><div><h3>${esc(definition.name)}</h3><span class="key">${esc(entry.key)} / R${definition.registers.join(",")}</span>
		<div class="badges"><span class="badge">${esc(controlMethodName(definition.method))}</span></div></div>
		<label class="toggle"><input type="checkbox" data-control-monitor="${esc(entry.key)}" ${entry.monitor ? "checked" : ""} ${(!supported.length || (!selectedWritable && !entry.monitor)) ? "disabled" : ""}> ${esc(t("common.mqtt"))}</label></div>
		${transportResultCards(entry)}
		${writeReason ? `<p class="notice">${esc(writeReason)}</p>` : ""}
		<details><summary>${esc(t("controls.configure"))}</summary><div class="fields">
		${selector}
		${controlField(entry,"name",t("common.name"))}${controlField(entry,"icon",t("common.icon"))}
		${controlField(entry,"read_every",t("common.read_every"),"number")}${controlField(entry,"report_every",t("common.report_every"),"number")}
		${controlField(entry,"change_by",t("common.change_by"),"number")}
		<label class="toggle"><input type="checkbox" data-control-key="${esc(entry.key)}" data-control-field="retain" ${definition.retain ? "checked" : ""}> ${esc(t("common.retain"))}</label>
		<p class="notice wide">${esc(bounds)}<br>${esc(t("controls.mask"))}: ${definition.bitmask ? "0x"+definition.bitmask.toString(16).toUpperCase() : esc(t("controls.whole_register"))}${definition.shift ? `; ${esc(t("controls.shift",{value:definition.shift}))}` : ""}<br>${esc(choices)}<br>${esc(definition.read_only ? t("controls.read_only") : t("controls.write_method"))}</p>
		</div></details></article>`;
}

function renderControls()
{
	const query=byId("control-search").value.toLowerCase();
	const status=byId("control-filter").value;
	const filtered=controlSensors.filter(entry=>[entry.key,entry.definition.name,entry.definition.method,entry.definition.registers.join(",")].join(" ").toLowerCase().includes(query) && (status === "all" || transportBranches(entry).some(([,result])=>result.status === status)));
	const groups=new Map();
	for (const entry of filtered)
	{
		const method=entry.definition.method;
		if (!groups.has(method)) groups.set(method,[]);
		groups.get(method).push(entry);
	}
	byId("control-groups").innerHTML=[...groups].map(([method,entries])=>`<section class="group"><div class="group-title"><b>${esc(controlMethodName(method))}</b><small>${esc(t("common.entries",{value:entries.length}))}</small></div><div class="sensor-grid">${entries.map(controlCard).join("")}</div></section>`).join("");
	byId("control-empty").hidden=controlSensors.length !== 0;
	byId("control-total").textContent=controlSensors.length;
	byId("control-supported").textContent=controlSensors.filter(entry=>transportBranches(entry).some(([,result])=>result.status === "supported")).length;
	byId("control-selected").textContent=controlSensors.filter(entry=>entry.monitor).length;
	byId("control-other").textContent=controlSensors.filter(entry=>!transportBranches(entry).some(([,result])=>result.status === "supported")).length;
}

async function loadControls()
{
	controlSensors=(await request("api/controls")).available_sensors || [];
	renderControls();
}

async function controlAction(action)
{
	if (controlBusy) return;
	if (action === "reset" && !window.confirm(t("confirm.reset_controls"))) return;
	if (action === "delete" && !window.confirm(t("confirm.delete_controls"))) return;
	controlBusy=true;
	try
	{
		const fields=["name","icon","read_every","report_every","change_by","retain","transport"];
		const payload=action === "save" ? {sensors:controlSensors.map(entry=>({key:entry.key,monitor:entry.monitor,definition:Object.fromEntries(fields.map(field=>[field,entry.definition[field]]))}))} : {};
		await request(action === "save" ? "api/controls" : `api/controls/${action}`,{method:"POST",body:JSON.stringify(payload)});
		if (action === "scan") await controlScanStatus();
		else
		{
			await loadControls();
			controlMessage(t("messages.saved"));
		}
	}
	catch (error) { controlMessage(error.message,true); }
	finally { controlBusy=false; }
}

async function controlScanStatus()
{
	try
	{
		const job=await request("api/controls/scan-status");
		for (const action of ["scan","save","reset","delete"]) byId(`control-${action}`).disabled=job.status === "running";
		controlMessage(job.status === "failed" ? job.message : t(`scan.${job.status}`),job.status === "failed");
		if (job.status === "running") controlTimer=setTimeout(controlScanStatus,2000);
		else
		{
			clearTimeout(controlTimer);
			controlTimer=null;
			if (job.status === "completed") await loadControls();
		}
	}
	catch (error) { controlMessage(error.message,true); }
}

byId("control-tab").addEventListener("change",event=>
{
	const target=event.target;
	const key=target.dataset.controlKey || target.dataset.controlMonitor || target.dataset.controlTransport;
	const entry=controlSensors.find(item=>item.key === key);
	if (!entry) return;
	if (target.dataset.controlMonitor)
	{
		entry.monitor=target.checked;
		target.closest(".sensor").classList.toggle("selected",entry.monitor);
		byId("control-selected").textContent=controlSensors.filter(item=>item.monitor).length;
	}
	else if (target.dataset.controlTransport) entry.definition.transport=target.value;
	else entry.definition[target.dataset.controlField]=target.type === "checkbox" ? target.checked : target.value;
});

for (const action of ["scan","save","reset","delete"]) byId(`control-${action}`).addEventListener("click",()=>controlAction(action));
byId("control-search").addEventListener("input",renderControls);
byId("control-filter").addEventListener("change",renderControls);
if (window.i18nReady) window.i18nReady.then(()=>Promise.all([loadControls(),controlScanStatus()])).catch(error=>controlMessage(error.message,true));
