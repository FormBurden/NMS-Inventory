<?php
declare(strict_types=1);
?><!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>NMS Inventory · Settings</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="stylesheet" href="/assets/css/app.css">
  <style>
    .settings-wrap{max-width:780px;margin:24px auto;padding:0 14px;}
    .settings-card{background:var(--card);border:1px solid #1c2733;border-radius:12px;padding:16px;box-shadow:0 2px 10px rgba(0,0,0,.2);}
    .settings-grid{display:grid;grid-template-columns:1fr 2fr;gap:12px;align-items:center;}
    .settings-grid label{color:var(--muted)}
    .settings-grid input[type="checkbox"]{transform:scale(1.15)}
    .row{display:flex;gap:10px;margin-top:14px}
    .row .btn{display:inline-block;text-decoration:none;color:var(--fg);background:#0b0f14;border:1px solid #1c2733;padding:8px 12px;border-radius:8px;cursor:pointer}
    .status{margin-left:auto;opacity:.8}
    select, input[type="number"]{background:#0b0f14;color:var(--fg);border:1px solid #1c2733;padding:6px 8px;border-radius:6px}
  </style>
</head>
<body>
  <header class="topbar">
    <div class="title">Settings</div>
    <div class="actions"><a class="btn" href="/">← Back</a></div>
  </header>

  <main class="settings-wrap">
    <div class="settings-card">
      <div class="settings-grid">
        <label for="defaultWindow">Default Inventory Window</label>
        <select id="defaultWindow">
          <option>Character</option>
          <option>Base</option>
          <option>Storage</option>
          <option>Frigate</option>
          <option>Corvette</option>
          <option>Ship</option>
          <option>Vehicles</option>
        </select>

        <label for="language">Language</label>
        <select id="language">
          <option value="en-us">English (en-us)</option>
        </select>

        <label for="iconSize">Icon Size</label>
        <select id="iconSize">
          <option value="small">Small</option>
          <option value="medium">Medium</option>
          <option value="large">Large</option>
        </select>

        <label for="showNegatives">Show Negative Rows</label>
        <div><input type="checkbox" id="showNegatives"></div>

        <label for="autoRefreshSec">Auto-Refresh (seconds, 0=off)</label>
        <input id="autoRefreshSec" type="number" min="0" step="1" value="15">

        <label for="theme">Theme</label>
        <select id="theme">
          <option value="system">System</option>
          <option value="light">Light</option>
          <option value="dark">Dark</option>
        </select>
      </div>

      <div class="row">
        <button id="saveBtn" class="btn">Save</button>
        <button id="resetBtn" class="btn">Reset to Defaults</button>
        <span class="status" id="status"></span>
      </div>
    </div>
  </main>

  <script src="/assets/js/settings.js"></script>
</body>
</html>
