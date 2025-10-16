/* NMS Inventory UI – uses local items catalogue (public/data/items_local.json)
   and your own icon redirector (/api/icon.php). No external API calls. */

(() => {
  // ---------- DOM ----------
  const els = {
    grid: document.getElementById("grid"),
    search: document.getElementById("search"),
    includeTech: document.getElementById("includeTech"),
    tabs: document.getElementById("tabs"),
  };

  // ---------- Config ----------
  const BASE = (window.NMS_BASE || "/").replace(/\/+$/, "");
  const ENDPOINTS = {
    catalogue: `${BASE}/api/item_meta.php`,
    inventory: `${BASE}/api/inventory.php`,
    settings: `${BASE}/api/settings.php`,
    items: `${BASE}/data/items_local.json`,
    icon: `${BASE}/api/icon.php`,
    placeholder: 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw=='
    
  };
  const EAGER_IMG_COUNT = 12; // first N icons render eager + high priority




  // ---------- State ----------
  const state = {
    catalogue: {},  // { GAMEID: { name, kind, icon, appId } }
    rows: [],       // API rows enriched with display_name, icon_url, etc.
    scope: "character",
  };

  // ---------- Utils ----------
  function el(tag, props = {}, children = []) {
    const e = document.createElement(tag);
    Object.assign(e, props);
    for (const c of [].concat(children)) if (c != null) e.appendChild(c);
    return e;
  }

  function normalizeRID(x) {
    return String(x || "").replace(/^\^/, "").trim().toUpperCase();
  }

  function resolveMeta(id) {
    const gid = normalizeRID(id);
    const m = state.catalogue[gid] || {};
    return {
      id: gid,
      name: m.name || gid,
      kind: m.kind || null,      // "Substance" | "Product" | "Technology" | null
      icon: m.icon || null,      // may be a CDN URL; we still route via icon.php
      appId: m.appId || null,
    };
  }

  function iconSrcFor(row) {
    // Route through PHP so sources can be swapped centrally and to leverage fallbacks
    const typeHint = encodeURIComponent(row.type || "");
    return `${ENDPOINTS.icon}?id=${encodeURIComponent(row.resource_id)}${typeHint ? `&type=${typeHint}` : ""}`;
  }

  // ---------- Rendering ----------
  function cardRow(r, eager = false) {
    const img = el("img", {
      src: r.icon_url,
      alt: r.display_name || r.resource_id,
      loading: eager ? "eager" : "lazy",
      crossOrigin: "anonymous",
    });
    if (eager) img.setAttribute("fetchpriority", "high");

    // If CDN/icon fails, try icon.php without type, then a final 1x1 placeholder
    img.addEventListener("error", () => {
      if (!img.dataset.fallback1) {
        img.dataset.fallback1 = "1";
        img.src = `${ENDPOINTS.icon}?id=${encodeURIComponent(String(r.resource_id || ""))}`;
      } else if (!img.dataset.fallback2) {
        img.dataset.fallback2 = "1";
        img.src = ENDPOINTS.placeholder;
      }
    });

    return el("div", { className: "card" }, [
      el("div", { className: "icon" }, [img]),
      el("div", { className: "meta" }, [
        el("div", { className: "rid", title: r.display_name || r.resource_id, textContent: r.display_name || r.resource_id }),
        el("div", { className: "amt", textContent: Number(r.amount || 0).toLocaleString() }),
      ]),
    ]);
  }

  function render() {
    if (!els.grid) return;
    els.grid.innerHTML = "";

    const q = (els.search?.value || "").trim().toLowerCase();
    let rows = state.rows;

    if (q) {
      rows = rows.filter((r) => {
        const a = (r.display_name || "").toLowerCase();
        const b = (r.resource_id || "").toLowerCase();
        const c = (r.display_id || "").toLowerCase();
        return a.includes(q) || b.includes(q) || c.includes(q);
      });
    }
    // Hide negative totals if user disabled them in Settings
    if (!settings.showNegatives) {
      rows = rows.filter((r) => Number(r.amount || 0) >= 0);
    }
    
    // Sort: "recent first" if enabled and timestamps are present; else alpha by name
    if (settings.recentFirst) {
      const toTs = (v) => {
        if (!v) return 0;
        const t = Date.parse(v);
        return Number.isFinite(t) ? t : 0;
      };
      rows = rows.slice().sort((a, b) => (toTs(b.changed_at) - toTs(a.changed_at)));
    } else {
      rows = rows.slice().sort((x, y) =>
        String(x.display_name || x.resource_id).localeCompare(String(y.display_name || y.resource_id))
      );
    }


    rows.forEach((r, i) => els.grid.appendChild(cardRow(r, i < EAGER_IMG_COUNT)));
  }
  // ---------- Scope / Tabs ----------
  function setScope(scope) {
    state.scope = String(scope || "character").toLowerCase();
    if (els.tabs) {
      const btns = els.tabs.querySelectorAll('button[data-scope]');
      btns.forEach(b => b.classList.toggle('active', b.dataset.scope === state.scope));
    }
    // Reflect scope in URL (?tab=...) without reload
    try {
      const url = new URL(location.href);
      url.searchParams.set('tab', state.scope);
      history.replaceState(null, '', url);
    } catch { }
    // Fetch inventory for the selected scope
    loadInventory();
  }

  
  // ---------- Data loaders ----------
  async function loadCatalogue() {
    try {
      const qs = new URLSearchParams();
      if (els.includeTech && els.includeTech.checked) qs.set("include_tech", "1");
      // Load the entire local catalogue map (GAMEID -> {name, kind, icon, appId})
      const res = await fetch(ENDPOINTS.items, { cache: "no-store" });
      if (!res.ok) throw new Error(`Failed to load ${ENDPOINTS.items}`);
      state.catalogue = await res.json();

    } catch (e) {
      console.warn("[inventory] items_local.json unavailable; names/icons may be raw IDs", e);
      state.catalogue = {};
    }
  }

  async function loadInventory() {
    try {
      const params = new URLSearchParams();
      if (els.includeTech && els.includeTech.checked) params.set("include_tech", "1");
      if (state.scope) params.set("scope", state.scope);
      if (settings.recentFirst) params.set("sort", "recent"); // ensure API returns changed_at + recent ORDER BY
      params.set("__nocache", String(Date.now()));

      const url = `${ENDPOINTS.inventory}?${params}`;
      const res = await fetch(url, { cache: "no-store" });
      if (!res.ok) throw new Error(`Failed to load ${url} (${res.status})`);
      const payload = await res.json();

      // Accept either { rows: [...] } or a raw array fallback
      const rows = Array.isArray(payload?.rows) ? payload.rows : (Array.isArray(payload) ? payload : []);

      state.rows = rows.map((row) => {
        const rid = normalizeRID(row.resource_id || row.id || row.rid || "");
        const meta = resolveMeta(rid);

        const enriched = {
          ...row,
          resource_id: rid,
          display_id: row.display_id || rid,
          display_name: meta.name || row.display_name || rid,
          type: (meta.kind || row.type || "").toString(),
        };

        enriched.icon_url = iconSrcFor(enriched);
        return enriched;
      });

      render();
    } catch (e) {
      console.warn("[inventory] loadInventory() failed", e);
      // keep current UI; auto-refresh will retry
      return;
    }
  }
  


  // ---------- Settings ----------
  const DEFAULT_SETTINGS = {
    language: "en-us",
    defaultWindow: "Character",
    iconSize: "medium",          // small | medium | large
    showNegatives: true,         // show negative rows in Inventory
    autoRefreshSec: 10,          // 0 (off), 5, 15, 60, ...
    theme: "system",             // light | dark | system
    recentFirst: false,
  };
  let settings = { ...DEFAULT_SETTINGS };
  let refreshTimer = null;

  function applySettings() {
    // icon size class on <body>
    document.body.classList.remove("icon-sm", "icon-md", "icon-lg");
    const sizeClass = settings.iconSize === "small" ? "icon-sm"
      : settings.iconSize === "large" ? "icon-lg"
        : "icon-md";
    document.body.classList.add(sizeClass);

    // theme class on <body>
    document.body.classList.remove("theme-light");
    if (settings.theme === "light") {
      document.body.classList.add("theme-light");
    } else if (settings.theme === "dark") {
      // current CSS defaults are dark; no extra class needed
    } else {
      // system: do nothing; keep default
    }
  }

  async function loadSettings() {
    // 1) Start from localStorage cache
    try {
      const raw = localStorage.getItem("nms_settings");
      if (raw) settings = { ...settings, ...JSON.parse(raw) };
    } catch { }

    // 2) Prefer server copy if available
    if (ENDPOINTS.settings) {
      try {
        const res = await fetch(ENDPOINTS.settings, { cache: "no-store" });
        if (res.ok) {
          const payload = await res.json();
          const sv = payload?.settings || payload || {};
          settings = { ...settings, ...sv };
          localStorage.setItem("nms_settings", JSON.stringify(settings));
        }
      } catch { }
    }
  }

  function scheduleAutoRefresh() {
    if (refreshTimer) clearInterval(refreshTimer);
    const n = parseInt(settings.autoRefreshSec, 10) || 0;
    if (n > 0) refreshTimer = setInterval(() => loadInventory(), n * 1000);
  }
  

  // ---------- Init ----------
  async function boot() {
    // Hook UI events first
    if (els.search) els.search.addEventListener("input", render);
    if (els.includeTech) els.includeTech.addEventListener("change", loadInventory);
    // --- Recent-first toggle UI ---
    try {
      const host = els.tabs || (els.search && els.search.parentElement) || document.body;
      const wrap = el("label", { className: "nms-toggle-recent", style: "margin-left: .75rem; display:inline-flex; gap:.4rem; align-items:center;" }, []);
      const cb = el("input", { type: "checkbox", id: "toggleRecentFirst" }, []);
      const txt = el("span", { textContent: "Recent first" }, []);
      wrap.appendChild(cb);
      wrap.appendChild(txt);
      host.appendChild(wrap);

      // reflect current setting
      cb.checked = !!settings.recentFirst;

      // persist and re-render on change
      cb.addEventListener("change", () => {
        settings.recentFirst = !!cb.checked;
        try { localStorage.setItem("nms_settings", JSON.stringify(settings)); } catch { }
        // re-load so we can request ?sort=recent and get changed_at when available
        loadInventory();
      });
    } catch { }


    // Load settings first, apply visual prefs (icon size/theme)
    try { await loadSettings(); } catch { }
    try { applySettings(); } catch { }

    // Choose initial scope: URL ?tab= overrides Settings.defaultWindow
    let initialScope = "character";
    try {
      const qp = new URLSearchParams(location.search);
      const tab = qp.get("tab");
      initialScope = (tab || settings.defaultWindow || "character").toLowerCase();
    } catch { }
    setScope(initialScope);

    // Data bootstrap (start auto-refresh early so a transient API error doesn't stall the UI)
    try { await loadCatalogue(); } catch { }
    try { scheduleAutoRefresh(); } catch { }

    // Kick off a first load but don't block boot on network/DB hiccups
    try {
      await loadInventory();
    } catch (e) {
      console.warn("[inventory] initial load failed; will retry via auto-refresh", e);
    }


  }

  if (els.tabs) {
    els.tabs.addEventListener("click", (ev) => {
      const b = ev.target.closest("button[data-scope]");
      if (b) setScope(b.dataset.scope);
    });
    // initialize from the active button (or first)
    const current = els.tabs.querySelector("button.active[data-scope]") || els.tabs.querySelector("button[data-scope]");
    if (current) state.scope = current.dataset.scope;
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot, { once: true });
  } else {
    boot();
  }
})();
  