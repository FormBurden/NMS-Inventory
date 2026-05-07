#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_FULLPARSE = ROOT / "output/fullparse/save2.full.json"
DEFAULT_CATALOGUE = ROOT / "public/data/items_local.json"
DEFAULT_OUT = ROOT / "output/reports/unresolved_item_ids_report.json"

ID_RE = re.compile(r"^\^?[A-Z][A-Z0-9_]*(?:#[0-9]+)?$")

INVENTORY_PREFIXES = (
    "CV_",
    "PROC_",
    "T_",
    "U_",
    "UP_",
    "UT_",
)

STAT_PREFIXES = (
    "FREI_",
    "SHIP_",
)

BUILDING_PREFIXES = (
    "B_",
    "F_",
    "FRE_ROOM_",
    "S_",
)

BUILDING_EXACT_IDS = {
    "ARCHIVE",
    "BASE_STARJOINT",
    "BIOROOM",
    "BUILDCHAIR2",
    "BUILDDECALVIS2",
    "BUILDDECALVIS5",
    "BUILDLCRATE",
    "BUILDLOCKER",
    "BUILDLIGHTTABLE",
    "BUILD_REFINER2",
    "BUILD_REFINER3",
    "BUILDWINDOW",
    "BUILDWORKTOP",
    "CONTAINER0",
    "CONTAINER1",
    "CONTAINER2",
    "CONTAINER3",
    "CONTAINER4",
    "CONTAINER5",
    "CONT_S",
    "COOKER",
    "CORRIDORV_WATER",
    "CRATEFRAME",
    "CREATURE_FEED",
    "CUBEFRAME",
    "CUBEWINDOW",
    "CUBEWINDOWOVAL",
    "CURVEDCUBEROOF",
    "FLAG1",
    "HEALTHSTATION",
    "HOLO_DISCO_0",
    "LIGHT_TALL",
    "MAINROOMFRAME",
    "MAINROOM_WATER",
    "NOISEBOX",
    "PLANTPOT2",
    "PLANTPOT3",
    "RACE_RAMP",
    "SHIELDSTATION",
    "SPEC_FIREWORK06",
    "TECHPANEL",
    "TELEPORTER_F",
    "VIEWSPHERE",
    "WATERBUBBLE",
}

REWARD_PREFIXES = (
    "RS_",
)

LOC_PREFIXES = (
    "CV_AUTO_HINT",
    "EXPED",
    "FREI_COLOURHINT",
    "FREI_INVHINT",
    "GAMEMODE_",
    "NOT_TECH_",
    "PROC_PRODS",
    "PROC_TECH_COUNT",
    "PROC_TECH_HINT",
    "SHIPFUEL_WIKI",
    "SHIPS_BOUGHT",
    "SHIPSLOTREPAIRS",
    "SHIPSWAP_HINT",
    "SHIP_SUMMON",
    "T_CHART_USED",
    "TECH_PRODS",
    "UI_",
    "W_",
)

NOISE_EXACT_IDS = {
    "",
    "A",
    "B",
    "C",
    "S",
    "NONE",
    "DEFAULT",
    "NORMAL",
    "PRIMARY",
    "PRODUCT",
    "TECHNOLOGY",
}


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def base_id(value: Any) -> str:
    s = str(value or "").strip().upper()
    if not s:
        return ""
    if s.startswith("^"):
        s = s[1:]
    if "#" in s:
        s = s.split("#", 1)[0]
    return s


def alias_candidates(raw: str) -> list[str]:
    base = base_id(raw)
    if not base:
        return []

    candidates = [base]

    if base.startswith("T_"):
        candidates.append(base[2:])

    if base.startswith("U_"):
        candidates.append(base[2:])
        candidates.append("UT_" + base[2:])

    if base.startswith("UP_"):
        suffix = base[3:]
        candidates.append(suffix)
        candidates.append("UT_" + suffix)

    stripped_digit = re.sub(r"[0-9]+$", "", base)
    if stripped_digit and stripped_digit != base:
        candidates.append(stripped_digit)

    if base.startswith("U_"):
        core = base[2:]
        core_no_digit = re.sub(r"[0-9]+$", "", core)
        if core_no_digit:
            candidates.append(core_no_digit)
            candidates.append("UT_" + core_no_digit)

    if base.startswith("UP_"):
        core = base[3:]
        core_no_digit = re.sub(r"[0-9]+$", "", core)
        if core_no_digit:
            candidates.append(core_no_digit)
            candidates.append("UT_" + core_no_digit)

    out: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        item = item.strip().upper()
        if item and item not in seen:
            out.append(item)
            seen.add(item)
    return out


def is_noise_id(base: str) -> bool:
    if base in NOISE_EXACT_IDS:
        return True
    if re.fullmatch(r"SECONDARY[0-9]*", base):
        return True
    if re.fullmatch(r"TERTIARY[0-9]*", base):
        return True
    return False


def parent_has_keys(parent: Any, keys: set[str]) -> bool:
    return isinstance(parent, dict) and keys.issubset(set(parent.keys()))


def is_inventory_slot_hit(path: str, parent: Any) -> bool:
    if not path.endswith(".Id"):
        return False
    return parent_has_keys(parent, {"Id", "Amount"})


def is_maintenance_slot_id(base: str) -> bool:
    return base.startswith("MAINT_")


def is_repair_requirement_slot_id(base: str) -> bool:
    return re.fullmatch(r"R[0-9]+_.+", base) is not None


def is_building_slot_id(base: str) -> bool:
    if base.startswith(BUILDING_PREFIXES) or base in BUILDING_EXACT_IDS:
        return True
    if base.startswith(("BASE_", "BUILD", "FOS_", "FIGHT_COCK")):
        return True
    return False


def is_stat_hit(parent: Any) -> bool:
    return parent_has_keys(parent, {"QL1", "Value"})


def is_placed_buildable_path(path: str) -> bool:
    return ".eZ<[" in path or ".qJ7[" in path


def classify_base_id(base: str) -> str:
    if is_noise_id(base):
        return "noise"
    if base.startswith(REWARD_PREFIXES):
        return "reward_like"
    if base.startswith(LOC_PREFIXES):
        return "loc_like"
    if base.startswith(BUILDING_PREFIXES) or base in BUILDING_EXACT_IDS:
        return "building_like"
    if base.startswith(STAT_PREFIXES):
        return "stat_like"
    if base.startswith(INVENTORY_PREFIXES):
        return "inventory_like"
    return "other"


def classify_hit(base: str, path: str, parent: Any) -> str:
    if is_noise_id(base):
        return "noise"
    if is_stat_hit(parent):
        return "stat_like"
    if is_maintenance_slot_id(base):
        return "maintenance_slot_like"
    if is_repair_requirement_slot_id(base):
        return "repair_requirement_slot_like"
    if is_building_slot_id(base):
        return "building_like"
    if is_inventory_slot_hit(path, parent):
        return "inventory_slot_like"
    if is_placed_buildable_path(path):
        return "building_like"
    return classify_base_id(base)


def compact_parent(value: Any) -> Any:
    if isinstance(value, dict):
        out = {}
        for key, val in value.items():
            if isinstance(val, (str, int, float, bool)) or val is None:
                out[key] = val
            elif isinstance(val, list):
                out[key] = f"[list:{len(val)}]"
            elif isinstance(val, dict):
                out[key] = f"[dict:{len(val)}]"
            else:
                out[key] = str(type(val).__name__)
        return out
    return value


def walk(value: Any, path: str, parent: Any, hits: list[dict[str, Any]]) -> None:
    if isinstance(value, dict):
        for key, val in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            walk(val, child_path, value, hits)
        return

    if isinstance(value, list):
        for index, item in enumerate(value):
            walk(item, f"{path}[{index}]", parent, hits)
        return

    if isinstance(value, str):
        candidate = value.strip().upper()
        if ID_RE.match(candidate):
            base = base_id(value)
            hits.append({
                "raw": value,
                "base": base,
                "class": classify_hit(base, path, parent),
                "path": path,
                "key": "",
                "parent": compact_parent(parent),
            })


def main() -> int:
    fullparse = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_FULLPARSE
    catalogue_path = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_CATALOGUE
    out_path = Path(sys.argv[3]) if len(sys.argv) > 3 else DEFAULT_OUT

    data = load_json(fullparse)
    catalogue = load_json(catalogue_path)

    if not isinstance(catalogue, dict):
        raise SystemExit(f"catalogue is not an object: {catalogue_path}")

    hits: list[dict[str, Any]] = []
    walk(data, "", None, hits)

    all_counts: Counter[str] = Counter()
    unresolved_counts: Counter[str] = Counter()
    unresolved_by_class: dict[str, Counter[str]] = {
        "inventory_slot_like": Counter(),
        "maintenance_slot_like": Counter(),
        "repair_requirement_slot_like": Counter(),
        "inventory_like": Counter(),
        "stat_like": Counter(),
        "building_like": Counter(),
        "reward_like": Counter(),
        "loc_like": Counter(),
        "other": Counter(),
        "noise": Counter(),
    }
    resolved_by_alias: dict[str, dict[str, Any]] = {}
    examples: dict[str, list[dict[str, Any]]] = defaultdict(list)
    examples_by_class: dict[str, dict[str, list[dict[str, Any]]]] = {
        "inventory_slot_like": defaultdict(list),
        "maintenance_slot_like": defaultdict(list),
        "repair_requirement_slot_like": defaultdict(list),
        "inventory_like": defaultdict(list),
        "stat_like": defaultdict(list),
        "building_like": defaultdict(list),
        "reward_like": defaultdict(list),
        "loc_like": defaultdict(list),
        "other": defaultdict(list),
        "noise": defaultdict(list),
    }

    for hit in hits:
        raw = str(hit["raw"]).strip()
        base = base_id(raw)
        if not base:
            continue

        all_counts[base] += 1

        direct = catalogue.get(base)
        alias_match = None
        for candidate in alias_candidates(raw):
            if candidate in catalogue:
                alias_match = candidate
                break

        if direct is None and alias_match is None:
            cls = str(hit.get("class") or classify_base_id(base))
            unresolved_counts[base] += 1
            unresolved_by_class.setdefault(cls, Counter())[base] += 1
            if len(examples[base]) < 5:
                examples[base].append(hit)
            if len(examples_by_class[cls][base]) < 5:
                examples_by_class[cls][base].append(hit)
            continue

        if direct is None and alias_match is not None:
            row = catalogue.get(alias_match)
            if isinstance(row, dict):
                resolved_by_alias[base] = {
                    "matched_id": alias_match,
                    "name": row.get("name"),
                    "kind": row.get("kind"),
                    "icon": row.get("icon"),
                    "appId": row.get("appId"),
                    "candidates": alias_candidates(raw),
                }

    def rows_for(counter: Counter[str], class_name: str | None = None) -> list[dict[str, Any]]:
        out = []
        for key, _ in counter.most_common():
            cls = class_name or classify_base_id(key)
            out.append({
                "base_id": key,
                "class": cls,
                "count": counter[key],
                "examples": examples_by_class.get(cls, {}).get(key, examples.get(key, [])),
                "alias_candidates": alias_candidates(key),
            })
        return out

    report = {
        "input": str(fullparse),
        "catalogue": str(catalogue_path),
        "total_candidate_strings": len(hits),
        "unique_candidate_base_ids": len(all_counts),
        "unresolved_unique_base_ids": len(unresolved_counts),
        "unresolved_unique_by_class": {
            key: len(counter)
            for key, counter in unresolved_by_class.items()
        },
        "resolved_by_alias_unique_base_ids": len(resolved_by_alias),
        "resolved_by_alias": dict(sorted(resolved_by_alias.items())),
        "unresolved_inventory_slot_like_ids": rows_for(unresolved_by_class["inventory_slot_like"], "inventory_slot_like"),
        "unresolved_maintenance_slot_like_ids": rows_for(unresolved_by_class["maintenance_slot_like"], "maintenance_slot_like"),
        "unresolved_repair_requirement_slot_like_ids": rows_for(unresolved_by_class["repair_requirement_slot_like"], "repair_requirement_slot_like"),
        "unresolved_inventory_like_ids": rows_for(unresolved_by_class["inventory_like"], "inventory_like"),
        "unresolved_stat_like_ids": rows_for(unresolved_by_class["stat_like"], "stat_like"),
        "unresolved_building_like_ids": rows_for(unresolved_by_class["building_like"], "building_like"),
        "unresolved_reward_like_ids": rows_for(unresolved_by_class["reward_like"], "reward_like"),
        "unresolved_other_loc_like_ids": rows_for(unresolved_by_class["loc_like"], "loc_like"),
        "unresolved_other_strings": rows_for(unresolved_by_class["other"], "other"),
        "ignored_noise_strings": rows_for(unresolved_by_class["noise"], "noise"),
        "all_unresolved_strings": rows_for(unresolved_counts),
        "unresolved": rows_for(unresolved_counts),
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())