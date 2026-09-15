let controlSensors=[];
let controlTimer=null;
let controlBusy=false;
const controlMethodNames={NumberRWSensor:"Nastawy liczbowe",SelectRWSensor:"Listy wyboru",SwitchRWSensor:"Przełączniki",TimeRWSensor:"Godziny harmonogramu",SystemTimeRWSensor:"Data i czas"};

function controlMessage(message,error=false)
{
	byId("control-message").textContent=message;
	byId("control-message").style.color=error ? "var(--red)" : "var(--green)";
}

function controlField(entry,field,label,type="text")
{
	return `<label class="field">${label}<input data-control-key="${esc(entry.key)}" data-control-field="${field}" type="${type}" value="${esc(entry.definition[field])}"></label>`;
}

function controlCard(entry)
{
	const definition=entry.definition;
	const scan=entry.last_scan || {};
	const choices=definition.options ? Object.entries(definition.options).map(([raw,label])=>`${raw}: ${label}`).join("; ") : "";
	const bounds=definition.method === "NumberRWSensor" ? `Zakres: ${scan.min ?? "odczytywany"}..${scan.max ?? "odczytywany"}; krok: ${Math.abs(definition.factor)}` : "";
	return `<article class="sensor ${entry.monitor ? "selected" : ""}">
		<div class="sensor-head"><div><h3>${esc(definition.name)}</h3><span class="key">${esc(entry.key)} / R${definition.registers.join(",")}</span>
		<div class="reading"><b>${esc(scan.value ?? "-")} ${esc(definition.unit)}</b><div class="raw-line"><span class="raw-label">HEX</span><code>${esc((scan.raw_hex || []).join(", ") || "-")}</code></div></div>
		<div class="badges">${statusBadge(scan.status)}<span class="badge">${esc(controlMethodNames[definition.method])}</span></div>
		${scan.error ? `<p class="notice">${esc(scan.error)}</p>` : ""}</div>
		<label class="toggle"><input type="checkbox" data-control-monitor="${esc(entry.key)}" ${entry.monitor ? "checked" : ""} ${scan.status !== "supported" && !entry.monitor ? "disabled" : ""}> MQTT</label></div>
		<div class="fields"><button class="button secondary" type="button" data-control-test="${esc(entry.key)}">Test - odczytaj stan</button></div>
		<details><summary>Konfiguruj encję i odpytywanie</summary><div class="fields">
		${controlField(entry,"name","Nazwa")}${controlField(entry,"icon","Ikona")}
		${controlField(entry,"read_every","Odczyt co sekund","number")}${controlField(entry,"report_every","Ponowna publikacja co sekund","number")}
		${controlField(entry,"change_by","Próg zmiany","number")}
		<label class="toggle"><input type="checkbox" data-control-key="${esc(entry.key)}" data-control-field="retain" ${definition.retain ? "checked" : ""}> Zachowaj stan MQTT</label>
		<p class="notice wide">${esc(bounds)}<br>Maska: ${definition.bitmask ? "0x"+definition.bitmask.toString(16).toUpperCase() : "cały rejestr"}<br>${esc(choices)}<br>Metoda: odczyt, kodowanie wartości, zapis FC16, odczyt kontrolny.</p>
		</div></details></article>`;
}

function renderControls()
{
	const query=byId("control-search").value.toLowerCase();
	const status=byId("control-filter").value;
	const filtered=controlSensors.filter(entry=>[entry.key,entry.definition.name,entry.definition.method,entry.definition.registers.join(",")].join(" ").toLowerCase().includes(query) && (status === "all" || entry.last_scan?.status === status));
	const groups=new Map();
	for (const entry of filtered)
	{
		const method=entry.definition.method;
		if (!groups.has(method)) groups.set(method,[]);
		groups.get(method).push(entry);
	}
	byId("control-groups").innerHTML=[...groups].map(([method,entries])=>`<section class="group"><div class="group-title"><b>${esc(controlMethodNames[method])}</b><small>Liczba encji: ${entries.length}</small></div><div class="sensor-grid">${entries.map(controlCard).join("")}</div></section>`).join("");
	byId("control-empty").hidden=controlSensors.length !== 0;
	byId("control-total").textContent=controlSensors.length;
	byId("control-supported").textContent=controlSensors.filter(e=>e.last_scan?.status === "supported").length;
	byId("control-selected").textContent=controlSensors.filter(e=>e.monitor).length;
	byId("control-other").textContent=controlSensors.filter(e=>e.last_scan?.status !== "supported").length;
}

async function loadControls()
{
	controlSensors=(await request("api/controls")).available_sensors || [];
	renderControls();
}

async function controlAction(action)
{
	if (controlBusy) return;
	if (["reset","delete"].includes(action) && !window.confirm(action === "reset" ? "Przywrócić konfigurację encji sterowania i wyłączyć ich MQTT?" : "Usunąć lokalną listę encji sterowania oraz ich MQTT Discovery?")) return;
	controlBusy=true;
	try
	{
		const payload=action === "save" ? {sensors:controlSensors.map(entry=>({key:entry.key,monitor:entry.monitor,definition:Object.fromEntries(["name","icon","read_every","report_every","change_by","retain"].map(field=>[field,entry.definition[field]]))}))} : {};
		await request(action === "save" ? "api/controls" : `api/controls/${action}`,{method:"POST",body:JSON.stringify(payload)});
		if (action === "scan") await controlScanStatus();
		else
		{
			await loadControls();
			controlMessage("Zapisano. Encje MQTT zostaną automatycznie przeładowane.");
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
		controlMessage(job.message,job.status === "failed");
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
	const key=target.dataset.controlKey || target.dataset.controlMonitor;
	const entry=controlSensors.find(item=>item.key === key);
	if (!entry) return;
	if (target.dataset.controlMonitor)
	{
		entry.monitor=target.checked;
		target.closest(".sensor").classList.toggle("selected",entry.monitor);
		byId("control-selected").textContent=controlSensors.filter(e=>e.monitor).length;
	}
	else entry.definition[target.dataset.controlField]=target.type === "checkbox" ? target.checked : target.value;
});

byId("control-tab").addEventListener("click",async event=>
{
	const button=event.target.closest("[data-control-test]");
	if (!button) return;
	button.disabled=true;
	try
	{
		const result=await request("api/controls/test",{method:"POST",body:JSON.stringify({key:button.dataset.controlTest})});
		const entry=controlSensors.find(item=>item.key === button.dataset.controlTest);
		entry.last_scan=result;
		renderControls();
		controlMessage("Test zakończony: odczytano aktualny stan.");
	}
	catch (error) { controlMessage(error.message,true); }
	finally { button.disabled=false; }
});

for (const action of ["scan","save","reset","delete"]) byId(`control-${action}`).addEventListener("click",()=>controlAction(action));
byId("control-search").addEventListener("input",renderControls);
byId("control-filter").addEventListener("change",renderControls);
Promise.all([loadControls(),controlScanStatus()]).catch(error=>controlMessage(error.message,true));
