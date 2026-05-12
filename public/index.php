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
      <input type="text" id="search" placeholder="Search…">
      <a class="btn" href="/Settings/">Settings</a>
    </div>
  </header>
  <main>
    <nav class="tabs" id="tabs">
      <div class="tabs-left">
        <button class="tab active" data-scope="character" data-view="inventory">Character</button>
        <button class="tab" data-scope="base" data-view="inventory">Base</button>
        <button class="tab" data-scope="storage" data-view="inventory">Storage</button>
        <button class="tab" data-scope="frigate" data-view="inventory">Frigate</button>
        <button class="tab" data-scope="corvette" data-view="inventory">Corvette</button>
        <button class="tab" data-scope="ship" data-view="inventory">Ship</button>
        <button class="tab" data-scope="vehicle" data-view="inventory">Vehicles</button>
      </div>
      <div class="tabs-right">
        <button class="tab recent-tab" data-scope="all" data-view="recent">Recent</button>
        <button class="tab stat-tab" data-scope="character" data-view="stats">Character Stats</button>
        <button class="tab stat-tab" data-scope="ship" data-view="stats">Ship Stats</button>
        <button class="tab stat-tab" data-scope="corvette" data-view="stats">Corvette Stats</button>
        <button class="tab stat-tab" data-scope="freighter" data-view="stats">Freighter Stats</button>
        <button class="tab stat-tab" data-scope="vehicle" data-view="stats">Vehicle Stats</button>
      </div>
    </nav>

    <div id="recentSessionBar" class="recent-session-bar" hidden>
      <label for="recentSessionSelect">Session</label>
      <select id="recentSessionSelect" class="recent-session-select"></select>
    </div>

    <div id="grid" class="grid"></div>
  </main>
  <script src="/assets/js/inventory.js"></script>
</body>
</html>
