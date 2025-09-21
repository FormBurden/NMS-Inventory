(() => {
	const els = {
		defaultWindow: document.getElementById("defaultWindow"),
		language: document.getElementById("language"),
		iconSize: document.getElementById("iconSize"),
		showNegatives: document.getElementById("showNegatives"),
		autoRefreshSec: document.getElementById("autoRefreshSec"),
		theme: document.getElementById("theme"),
		saveBtn: document.getElementById("saveBtn"),
		resetBtn: document.getElementById("resetBtn"),
		status: document.getElementById("status"),
	};

	const BASE = (window.NMS_BASE || "/").replace(/\/+$/, "");
	const SETTINGS_API = `${BASE}/api/settings.php`;

	const DEFAULTS = {
		language: "en-us",
		defaultWindow: "Character",
		iconSize: "medium",
		showNegatives: true,
		autoRefreshSec: 15,
		theme: "system",
	};

	function uiSet(s) {
		if (els.defaultWindow) els.defaultWindow.value = s.defaultWindow || DEFAULTS.defaultWindow;
		if (els.language) els.language.value = s.language || DEFAULTS.language;
		if (els.iconSize) els.iconSize.value = s.iconSize || DEFAULTS.iconSize;
		if (els.showNegatives) els.showNegatives.checked = !!s.showNegatives;
		if (els.autoRefreshSec) els.autoRefreshSec.value = String(s.autoRefreshSec ?? DEFAULTS.autoRefreshSec);
		if (els.theme) els.theme.value = s.theme || DEFAULTS.theme;
	}

	function uiGet() {
		return {
			defaultWindow: els.defaultWindow?.value || DEFAULTS.defaultWindow,
			language: els.language?.value || DEFAULTS.language,
			iconSize: els.iconSize?.value || DEFAULTS.iconSize,
			showNegatives: !!els.showNegatives?.checked,
			autoRefreshSec: parseInt(els.autoRefreshSec?.value || "0", 10) || 0,
			theme: els.theme?.value || DEFAULTS.theme,
		};
	}

	function note(msg) {
		if (!els.status) return;
		els.status.textContent = msg;
		setTimeout(() => { if (els.status.textContent === msg) els.status.textContent = ""; }, 2000);
	}

	async function load() {
		// start with cache
		let s = { ...DEFAULTS };
		try {
			const raw = localStorage.getItem("nms_settings");
			if (raw) s = { ...s, ...JSON.parse(raw) };
		} catch { }

		// try server
		try {
			const res = await fetch(SETTINGS_API, { cache: "no-store" });
			if (res.ok) {
				const payload = await res.json();
				s = { ...s, ...(payload?.settings || payload || {}) };
			}
		} catch { }

		// cache and paint
		localStorage.setItem("nms_settings", JSON.stringify(s));
		uiSet(s);
	}

	async function save() {
		const s = uiGet();
		try {
			const res = await fetch(SETTINGS_API, {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify(s),
			});
			if (!res.ok) throw new Error("HTTP " + res.status);
			localStorage.setItem("nms_settings", JSON.stringify(s));
			note("Saved");
		} catch (e) {
			console.error("Save failed", e);
			note("Save failed");
		}
	}

	async function reset() {
		uiSet(DEFAULTS);
		await save();
	}

	function boot() {
		els.saveBtn?.addEventListener("click", (e) => { e.preventDefault(); save(); });
		els.resetBtn?.addEventListener("click", (e) => { e.preventDefault(); reset(); });
		load();
	}

	if (document.readyState === "loading") {
		document.addEventListener("DOMContentLoaded", boot, { once: true });
	} else {
		boot();
	}
})();
  