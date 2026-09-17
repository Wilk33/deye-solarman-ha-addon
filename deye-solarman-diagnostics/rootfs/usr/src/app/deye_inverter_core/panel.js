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
		const raw=(result.raw_hex || []).join(", ") || (result.raw_registers || []).join(", ");
		const value=result.value === null || result.value === undefined ? "" : `<div><b>${panelEsc(t("result.value"))}:</b> ${panelEsc(result.value)} ${panelEsc(entry.definition?.unit || "")}</div>`;
		const rawLine=raw ? `<div><b>${panelEsc(t("result.raw"))}:</b> <code>${panelEsc(raw)}</code></div>` : "";
		const latency=result.latency_ms === null || result.latency_ms === undefined ? "" : `<div><b>${panelEsc(t("result.latency"))}:</b> ${panelEsc(result.latency_ms)} ms</div>`;
		const error=result.error || result.message;
		return `<section class="transport-result ${panelEsc(result.status || "unavailable")}" data-transport-result="${panelEsc(transport)}"><header><strong>${panelEsc(transportName(transport))}</strong>${statusBadge(result.status || "unavailable")}</header>${value}${rawLine}${latency}${error ? `<p class="transport-error"><b>${panelEsc(t("result.error"))}:</b> ${panelEsc(error)}</p>` : ""}</section>`;
	}).join("")}</div>`;
}

function transportSelector(entry,prefix="")
{
	const definition=entry.definition || {};
	const branches=transportBranches(entry);
	const supported=branches.filter(([,result])=>result.status === "supported").map(([transport])=>transport);
	if (supported.length === 1) {
		definition.transport=supported[0];
		return `<input type="hidden" data-${prefix ? `${prefix}-` : ""}transport="${panelEsc(entry.key)}" value="${panelEsc(supported[0])}">`;
	}
	if (supported.length === 2) {
		if (!supported.includes(definition.transport)) definition.transport="";
		return `<label class="field wide">${panelEsc(t("transport.title"))}<select required data-${prefix ? `${prefix}-` : ""}transport="${panelEsc(entry.key)}"><option value="" ${definition.transport ? "" : "selected"} disabled>${panelEsc(t("transport.select"))}</option>${supported.map(transport=>`<option value="${panelEsc(transport)}" ${definition.transport === transport ? "selected" : ""}>${panelEsc(transportName(transport))}</option>`).join("")}</select></label>`;
	}
	return `<label class="field wide">${panelEsc(t("transport.title"))}<select disabled data-${prefix ? `${prefix}-` : ""}transport="${panelEsc(entry.key)}">${branches.map(([transport,result])=>`<option value="${panelEsc(transport)}" ${definition.transport === transport ? "selected" : ""}>${panelEsc(transportName(transport))} - ${panelEsc(t(`status.${result.status || "unavailable"}`))}</option>`).join("")}</select></label>`;
}

function renderTransportRuntime(payload)
{
	window.activeTransportIds=(payload.transports || []).map(status=>status.id);
	const target=document.getElementById("transport-status-list");
	if (!target) return;
	target.innerHTML=(payload.transports || []).map(status=>{
		const reconnectSeconds=status.reconnect_in_seconds ?? status.next_reconnect_at ?? 0;
		const reconnect=reconnectSeconds > 0 ? t("runtime.reconnect",{value:`${Number(reconnectSeconds).toFixed(2)} s`}) : "";
		return `<section class="runtime-transport"><strong>${panelEsc(transportName(status.id))}: ${panelEsc(t(status.online ? "runtime.online" : "runtime.offline"))}</strong><span>${panelEsc(t("runtime.latency",{value:Number(status.latency_ms || 0).toFixed(2)}))}</span><span>${panelEsc(t("runtime.errors",{value:status.error_count || 0}))}</span>${reconnect ? `<span>${panelEsc(reconnect)}</span>` : ""}${status.last_error ? `<span class="transport-error">${panelEsc(status.last_error)}</span>` : ""}</section>`;
	}).join("");
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
