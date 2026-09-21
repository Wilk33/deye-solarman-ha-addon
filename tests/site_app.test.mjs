import test from "node:test";
import assert from "node:assert/strict";

import {
	chooseLanguage,
	loadTranslations,
	summarizeCatalogManifest,
} from "../site/assets/app.mjs";


test("language precedence is URL then storage then browser",()=>
{
	assert.equal(chooseLanguage("https://example.test/?lang=en","pl-PL","pl"),"en");
	assert.equal(chooseLanguage("https://example.test/","en-US","pl"),"pl");
	assert.equal(chooseLanguage("https://example.test/","pl-PL",null),"pl");
	assert.equal(chooseLanguage("https://example.test/","de-DE",null),"en");
});


test("translation loader requests selected language below base path",async()=>
{
	const previousFetch=globalThis.fetch;
	let requestedUrl="";
	globalThis.fetch=async url=>
	{
		requestedUrl=String(url);
		return {ok:true,json:async()=>({nav:{home:"Home"}})};
	};
	try
	{
		const translations=await loadTranslations("en","/project/");
		assert.equal(requestedUrl,"/project/i18n/en.json");
		assert.equal(translations.nav.home,"Home");
	}
	finally
	{
		globalThis.fetch=previousFetch;
	}
});


test("catalog summary counts maps stored as manifest objects",()=>
{
	const manifest={
		models:[
			{maps:{telemetry:{definition_count:94},control:{definition_count:115}}},
			{maps:{telemetry:{definition_count:7}}},
		],
	};
	assert.deepEqual(summarizeCatalogManifest(manifest),{
		models:2,
		maps:3,
		definitions:216,
	});
});
