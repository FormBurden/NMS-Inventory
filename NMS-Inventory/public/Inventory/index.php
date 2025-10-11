<?php require_once __DIR__ . '/../../includes/bootstrap.php'; ?>
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>NMS Inventory</title>
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <link rel="stylesheet" href="/assets/css/app.css">
</head>
<body>
  <header class="topbar">
    <div class="title">NMS Inventory</div>
    <div class="actions">
      <label><input type="checkbox" id="includeTech"> Include Tech</label>
      <input type="text" id="search" placeholder="Search…">
    </div>
  </header>
  <main>
    <div id="grid" class="grid"></div>
  </main>
  <script>window.NMS_BASE="/";</script>
  <script src="/assets/js/inventory.js"></script>
</body>
</html>
