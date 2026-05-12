/* NMS-Inventory: boot.inventory.js */
(() => {
	const NS = (window.NMSI = window.NMSI || {});
	const { assert, on, API, State, UI, baseIdFromRid } = NS;
	const VIEW_PREFS_STORAGE_KEY = "nms_inventory_view_options";
	const VIEW_PREF_DEFAULTS = {
		sort: "alpha",
		showResources: true,
		showTechnology: true,
		showUpgrades: true,
		showBuilding: true,
		showUnknown: true,
		hiddenCategories: [],
		hiddenGroups: [],
		hiddenTags: [],
		hiddenKinds: [],
	};

	let lastObservedActiveSessionId = "";
	let recentSessionUserSelected = false;
	let viewPrefs = loadViewPrefs();

	async function loadCatalogue(includeTech) {
		try {
			const map = await API.fetchJSON(API.ENDPOINTS.items);
			State.state.catalogue = map || {};
		} catch {
			console.warn("[inventory] items_local.json unavailable; names/icons may be raw IDs");
			State.state.catalogue = {};
		}
	}

	function coerceRows(payload) {
		if (Array.isArray(payload)) return payload;
		if (payload && Array.isArray(payload.rows)) return payload.rows;
		if (payload && Array.isArray(payload.data)) return payload.data;
		return [];
		// If API ever changes, extend here (Power-of-Ten rule: explicit checks).
	}

	function lookupName(cat, rid) {
		const base = baseIdFromRid(rid);
		const tryKeys = [
			base,              // "CV_INV1"
			rid,               // "^CV_INV1#21992"
			base.toUpperCase(),
			base.toLowerCase(),
		];
		for (const k of tryKeys) {
			const v = k && cat[k];
			if (v && (typeof v === "string" || (v.name && typeof v.name === "string"))) {
				return typeof v === "string" ? v : v.name;
			}
		}
		return ""; // fallback to showing rid
	}

	function selectedButton() {
		return document.getElementById("tabs")?.querySelector("button.active") || null;
	}

	function selectedScope() {
		const b = selectedButton();
		return String(b?.dataset.scope || State.state.scope || "character").toLowerCase();
	}

	function selectedView() {
		const b = selectedButton();
		const view = b?.dataset.view || "inventory";
		return view === "stats" || view === "recent" ? view : "inventory";
	}

	function selectedRecentSessionId() {
		const select = document.getElementById("recentSessionSelect");
		return String(select?.value || "");
	}

	function setRecentSessionId(sessionId) {
		const select = document.getElementById("recentSessionSelect");
		if (!select) return;
		select.value = String(sessionId || "");
	}

	function activeSessionFromPayload(payload) {
		const sessions = Array.isArray(payload?.sessions) ? payload.sessions : [];

		for (const session of sessions) {
			if (session && session.active === true && session.id) {
				return session;
			}
		}

		if (payload?.session?.active === true && payload.session.id) {
			return payload.session;
		}

		return null;
	}

	function shouldAttachToActiveSession(payload) {
		const activeSession = activeSessionFromPayload(payload);
		if (!activeSession || !activeSession.id) {
			return false;
		}

		const activeId = String(activeSession.id);
		const selectedId = selectedRecentSessionId();
		const isNewActiveSession = activeId !== lastObservedActiveSessionId;

		lastObservedActiveSessionId = activeId;

		if (!selectedId || isNewActiveSession) {
			recentSessionUserSelected = false;
			setRecentSessionId(activeId);
			return selectedId !== activeId;
		}

		return false;
	}

	function setUrlView(view) {
		try {
			const u = new URL(location.href);
			if (view === "stats" || view === "recent") {
				u.searchParams.set("view", view);
			} else {
				u.searchParams.delete("view");
				u.searchParams.delete("session_id");
			}

			if (view === "recent") {
				const sessionId = selectedRecentSessionId();
				if (sessionId) {
					u.searchParams.set("session_id", sessionId);
				} else {
					u.searchParams.delete("session_id");
				}
			}

			history.replaceState(null, "", u);
		} catch { }
	}

	function activateSelection(scope, view) {
		const tabs = document.getElementById("tabs");
		if (!tabs) return;
		const normalizedScope = String(scope || "character").toLowerCase();
		const normalizedView = view === "stats" || view === "recent" ? view : "inventory";
		tabs.querySelectorAll("button[data-scope]").forEach(b => {
			b.classList.toggle(
				"active",
				String(b.dataset.scope || "").toLowerCase() === normalizedScope &&
				(b.dataset.view || "inventory") === normalizedView
			);
		});
	}

	function statBaseKey(row) {
		const base = baseIdFromRid(row.resource_id || row.base_id || row.catalogue_id).toUpperCase();
		const alias = String(row.aliasOf || "").trim().toUpperCase();

		return alias || base;
	}

	function statVehicleKind(row) {
		const key = statBaseKey(row);
		const base = baseIdFromRid(row.resource_id || row.base_id || row.catalogue_id).toUpperCase();
		const name = String(row.display_name || "").trim().toLowerCase();

		if (
			key.startsWith("MECH_") ||
			base.startsWith("MECH_") ||
			name.includes("minotaur") ||
			name.includes("hardframe") ||
			name.includes("daedalus")
		) {
			return "minotaur";
		}

		if (
			key.startsWith("SUB_") ||
			key.startsWith("NAUT_") ||
			base.startsWith("SUB_") ||
			base.startsWith("NAUT_") ||
			name.includes("nautilon")
		) {
			return "nautilon";
		}

		if (
			key.startsWith("BIKE_") ||
			base.startsWith("BIKE_") ||
			name.includes("pilgrim")
		) {
			return "pilgrim";
		}

		if (
			key.startsWith("TRUCK_") ||
			base.startsWith("TRUCK_") ||
			name.includes("colossus")
		) {
			return "colossus";
		}

		if (
			key.startsWith("BUGGY_") ||
			base.startsWith("BUGGY_") ||
			name.includes("nomad")
		) {
			return "nomad";
		}

		if (
			key.startsWith("ROVER_") ||
			key.startsWith("WHEELED_") ||
			base.startsWith("ROVER_") ||
			base.startsWith("WHEELED_") ||
			name.includes("roamer")
		) {
			return "roamer";
		}

		if (
			key === "FISH_SKIFF" ||
			base === "FISH_SKIFF" ||
			name.includes("exo-skiff") ||
			name.includes("exoskiff")
		) {
			return "skiff";
		}

		if (
			key.startsWith("VEHICLE_") ||
			base.startsWith("VEHICLE_") ||
			name.includes("exocraft") ||
			name.includes("drift suspension") ||
			name.includes("grip boost suspension") ||
			name.includes("fusion engine") ||
			name.includes("mounted cannon")
		) {
			return "exocraft";
		}

		return "";
	}

	function statVehicleKindLabel(kind) {
		if (kind === "minotaur") return "Minotaur";
		if (kind === "nautilon") return "Nautilon";
		if (kind === "pilgrim") return "Pilgrim";
		if (kind === "colossus") return "Colossus";
		if (kind === "nomad") return "Nomad";
		if (kind === "roamer") return "Roamer";
		if (kind === "exocraft") return "Exocraft";
		if (kind === "skiff") return "Exo-Skiff";

		return "";
	}

	function statTagMeta(row) {
		const key = statBaseKey(row);
		const base = baseIdFromRid(row.resource_id || row.base_id || row.catalogue_id).toUpperCase();
		const name = String(row.display_name || "").trim().toLowerCase();
		const vehicleKind = statVehicleKind(row);

		if (vehicleKind) {
			return {
				owner_category: "vehicle",
				vehicle_kind: vehicleKind,
				vehicle_kind_label: statVehicleKindLabel(vehicleKind),
				scope_tag: `vehicle:${vehicleKind}`,
			};
		}

		if (
			key.startsWith("FREI_") ||
			key === "F_HYPERDRIVE" ||
			key === "F_HDRIVEBOOST1"
		) {
			return {
				owner_category: "freighter",
				vehicle_kind: "",
				vehicle_kind_label: "",
				scope_tag: "freighter",
			};
		}

		if (
			key.startsWith("CV_") ||
			base.startsWith("CV_")
		) {
			return {
				owner_category: "corvette",
				vehicle_kind: "",
				vehicle_kind_label: "",
				scope_tag: "corvette",
			};
		}

		if (
			key.startsWith("SHIP") ||
			key.startsWith("HDRIVE") ||
			key.startsWith("LAUNCHER") ||
			key.startsWith("HYPERDRIVE") ||
			key.startsWith("WARP") ||
			key.startsWith("UT_SHIP") ||
			key === "UT_ROCKETS" ||
			key === "UT_LAUNCHCHARGE" ||
			key === "UT_QUICKWARP" ||
			key === "WATER_LANDER" ||
			name.includes("starship") ||
			name.includes("pulse engine") ||
			name.includes("launch thruster") ||
			name.includes("hyperdrive") ||
			name.includes("photon cannon") ||
			name.includes("deflector shield") ||
			name.includes("positron ejector") ||
			name.includes("phase beam") ||
			name.includes("rocket launcher")
		) {
			return {
				owner_category: "ship",
				vehicle_kind: "",
				vehicle_kind_label: "",
				scope_tag: "ship",
			};
		}

		return {
			owner_category: "character",
			vehicle_kind: "",
			vehicle_kind_label: "",
			scope_tag: "character",
		};
	}

	function statOwnerCategory(row) {
		return statTagMeta(row).owner_category;
	}

	function isStatRowForScope(row, scope) {
		const normalizedScope = String(scope || "character").toLowerCase();
		const ownerType = String(row.owner_type || "").trim().toLowerCase();
		const category = statOwnerCategory(row);

		if (normalizedScope === "vehicle" || normalizedScope === "exocraft" || normalizedScope === "vehicles") {
			return category === "vehicle";
		}

		if (normalizedScope === "ship" || normalizedScope === "starship") {
			return category === "ship";
		}

		if (normalizedScope === "corvette") {
			return category === "corvette";
		}

		if (normalizedScope === "freighter" || normalizedScope === "frigate") {
			return category === "freighter";
		}

		if (
			ownerType === "ship" ||
			ownerType === "vehicle" ||
			ownerType === "freighter" ||
			ownerType === "storage"
		) {
			return false;
		}

		return category === "character";
	}

	function isGeneralInventoryStatBase(base) {
		const allowed = new Set([
			"FISHLASER",
			"GRENADE",
			"LASER",
			"STUN_GREN",
			"TERRAINEDITOR",
		]);

		if (allowed.has(base)) return true;
		if (base.startsWith("U_")) return true;
		if (base.startsWith("UP_")) return true;
		if (base.startsWith("WEAPSLOT_DMG")) return true;

		return false;
	}

	function inventoryOwnerCategory(row) {
		const base = baseIdFromRid(row.resource_id || row.base_id || row.catalogue_id).toUpperCase();
		const kind = String(row.kind || "").trim().toLowerCase();

		if (base.startsWith("CV_")) {
			return "corvette";
		}

		if (
			kind === "building" ||
			base.startsWith("B_") ||
			base.startsWith("BASE_") ||
			base.startsWith("BUILD") ||
			base.startsWith("CONTAINER") ||
			base.startsWith("FRE_ROOM_") ||
			base.startsWith("GARAGE_")
		) {
			return "base";
		}

		return String(row.owner_type || "").trim().toLowerCase() || "unknown";
	}

	function isInventoryRowForScope(row, scope) {
		const normalizedScope = String(scope || "character").toLowerCase();
		const category = inventoryOwnerCategory(row);

		if (normalizedScope === "base") {
			return category === "base";
		}

		if (normalizedScope === "character" || normalizedScope === "exosuit" || normalizedScope === "suit") {
			return category === "character";
		}

		if (normalizedScope === "ship" || normalizedScope === "starship") {
			return category === "ship";
		}

		if (normalizedScope === "corvette") {
			return category === "corvette";
		}

		if (normalizedScope === "vehicle" || normalizedScope === "vehicles" || normalizedScope === "exocraft") {
			return category === "vehicle";
		}

		if (normalizedScope === "freighter" || normalizedScope === "frigate") {
			return category === "freighter";
		}

		if (normalizedScope === "storage") {
			return category === "storage";
		}

		return true;
	}

	function inventoryFamilyKey(row) {
		const category = inventoryOwnerCategory(row);
		const base = baseIdFromRid(row.resource_id || row.base_id || row.catalogue_id).toUpperCase();

		return `${category}:${base}`;
	}

	function combineInventoryRows(rows) {
		const groups = new Map();

		for (const row of rows) {
			const key = inventoryFamilyKey(row);
			const existing = groups.get(key);
			const amount = Number(row.amount || 0);
			const safeAmount = Number.isFinite(amount) ? amount : 0;

			if (!existing) {
				groups.set(key, {
					...row,
					amount: safeAmount,
					inventory_rows: [row],
					inventory_owner_category: inventoryOwnerCategory(row),
				});
				continue;
			}

			existing.amount = Number(existing.amount || 0) + safeAmount;
			existing.inventory_rows.push(row);

			if (String(existing.owner_type || "").toLowerCase() === "unknown" && String(row.owner_type || "").toLowerCase() !== "unknown") {
				existing.owner_type = row.owner_type;
			}

			if (!existing.source_icon_url && row.source_icon_url) existing.source_icon_url = row.source_icon_url;
			if (!existing.icon_url && row.icon_url) existing.icon_url = row.icon_url;
			if (!existing.appId && row.appId) existing.appId = row.appId;
			if (!existing.kind && row.kind) existing.kind = row.kind;
			if (!existing.display_name && row.display_name) existing.display_name = row.display_name;
		}

		return Array.from(groups.values()).sort((a, b) =>
			String(a.display_name || a.resource_id || "").localeCompare(String(b.display_name || b.resource_id || ""))
		);
	}

	function isStatRow(row) {
		const inventory = String(row.inventory || "").toLowerCase();
		const kind = String(row.kind || "").toLowerCase();
		const ownerType = String(row.owner_type || "").trim().toLowerCase();
		const base = baseIdFromRid(row.resource_id || row.base_id || row.catalogue_id).toUpperCase();

		if (base.startsWith("T_")) return false;
		if (base.startsWith("MAINT_")) return false;
		if (base.startsWith("EXOPOD_TECH")) return false;

		if (ownerType === "unknown" && statOwnerCategory(row) === "character") return false;

		if (base.startsWith("U_") || base.startsWith("UP_")) return true;
		if (base.startsWith("SHIP_") || base.startsWith("WEAPON_") || base.startsWith("FREI_") || base.startsWith("CV_")) return true;
		if (base === "F_HYPERDRIVE" || base === "F_HDRIVEBOOST1") return true;
		if (base.startsWith("VEHICLE_") || base.startsWith("MECH_") || base.startsWith("SUB_") || base.startsWith("NAUT_") || base === "FISH_SKIFF") return true;
		if (base.startsWith("SHIPSLOT_DMG") || base.startsWith("WEAPSLOT_DMG")) return true;

		if (inventory === "tech" || inventory === "technology") return true;

		if (inventory === "cargo") {
			return kind.includes("technology") || kind.includes("upgrade") || kind.includes("module");
		}

		if (inventory === "general") {
			return isGeneralInventoryStatBase(base);
		}

		return false;
	}

	function statFamilyKey(row) {
		const base = baseIdFromRid(row.resource_id || row.base_id || row.catalogue_id).toUpperCase();
		const alias = String(row.aliasOf || "").trim().toUpperCase();

		if (alias) return `family:${alias}`;

		if (base.startsWith("U_")) {
			return `family:${base.slice(2)}`;
		}

		if (base.startsWith("UP_")) {
			return `family:${base.slice(3)}`;
		}

		if (base === "UT_SHIPGUN") return "family:SHIPGUN1";
		if (base === "UT_SHIPLAS") return "family:SHIPLAS1";
		if (base === "UT_SHIPSHIELD") return "family:SHIPSHIELD";

		return `family:${base}`;
	}

	function statDisplayKey(row) {
		const name = String(row.display_name || "").trim().toLowerCase();
		if (name) return `name:${name}`;

		return statFamilyKey(row);
	}

	function statValueLabel(row) {
		const base = baseIdFromRid(row.resource_id || row.base_id || row.catalogue_id).toUpperCase();
		const name = String(row.display_name || "").toLowerCase();

		if (base.startsWith("SHIPSLOT_DMG") || base.startsWith("WEAPSLOT_DMG")) return "Damage";
		if (base.includes("SHIELD") || name.includes("shield")) return "Shield";

		if (
			base.includes("HYPERDRIVE") ||
			base.includes("LAUNCHER") ||
			base.includes("SHIPJUMP") ||
			base.includes("WARP") ||
			base.includes("WATER_LANDER") ||
			name.includes("drive") ||
			name.includes("thruster") ||
			name.includes("pulse engine")
		) {
			return "Fuel";
		}

		if (
			base.includes("GRENADE") ||
			base.includes("STUN_GREN") ||
			base.includes("BOLT") ||
			base.includes("SHIPGUN") ||
			base.includes("SHIPSHOT") ||
			base.includes("SHIPROCKET") ||
			base.includes("SHIPMINIGUN") ||
			base.includes("SHIPPLASMA") ||
			name.includes("cannon") ||
			name.includes("launcher") ||
			name.includes("mortar")
		) {
			return "Ammo";
		}

		return "Charge";
	}

	function isInstalledStatPart(row) {
		const base = baseIdFromRid(row.resource_id || row.base_id || row.catalogue_id).toUpperCase();
		const inventory = String(row.inventory || "").toLowerCase();

		if (base.startsWith("U_")) return true;
		if (base.startsWith("UP_")) return true;
		if (base.startsWith("CV_")) return true;
		if (base.startsWith("SHIPSLOT_DMG") || base.startsWith("WEAPSLOT_DMG")) return true;

		const amount = Number(row.amount || 0);
		return inventory === "cargo" && Number.isFinite(amount) && amount === 1;
	}

	function chooseStatPrimary(rows) {
		for (const row of rows) {
			if (!isInstalledStatPart(row)) return row;
		}

		return rows[0] || {};
	}

	function renderRecentSessionOptions(payload) {
		const bar = document.getElementById("recentSessionBar");
		const select = document.getElementById("recentSessionSelect");
		if (!bar || !select) return;

		const view = selectedView();
		bar.hidden = view !== "recent";

		if (view !== "recent") {
			return;
		}

		const sessions = Array.isArray(payload?.sessions) ? payload.sessions : [];
		const selectedId = String(payload?.session?.id || selectedRecentSessionId() || "");

		select.textContent = "";

		if (!sessions.length) {
			const option = document.createElement("option");
			option.value = "";
			option.textContent = "No recorded sessions";
			select.appendChild(option);
			select.disabled = true;
			return;
		}

		select.disabled = false;

		for (const session of sessions) {
			if (!session || !session.id) continue;

			const option = document.createElement("option");
			option.value = String(session.id);
			option.textContent = session.label || session.started_at || String(session.id);
			select.appendChild(option);
		}

		if (selectedId) {
			select.value = selectedId;
		}
	}

	function prepareRecentRows(rows) {
		return rows
			.filter(r => r && Number(r.delta ?? r.amount ?? 0) !== 0)
			.map(r => {
				const delta = Number(r.delta ?? r.amount ?? 0);
				const kind = String(r.kind || "").toLowerCase();
				const chargeLabel = kind === "technology" || kind === "upgrade";
				return {
					...r,
					amount: delta,
					delta,
					change_label: chargeLabel
						? (delta > 0 ? "Session charge gained" : "Session charge spent")
						: (delta > 0 ? "Session gained" : "Session spent"),
				};
			});
	}

	function combineStatRows(rows) {
		const groups = new Map();

		for (const row of rows) {
			const key = statFamilyKey(row);
			const existing = groups.get(key);

			if (!existing) {
				groups.set(key, { stat_rows: [row] });
				continue;
			}

			existing.stat_rows.push(row);
		}

		const combined = [];

		for (const group of groups.values()) {
			const groupRows = group.stat_rows.filter(Boolean);
			const primary = chooseStatPrimary(groupRows);
			const primaryTags = statTagMeta(primary);
			const out = {
				...primary,
				stat_rows: groupRows,
				stat_owner_category: primaryTags.owner_category,
				stat_vehicle_kind: primaryTags.vehicle_kind,
				stat_vehicle_kind_label: primaryTags.vehicle_kind_label,
				stat_scope_tag: primaryTags.scope_tag,
				stat_ammo_amount: null,
				stat_item_amount: null,
				stat_value_label: statValueLabel(primary),
			};

			let valueAmount = null;
			let installedCount = 0;

			for (const row of groupRows) {
				const amount = Number(row.amount || 0);
				if (!Number.isFinite(amount) || amount <= 0) continue;

				if (isInstalledStatPart(row)) {
					installedCount += 1;
					continue;
				}

				if (amount > 1 && (valueAmount == null || amount > valueAmount)) {
					valueAmount = amount;
				}
			}

			const itemCount = installedCount > 0 ? installedCount : (groupRows.length > 0 ? 1 : null);

			out.stat_ammo_amount = valueAmount;
			out.stat_item_amount = itemCount;
			out.amount = itemCount || valueAmount || 0;

			for (const row of groupRows) {
				const rowTags = statTagMeta(row);

				if (!out.stat_vehicle_kind && rowTags.vehicle_kind) {
					out.stat_vehicle_kind = rowTags.vehicle_kind;
					out.stat_vehicle_kind_label = rowTags.vehicle_kind_label;
					out.stat_scope_tag = rowTags.scope_tag;
				}

				if (!out.source_icon_url && row.source_icon_url) out.source_icon_url = row.source_icon_url;
				if (!out.icon_url && row.icon_url) out.icon_url = row.icon_url;
				if (!out.appId && row.appId) out.appId = row.appId;
				if (!out.aliasOf && row.aliasOf) out.aliasOf = row.aliasOf;
			}

			combined.push(out);
		}

		return combined.sort((a, b) =>
			String(a.display_name || a.resource_id || "").localeCompare(String(b.display_name || b.resource_id || ""))
		);
	}

	function loadViewPrefs() {
		try {
			const raw = localStorage.getItem(VIEW_PREFS_STORAGE_KEY);
			const parsed = raw ? JSON.parse(raw) : {};
			return {
				...VIEW_PREF_DEFAULTS,
				...(parsed && typeof parsed === "object" ? parsed : {}),
				hiddenCategories: Array.isArray(parsed?.hiddenCategories) ? parsed.hiddenCategories : [],
				hiddenGroups: Array.isArray(parsed?.hiddenGroups) ? parsed.hiddenGroups : [],
				hiddenTags: Array.isArray(parsed?.hiddenTags) ? parsed.hiddenTags : [],
				hiddenKinds: Array.isArray(parsed?.hiddenKinds) ? parsed.hiddenKinds : [],
			};
		} catch {
			return { ...VIEW_PREF_DEFAULTS };
		}
	}

	function saveViewPrefs() {
		try {
			localStorage.setItem(VIEW_PREFS_STORAGE_KEY, JSON.stringify(viewPrefs));
		} catch { }
	}

	function viewKindKey(row) {
		const kind = String(row.kind || row.inventory || row.owner_type || "").trim();
		return kind || "Unknown";
	}

	function viewCategoryKey(row) {
		const category = String(row.category || "").trim();
		return category || "Unknown";
	}

	function viewGroupKey(row) {
		const group = String(row.group || "").trim();
		return group || "Unknown";
	}

	function viewTagKeys(row) {
		const tags = Array.isArray(row.tags) ? row.tags : [];
		const out = [];

		for (const tag of tags) {
			const normalized = String(tag || "").trim();
			if (normalized !== "") {
				out.push(normalized);
			}
		}

		return out.length ? out : ["unknown"];
	}

	function viewLabel(value) {
		const smallWords = new Set(["a", "an", "and", "as", "at", "but", "by", "for", "in", "nor", "of", "on", "or", "per", "the", "to", "vs", "via"]);
		const words = String(value || "Unknown")
			.replace(/[_-]+/g, " ")
			.replace(/\s+/g, " ")
			.trim()
			.split(" ")
			.filter(Boolean);

		if (words.length === 0) {
			return "Unknown";
		}

		return words.map((word, index) => {
			const lower = word.toLowerCase();

			if (index > 0 && smallWords.has(lower)) {
				return lower;
			}

			return lower.charAt(0).toUpperCase() + lower.slice(1);
		}).join(" ");
	}

	function viewKindLabel(kind) {
		return viewLabel(kind);
	}

	function broadViewType(row) {
		const category = String(row.category || "").trim().toLowerCase();
		const kind = String(row.kind || "").trim().toLowerCase();
		const inventory = String(row.inventory || "").trim().toLowerCase();
		const tags = new Set(viewTagKeys(row).map(tag => String(tag).toLowerCase()));
		const base = baseIdFromRid(row.resource_id || row.base_id || row.catalogue_id).toUpperCase();

		if (
			tags.has("upgrade") ||
			tags.has("module") ||
			kind.includes("upgrade") ||
			kind.includes("module") ||
			base.startsWith("U_") ||
			base.startsWith("UP_")
		) {
			return "upgrade";
		}

		if (
			category === "technology" ||
			kind.includes("technology") ||
			inventory === "tech" ||
			inventory === "technology"
		) {
			return "technology";
		}

		if (
			category === "building" ||
			category === "cosmetic" ||
			tags.has("base_part") ||
			kind === "building" ||
			base.startsWith("B_") ||
			base.startsWith("BASE_") ||
			base.startsWith("BUILD") ||
			base.startsWith("CONTAINER") ||
			base.startsWith("FRE_ROOM_") ||
			base.startsWith("GARAGE_")
		) {
			return "building";
		}

		if (
			category === "resource" ||
			tags.has("resource") ||
			tags.has("substance")
		) {
			return "resource";
		}

		if (!category && !kind && !inventory) {
			return "unknown";
		}

		return "resource";
	}

	function rowPassesBroadPrefs(row) {
		const broad = broadViewType(row);
		if (broad === "resource" && !viewPrefs.showResources) return false;
		if (broad === "technology" && !viewPrefs.showTechnology) return false;
		if (broad === "upgrade" && !viewPrefs.showUpgrades) return false;
		if (broad === "building" && !viewPrefs.showBuilding) return false;
		if (broad === "unknown" && !viewPrefs.showUnknown) return false;

		return true;
	}

	function rowPassesCategoryPrefs(row) {
		const hiddenCategories = new Set(viewPrefs.hiddenCategories || []);
		return !hiddenCategories.has(viewCategoryKey(row));
	}

	function rowPassesGroupPrefs(row) {
		const hiddenGroups = new Set(viewPrefs.hiddenGroups || []);
		return !hiddenGroups.has(viewGroupKey(row));
	}

	function rowPassesTagPrefs(row) {
		const hiddenTags = new Set(viewPrefs.hiddenTags || []);
		for (const tag of viewTagKeys(row)) {
			if (hiddenTags.has(tag)) return false;
		}

		return true;
	}

	function rowPassesKindPrefs(row) {
		const hiddenKinds = new Set(viewPrefs.hiddenKinds || []);
		return !hiddenKinds.has(viewKindKey(row));
	}

	function rowPassesViewPrefsExcept(row, except = "") {
		if (except !== "broad" && !rowPassesBroadPrefs(row)) return false;
		if (except !== "category" && !rowPassesCategoryPrefs(row)) return false;
		if (except !== "group" && !rowPassesGroupPrefs(row)) return false;
		if (except !== "tag" && !rowPassesTagPrefs(row)) return false;
		if (except !== "kind" && !rowPassesKindPrefs(row)) return false;

		return true;
	}

	function rowPassesViewPrefs(row) {
		return rowPassesViewPrefsExcept(row);
	}

	function rowSearchText(row) {
		return [
			row.display_name,
			row.resource_id,
			row.base_id,
			row.catalogue_id,
			row.kind,
			row.category,
			row.group,
			Array.isArray(row.tags) ? row.tags.join(" ") : "",
			row.inventory,
			row.owner_type,
		].map(v => String(v || "").toLowerCase()).join(" ");
	}

	function sortedViewRows(rows) {
		const sorted = [...rows];
		const sort = String(viewPrefs.sort || "alpha");

		if (sort === "type") {
			sorted.sort((a, b) => {
				const typeCmp = viewKindLabel(viewKindKey(a)).localeCompare(viewKindLabel(viewKindKey(b)));
				if (typeCmp !== 0) return typeCmp;
				return String(a.display_name || a.resource_id || "").localeCompare(String(b.display_name || b.resource_id || ""));
			});
			return sorted;
		}

		if (sort === "category") {
			sorted.sort((a, b) => {
				const categoryCmp = viewLabel(viewCategoryKey(a)).localeCompare(viewLabel(viewCategoryKey(b)));
				if (categoryCmp !== 0) return categoryCmp;
				return String(a.display_name || a.resource_id || "").localeCompare(String(b.display_name || b.resource_id || ""));
			});
			return sorted;
		}

		if (sort === "group") {
			sorted.sort((a, b) => {
				const groupCmp = viewLabel(viewGroupKey(a)).localeCompare(viewLabel(viewGroupKey(b)));
				if (groupCmp !== 0) return groupCmp;
				return String(a.display_name || a.resource_id || "").localeCompare(String(b.display_name || b.resource_id || ""));
			});
			return sorted;
		}

		if (sort === "amount_desc") {
			sorted.sort((a, b) => Number(b.amount || 0) - Number(a.amount || 0));
			return sorted;
		}

		if (sort === "amount_asc") {
			sorted.sort((a, b) => Number(a.amount || 0) - Number(b.amount || 0));
			return sorted;
		}

		if (sort === "id") {
			sorted.sort((a, b) => String(a.resource_id || "").localeCompare(String(b.resource_id || "")));
			return sorted;
		}

		sorted.sort((a, b) =>
			String(a.display_name || a.resource_id || "").localeCompare(String(b.display_name || b.resource_id || ""))
		);
		return sorted;
	}

	function visibleRows() {
		const search = document.getElementById("search");
		const q = String(search?.value || "").trim().toLowerCase();
		const filtersEnabled = selectedView() !== "stats";

		return sortedViewRows(State.state.rows.filter(row => {
			if (filtersEnabled && !rowPassesViewPrefs(row)) return false;
			return !q || rowSearchText(row).includes(q);
		}));
	}

	function renderVisibleRows() {
		const grid = document.getElementById("grid");
		const rows = visibleRows();

		if (selectedView() === "recent") {
			UI.renderRecentGrid(grid, rows);
		} else if (selectedView() === "stats") {
			UI.renderStatGrid(grid, rows);
		} else {
			UI.renderGrid(grid, rows);
		}
	}

	function countRowValues(rows, valueFn) {
		const counts = new Map();

		for (const row of rows) {
			const values = valueFn(row);
			for (const value of values) {
				counts.set(value, (counts.get(value) || 0) + 1);
			}
		}

		return counts;
	}

	function populateCheckboxList(list, counts, hiddenValues, dataName, idPrefix, filterText = "") {
		if (!list) return;

		const normalizedFilter = String(filterText || "").trim().toLowerCase();

		list.textContent = "";
		const sortedValues = Array.from(counts.keys()).sort((a, b) => viewLabel(a).localeCompare(viewLabel(b)));

		for (const value of sortedValues) {
			if (normalizedFilter !== "" && !viewLabel(value).toLowerCase().includes(normalizedFilter)) {
				continue;
			}
			const id = `${idPrefix}_${value.replace(/[^a-z0-9]+/gi, "_")}`;
			const checkbox = document.createElement("input");
			checkbox.type = "checkbox";
			checkbox.id = id;
			checkbox.checked = !hiddenValues.has(value);
			checkbox.dataset[dataName] = value;

			const name = document.createElement("span");
			name.textContent = viewLabel(value);

			const count = document.createElement("span");
			count.className = "view-type-count";
			count.textContent = Number(counts.get(value) || 0).toLocaleString();

			const label = document.createElement("label");
			label.htmlFor = id;
			label.appendChild(checkbox);
			label.appendChild(name);
			label.appendChild(count);
			list.appendChild(label);
		}
	}

	function pruneHiddenValues(hiddenValues, counts) {
		const current = new Set(counts.keys());
		return (hiddenValues || []).filter(value => current.has(value));
	}

	function checkboxValuesInList(list, dataKey) {
		if (!list) return [];

		const selector = `input[data-${dataKey}]`;
		const datasetKey = dataKey.replace(/-([a-z])/g, (_, c) => c.toUpperCase());
		const values = [];

		for (const input of list.querySelectorAll(selector)) {
			const value = input.dataset[datasetKey];
			if (typeof value === "string" && value.trim() !== "") {
				values.push(value);
			}
		}

		return values;
	}

	function setHiddenValuesForVisibleList(list, dataKey, prefKey, checked) {
		const values = checkboxValuesInList(list, dataKey);
		const hiddenValues = new Set(viewPrefs[prefKey] || []);

		for (const value of values) {
			if (checked) {
				hiddenValues.delete(value);
			} else {
				hiddenValues.add(value);
			}
		}

		viewPrefs[prefKey] = Array.from(hiddenValues).sort((a, b) => viewLabel(a).localeCompare(viewLabel(b)));
		saveViewPrefs();
		populateViewOptions(State.state.rows);
		renderVisibleRows();
	}

	function setBroadTypeBulk(checked) {
		for (const input of document.querySelectorAll("[data-view-setting]")) {
			const key = input.dataset.viewSetting;
			viewPrefs[key] = checked;
			input.checked = checked;
		}

		saveViewPrefs();
		populateViewOptions(State.state.rows);
		renderVisibleRows();
	}

	function populateViewOptions(rows) {
		const sort = document.getElementById("inventoryViewSort");
		const categoryList = document.getElementById("viewCategoryList");
		const groupList = document.getElementById("viewGroupList");
		const groupSearch = document.getElementById("viewGroupSearch");
		const tagList = document.getElementById("viewTagList");
		const tagSearch = document.getElementById("viewTagSearch");
		const typeList = document.getElementById("viewTypeList");
		const filtersHidden = selectedView() === "stats";

		for (const el of [
			categoryList,
			groupList,
			tagList,
			typeList,
			document.querySelector("[data-view-setting]")?.closest(".view-panel-section"),
		]) {
			const section = el?.closest(".view-panel-disclosure") || el;
			if (section) section.hidden = filtersHidden;
		}

		if (sort) sort.value = viewPrefs.sort || VIEW_PREF_DEFAULTS.sort;

		for (const input of document.querySelectorAll("[data-view-setting]")) {
			const key = input.dataset.viewSetting;
			input.checked = viewPrefs[key] !== false;
		}

		const allCategoryCounts = countRowValues(rows, row => [viewCategoryKey(row)]);
		const allGroupCounts = countRowValues(rows, row => [viewGroupKey(row)]);
		const allTagCounts = countRowValues(rows, row => viewTagKeys(row));
		const allKindCounts = countRowValues(rows, row => [viewKindKey(row)]);

		viewPrefs.hiddenCategories = pruneHiddenValues(viewPrefs.hiddenCategories, allCategoryCounts);
		viewPrefs.hiddenGroups = pruneHiddenValues(viewPrefs.hiddenGroups, allGroupCounts);
		viewPrefs.hiddenTags = pruneHiddenValues(viewPrefs.hiddenTags, allTagCounts);
		viewPrefs.hiddenKinds = pruneHiddenValues(viewPrefs.hiddenKinds, allKindCounts);

		const categoryRows = rows.filter(row =>
			rowPassesBroadPrefs(row)
		);

		const groupRows = rows.filter(row =>
			rowPassesBroadPrefs(row) &&
			rowPassesCategoryPrefs(row)
		);

		const tagRows = rows.filter(row =>
			rowPassesBroadPrefs(row) &&
			rowPassesCategoryPrefs(row) &&
			rowPassesGroupPrefs(row)
		);

		const kindRows = rows.filter(row =>
			rowPassesBroadPrefs(row) &&
			rowPassesCategoryPrefs(row) &&
			rowPassesGroupPrefs(row) &&
			rowPassesTagPrefs(row)
		);

		const categoryCounts = countRowValues(categoryRows, row => [viewCategoryKey(row)]);
		const groupCounts = countRowValues(groupRows, row => [viewGroupKey(row)]);
		const tagCounts = countRowValues(tagRows, row => viewTagKeys(row));
		const kindCounts = countRowValues(kindRows, row => [viewKindKey(row)]);

		populateCheckboxList(categoryList, categoryCounts, new Set(viewPrefs.hiddenCategories || []), "viewCategory", "viewCategory");
		populateCheckboxList(groupList, groupCounts, new Set(viewPrefs.hiddenGroups || []), "viewGroup", "viewGroup", groupSearch?.value || "");
		populateCheckboxList(tagList, tagCounts, new Set(viewPrefs.hiddenTags || []), "viewTag", "viewTag", tagSearch?.value || "");
		populateCheckboxList(typeList, kindCounts, new Set(viewPrefs.hiddenKinds || []), "viewKind", "viewKind");

		saveViewPrefs();
	}

	async function loadInventory(options = {}) {
		const allowAutoSessionAttach = options.allowAutoSessionAttach !== false;
		const p = new URLSearchParams();
		const view = selectedView();

		if (selectedScope() && view !== "recent" && view !== "stats" && selectedScope() !== "base") p.set("scope", selectedScope());
		if (view === "stats" || view === "recent" || selectedScope() === "corvette") p.set("include_tech", "1");
		if (view === "stats" || selectedScope() === "corvette") p.set("limit", "5000");
		if (State.state.settings.showNegatives) p.set("show_negatives", "1");
		if (view === "recent") {
			p.set("sort", "ledger_session");
			p.set("limit", "100");
			if (selectedRecentSessionId()) {
				p.set("session_id", selectedRecentSessionId());
			}
		} else if (State.state.settings.recentFirst) {
			p.set("sort", "recent");
		}

		let payload;
		try {
			payload = await API.fetchJSON(`${API.ENDPOINTS.inventory}?${p.toString()}`);
		} catch (e) {
			console.warn("[inventory] inventory load failed", e);
			payload = [];
		}

		if (
			view === "recent" &&
			allowAutoSessionAttach &&
			shouldAttachToActiveSession(payload)
		) {
			setUrlView("recent");
			return loadInventory({ allowAutoSessionAttach: false });
		}

		const rows = coerceRows(payload).filter(r => r && r.resource_id != null);
		const cat = State.state.catalogue || {};

		const enrichedRows = rows.map(r => {
			const baseId = r.base_id || baseIdFromRid(r.resource_id);
			const meta = cat[baseId] || cat[r.catalogue_id] || null;
			const catalogueName = lookupName(cat, r.resource_id);
			const catalogueKind = meta && typeof meta.kind === "string" ? meta.kind : "";
			const catalogueIcon = meta && typeof meta.icon === "string" ? meta.icon : "";

			return {
				...r,
				base_id: baseId,
				catalogue_id: r.catalogue_id || baseId,
				display_name: r.display_name || catalogueName || baseId || r.resource_id,
				kind: r.kind || catalogueKind || "",
				icon_url: r.icon_url || catalogueIcon || "",
			};
		});

		if (view === "recent") {
			renderRecentSessionOptions(payload);
			State.state.rows = prepareRecentRows(enrichedRows);
			setUrlView("recent");
		} else if (view === "stats") {
			renderRecentSessionOptions(null);
			State.state.rows = combineStatRows(enrichedRows.filter(r =>
				isStatRow(r) && isStatRowForScope(r, selectedScope())
			));
		} else {
			renderRecentSessionOptions(null);
			const scope = selectedScope();
			State.state.rows = combineInventoryRows(enrichedRows.filter(r =>
				isInventoryRowForScope(r, scope) && (scope === "corvette" || !isStatRow(r))
			));
		}

		populateViewOptions(State.state.rows);
		renderVisibleRows();
	}

	function wireUI() {
		const tabs = document.getElementById("tabs");
		const search = document.getElementById("search");
		const recentSessionSelect = document.getElementById("recentSessionSelect");
		const viewToggle = document.getElementById("inventoryViewToggle");
		const viewPanel = document.getElementById("inventoryViewPanel");
		const viewClose = document.getElementById("inventoryViewClose");
		const viewSort = document.getElementById("inventoryViewSort");
		const viewReset = document.getElementById("inventoryViewReset");
		const viewBulkButtons = document.querySelectorAll("[data-view-bulk][data-view-bulk-action]");
		const viewCategoryList = document.getElementById("viewCategoryList");
		const viewGroupSearch = document.getElementById("viewGroupSearch");
		const viewGroupList = document.getElementById("viewGroupList");
		const viewTagSearch = document.getElementById("viewTagSearch");
		const viewTagList = document.getElementById("viewTagList");
		const viewTypeList = document.getElementById("viewTypeList");

		function setViewPanelOpen(open) {
			if (!viewPanel || !viewToggle) return;
			viewPanel.hidden = !open;
			viewPanel.setAttribute("aria-hidden", open ? "false" : "true");
			viewToggle.setAttribute("aria-expanded", open ? "true" : "false");
		}

		on(tabs, "click", (ev) => {
			const b = ev.target.closest("button[data-scope]");
			if (!b) return;

			const scope = String(b.dataset.scope || "character").toLowerCase();
			const rawView = b.dataset.view || "inventory";
			const view = rawView === "stats" || rawView === "recent" ? rawView : "inventory";

			activateSelection(scope, view);
			State.setScope(scope);
			setUrlView(view);
			loadCatalogue(view === "stats" || view === "recent");
			loadInventory();
		});

		on(recentSessionSelect, "change", () => {
			recentSessionUserSelected = true;
			setUrlView("recent");
			loadInventory({ allowAutoSessionAttach: false });
		});

		on(search, "input", renderVisibleRows);

		on(viewToggle, "click", () => {
			setViewPanelOpen(!!viewPanel?.hidden);
		});

		on(viewClose, "click", () => {
			setViewPanelOpen(false);
		});

		on(viewSort, "change", () => {
			viewPrefs.sort = viewSort.value || VIEW_PREF_DEFAULTS.sort;
			saveViewPrefs();
			renderVisibleRows();
		});

		for (const input of document.querySelectorAll("[data-view-setting]")) {
			on(input, "change", () => {
				const key = input.dataset.viewSetting;
				viewPrefs[key] = !!input.checked;
				saveViewPrefs();
				populateViewOptions(State.state.rows);
				renderVisibleRows();
			});
		}

		for (const button of viewBulkButtons) {
			on(button, "click", () => {
				const checked = button.dataset.viewBulkAction === "select";

				if (button.dataset.viewBulk === "broad") {
					setBroadTypeBulk(checked);
					return;
				}

				if (button.dataset.viewBulk === "category") {
					setHiddenValuesForVisibleList(viewCategoryList, "view-category", "hiddenCategories", checked);
					return;
				}

				if (button.dataset.viewBulk === "group") {
					setHiddenValuesForVisibleList(viewGroupList, "view-group", "hiddenGroups", checked);
					return;
				}

				if (button.dataset.viewBulk === "tag") {
					setHiddenValuesForVisibleList(viewTagList, "view-tag", "hiddenTags", checked);
					return;
				}

				if (button.dataset.viewBulk === "kind") {
					setHiddenValuesForVisibleList(viewTypeList, "view-kind", "hiddenKinds", checked);
				}
			});
		}

		function wireHiddenList(list, dataKey, prefKey) {
			on(list, "change", (ev) => {
				const selector = `input[data-${dataKey}]`;
				const input = ev.target.closest(selector);
				if (!input) return;

				const value = input.dataset[dataKey.replace(/-([a-z])/g, (_, c) => c.toUpperCase())];
				const hiddenValues = new Set(viewPrefs[prefKey] || []);
				if (input.checked) {
					hiddenValues.delete(value);
				} else {
					hiddenValues.add(value);
				}

				viewPrefs[prefKey] = Array.from(hiddenValues).sort((a, b) => viewLabel(a).localeCompare(viewLabel(b)));
				saveViewPrefs();
				populateViewOptions(State.state.rows);
				renderVisibleRows();
			});
		}

		wireHiddenList(viewCategoryList, "view-category", "hiddenCategories");
		wireHiddenList(viewGroupList, "view-group", "hiddenGroups");
		wireHiddenList(viewTagList, "view-tag", "hiddenTags");
		wireHiddenList(viewTypeList, "view-kind", "hiddenKinds");

		on(viewGroupSearch, "input", () => {
			populateViewOptions(State.state.rows);
		});

		on(viewTagSearch, "input", () => {
			populateViewOptions(State.state.rows);
		});

		on(viewReset, "click", () => {
			viewPrefs = {
				...VIEW_PREF_DEFAULTS,
				hiddenCategories: [],
				hiddenGroups: [],
				hiddenTags: [],
				hiddenKinds: [],
			};
			saveViewPrefs();
			populateViewOptions(State.state.rows);
			renderVisibleRows();
		});
	}

	async function boot() {
		await State.loadSettings();
		wireUI();

		let initial = "character";
		let initialView = "inventory";
		try {
			const qp = new URLSearchParams(location.search);
			initial = (qp.get("tab") || State.state.settings.defaultWindow || "character").toLowerCase();
			const qpView = qp.get("view") || "inventory";
			initialView = qpView === "stats" || qpView === "recent" ? qpView : "inventory";
			if (initialView === "recent") {
				setRecentSessionId(qp.get("session_id") || "");
				recentSessionUserSelected = !!qp.get("session_id");
			}
		} catch { }

		activateSelection(initial, initialView);
		State.setScope(initial);
		setUrlView(initialView);

		await loadCatalogue(initialView === "stats" || initialView === "recent");
		await loadInventory();
		State.scheduleAutoRefresh(loadInventory);
	}

	NS.bootInventory = boot;
})();
  