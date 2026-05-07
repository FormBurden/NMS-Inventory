/* NMS-Inventory: state.inventory.js */
(() => {
	const NS = (window.NMSI = window.NMSI || {});
	const { assert, API } = NS;

	const DEFAULTS = {
		defaultWindow: "character",
		iconSize: "medium",
		showNegatives: true,
		autoRefreshSec: 10,
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

	function applyThemeAndIcons(s) {
		document.body.classList.remove("icon-sm", "icon-md", "icon-lg");
		document.body.classList.add(
			s.iconSize === "small" ? "icon-sm" : s.iconSize === "large" ? "icon-lg" : "icon-md"
		);
		document.body.classList.toggle("theme-light", s.theme === "light");
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
  