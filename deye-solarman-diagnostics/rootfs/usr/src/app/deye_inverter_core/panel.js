console.info("[Deye Solarman] external diagnostics script loaded",{
	href:window.location.href,
	base:document.baseURI,
});

window.addEventListener("error",event=>{
	console.error("[Deye Solarman] captured browser error",event.error || event.message);
});

window.addEventListener("unhandledrejection",event=>{
	console.error("[Deye Solarman] captured promise rejection",event.reason);
});
