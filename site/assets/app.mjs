const SUPPORTED_LANGUAGES=new Set(["pl","en"]);


function normalizedLanguage(value)
{
	const language=String(value||"").trim().toLowerCase().split("-")[0];
	return SUPPORTED_LANGUAGES.has(language)?language:null;
}


function translatedValue(dictionary,path)
{
	return path.split(".").reduce((value,key)=>value&&value[key],dictionary);
}


export function chooseLanguage(url,navigatorLanguage,storedLanguage)
{
	const requested=normalizedLanguage(new URL(url,"https://example.invalid/").searchParams.get("lang"));
	return requested||normalizedLanguage(storedLanguage)||normalizedLanguage(navigatorLanguage)||"en";
}


export async function loadTranslations(language,basePath)
{
	const response=await fetch(`${basePath}i18n/${language}.json`);
	if (!response.ok)
	{
		throw new Error(`Translation request failed: ${response.status}`);
	}
	return response.json();
}


export function summarizeCatalogManifest(manifest)
{
	const models=Array.isArray(manifest?.models)?manifest.models:[];
	const maps=models.flatMap(model=>Object.values(model.maps||{}));
	return {
		models:models.length,
		maps:maps.length,
		definitions:maps.reduce((total,map)=>total+Number(map.definition_count||0),0),
	};
}


function applyTranslations(dictionary)
{
	document.querySelectorAll("[data-i18n]").forEach(element=>
	{
		const value=translatedValue(dictionary,element.dataset.i18n);
		if (typeof value === "string")
		{
			element.textContent=value;
		}
	});
	document.querySelectorAll("[data-i18n-aria]").forEach(element=>
	{
		const value=translatedValue(dictionary,element.dataset.i18nAria);
		if (typeof value === "string")
		{
			element.setAttribute("aria-label",value);
		}
	});
	document.querySelectorAll("[data-i18n-meta]").forEach(element=>
	{
		const value=translatedValue(dictionary,element.dataset.i18nMeta);
		if (typeof value === "string")
		{
			element.setAttribute("content",value);
		}
	});
	document.querySelectorAll("[data-i18n-alt]").forEach(element=>
	{
		const value=translatedValue(dictionary,element.dataset.i18nAlt);
		if (typeof value === "string")
		{
			element.setAttribute("alt",value);
		}
	});
}


function normalizeBasePath(value)
{
	const path=String(value||"/");
	return path.endsWith("/")?path:`${path}/`;
}


async function loadCatalogStats(basePath)
{
	try
	{
		const response=await fetch(`${basePath}generated/models.json`);
		if (!response.ok)
		{
			return;
		}
		const manifest=await response.json();
		const values=summarizeCatalogManifest(manifest);
		document.querySelectorAll("[data-catalog-stat]").forEach(element=>
		{
			const value=values[element.dataset.catalogStat];
			if (Number.isFinite(value))
			{
				element.textContent=new Intl.NumberFormat(document.documentElement.lang).format(value);
			}
		});
	}
	catch (_error)
	{
		return;
	}
}


function preferredTheme()
{
	const saved=localStorage.getItem("solarman-site-theme");
	if (saved === "dark"||saved === "light")
	{
		return saved;
	}
	return window.matchMedia("(prefers-color-scheme: light)").matches?"light":"dark";
}


function applyTheme(theme)
{
	document.documentElement.dataset.theme=theme;
	document.querySelector('meta[name="theme-color"]')?.setAttribute("content",theme === "dark"?"#071217":"#f2f7f8");
}


async function initialize()
{
	const basePath=normalizeBasePath(document.body.dataset.basePath);
	let activeLanguage=chooseLanguage(window.location.href,navigator.language,localStorage.getItem("solarman-site-language"));
	const languageToggle=document.querySelector("[data-language-toggle]");
	const themeToggle=document.querySelector("[data-theme-toggle]");

	const setLanguage=async language=>
	{
		activeLanguage=normalizedLanguage(language)||"en";
		const dictionary=await loadTranslations(activeLanguage,basePath);
		document.documentElement.lang=activeLanguage;
		applyTranslations(dictionary);
		localStorage.setItem("solarman-site-language",activeLanguage);
		if (languageToggle)
		{
			languageToggle.textContent=activeLanguage === "pl"?"EN":"PL";
			languageToggle.title=activeLanguage === "pl"?"English":"Polski";
		}
		window.solarmanSite.activeLanguage=activeLanguage;
		window.dispatchEvent(new CustomEvent("solarman:language",{detail:{language:activeLanguage,dictionary}}));
	};

	window.solarmanSite={activeLanguage,setLanguage};
	applyTheme(preferredTheme());
	await setLanguage(activeLanguage);
	await loadCatalogStats(basePath);

	languageToggle?.addEventListener("click",async()=>
	{
		const next=activeLanguage === "pl"?"en":"pl";
		const url=new URL(window.location.href);
		url.searchParams.set("lang",next);
		window.history.replaceState({},"",url);
		await setLanguage(next);
	});
	themeToggle?.addEventListener("click",()=>
	{
		const next=document.documentElement.dataset.theme === "dark"?"light":"dark";
		localStorage.setItem("solarman-site-theme",next);
		applyTheme(next);
	});
}


if (typeof window !== "undefined"&&typeof document !== "undefined")
{
	initialize().catch(error=>console.error("SolarMan site initialization failed",error));
}
