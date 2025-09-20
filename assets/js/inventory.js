/* NMS Inventory UI – uses local items catalogue (public/data/items_local.json)
   and your own icon redirector (/api/icon.php). No external API calls. */

(() => {
  // ---------- DOM ----------
  const els = {
    grid: document.getElementById("grid"),
    search: document.getElementById("search"),
    includeTech: document.getElementById("includeTech"),
  };

  // ---------- Config ----------
  const BASE = (window.NMS_BASE || "/").replace(/\/+$/, "");
  const ENDPOINTS = {
    items: `${BASE}/data/items_local.json`,
    inventory: `${BASE}/api/inventory.php`,
    icon: `${BASE}/api/icon.php`,
    placeholder: `${BASE}/assets/img/placeholder.png`,
  };

  // ---------- State ----------
  const state = {
    catalogue: {},  // { GAMEID: { name, kind, icon, appId } }
    rows: [],       // API rows enriched with display_name, icon_url, etc.
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
  function cardRow(r) {
    const img = el("img", {
      src: r.icon_url,
      alt: r.display_name || r.resource_id,
      loading: "lazy",
      crossOrigin: "anonymous",
    });

    // If CDN icon fails, try icon.php without type, then final placeholder
    img.addEventListener("error", () => {
      if (!img.dataset.fallback1) {
        img.dataset.fallback1 = "1";
        img.src = `${ENDPOINTS.icon}?id=${encodeURIComponent(r.resource_id)}`;
      } else if (!img.dataset.fallback2) {
        img.dataset.fallback2 = "1";
        img.src = ENDPOINTS.placeholder;
      }
    });

    return el("div", { className: "card" }, [
      el("div", { className: "icon" }, [img]),
      el("div", { className: "meta" }, [
        el("div", {
          className: "rid",
          title: r.display_name || r.resource_id,
          textContent: r.display_name || r.resource_id,
        }),
        el("div", {
          className: "amt",
          textContent: Number(r.amount || 0).toLocaleString(),
        }),
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

    // Optional: alpha sort by display name for readability
    rows = rows.slice().sort((x, y) =>
      String(x.display_name || x.resource_id).localeCompare(String(y.display_name || y.resource_id))
    );

    for (const r of rows) els.grid.appendChild(cardRow(r));
  }

  // ---------- Data loaders ----------
  async function loadCatalogue() {
    try {
      const res = await fetch(ENDPOINTS.items, { cache: "no-store" });
      if (!res.ok) throw new Error(`Failed to load ${ENDPOINTS.items}`);
      state.catalogue = await res.json();
    } catch (e) {
      console.warn("[inventory] items_local.json unavailable; names/icons may be raw IDs", e);
      state.catalogue = {};
    }
  }

  async function loadInventory() {
    const params = new URLSearchParams();
    if (els.includeTech && els.includeTech.checked) params.set("include_tech", "1");

    const url = `${ENDPOINTS.inventory}${params.toString() ? `?${params}` : ""}`;
    const res = await fetch(url, { cache: "no-store" });
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
  }

  // ---------- Init ----------
  async function boot() {
    // hook events first so quick typing is responsive after first paint
    if (els.search) els.search.addEventListener("input", render);
    if (els.includeTech) els.includeTech.addEventListener("change", loadInventory);

    await loadCatalogue();   // names/kinds/icons
    await loadInventory();   // data from DB → then render
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot, { once: true });
  } else {
    boot();
  }
})();
  