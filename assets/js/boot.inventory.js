/* NMS-Inventory: boot.inventory.js */
(() => {
	const NS = (window.NMSI = window.NMSI || {});
	const { assert, on, API, State, UI, baseIdFromRid } = NS;

	async function loadCatalogue(includeTech) {
		// Prefer dynamic meta service; fallback to local JSON.
		const qs = `include_tech=${includeTech ? 1 : 0}`;
		try {
			const map = await API.fetchJSON(`${API.ENDPOINTS.catalogue}?${qs}`);
			if (map && typeof map === "object") {
				State.state.catalogue = map;
				return;
			}
		} catch { }
		try {
			const map = await API.fetchJSON(API.ENDPOINTS.items);
			State.state.catalogue = map || {};
		} catch {
			console.warn("[inventory] items_local.json unavailable; names/icons may be raw IDs");
			State.state.catalogue = {};
		}
	}

	function coerceRows(payload) {
		if (Array.isArray(payload)) return payload;
		if (payload && Array.isArray(payload.rows)) return payload.rows;
		if (payload && Array.isArray(payload.data)) return payload.data;
		return [];
		// If API ever changes, extend here (Power-of-Ten rule: explicit checks).
	}

	function lookupName(cat, rid) {
		const base = baseIdFromRid(rid);
		const tryKeys = [
			base,              // "CV_INV1"
			rid,               // "^CV_INV1#21992"
			base.toUpperCase(),
			base.toLowerCase(),
		];
		for (const k of tryKeys) {
			const v = k && cat[k];
			if (v && (typeof v === "string" || (v.name && typeof v.name === "string"))) {
				return typeof v === "string" ? v : v.name;
			}
		}
		return ""; // fallback to showing rid
	}

	async function loadInventory() {
		const p = new URLSearchParams();
		if (State.state.scope) p.set("scope", State.state.scope);
		if (State.state.settings.showNegatives) p.set("show_negatives", "1");
		if (State.state.settings.recentFirst) p.set("sort", "recent");
		let rows;
		try {
			rows = await API.fetchJSON(`${API.ENDPOINTS.inventory}?${p.toString()}`);
		} catch (e) {
			console.warn("[inventory] inventory load failed", e);
			rows = [];
		}
		const arr = coerceRows(rows).filter(r => r && r.resource_id != null);
		const cat = State.state.catalogue || {};
		State.state.rows = arr.map(r => {
			const baseId = baseIdFromRid(r.resource_id);
			const name = lookupName(cat, r.resource_id);
			const kind = (cat[baseId]?.kind) || r.kind || "";
			return {
				...r,
				display_name: name || baseId || r.resource_id,
				kind,
				icon_url: "",
			};
		});
		UI.renderGrid(document.getElementById("grid"), State.state.rows);
	}

	function wireUI() {
		const tabs = document.getElementById("tabs");
		const search = document.getElementById("search");
		const includeTech = document.getElementById("includeTech");

		on(tabs, "click", (ev) => {
			const b = ev.target.closest("button[data-scope]");
			if (!b) return;
			tabs.querySelectorAll("button").forEach(x => x.classList.toggle("active", x === b));
			State.setScope(b.dataset.scope || "character");
			loadInventory();
		});

		on(search, "input", () => {
			const q = (search.value || "").toLowerCase();
			const filtered = State.state.rows.filter(r =>
				(r.display_name || "").toLowerCase().includes(q) ||
				String(r.resource_id).toLowerCase().includes(q)
			);
			UI.renderGrid(document.getElementById("grid"), filtered);
		});

		on(includeTech, "change", async () => {
			const wantTech = !!includeTech?.checked;
			await loadCatalogue(wantTech);
			await loadInventory();
		});
	}

	async function boot() {
		await State.loadSettings();
		wireUI();
		// initial scope from URL or settings
		let initial = "character";
		try {
			const qp = new URLSearchParams(location.search);
			initial = (qp.get("tab") || State.state.settings.defaultWindow || "character").toLowerCase();
		} catch { }
		State.setScope(initial);
		const wantTech = !!document.getElementById("includeTech")?.checked;
		await loadCatalogue(wantTech);
		await loadInventory();
		State.scheduleAutoRefresh(loadInventory);
	}

	NS.bootInventory = boot;
})();
  