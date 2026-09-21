import {chooseLanguage,loadTranslations} from "./app.mjs";


const DEFAULT_FILTERS={
	query:"",
	category:"all",
	transport:"all",
	type:"all",
	access:"all",
	registerCount:"all",
	range:"all",
};


export function normalizeSearchValue(value)
{
	return String(value??"").normalize("NFD").replace(/[\u0300-\u036f]/g,"").replaceAll("Ł","L").replaceAll("ł","l").trim().toLowerCase();
}


function rangeKind(definition)
{
	if ((definition.min&&typeof definition.min === "object")||(definition.max&&typeof definition.max === "object"))
	{
		return "dynamic";
	}
	if (definition.min !== undefined||definition.max !== undefined)
	{
		return "fixed";
	}
	return "none";
}


export function extractDefinitions(document)
{
	const catalog=document?.catalog||{};
	const source=catalog.map_id === "control"?catalog.commands:catalog.sensors;
	return (Array.isArray(source)?source:[]).map(definition=>({
		...definition,
		_referenceMapId:catalog.map_id||document?.reference?.map_id||"telemetry",
		_referenceWritable:Boolean(catalog.writable)&&definition.read_only !== true&&definition.writable !== false,
		_referenceTransports:Array.isArray(definition.transports)?[...definition.transports]:[...(catalog.transports||[])],
		_referenceRegisterCount:Array.isArray(definition.registers)?definition.registers.length:0,
		_referenceRange:rangeKind(definition),
	}));
}


function searchableText(definition)
{
	return normalizeSearchValue([
		definition.name,
		definition.key,
		...(definition.registers||[]),
		definition.unit,
		definition.category,
		definition.type,
		definition.method,
		definition.zero,
		definition.unknown,
		...Object.keys(definition.options||{}),
		...Object.values(definition.options||{}),
	].join(" "));
}


export function filterDefinitions(definitions,filters={})
{
	const values={...DEFAULT_FILTERS,...filters};
	const query=normalizeSearchValue(values.query);
	return definitions.filter(definition=>
	{
		if (query&&!searchableText(definition).includes(query)) return false;
		if (values.category !== "all"&&(definition.category||"other") !== values.category) return false;
		if (values.transport !== "all"&&!definition._referenceTransports?.includes(values.transport)) return false;
		if (values.type !== "all"&&(definition.type||definition.method||"unknown") !== values.type) return false;
		if (values.access === "write"&&!definition._referenceWritable) return false;
		if (values.access === "read"&&definition._referenceWritable) return false;
		if (values.registerCount === "single"&&definition._referenceRegisterCount !== 1) return false;
		if (values.registerCount === "multiple"&&definition._referenceRegisterCount < 2) return false;
		if (values.range !== "all"&&definition._referenceRange !== values.range) return false;
		return true;
	});
}


export function parseReferenceState(url)
{
	const target=url instanceof URL?url:new URL(url,"https://example.invalid/");
	const parameters=target.searchParams;
	return {
		model:parameters.get("model")||"",
		map:parameters.get("map")||"",
		query:parameters.get("q")||"",
		category:parameters.get("category")||"all",
		transport:parameters.get("transport")||"all",
		type:parameters.get("type")||"all",
		access:parameters.get("access")||"all",
		registerCount:parameters.get("count")||"all",
		range:parameters.get("range")||"all",
		definition:decodeURIComponent(target.hash.replace(/^#/,"")),
	};
}


export function updateReferenceUrl(url,state)
{
	const target=new URL(url instanceof URL?url.href:url,"https://example.invalid/");
	const assignments={
		model:state.model,
		map:state.map,
		q:state.query,
		category:state.category,
		transport:state.transport,
		type:state.type,
		access:state.access,
		count:state.registerCount,
		range:state.range,
	};
	Object.entries(assignments).forEach(([key,value])=>
	{
		if (!value||value === "all") target.searchParams.delete(key);
		else target.searchParams.set(key,value);
	});
	target.hash=state.definition||"";
	return target.href;
}


export function selectAvailableMap(model,requestedMap)
{
	const mapIds=Object.keys(model?.maps||{});
	if (mapIds.includes(requestedMap)) return requestedMap;
	return mapIds[0]||null;
}


function structuredRange(definition)
{
	return {
		kind:rangeKind(definition),
		minimum:definition.min,
		maximum:definition.max,
	};
}


export function describeDefinition(definition,mapMetadata={})
{
	return {
		name:definition.name||definition.key,
		key:definition.key,
		registers:[...(definition.registers||[])],
		access:(definition._referenceWritable??mapMetadata.writable)?"write":"read",
		transports:[...(definition._referenceTransports||mapMetadata.transports||[])],
		range:structuredRange(definition),
		fields:Object.fromEntries(Object.entries(definition).filter(([key])=>!key.startsWith("_reference"))),
	};
}


function createElement(tag,className,textValue)
{
	const element=document.createElement(tag);
	if (className) element.className=className;
	if (textValue !== undefined) element.textContent=String(textValue);
	return element;
}


function setChildren(element,children=[])
{
	element.textContent="";
	children.forEach(child=>element.append(child));
}


function translated(dictionary,path,fallback)
{
	const value=path.split(".").reduce((current,key)=>current&&current[key],dictionary);
	return typeof value === "string"?value:fallback;
}


function formatValue(value)
{
	if (value === null) return "null";
	if (typeof value === "object") return JSON.stringify(value,null,2);
	if (typeof value === "boolean") return value?"true":"false";
	return String(value);
}


function option(select,value,label)
{
	const item=createElement("option",null,label);
	item.value=value;
	select.append(item);
}


function uniqueValues(definitions,getter)
{
	return [...new Set(definitions.flatMap(getter).filter(Boolean))].sort((a,b)=>String(a).localeCompare(String(b)));
}


function initializeReference()
{
	const basePath=document.body.dataset.basePath.endsWith("/")?document.body.dataset.basePath:`${document.body.dataset.basePath}/`;
	const elements={
		model:document.querySelector("#model-select"),
		summary:document.querySelector("#model-summary"),
		search:document.querySelector("#definition-search"),
		count:document.querySelector("#result-count"),
		tableBody:document.querySelector("#definition-table tbody"),
		cards:document.querySelector("#definition-cards"),
		empty:document.querySelector("#empty-state"),
		results:document.querySelector("#reference-results"),
		error:document.querySelector("#error-state"),
		errorSource:document.querySelector("#error-source"),
		mapSource:document.querySelector("#map-source"),
		dialog:document.querySelector("#definition-details"),
		detailTitle:document.querySelector("#detail-title"),
		detailKey:document.querySelector("#detail-key"),
		detailMap:document.querySelector("#detail-map"),
		detailContent:document.querySelector("#detail-content"),
		detailSource:document.querySelector("#detail-source"),
	};
	const filterElements=Object.fromEntries([...document.querySelectorAll("[data-filter]")].map(element=>[element.dataset.filter,element]));
	let manifest={models:[]};
	let activeModel=null;
	let mapMetadata=null;
	let definitions=[];
	let dictionary={};
	let state=parseReferenceState(window.location.href);
	let sort={key:"register",direction:1};

	function language()
	{
		return window.solarmanSite?.activeLanguage||chooseLanguage(window.location.href,navigator.language,localStorage.getItem("solarman-site-language"));
	}

	function updateUrl(replace=true)
	{
		const next=updateReferenceUrl(window.location.href,state);
		window.history[replace?"replaceState":"pushState"]({},"",next);
	}

	function filterLabel(key,fallback)
	{
		return translated(dictionary,`referenceBrowser.${key}`,fallback);
	}

	function populateFilter(select,key,values)
	{
		const selected=state[key]||"all";
		setChildren(select);
		option(select,"all",filterLabel("all","Wszystkie"));
		values.forEach(value=>option(select,value,filterLabel(value,value)));
		select.value=[...select.options].some(item=>item.value === selected)?selected:"all";
		state[key]=select.value;
	}

	function configureFilters()
	{
		populateFilter(filterElements.category,"category",uniqueValues(definitions,item=>[item.category||"other"]));
		populateFilter(filterElements.transport,"transport",uniqueValues(definitions,item=>item._referenceTransports||[]));
		populateFilter(filterElements.type,"type",uniqueValues(definitions,item=>[item.type||item.method||"unknown"]));
		populateFilter(filterElements.access,"access",["read","write"]);
		populateFilter(filterElements.registerCount,"registerCount",["single","multiple"]);
		populateFilter(filterElements.range,"range",["none","fixed","dynamic"]);
	}

	function registerText(definition)
	{
		return (definition.registers||[]).map(value=>`R${value}`).join(", ");
	}

	function typeText(definition)
	{
		return definition.type||definition.method||"-";
	}

	function accessText(definition)
	{
		return definition._referenceWritable?filterLabel("write","Zapis"):filterLabel("read","Odczyt");
	}

	function openDetails(definition,writeHistory=true)
	{
		const description=describeDefinition(definition,mapMetadata||{});
		elements.detailTitle.textContent=description.name;
		elements.detailKey.textContent=description.key;
		elements.detailMap.textContent=filterLabel(state.map,state.map);
		elements.detailSource.href=mapMetadata?.source_url||activeModel?.source_url||"#";
		const list=createElement("dl","detail-list");
		Object.entries(description.fields).forEach(([key,value])=>
		{
			const term=createElement("dt",null,filterLabel(`field_${key}`,key.replaceAll("_"," ")));
			const detail=createElement("dd");
			const valueElement=createElement(typeof value === "object"?"pre":"span",null,formatValue(value));
			detail.append(valueElement);
			list.append(term,detail);
		});
		setChildren(elements.detailContent,[list]);
		state.definition=definition.key;
		updateUrl(!writeHistory);
		if (typeof elements.dialog.showModal === "function") elements.dialog.showModal();
		else elements.dialog.setAttribute("open","");
	}

	function resultButton(definition,className)
	{
		const button=createElement("button",className);
		button.type="button";
		button.addEventListener("click",()=>openDetails(definition,false));
		return button;
	}

	function renderTableRow(definition)
	{
		const row=createElement("tr");
		const nameCell=createElement("td");
		const nameButton=resultButton(definition,"definition-link");
		nameButton.append(createElement("strong",null,definition.name||definition.key));
		nameCell.append(nameButton);
		const values=[
			definition.key,
			registerText(definition),
			typeText(definition),
			definition.unit||"-",
			accessText(definition),
			(definition._referenceTransports||[]).join(", ")||"-",
			definition.category||"other",
		];
		row.append(nameCell,...values.map(value=>createElement("td",null,value)));
		return row;
	}

	function renderCard(definition)
	{
		const article=createElement("article","definition-card");
		const button=resultButton(definition,"definition-card-button");
		button.append(
			createElement("strong",null,definition.name||definition.key),
			createElement("code",null,definition.key),
			createElement("span",null,registerText(definition)),
		);
		const badges=createElement("div","definition-badges");
		[typeText(definition),accessText(definition),definition.category||"other"].forEach(value=>badges.append(createElement("span",null,value)));
		article.append(button,badges);
		return article;
	}

	function sortedDefinitions(items)
	{
		return [...items].sort((left,right)=>
		{
			const a=sort.key === "register"?(left.registers?.[0]??0):normalizeSearchValue(left[sort.key]);
			const b=sort.key === "register"?(right.registers?.[0]??0):normalizeSearchValue(right[sort.key]);
			return (typeof a === "number"?a-b:String(a).localeCompare(String(b)))*sort.direction;
		});
	}

	function render()
	{
		const filters={
			query:state.query,
			category:state.category,
			transport:state.transport,
			type:state.type,
			access:state.access,
			registerCount:state.registerCount,
			range:state.range,
		};
		const visible=sortedDefinitions(filterDefinitions(definitions,filters));
		setChildren(elements.tableBody,visible.map(renderTableRow));
		setChildren(elements.cards,visible.map(renderCard));
		elements.empty.hidden=visible.length > 0;
		elements.count.textContent=filterLabel("resultCount","{count} definicji").replace("{count}",String(visible.length));
		elements.results.setAttribute("aria-busy","false");
	}

	function updateTabs()
	{
		document.querySelectorAll("[data-map]").forEach(tab=>
		{
			const available=Boolean(activeModel?.maps?.[tab.dataset.map]);
			tab.hidden=!available;
			tab.disabled=!available;
			tab.setAttribute("aria-selected",String(tab.dataset.map === state.map));
			tab.tabIndex=tab.dataset.map === state.map?0:-1;
		});
	}

	async function loadMap()
	{
		state.map=selectAvailableMap(activeModel,state.map);
		if (!state.map) throw new Error("Model does not expose a catalog map");
		mapMetadata=activeModel.maps[state.map];
		updateTabs();
		updateUrl();
		elements.results.setAttribute("aria-busy","true");
		elements.error.hidden=true;
		elements.mapSource.href=mapMetadata.source_url||activeModel.source_url;
		elements.errorSource.href=mapMetadata.source_url||activeModel.source_url;
		elements.detailSource.href=mapMetadata.source_url||activeModel.source_url;
		try
		{
			const response=await fetch(`${basePath}${mapMetadata.data_path}`);
			if (!response.ok) throw new Error(`Catalog request failed: ${response.status}`);
			const payload=await response.json();
			definitions=extractDefinitions(payload);
			configureFilters();
			render();
			if (state.definition)
			{
				const selected=definitions.find(item=>item.key === state.definition);
				if (selected) openDetails(selected,true);
				else
				{
					state.definition="";
					updateUrl();
				}
			}
		}
		catch (error)
		{
			definitions=[];
			elements.results.setAttribute("aria-busy","false");
			elements.error.hidden=false;
			console.error("Register catalog failed",error);
		}
	}

	async function selectModel(modelId)
	{
		activeModel=manifest.models.find(model=>model.catalog_set === modelId)||manifest.models[0]||null;
		if (!activeModel) throw new Error("No catalog models available");
		state.model=activeModel.catalog_set;
		elements.model.value=state.model;
		const families=(activeModel.model_families||[]).join(", ");
		elements.summary.textContent=[activeModel.manufacturer,families,activeModel.revision?`v${activeModel.revision}`:""].filter(Boolean).join(" - ");
		await loadMap();
	}

	async function loadManifest()
	{
		const response=await fetch(`${basePath}generated/models.json`);
		if (!response.ok) throw new Error(`Manifest request failed: ${response.status}`);
		manifest=await response.json();
		setChildren(elements.model);
		manifest.models.forEach(model=>option(elements.model,model.catalog_set,model.display_name||model.catalog_set));
		await selectModel(state.model);
	}

	async function refreshLanguage(nextDictionary)
	{
		dictionary=nextDictionary||await loadTranslations(language(),basePath);
		elements.search.placeholder=filterLabel("searchPlaceholder","Nazwa, klucz, rejestr, opcja...");
		if (definitions.length)
		{
			configureFilters();
			render();
		}
	}

	elements.model.addEventListener("change",async()=>
	{
		state.definition="";
		state.map="";
		await selectModel(elements.model.value);
	});
	document.querySelectorAll("[data-map]").forEach(tab=>tab.addEventListener("click",async()=>
	{
		state.definition="";
		state.map=tab.dataset.map;
		await loadMap();
	}));
	elements.search.addEventListener("input",()=>
	{
		state.query=elements.search.value;
		updateUrl();
		render();
	});
	Object.entries(filterElements).forEach(([key,element])=>element.addEventListener("change",()=>
	{
		state[key]=element.value;
		updateUrl();
		render();
	}));
	document.querySelectorAll("[data-sort]").forEach(button=>button.addEventListener("click",()=>
	{
		if (sort.key === button.dataset.sort) sort.direction*=-1;
		else sort={key:button.dataset.sort,direction:1};
		render();
	}));
	elements.dialog.addEventListener("close",()=>
	{
		state.definition="";
		updateUrl();
	});
	window.addEventListener("popstate",async()=>
	{
		state=parseReferenceState(window.location.href);
		elements.search.value=state.query;
		await selectModel(state.model);
	});
	window.addEventListener("solarman:language",event=>refreshLanguage(event.detail.dictionary));

	elements.search.value=state.query;
	refreshLanguage().then(loadManifest).catch(error=>
	{
		elements.results.setAttribute("aria-busy","false");
		elements.error.hidden=false;
		console.error("Register reference failed",error);
	});
}


if (typeof window !== "undefined"&&typeof document !== "undefined")
{
	initializeReference();
}
