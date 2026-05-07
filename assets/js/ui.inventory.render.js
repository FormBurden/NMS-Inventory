/* NMS-Inventory: ui.inventory.render.js */
(() => {
	const NS = (window.NMSI = window.NMSI || {});
	const { el, API } = NS;

	// "^CV_INV1#21992" -> "CV_INV1"
	function baseIdFromRid(input) {
		const s = String(input || "").trim();
		if (!s) return "";
		const noCaret = s[0] === "^" ? s.slice(1) : s;
		const i = noCaret.indexOf("#");
		return (i >= 0 ? noCaret.slice(0, i) : noCaret) || "";
	}

	function normalizeRIDForIcon(input) {
		return baseIdFromRid(input);
	}

	function iconFor(row) {
		const rid = normalizeRIDForIcon(row.resource_id);
		const type = row.kind && typeof row.kind === "string" ? `&type=${encodeURIComponent(row.kind)}` : "";
		// IMPORTANT: No cache-buster here; allow browser to reuse cached icon responses.
		return `${API.ENDPOINTS.icon}?id=${encodeURIComponent(rid)}${type}`;
	}
	
	function cardRow(r, eager) {
		const img = el("img", {
			src: r.icon_url,
			alt: r.display_name || r.resource_id,
			loading: eager ? "eager" : "lazy",
		});
		if (eager) img.setAttribute("fetchpriority", "high");
		img.addEventListener("error", () => {
			if (img.src !== API.ENDPOINTS.placeholder) img.src = API.ENDPOINTS.placeholder;
		});
		return el("div", { className: "card" }, [
			el("div", { className: "icon" }, [img]),
			el("div", { className: "meta" }, [
				el("div", { className: "rid", title: r.resource_id, textContent: r.display_name || r.resource_id }),
				el("div", { className: "amt", textContent: Number(r.amount || 0).toLocaleString() }),
			]),
		]);
	}

	function renderGrid(container, rows) {
		if (!container) return;
		container.textContent = "";
		const frag = document.createDocumentFragment();
		rows.forEach((r, i) => {
			r.icon_url = r.icon_url || iconFor(r);
			frag.appendChild(cardRow(r, i < 12));
		});
		container.appendChild(frag);
	}

	NS.UI = { renderGrid };
	NS.baseIdFromRid = baseIdFromRid;
})();
  