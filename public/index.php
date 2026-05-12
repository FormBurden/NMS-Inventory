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

    <button id="inventoryViewToggle" class="view-toggle" type="button" aria-controls="inventoryViewPanel" aria-expanded="false">&gt;&gt;&gt;</button>

    <aside id="inventoryViewPanel" class="view-panel" aria-hidden="true" hidden>
      <div class="view-panel-header">
        <div class="view-panel-title">View Options</div>
        <button id="inventoryViewClose" class="view-panel-close" type="button" aria-label="Close view options">×</button>
      </div>

      <div class="view-panel-section">
        <label for="inventoryViewSort">Sort by</label>
        <select id="inventoryViewSort">
          <option value="alpha">Alphabetically</option>
          <option value="type">Type</option>
          <option value="category">Category</option>
          <option value="group">Group</option>
          <option value="amount_desc">Amount: high to low</option>
          <option value="amount_asc">Amount: low to high</option>
          <option value="id">Raw ID</option>
        </select>
      </div>

      <details class="view-panel-disclosure">
        <summary>Include broad types</summary>
        <fieldset class="view-panel-section">
          <div class="view-filter-actions">
            <button class="view-filter-action" type="button" data-view-bulk="broad" data-view-bulk-action="select">Select all</button>
            <button class="view-filter-action" type="button" data-view-bulk="broad" data-view-bulk-action="deselect">Deselect all</button>
          </div>
          <label><input type="checkbox" id="viewTypeResources" data-view-setting="showResources"> Resources</label>
          <label><input type="checkbox" id="viewTypeTechnology" data-view-setting="showTechnology"> Technology</label>
          <label><input type="checkbox" id="viewTypeUpgrades" data-view-setting="showUpgrades"> Upgrades / Modules</label>
          <label><input type="checkbox" id="viewTypeBuilding" data-view-setting="showBuilding"> Building / Base</label>
          <label><input type="checkbox" id="viewTypeUnknown" data-view-setting="showUnknown"> Unknown</label>
        </fieldset>
      </details>

      <details class="view-panel-disclosure">
        <summary>Categories</summary>
        <fieldset class="view-panel-section">
          <div class="view-filter-actions">
            <button class="view-filter-action" type="button" data-view-bulk="category" data-view-bulk-action="select">Select all</button>
            <button class="view-filter-action" type="button" data-view-bulk="category" data-view-bulk-action="deselect">Deselect all</button>
          </div>
          <div id="viewCategoryList" class="view-type-list"></div>
        </fieldset>
      </details>

      <details class="view-panel-disclosure">
        <summary>Groups</summary>
        <fieldset class="view-panel-section">
          <input type="search" id="viewGroupSearch" class="view-filter-search" placeholder="Search groups…" autocomplete="off">
          <div class="view-filter-actions">
            <button class="view-filter-action" type="button" data-view-bulk="group" data-view-bulk-action="select">Select all</button>
            <button class="view-filter-action" type="button" data-view-bulk="group" data-view-bulk-action="deselect">Deselect all</button>
          </div>
          <div id="viewGroupList" class="view-type-list"></div>
        </fieldset>
      </details>

      <details class="view-panel-disclosure">
        <summary>Tags</summary>
        <fieldset class="view-panel-section">
          <input type="search" id="viewTagSearch" class="view-filter-search" placeholder="Search tags…" autocomplete="off">
          <div class="view-filter-actions">
            <button class="view-filter-action" type="button" data-view-bulk="tag" data-view-bulk-action="select">Select all</button>
            <button class="view-filter-action" type="button" data-view-bulk="tag" data-view-bulk-action="deselect">Deselect all</button>
          </div>
          <div id="viewTagList" class="view-type-list"></div>
        </fieldset>
      </details>

      <details class="view-panel-disclosure">
        <summary>Exact types</summary>
        <fieldset class="view-panel-section">
          <div class="view-filter-actions">
            <button class="view-filter-action" type="button" data-view-bulk="kind" data-view-bulk-action="select">Select all</button>
            <button class="view-filter-action" type="button" data-view-bulk="kind" data-view-bulk-action="deselect">Deselect all</button>
          </div>
          <div id="viewTypeList" class="view-type-list"></div>
        </fieldset>
      </details>

      <div class="view-panel-actions">
        <button id="inventoryViewReset" class="tab" type="button">Reset View</button>
      </div>
    </aside>

    <div id="grid" class="grid"></div>
  </main>
  <script src="/assets/js/inventory.js"></script>
</body>
</html>
