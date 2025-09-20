(function () {
  // ---- DOM ----
  const grid = document.getElementById("grid");
  const search = document.getElementById("search");
  const includeTech = document.getElementById("includeTech");

  // ---- tiny DOM helper ----
  function el(tag, props = {}, children = []) {
    const e = document.createElement(tag);
    Object.assign(e, props);
    for (const c of children) e.appendChild(c);
    return e;
  }

  // ---- Human-readable name resolver (with cache + graceful fallbacks) ----
  const metaCache = new Map(); // gameId -> {name, kind}

  async function resolveItemMeta(gameId) {
    const key = String(gameId || "").toUpperCase();
    if (!key) return { name: "", kind: null };
    if (metaCache.has(key)) return metaCache.get(key);

    // 1) Fast local map for the common stuff
    const quick = {
      LAND1: { name: "Ferrite Dust", kind: "Substance" },
      LAND2: { name: "Pure Ferrite", kind: "Substance" },
      LAND3: { name: "Magnetised Ferrite", kind: "Substance" },
      FUEL1: { name: "Carbon", kind: "Substance" },
      FUEL2: { name: "Condensed Carbon", kind: "Substance" },
      YELLOW2: { name: "Copper", kind: "Substance" },
      WATER2: { name: "Chlorine", kind: "Substance" },
      LAUNCHFUEL: { name: "Starship Launch Fuel", kind: "Product" },
    };
    if (quick[key]) {
      metaCache.set(key, quick[key]);
      return quick[key];
    }

    // 2) Try a public catalogue (optional; ignored if it fails/CORS blocks)
    try {
      const resp = await fetch(
        "/api/item_meta.php?search=" + encodeURIComponent(key),
        { credentials: "same-origin" }
      );
      if (resp.ok) {
        const data = await resp.json();
        const items = Array.isArray(data?.items) ? data.items : [];
        const hit =
          items.find((x) => String(x.gameId || "").toUpperCase() === key) ||
          items[0];
        if (hit) {
          const meta = {
            name: hit.name || key,
            // prefer Product/Technology signals if present; else assume Substance
            kind: hit.type === "Product" ? "Product" : hit.isTech ? "Technology" : "Substance",
          };
          metaCache.set(key, meta);
          return meta;
        }
      }
    } catch (_) {
      // offline / CORS / API change — just fall through to prettified fallback
    }

    // 3) Prettify the code as a last resort
    const nice =
      key
        .replace(/^(\^|U_)/, "") // strip leading ^ or U_
        .replace(/_/g, " ")
        .toLowerCase()
        .replace(/\b\w/g, (c) => c.toUpperCase()) || key;
    const meta = { name: nice, kind: null };
    metaCache.set(key, meta);
    return meta;
  }

  // ---- Rendering ----
  function cardRow(r) {
    const img = el("img", {
      src: r.icon_url, // already built by the API (with &type hint)
      alt: r.display_name || r.display_id || r.resource_id,
      loading: "lazy",
    });

    return el("div", { className: "card" }, [
      el("div", { className: "icon" }, [img]),
      el("div", { className: "meta" }, [
        el("div", {
          className: "rid",
          title: r.display_name || r.display_id || r.resource_id,
          textContent: r.display_name || r.display_id || r.resource_id,
        }),
        el("div", {
          className: "amt",
          textContent: Number(r.amount || 0).toLocaleString(),
        }),
      ]),
    ]);
  }

  let all = [];

  function render() {
    grid.innerHTML = "";
    const q = (search.value || "").trim().toUpperCase();
    const rows = q
      ? all.filter((r) => {
        const name = String(r.display_name || "").toUpperCase();
        const rid = String(r.resource_id || "").toUpperCase();
        const disp = String(r.display_id || "").toUpperCase();
        return name.includes(q) || rid.includes(q) || disp.includes(q);
      })
      : all;

    for (const r of rows) grid.appendChild(cardRow(r));
  }

  async function decorateRowsWithNames(rows) {
    // Resolve names in parallel (but don’t block the UI longer than needed)
    await Promise.all(
      rows.map(async (r) => {
        const meta = await resolveItemMeta(r.resource_id);
        if (meta?.name) r.display_name = meta.name;
        // If resolver learned a better kind, you can rebuild icon_url if desired:
        // if (meta?.kind && meta.kind !== r.type) {
        //   r.icon_url = `/api/icon.php?id=${encodeURIComponent(r.resource_id)}&type=${encodeURIComponent(meta.kind)}`;
        // }
      })
    );
  }

  async function load() {
    const params = new URLSearchParams();
    if (includeTech && includeTech.checked) params.set("include_tech", "1");

    const res = await fetch("/api/inventory.php?" + params.toString());
    const js = await res.json();
    all = js.rows || [];

    // add human-readable names (non-fatal if network blocks)
    try {
      await decorateRowsWithNames(all);
    } catch (_) { }

    render();
  }

  if (search) search.addEventListener("input", render);
  if (includeTech) includeTech.addEventListener("change", load);

  load();
})();
