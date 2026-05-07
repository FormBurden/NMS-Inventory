/* NMS-Inventory: inventory.js (compat shim) */
(() => {
  const BASE = (window.NMS_BASE || "/").replace(/\/+$/, "");
  const scripts = [
    `${BASE}/assets/js/util.assert.js`,
    `${BASE}/assets/js/core.dom.js`,
    `${BASE}/assets/js/api.client.js`,
    `${BASE}/assets/js/state.inventory.js`,
    `${BASE}/assets/js/ui.inventory.render.js`,
    `${BASE}/assets/js/boot.inventory.js`,
  ];
  function loadScript(url) {
    return new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = url;
      s.async = false; // preserve order
      s.onload = () => resolve();
      s.onerror = () => reject(new Error("Failed to load " + url));
      document.head.appendChild(s);
    });
  }
  async function boot() {
    for (const u of scripts) { await loadScript(u); }
    if (window.NMSI && typeof window.NMSI.bootInventory === "function") {
      window.NMSI.bootInventory();
    } else {
      console.error("[inventory] boot module missing");
    }
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => { boot().catch(console.error); }, { once: true });
  } else {
    boot().catch(console.error);
  }
})();
