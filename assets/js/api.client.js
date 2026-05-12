/* NMS-Inventory: api.client.js */
(() => {
	const NS = (window.NMSI = window.NMSI || {});
	const BASE = (window.NMS_BASE || "/").replace(/\/+$/, "");
	const ENDPOINTS = {
		catalogue: `${BASE}/api/item_meta.php`,
		inventory: `${BASE}/api/inventory.php`,
		settings: `${BASE}/api/settings.php`,
		recent: `${BASE}/api/inventory.php`,
		items: `${BASE}/data/items_local.json`,
		icon: `${BASE}/api/icon.php`,
		placeholder: "/assets/img/placeholder.png",
	};

	function cacheTag() {
		// Prefer a stable tag if provided; else change once per second.
		const fromWin = (NS.CACHE_TAG || window.NMSI_CACHE_TAG);
		if (fromWin) return String(fromWin);
		return String(Math.floor(Date.now() / 1000));
	}

	function withTimeout(ms, promise, abort) {
		let t;
		const timeout = new Promise((_, rej) => {
			t = setTimeout(() => { abort?.(); rej(new Error("Timeout")); }, ms);
		});
		return Promise.race([promise.finally(() => clearTimeout(t)), timeout]);
	}

	async function fetchJSON(url, opts = {}) {
		const ctl = new AbortController();
		const u = new URL(url, location.origin);
		if (opts.cacheBust !== false) u.searchParams.set("_", cacheTag());
		const p = fetch(u.toString(), { cache: "no-store", ...opts, signal: ctl.signal });
		const res = await withTimeout(opts.timeoutMs ?? 10000, p, () => ctl.abort());
		if (!res.ok) throw new Error(`HTTP ${res.status} for ${u.pathname}`);
		return res.json();
	}

	NS.API = { BASE, ENDPOINTS, fetchJSON, cacheTag };
})();
  