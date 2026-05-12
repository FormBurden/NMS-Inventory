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

	const BASE = (window.NMS_BASE || "/").replace(/\/+$/, ""), SETTINGS_API = `${BASE}/api/settings.php`;
	const DEFAULTS = (window.NMSI && window.NMSI.SETTINGS_DEFAULTS) || { language: "en-us", defaultWindow: "character", iconSize: "medium", showNegatives: true, autoRefreshSec: 15, theme: "system" };

	function normalizeDefaultWindow(value) {
		const normalized = String(value || DEFAULTS.defaultWindow).trim().toLowerCase();
		if (normalized === "vehicles" || normalized === "exocraft") return "vehicle";
		if (normalized === "freighter") return "frigate";
		if (normalized === "exosuit" || normalized === "suit") return "character";
		return normalized || DEFAULTS.defaultWindow;
	}

	function normalizeIconSize(value) {
		const normalized = String(value || DEFAULTS.iconSize).trim().toLowerCase();
		return normalized === "small" || normalized === "medium" || normalized === "large" ? normalized : DEFAULTS.iconSize;
	}

	function normalizeTheme(value) {
		const normalized = String(value || DEFAULTS.theme).trim().toLowerCase();
		return normalized === "system" || normalized === "light" || normalized === "dark" ? normalized : DEFAULTS.theme;
	}

	function normalizeAutoRefresh(value) {
		const n = Number.parseInt(String(value ?? DEFAULTS.autoRefreshSec), 10);
		if (!Number.isFinite(n) || n < 0) return 0;
		return Math.min(n, 3600);
	}

	function shouldUseLightTheme(theme) {
		if (theme === "light") return true;
		if (theme === "dark") return false;
		return !!window.matchMedia?.("(prefers-color-scheme: light)")?.matches;
	}

	function applyThemeAndIcons(s) {
		const iconSize = normalizeIconSize(s.iconSize);
		const theme = normalizeTheme(s.theme);

		document.body.classList.remove("icon-sm", "icon-md", "icon-lg");
		document.body.classList.add(
			iconSize === "small" ? "icon-sm" : iconSize === "large" ? "icon-lg" : "icon-md"
		);
		document.body.classList.toggle("theme-light", shouldUseLightTheme(theme));
	}

	function normalizeSettings(s) {
		return {
			language: String(s.language || DEFAULTS.language),
			defaultWindow: normalizeDefaultWindow(s.defaultWindow),
			iconSize: normalizeIconSize(s.iconSize),
			showNegatives: s.showNegatives !== false,
			autoRefreshSec: normalizeAutoRefresh(s.autoRefreshSec),
			theme: normalizeTheme(s.theme),
		};
	}

	function uiSet(s) {
		const normalized = normalizeSettings(s || {});
		if (els.defaultWindow) els.defaultWindow.value = normalized.defaultWindow;
		if (els.language) els.language.value = normalized.language;
		if (els.iconSize) els.iconSize.value = normalized.iconSize;
		if (els.showNegatives) els.showNegatives.checked = normalized.showNegatives;
		if (els.autoRefreshSec) els.autoRefreshSec.value = String(normalized.autoRefreshSec);
		if (els.theme) els.theme.value = normalized.theme;
		applyThemeAndIcons(normalized);
	}

	function uiGet() {
		return normalizeSettings({
			defaultWindow: els.defaultWindow?.value || DEFAULTS.defaultWindow,
			language: els.language?.value || DEFAULTS.language,
			iconSize: els.iconSize?.value || DEFAULTS.iconSize,
			showNegatives: !!els.showNegatives?.checked,
			autoRefreshSec: els.autoRefreshSec?.value || "0",
			theme: els.theme?.value || DEFAULTS.theme,
		});
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

		s = normalizeSettings(s);

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
			const payload = await res.json().catch(() => null);
			const saved = normalizeSettings(payload?.settings || s);
			localStorage.setItem("nms_settings", JSON.stringify(saved));
			uiSet(saved);
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