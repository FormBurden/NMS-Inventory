<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>NMS Inventory</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="stylesheet" href="/assets/css/app.css">
</head>
<body>
  <header class="topbar">
    <div class="title">NMS Inventory</div>
    <div class="actions">
      <label><input type="checkbox" id="includeTech"> Include Tech</label>
      <input type="text" id="search" placeholder="Search…">
      <a class="btn" href="/Settings/">Settings</a>
    </div>
  </header>
  <main>
  <nav class="tabs" id="tabs">
      <button class="tab active" data-scope="character">Character</button>
      <button class="tab" data-scope="base">Base</button>
      <button class="tab" data-scope="storage">Storage</button>
      <button class="tab" data-scope="frigate">Frigate</button>
      <button class="tab" data-scope="corvette">Corvette</button>
      <button class="tab" data-scope="ship">Ship</button>
      <button class="tab" data-scope="vehicle">Vehicles</button>
    </nav>

    <div id="grid" class="grid"></div>
  </main>
  <script src="/assets/js/inventory.js"></script>
</body>
</html>
