let ownershipSnapshot=null;

function ownershipInfo(entry,kind="sensor")
{
	if (!ownershipSnapshot) return entry.ownership || {owner:null,editable:true};
	const record=ownershipSnapshot.owners[`${kind}:${entry.key}`] || {};
	return {owner:record.owner,name:record.name || record.owner,editable:!record.owner || record.owner === ownershipSnapshot.source};
}

function ownershipLabel(info)
{
	return info.owner ? `Używane przez: ${info.name || info.owner}` : "Dostępne";
}

function ownershipBadge(entry,kind="sensor")
{
	return `<p class="notice" data-owned-entity="${esc(kind+":"+entry.key)}">${esc(ownershipLabel(ownershipInfo(entry,kind)))}</p>`;
}

function ownershipToggle(entry,kind="sensor",disabled=false)
{
	return `data-owned-toggle="${esc(kind+":"+entry.key)}" data-owned-disabled="${disabled}" ${disabled || !ownershipInfo(entry,kind).editable ? "disabled" : ""}`;
}

async function refreshOwnership()
{
	try
	{
		ownershipSnapshot=await request("api/ownership");
		for (const badge of document.querySelectorAll("[data-owned-entity]"))
		{
			const record=ownershipSnapshot.owners[badge.dataset.ownedEntity] || {};
			badge.textContent=ownershipLabel({owner:record.owner,name:record.name});
		}
		for (const checkbox of document.querySelectorAll("[data-owned-toggle]"))
		{
			const record=ownershipSnapshot.owners[checkbox.dataset.ownedToggle] || {};
			const blocked=record.owner && record.owner !== ownershipSnapshot.source;
			checkbox.disabled=checkbox.dataset.ownedDisabled === "true" || Boolean(blocked);
			if (blocked && checkbox.checked)
			{
				checkbox.checked=false;
				checkbox.dispatchEvent(new Event("change",{bubbles:true}));
			}
		}
	}
	catch (error)
	{
		for (const badge of document.querySelectorAll("[data-owned-entity]")) badge.textContent=`Rejestr niedostępny: ${error.message}`;
		for (const checkbox of document.querySelectorAll("[data-owned-toggle]")) checkbox.disabled=true;
	}
	finally
	{
		window.setTimeout(refreshOwnership,5000);
	}
}

window.setTimeout(refreshOwnership,0);
