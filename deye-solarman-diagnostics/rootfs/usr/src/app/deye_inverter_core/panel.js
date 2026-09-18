console.info("[SolarMan Diagnostics] external diagnostics script loaded",{
	href:window.location.href,
	base:document.baseURI,
});

window.addEventListener("error",event=>{
	console.error("[SolarMan Diagnostics] captured browser error",event.error || event.message);
});

window.addEventListener("unhandledrejection",event=>{
	console.error("[SolarMan Diagnostics] captured promise rejection",event.reason);
});

const TRANSPORT_IDS=["solarman_tcp","modbus_rtu"];
let translations={};

function normalizePanelLanguage(value)
{
	const primary=String(value || "").trim().toLowerCase().split(",",1)[0].split(";",1)[0].split("-",1)[0];
	return primary === "en" ? "en" : "pl";
}

function t(key,variables={})
{
	let value=translations[key] || key;
	for (const [name,replacement] of Object.entries(variables)) value=value.replaceAll(`{${name}}`,String(replacement));
	return value;
}

function panelEsc(value)
{
	return String(value ?? "").replace(/[&<>'"]/g,char=>{
		if (char.charCodeAt(0) === 34) return "&quot;";
		return {"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;"}[char];
	});
}

function applyTranslations(root=document)
{
	for (const element of root.querySelectorAll("[data-i18n]")) element.textContent=t(element.dataset.i18n);
	for (const element of root.querySelectorAll("[data-i18n-placeholder]")) element.placeholder=t(element.dataset.i18nPlaceholder);
	for (const element of root.querySelectorAll("[data-i18n-aria-label]")) element.setAttribute("aria-label",t(element.dataset.i18nAriaLabel));
	document.title=t("app.title");
}

function transportName(transportId)
{
	return t(`transport.${transportId}`);
}

function transportBranches(entry)
{
	const definition=entry.definition || {};
	const allowed=Array.isArray(definition.transports) && definition.transports.length ? definition.transports : [definition.transport || "solarman_tcp"];
	return TRANSPORT_IDS.filter(transport=>allowed.includes(transport)).map(transport=>[
		transport,
		entry.last_scan?.[transport] || {status:"unavailable"},
	]);
}

function transportResultCards(entry)
{
	return `<div class="transport-results">${transportBranches(entry).map(([transport,result])=>{
		const runtime=window.transportRuntimeById?.[transport];
		const runtimeBadge=runtime ? statusBadge(runtime.online ? "online" : "offline") : "";
		const raw=(result.raw_hex || []).join(", ") || (result.raw_registers || []).join(", ");
		const value=result.value === null || result.value === undefined ? "" : `<div><b>${panelEsc(t("result.value"))}:</b> ${panelEsc(result.value)} ${panelEsc(entry.definition?.unit || "")}</div>`;
		const rawLine=raw ? `<div><b>${panelEsc(t("result.raw"))}:</b> <code>${panelEsc(raw)}</code></div>` : "";
		const latency=result.latency_ms === null || result.latency_ms === undefined ? "" : `<div><b>${panelEsc(t("result.latency"))}:</b> ${panelEsc(result.latency_ms)} ms</div>`;
		const error=result.error || result.message;
		return `<section class="transport-result ${panelEsc(result.status || "unavailable")}" data-transport-result="${panelEsc(transport)}"><header><strong>${panelEsc(transportName(transport))}</strong><span class="badges">${statusBadge(result.status || "unavailable")}${runtimeBadge}</span></header>${value}${rawLine}${latency}${error ? `<p class="transport-error"><b>${panelEsc(t("result.error"))}:</b> ${panelEsc(error)}</p>` : ""}</section>`;
	}).join("")}</div>`;
}

function transportSelector(entry,prefix="")
{
	const definition=entry.definition || {};
	const branches=transportBranches(entry);
	const online=Array.isArray(window.onlineTransportIds) ? window.onlineTransportIds : TRANSPORT_IDS;
	const supported=branches.filter(([transport,result])=>result.status === "supported" && online.includes(transport)).map(([transport])=>transport);
	const attribute=`data-${prefix ? `${prefix}-` : ""}transport="${panelEsc(entry.key)}"`;
	if (supported.length === 1) {
		definition.transport=supported[0];
		return `<input type="hidden" ${attribute} value="${panelEsc(supported[0])}">`;
	}
	if (supported.length === 2) {
		if (!supported.includes(definition.transport)) definition.transport="";
		const selectedLabel=definition.transport ? transportName(definition.transport) : t("transport.select");
		return `<label class="field wide">${panelEsc(t("transport.title"))}<div class="select-control" data-select-control><input type="hidden" required ${attribute} value="${panelEsc(definition.transport)}"><button class="select-trigger" type="button" data-select-trigger aria-haspopup="listbox" aria-expanded="false"><span class="select-value">${panelEsc(selectedLabel)}</span><span class="select-chevron">&#9662;</span></button><div class="select-options" role="listbox">${supported.map(transport=>`<button class="select-option ${definition.transport === transport ? "selected" : ""}" type="button" data-select-option data-value="${panelEsc(transport)}">${panelEsc(transportName(transport))}</button>`).join("")}</div></div></label>`;
	}
	const selected=branches.find(([transport])=>transport === definition.transport) || branches[0];
	const value=selected?.[0] || "";
	const label=selected ? `${transportName(selected[0])} - ${t(`status.${selected[1].status || "unavailable"}`)}` : t("transport.select");
	return `<label class="field wide">${panelEsc(t("transport.title"))}<div class="select-control"><input type="hidden" ${attribute} value="${panelEsc(value)}"><button class="select-trigger" type="button" disabled><span class="select-value">${panelEsc(label)}</span><span class="select-chevron">&#9662;</span></button></div></label>`;
}

function renderTransportRuntime(payload)
{
	const previousOnline=Array.isArray(window.onlineTransportIds) ? [...window.onlineTransportIds] : null;
	window.transportRuntimeById=Object.fromEntries((payload.transports || []).map(status=>[status.id,status]));
	window.onlineTransportIds=(payload.transports || []).filter(status=>status.online).map(status=>status.id);
	window.activeTransportIds=(payload.transports || []).map(status=>status.id);
	const onlineChanged=previousOnline === null || previousOnline.length !== window.onlineTransportIds.length || previousOnline.some((transport,index)=>transport !== window.onlineTransportIds[index]);
	const target=document.getElementById("transport-status-list");
	if (!target) return onlineChanged;
	target.innerHTML=(payload.transports || []).map(status=>{
		const reconnectSeconds=status.reconnect_in_seconds ?? status.next_reconnect_at ?? 0;
		const reconnect=reconnectSeconds > 0 ? t("runtime.reconnect",{value:`${Number(reconnectSeconds).toFixed(2)} s`}) : "";
		return `<section class="runtime-transport"><strong>${panelEsc(transportName(status.id))}: ${panelEsc(t(status.online ? "runtime.online" : "runtime.offline"))}</strong><span>${panelEsc(t("runtime.latency",{value:Number(status.latency_ms || 0).toFixed(2)}))}</span><span>${panelEsc(t("runtime.errors",{value:status.error_count || 0}))}</span>${reconnect ? `<span>${panelEsc(reconnect)}</span>` : ""}${status.last_error ? `<span class="transport-error">${panelEsc(status.last_error)}</span>` : ""}</section>`;
	}).join("");
	return onlineChanged;
}

async function loadPanelTranslations()
{
	const explicit=document.documentElement.dataset.language;
	const language=normalizePanelLanguage(explicit || navigator.language || "pl");
	const response=await fetch(new URL(`api/i18n/${language}`,document.baseURI).toString(),{cache:"no-store"});
	if (!response.ok) throw new Error(`i18n ${response.status}`);
	const payload=await response.json();
	translations=payload.translations || {};
	document.documentElement.lang=payload.language || language;
	applyTranslations();
	return payload.language || language;
}

window.t=t;
window.applyTranslations=applyTranslations;
window.transportName=transportName;
window.transportBranches=transportBranches;
window.transportResultCards=transportResultCards;
window.transportSelector=transportSelector;
window.renderTransportRuntime=renderTransportRuntime;
window.TRANSPORT_IDS=TRANSPORT_IDS;
window.i18nReady=loadPanelTranslations().catch(error=>{
	console.error("[SolarMan Diagnostics] i18n load failed",error);
	translations={};
	return "pl";
});
