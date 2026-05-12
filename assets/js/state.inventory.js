/* NMS-Inventory: state.inventory.js */
(() => {
	const NS = (window.NMSI = window.NMSI || {});
	const { assert, API } = NS;

	const DEFAULTS = {
		defaultWindow: "character",
		iconSize: "medium",
		showNegatives: true,
		autoRefreshSec: 15,
		theme: "system",
		recentFirst: false,
	};

	const state = {
		scope: "character",
		rows: [],
		catalogue: {},
		settings: { ...DEFAULTS },
		timer: null,
	};

	function normalizeSettings(s) {
		const defaultWindow = String(s.defaultWindow || DEFAULTS.defaultWindow).trim().toLowerCase();
		const iconSize = String(s.iconSize || DEFAULTS.iconSize).trim().toLowerCase();
		const theme = String(s.theme || DEFAULTS.theme).trim().toLowerCase();
		const autoRefreshSec = Number.parseInt(String(s.autoRefreshSec ?? DEFAULTS.autoRefreshSec), 10);

		return {
			...s,
			defaultWindow: defaultWindow === "vehicles" || defaultWindow === "exocraft" ? "vehicle" : defaultWindow,
			iconSize: iconSize === "small" || iconSize === "medium" || iconSize === "large" ? iconSize : DEFAULTS.iconSize,
			showNegatives: s.showNegatives !== false,
			autoRefreshSec: Number.isFinite(autoRefreshSec) ? Math.max(0, Math.min(3600, autoRefreshSec)) : DEFAULTS.autoRefreshSec,
			theme: theme === "system" || theme === "light" || theme === "dark" ? theme : DEFAULTS.theme,
			recentFirst: s.recentFirst === true,
		};
	}

	function shouldUseLightTheme(theme) {
		if (theme === "light") return true;
		if (theme === "dark") return false;
		return !!window.matchMedia?.("(prefers-color-scheme: light)")?.matches;
	}

	function applyThemeAndIcons(s) {
		const normalized = normalizeSettings(s || {});
		document.body.classList.remove("icon-sm", "icon-md", "icon-lg");
		document.body.classList.add(
			normalized.iconSize === "small" ? "icon-sm" : normalized.iconSize === "large" ? "icon-lg" : "icon-md"
		);
		document.body.classList.toggle("theme-light", shouldUseLightTheme(normalized.theme));
	}

	async function loadSettings() {
		try {
			const raw = localStorage.getItem("nms_settings");
			if (raw) state.settings = { ...state.settings, ...JSON.parse(raw) };
		} catch { }
		try {
			const payload = await API.fetchJSON(API.ENDPOINTS.settings).catch(() => null);
			if (payload) state.settings = { ...state.settings, ...(payload.settings || payload) };
		} catch { }
		state.settings = normalizeSettings(state.settings);
		try { localStorage.setItem("nms_settings", JSON.stringify(state.settings)); } catch { }
		applyThemeAndIcons(state.settings);
	}

	function setScope(scope) {
		state.scope = String(scope || "character").toLowerCase();
		try {
			const u = new URL(location.href);
			u.searchParams.set("tab", state.scope);
			history.replaceState(null, "", u);
		} catch { }
	}

	function scheduleAutoRefresh(fn) {
		if (state.timer) clearInterval(state.timer);
		const sec = Number(state.settings.autoRefreshSec || 0);
		if (sec > 0 && sec <= 3600) state.timer = setInterval(fn, sec * 1000);
	}

	NS.State = { state, setScope, loadSettings, scheduleAutoRefresh };
})();
  