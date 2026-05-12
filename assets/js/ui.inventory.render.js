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
		const rid = normalizeRIDForIcon(row.resource_id || row.base_id || row.catalogue_id);
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

	function statCardRow(r, eager) {
		const img = el("img", {
			src: r.icon_url,
			alt: r.display_name || r.resource_id,
			loading: eager ? "eager" : "lazy",
		});
		if (eager) img.setAttribute("fetchpriority", "high");
		img.addEventListener("error", () => {
			if (img.src !== API.ENDPOINTS.placeholder) img.src = API.ENDPOINTS.placeholder;
		});

		const valueLabel = r.stat_value_label || "Charge";
		const statValue = r.stat_ammo_amount == null ? "—" : Number(r.stat_ammo_amount || 0).toLocaleString();
		const qty = r.stat_item_amount == null ? "—" : Number(r.stat_item_amount || 0).toLocaleString();

		return el("div", { className: "card stat-card" }, [
			el("div", { className: "icon" }, [img]),
			el("div", { className: "meta" }, [
				el("div", { className: "rid", title: r.resource_id, textContent: r.display_name || r.resource_id }),
				el("div", { className: "stat-values" }, [
					el("div", { className: "stat-value" }, [
						el("span", { className: "stat-label", textContent: valueLabel }),
						el("span", { className: "stat-number", textContent: statValue }),
					]),
					el("div", { className: "stat-value" }, [
						el("span", { className: "stat-label", textContent: "Qty" }),
						el("span", { className: "stat-number", textContent: qty }),
					]),
				]),
			]),
		]);
	}

	function recentCardRow(r, eager) {
		const img = el("img", {
			src: r.icon_url,
			alt: r.display_name || r.resource_id,
			loading: eager ? "eager" : "lazy",
		});
		if (eager) img.setAttribute("fetchpriority", "high");
		img.addEventListener("error", () => {
			if (img.src !== API.ENDPOINTS.placeholder) img.src = API.ENDPOINTS.placeholder;
		});

		const delta = Number(r.delta ?? r.amount ?? 0);
		const prefix = delta > 0 ? "+" : "";
		const deltaText = `${prefix}${delta.toLocaleString()}`;
		const label = r.change_label || (delta > 0 ? "Session gained" : "Session spent");

		return el("div", { className: `card recent-card ${delta > 0 ? "recent-gain" : "recent-loss"}` }, [
			el("div", { className: "icon" }, [img]),
			el("div", { className: "meta" }, [
				el("div", { className: "rid", title: r.resource_id, textContent: r.display_name || r.resource_id }),
				el("div", { className: "recent-values" }, [
					el("span", { className: "recent-label", textContent: label }),
					el("span", { className: "recent-delta", textContent: deltaText }),
				]),
			]),
		]);
	}

	function renderGrid(container, rows) {
		if (!container) return;
		container.classList.remove("stat-grid", "recent-grid");
		container.textContent = "";
		const frag = document.createDocumentFragment();
		rows.forEach((r, i) => {
			r.icon_url = iconFor(r);
			frag.appendChild(cardRow(r, i < 12));
		});
		container.appendChild(frag);
	}

	function renderStatGrid(container, rows) {
		if (!container) return;
		container.classList.remove("recent-grid");
		container.classList.add("stat-grid");
		container.textContent = "";
		const frag = document.createDocumentFragment();
		rows.forEach((r, i) => {
			r.icon_url = iconFor(r);
			frag.appendChild(statCardRow(r, i < 12));
		});
		container.appendChild(frag);
	}

	function renderRecentGrid(container, rows) {
		if (!container) return;
		container.classList.remove("stat-grid");
		container.classList.add("recent-grid");
		container.textContent = "";
		const frag = document.createDocumentFragment();
		rows.forEach((r, i) => {
			r.icon_url = iconFor(r);
			frag.appendChild(recentCardRow(r, i < 12));
		});
		container.appendChild(frag);
	}

	NS.UI = { renderGrid, renderStatGrid, renderRecentGrid };
	NS.baseIdFromRid = baseIdFromRid;
})();
  