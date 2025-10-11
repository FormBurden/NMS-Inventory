(function(){
  const grid = document.getElementById('grid');
  const search = document.getElementById('search');
  const includeTech = document.getElementById('includeTech');

  function el(tag, props={}, children=[]) {
    const e = document.createElement(tag);
    Object.assign(e, props);
    for (const c of children) e.appendChild(c);
    return e;
  }

  function cardRow(r) {
    const img = el('img', {src:r.icon_url, alt:r.resource_id, loading:'lazy'});
    return el('div', {className:'card'}, [
      el('div', {className:'icon'}, [img]),
      el('div', {className:'meta'}, [
        el('div', {className:'rid', title:r.resource_id, textContent:r.resource_id}),
        el('div', {className:'amt', textContent:r.amount.toLocaleString()}),
      ])
    ]);
  }

  let all = [];
  function render() {
    grid.innerHTML = '';
    const q = (search.value || '').trim().toUpperCase();
    const rows = q ? all.filter(r => r.resource_id.includes(q)) : all;
    for (const r of rows) grid.appendChild(cardRow(r));
  }

  async function load() {
    const params = new URLSearchParams();
    if (includeTech.checked) params.set('include_tech','1');
    const res = await fetch('/api/inventory.php?'+params.toString());
    const js = await res.json();
    all = js.rows || [];
    render();
  }

  search.addEventListener('input', render);
  includeTech.addEventListener('change', load);

  load();
})();
