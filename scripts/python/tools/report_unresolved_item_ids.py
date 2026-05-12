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
DEFAULT_DISPLAY_OVERRIDES = ROOT / "data/mappings/id_display_overrides.json"

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
    "BUILDERS_INTRO",
    "BUILDING_HINT",
    "CV_AUTO_HINT",
    "T_DEFAULT",
    "T_WORDSTONE_TUT",
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

LOC_EXACT_IDS = {
    "F_TELE_BP",
}

CUSTOMIZATION_EXACT_IDS = {
    "FIGHT_COCKE",
    "FIGHT_COCKF",
    "FOS_BI_TAIL_AN",
    "FOS_HEAD_KG",
    "FOS_LIMBS_F",
}

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

UNRESOLVED_CLASS_NAMES = (
    "inventory_slot_like",
    "maintenance_slot_like",
    "repair_requirement_slot_like",
    "inventory_like",
    "procedural_placeholder_like",
    "stat_like",
    "customization_like",
    "discovery_name_like",
    "progress_stat_like",
    "mission_key_like",
    "mission_reference_like",
    "dialog_key_like",
    "word_group_like",
    "recipe_key_like",
    "event_key_like",
    "milestone_objective_like",
    "mission_id_like",
    "procedural_generation_key_like",
    "preset_like",
    "creature_config_like",
    "metadata_like",
    "generated_unique_id_like",
    "generated_name_like",
    "waypoint_type_like",
    "settlement_state_like",
    "terminal_state_like",
    "loadout_config_like",
    "player_state_config_like",
    "account_config_like",
    "graphics_config_like",
    "persistent_base_type_like",
    "building_class_like",
    "frigate_config_like",
    "seasonal_config_like",
    "difficulty_config_like",
    "save_enum_like",
    "building_like",
    "generated_structural_building_like",
    "reward_like",
    "loc_like",
    "other",
    "noise",
)

CATALOGUE_ACTIONABLE_CLASS_NAMES = (
    "inventory_slot_like",
    "inventory_like",
    "building_like",
)

DIAGNOSTIC_NON_CATALOGUE_CLASS_NAMES = (
    "maintenance_slot_like",
    "repair_requirement_slot_like",
    "procedural_placeholder_like",
    "stat_like",
    "customization_like",
    "discovery_name_like",
    "progress_stat_like",
    "mission_key_like",
    "mission_reference_like",
    "dialog_key_like",
    "word_group_like",
    "recipe_key_like",
    "event_key_like",
    "milestone_objective_like",
    "mission_id_like",
    "procedural_generation_key_like",
    "preset_like",
    "creature_config_like",
    "metadata_like",
    "generated_unique_id_like",
    "generated_name_like",
    "waypoint_type_like",
    "settlement_state_like",
    "terminal_state_like",
    "loadout_config_like",
    "player_state_config_like",
    "account_config_like",
    "graphics_config_like",
    "persistent_base_type_like",
    "building_class_like",
    "frigate_config_like",
    "seasonal_config_like",
    "difficulty_config_like",
    "save_enum_like",
    "generated_structural_building_like",
    "reward_like",
    "loc_like",
    "noise",
)


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_optional_json_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}

    data = load_json(path)
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object: {path}")

    return data


def load_display_overrides(path: Path) -> dict[str, dict[str, Any]]:
    raw = load_optional_json_object(path)
    out: dict[str, dict[str, Any]] = {}

    for key, value in raw.items():
        base = base_id(key)
        if not base:
            continue

        if isinstance(value, str):
            name = value.strip()
            if name:
                out[base] = {"displayName": name}
            continue

        if not isinstance(value, dict):
            continue

        name = str(value.get("displayName") or value.get("name") or "").strip()
        if not name:
            continue

        row = dict(value)
        row["displayName"] = name
        out[base] = row

    return out


def base_id(value: Any) -> str:
    s = str(value or "").strip().upper()
    if not s:
        return ""
    if s.startswith("^"):
        s = s[1:]
    if "#" in s:
        s = s.split("#", 1)[0]
    return s


def append_alias_patterns(candidates: list[str], base: str) -> None:
    if not base:
        return

    candidates.append(base)

    if base.startswith("T_"):
        candidates.append(base[2:])

    if base.startswith("U_"):
        candidates.append(base[2:])
        candidates.append("UT_" + base[2:])

    if base.startswith("UP_"):
        suffix = base[3:]
        candidates.append(suffix)
        candidates.append("UT_" + suffix)

    if base.startswith("UT_"):
        candidates.append(base[3:])

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

    if base.startswith("UT_"):
        core = base[3:]
        core_no_digit = re.sub(r"[0-9]+$", "", core)
        if core_no_digit:
            candidates.append(core_no_digit)
            candidates.append("UT_" + core_no_digit)


def alias_candidates(raw: str) -> list[str]:
    base = base_id(raw)
    if not base:
        return []

    candidates: list[str] = []
    append_alias_patterns(candidates, base)

    repair_match = re.fullmatch(r"R[0-9]+_(.+)", base)
    if repair_match:
        append_alias_patterns(candidates, repair_match.group(1))

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

def is_base_object_hit(path: str, parent: Any) -> bool:
    if not path.endswith(".ObjectID"):
        return False
    if ".@ZJ[" not in path:
        return False
    return isinstance(parent, dict)

def is_maintenance_slot_id(base: str) -> bool:
    return base.startswith("MAINT_")


def is_repair_requirement_slot_id(base: str) -> bool:
    return re.fullmatch(r"R[0-9]+_.+", base) is not None


def is_generated_structural_building_id(base: str) -> bool:
    if base.startswith((
        "B_STR_",
        "B_WNG_",
        "B_WALL_",
        "B_CON_",
        "B_HAB_",
        "B_HAB1_",
        "B_LND_",
        "B_SHL_",
        "B_TUR_",
        "B_GEN_",
        "FRE_ROOM_",
        "GARAGE_",
    )):
        return True

    if base.startswith(("BASE_", "BLD_", "FOS_")):
        return True

    if base.startswith(("S_", "T_", "F_", "U_")):
        return True

    if base.startswith("B_"):
        return True

    return False


def is_mission_or_progress_key(base: str) -> bool:
    if base in LOC_EXACT_IDS:
        return True

    if re.fullmatch(r"BASE_UPGRADE[0-9]+", base):
        return True

    if base == "BASE_SAFETY":
        return True

    if base.startswith("S_CLASS_") or base == "S_MILESTONES":
        return True

    if base == "FOS_MADE":
        return True

    if re.fullmatch(r"FOS_[A-Z0-9_]+_MADE", base):
        return True

    return False


def is_building_slot_id(base: str) -> bool:
    if base in LOC_EXACT_IDS or base in CUSTOMIZATION_EXACT_IDS or base.startswith(LOC_PREFIXES):
        return False
    if base.startswith(BUILDING_PREFIXES) or base in BUILDING_EXACT_IDS:
        return True
    if base.startswith(("BASE_", "BUILD", "FOS_", "FIGHT_COCK")):
        return True
    return False


def is_stat_hit(parent: Any) -> bool:
    return parent_has_keys(parent, {"QL1", "Value"})


def is_discovery_name_hit(path: str) -> bool:
    return path.endswith(".USN")


def is_progress_stat_key_hit(path: str) -> bool:
    return ".gUR[" in path and (path.endswith(".Id") or path.endswith(".:rc"))


def is_mission_history_key_hit(path: str) -> bool:
    return ".dwb[" in path and path.endswith(".Mission")


def is_mission_reference_hit(base: str, path: str) -> bool:
    if base in {"MISSIONGIVER", "MISSIONGIVERREFERENCE"}:
        return ".dwb[" in path and ".eZ7[" in path

    return False


def is_dialog_key_hit(path: str) -> bool:
    return path.endswith(".Dialog")


def is_word_group_hit(base: str, path: str) -> bool:
    if not path.endswith(".Group"):
        return False

    return base.startswith(("TRA_", "EXP_", "WAR_", "ATLAS_"))


def is_name_loc_key_hit(base: str, path: str) -> bool:
    return path.endswith(".Name") and base.endswith("_NAME")


def is_recipe_key_hit(base: str, path: str) -> bool:
    if base.startswith(("RECIPE_", "REFINERECIPE_")):
        return True

    return ".Ddk[" in path


def is_event_key_hit(path: str) -> bool:
    return path.endswith(".Event") or path.endswith(".AkEvent")


def is_milestone_objective_hit(path: str) -> bool:
    return ".m4I[" in path and (path.endswith(".Vn8") or path.endswith(".Id"))


def is_mission_id_hit(path: str) -> bool:
    return path.endswith(".jGk")


def is_procedural_generation_key_hit(path: str) -> bool:
    return ".GQA[" in path and (".OEf[" in path or path.endswith(".rr0"))


def is_preset_id_hit(path: str) -> bool:
    return path.endswith(".SelectedPreset")


def is_creature_config_hit(path: str) -> bool:
    return ".Mcl[" in path or ".uKZ[" in path


def is_metadata_hit(path: str) -> bool:
    return path.startswith("_meta.") or path == "ActiveContext"


def is_generated_unique_id_hit(path: str) -> bool:
    return path.endswith(".UniqueId")


def is_generated_name_hit(path: str) -> bool:
    return path.endswith(".Name")


def is_generated_label_hit(path: str) -> bool:
    return path.endswith(".CN")


def is_generated_hash_hit(path: str) -> bool:
    return path.endswith(".J=S")


def is_waypoint_type_hit(path: str) -> bool:
    return path.endswith(".GalaxyWaypointType")


def is_settlement_state_hit(path: str) -> bool:
    return path.endswith(".SSo")


def is_terminal_state_hit(path: str) -> bool:
    return path.startswith("<h0.xgu[")


def is_loadout_config_hit(path: str) -> bool:
    return ".wnR.SMP[" in path or ".dgg[" in path


def is_player_state_config_hit(path: str) -> bool:
    return path.endswith(".Mg<") or path.endswith(".;R7")


def is_account_config_hit(path: str) -> bool:
    return path.endswith(".khi")


def is_graphics_config_hit(path: str) -> bool:
    return path.endswith(".DepthOfFieldSetting")


def is_persistent_base_type_hit(path: str) -> bool:
    return path.endswith(".PersistentBaseTypes")


def is_building_class_hit(path: str) -> bool:
    return path.endswith(".BuildingClass") or path.endswith(".BuildingClass.BuildingClass")


def is_frigate_config_hit(path: str) -> bool:
    return ".;Du[" in path and (
        path.endswith(".FrigateClass.FrigateClass") or ".Mjm[" in path
    )


def is_seasonal_config_hit(path: str) -> bool:
    return path.startswith("<h0.Rol.")


def is_difficulty_config_hit(path: str) -> bool:
    return ".LyC.:fe." in path or "Difficulty" in path


def is_save_enum_hit(path: str) -> bool:
    enum_suffixes = (
        ".InventoryStackSizeGroup",
        ".<Dn",
        ".D6b",
        ".RVl.RVl",
        ".Ty=",
        ".Biome.Biome",
        ".QA1",
        ".TeleporterType",
        ".ShipClass",
        ".DifficultyPresetType",
        ".0AL.0AL",
        ".KO>.KO>",
        ".elv",
        ".tj1",
        ".NUi.Ec6",
        ".93I",
        ".SS2.0Hi",
        ".cI>",
        ".SeasonSaveStateOnDeath",
        ".5LX",
        ".LastKnownPlayerState",
        ".SettlementJudgementType",
        ".WeaponMode",
        ".DepthOfFieldSetting",
        ".khi",
    )

    return path.endswith(enum_suffixes)


def is_placed_buildable_path(path: str) -> bool:
    return ".eZ<[" in path or ".qJ7[" in path


def classify_base_id(base: str) -> str:
    if is_noise_id(base):
        return "noise"
    if base.startswith(REWARD_PREFIXES):
        return "reward_like"
    if base in CUSTOMIZATION_EXACT_IDS:
        return "customization_like"
    if base.startswith(LOC_PREFIXES) or is_mission_or_progress_key(base):
        return "loc_like"
    if base.startswith(BUILDING_PREFIXES) or base in BUILDING_EXACT_IDS:
        return "building_like"
    if base.startswith(STAT_PREFIXES):
        return "stat_like"
    if base.startswith(INVENTORY_PREFIXES):
        return "inventory_like"
    return "other"


def building_family_id(base: str) -> str:
    if base.startswith("FRE_ROOM_"):
        return "FRE_ROOM_*"
    if base.startswith("B_HAB1_"):
        return "B_HAB1_*"
    if base.startswith("B_HAB_"):
        return "B_HAB_*"
    if base.startswith("B_LND_"):
        return "B_LND_*"
    if base.startswith("B_SHL_"):
        return "B_SHL_*"
    if base.startswith("B_TUR_"):
        return "B_TUR_*"
    if base.startswith("B_WNG_"):
        return "B_WNG_*"
    if base.startswith("B_WALL_"):
        return "B_WALL_*"
    if base.startswith("B_STR_"):
        return "B_STR_*"
    if base.startswith("B_GEN_"):
        return "B_GEN_*"
    if base.startswith("B_CON_"):
        return "B_CON_*"
    if base.startswith("BASE_"):
        return "BASE_*"
    if base.startswith("BUILD"):
        return "BUILD*"
    if "_" in base:
        return base.split("_", 1)[0] + "_*"

    match = re.match(r"^([A-Z]+)", base)
    if match:
        return match.group(1) + "*"

    return "other"

DIRECTION_LABELS = {
    "N": "North",
    "S": "South",
    "E": "East",
    "W": "West",
    "NE": "Northeast",
    "NW": "Northwest",
    "SE": "Southeast",
    "SW": "Southwest",
}


def split_alpha_numeric_token(token: str) -> tuple[str, str]:
    trailing_digit_match = re.fullmatch(r"([A-Z]+)([0-9]*)", token)
    if trailing_digit_match:
        return trailing_digit_match.group(1), trailing_digit_match.group(2)

    leading_digit_match = re.fullmatch(r"([0-9]+)([A-Z]+)", token)
    if leading_digit_match:
        return leading_digit_match.group(2), leading_digit_match.group(1)

    return token, ""


ACRONYM_LABELS = {
    "AI": "AI",
    "API": "API",
    "BP": "BP",
    "CV": "CV",
    "DM": "DM",
    "DNA": "DNA",
    "EVA": "EVA",
    "HUD": "HUD",
    "ID": "ID",
    "MB": "MB",
    "MP": "MP",
    "NMS": "NMS",
    "NPC": "NPC",
    "OSD": "OSD",
    "PCG": "PCG",
    "QS": "QS",
    "SE": "SE",
    "TGA": "TGA",
    "UI": "UI",
}

TOKEN_LABELS = {
    "AFF": "Affinity",
    "AGILE": "Agility",
    "ALIEN": "Alien",
    "ALIENS": "Aliens",
    "ALL": "All",
    "AN": "Animal",
    "ANIMAL": "Animal",
    "ARM": "Arm",
    "ATLAS": "Atlas",
    "ATLASSTATION": "Atlas Station",
    "AVERAGE": "Average",
    "BASE": "Base",
    "BI": "Biped",
    "BIPED": "Biped",
    "BLACKHOLE": "Black Hole",
    "BLESS": "Blessing",
    "BODY": "Body",
    "BOTT": "Bottle",
    "BOTTLE": "Bottle",
    "CAMP": "Camp",
    "CAT": "Cat",
    "CHANGE": "Change",
    "CHOICE": "Choice",
    "CLASS": "Class",
    "CLUE": "Clue",
    "COCKE": "Cockpit E",
    "COCKF": "Cockpit F",
    "COCKPIT": "Cockpit",
    "COLLECT": "Collect",
    "COMM": "Community",
    "COMPLETE": "Complete",
    "CONTROL": "Control",
    "COORDINATION": "Coordination",
    "COUNT": "Count",
    "CREATURE": "Creature",
    "CREATURES": "Creatures",
    "CRIT": "Critical",
    "DAMAGE": "Damage",
    "DATA": "Data",
    "DEATHS": "Deaths",
    "DECAL": "Decal",
    "DECORATIVE": "Decorative",
    "DEFAULT": "Default",
    "DELIVER": "Deliver",
    "DETAIL": "Detail",
    "DIG": "Dig",
    "DISC": "Discovery",
    "DISCO": "Disco",
    "DIST": "Distance",
    "DISTRESS": "Distress",
    "DISTRESSSIGNAL": "Distress Signal",
    "DONE": "Done",
    "DRONE": "Drone",
    "DRONEHIVE": "Drone Hive",
    "ECOSYSTEM": "Ecosystem",
    "EGG": "Egg",
    "EMOTES": "Emotes",
    "ENRAGE": "Enrage",
    "EVENT": "Event",
    "EXPED": "Expedition",
    "EXPEDITION": "Expedition",
    "EXPENSIVE": "Expensive",
    "EXPLORATION": "Exploration",
    "EXPLORE": "Explore",
    "FACT": "Factory",
    "FARM": "Farm",
    "FARMER": "Farmer",
    "FAST": "Fast",
    "FIGHT": "Fighter",
    "FIGHTER": "Fighter",
    "FISH": "Fish",
    "FISHROD": "Fishing Rod",
    "FLEET": "Fleet",
    "FLORA": "Flora",
    "FLOAT": "Float",
    "FOSSIL": "Fossil",
    "FOURTH": "Fourth",
    "FREIGHTER": "Freighter",
    "FREIGHTERBASE": "Freighter Base",
    "FULL": "Full",
    "FULLECOSYSTEM": "Full Ecosystem",
    "GAME": "Game",
    "GAMEPLAY": "Gameplay",
    "GAMEMODE": "Game Mode",
    "GAMESTARTSPAWN": "Game Start Spawn",
    "GENERIC": "Generic",
    "GLYPH": "Glyph",
    "HEAD": "Head",
    "HIGH": "High",
    "HINT": "Hint",
    "HIVE": "Hive",
    "HOMEPLANETBASE": "Home Planet Base",
    "HOLO_DISCO_0": "Holographic Disco 0",
    "HUB": "Hub",
    "HYPERDRIVE": "Hyperdrive",
    "INDUSTRIAL": "Industrial",
    "INTERACT": "Interact",
    "INTRCT": "Interact",
    "INVALID": "Invalid",
    "INVULN": "Invulnerable",
    "ITEM": "Item",
    "JUDG": "Judgement",
    "KEY": "Key",
    "KILL": "Kill",
    "KILLED": "Killed",
    "LAUNCH": "Launch",
    "LEGS": "Legs",
    "LIMBS": "Limbs",
    "LOG": "Log",
    "LOOT": "Loot",
    "LOW": "Low",
    "LUSH": "Lush",
    "MAIN": "Main",
    "MARKER": "Marker",
    "MISSIONMARKER": "Mission Marker",
    "MISSIONSURVEY": "Mission Survey",
    "MAINT": "Maintenance",
    "MAINTENANCE": "Maintenance",
    "MAINTENANCEOBJECT": "Maintenance Object",
    "MB": "MB",
    "MECH": "Minotaur",
    "MET": "Met",
    "MGR": "Manager",
    "MILESTONE": "Milestone",
    "MILESTONES": "Milestones",
    "MIN": "Minimum",
    "MINERAL": "Mineral",
    "MINING": "Mining",
    "MISSION": "Mission",
    "MISSIONGIVER": "Mission Giver",
    "MISSIONGIVERREFERENCE": "Mission Giver Reference",
    "MODE": "Mode",
    "MUS": "Music",
    "NEG": "Negative",
    "NEXUS": "Nexus",
    "NEXUSDATA": "Nexus Data",
    "NEXUSMILES": "Nexus Milestones",
    "NIKRAIDER": "Nikraider",
    "NORM": "Normal",
    "NOROOM": "No Room",
    "NULL": "Null",
    "OBJECT": "Object",
    "OFF": "Off",
    "PAINT": "Paint",
    "PARTY": "Party",
    "PASSIVE": "Passive",
    "PET": "Pet",
    "PHASE": "Phase",
    "PIRATE": "Pirate",
    "PLANET": "Planet",
    "PLAQUE": "Plaque",
    "PLAYERS": "Players",
    "PLAYERSHIPBASE": "Player Ship Base",
    "PLNT": "Plant",
    "PORTAL": "Portal",
    "POS": "Positive",
    "PREDATOR": "Predator",
    "PRI": "Primary",
    "PROC": "Procedural",
    "PROCEDURAL": "Procedural",
    "PRODUCT": "Product",
    "RANGE": "Range",
    "RECIPE": "Recipe",
    "RECKSTERS": "Recksters",
    "RECURSIVE": "Recursive",
    "REDEEMED": "Redeemed",
    "REFINE": "Refiner",
    "REFINER": "Refiner",
    "REFINERECIPE": "Refiner Recipe",
    "REPAIR": "Repair",
    "RET": "Return",
    "RETURN": "Return",
    "REWARDS": "Rewards",
    "ROBOT": "Robot",
    "ROBOTS": "Robots",
    "SALV": "Salvage",
    "SALVAGE": "Salvage",
    "SCAN": "Scan",
    "SCANNER": "Scanner",
    "SCAVENGER": "Scavenger",
    "SCRAP": "Scrap",
    "SECONDARY": "Secondary",
    "SEASON": "Season",
    "SEN": "Sentinel",
    "SENT": "Sentinel",
    "SENTINEL": "Sentinel",
    "SENTINELDISTRESSSIGNAL": "Sentinel Distress Signal",
    "SETTLE": "Settlement",
    "SETTLEMENT": "Settlement",
    "SHIELD": "Shield",
    "SHIP1": "Ship 1",
    "SIGNAL": "Signal",
    "SIMULATION": "Simulation",
    "SKIFF": "Skiff",
    "SLOT": "Slot",
    "SMALLINDUSTRIAL": "Small Industrial",
    "SNOWFIOUS": "Snowfious",
    "SPAWN": "Spawn",
    "SPEED": "Speed",
    "STATEMENT": "Statement",
    "STARTING": "Starting",
    "STARJOINT": "Star Joint",
    "STORAGE": "Storage",
    "SUB": "Subtitle",
    "SUBSTANCE": "Substance",
    "SURVIVAL": "Survival",
    "SURVEY": "Survey",
    "SWAM": "Swam",
    "TAIL": "Tail",
    "TECH": "Technology",
    "TECHNOLOGY": "Technology",
    "TELE": "Teleporter",
    "TELEPORTER": "Teleporter",
    "TER": "Tertiary",
    "TERMINAL": "Terminal",
    "TIME": "Time",
    "TITLE": "Title",
    "TOBYGENTLEMANE": "Tobygentlemane",
    "TRAIL": "Trail",
    "TREE": "Tree",
    "TRUSS": "Truss",
    "TRUCK": "Truck",
    "TURRET": "Turret",
    "TUT": "Tutorial",
    "UPGRADE": "Upgrade",
    "UPGRADES": "Upgrades",
    "USER": "User",
    "VEHICLE": "Vehicle",
    "VOLDSOY": "Voldsoy",
    "WALKED": "Walked",
    "WALKERS": "Walkers",
    "WAYPOINTS": "Waypoints",
    "WEAPON": "Weapon",
    "WEAPONS": "Weapons",
    "WEAPGUY": "Weapon Specialist",
    "WILD": "Wild",
    "WIN": "Win",
    "WORDSTONE": "Wordstone",
    "YELLOW": "Yellow",
}

BUILTIN_DISPLAY_NAME_OVERRIDES = {
    "AFF_WILD": "Wild Affinity",
    "ALIENS_MET": "Aliens Met",
    "ATTACK_NORM": "Attack Normal",
    "BLESS_POS": "Blessing Positive",
    "CHANGE_AFFINITY": "Change Affinity",
    "COLLECT1": "Collect 1",
    "COMM_EXPED_105": "Community Expedition 105",
    "CV_AUTO_HINT": "Corvette Auto Hint Mission Key",
    "D_NEXUS_SENT": "Nexus Sentinel Dialogue",
    "D_NEXUSDATA_2": "Nexus Data Dialogue 2",
    "D_NEXUSDATA_DONE_1": "Nexus Data Done Dialogue 1",
    "D_NEXUSDATA_DONE_2": "Nexus Data Done Dialogue 2",
    "D_NEXUSDATA_DONE_3": "Nexus Data Done Dialogue 3",
    "D_NEXUSMILES_RET_5": "Nexus Milestones Return Dialogue 5",
    "DEFAULT_FISHROD": "Default Fishing Rod",
    "DEFAULT_MECH": "Default Minotaur",
    "DEFAULT_PET": "Default Companion",
    "DEFAULT_SKIFF": "Default Skiff",
    "DEFAULT_TRUCK": "Default Roamer",
    "DEFAULT_VEHICLE": "Default Exocraft",
    "DEATHS": "Deaths",
    "DISTRESSSIGNAL": "Distress Signal",
    "DIST_SWAM": "Distance Swam",
    "DIST_WALKED": "Distance Walked",
    "DM_FARMER": "Farmer Mission",
    "DM_NEXUSDATA": "Nexus Data Mission",
    "DM_NEXUSMILES": "Nexus Milestones Mission",
    "DM_QS_REWARDS": "Quicksilver Rewards Mission",
    "DM_WEAPONS": "Weapons Mission",
    "DRONEHIVE": "Drone Hive",
    "DRONE_HIVE_DISABLED": "Drone Hive Disabled",
    "ENRAGE_CRIT": "Critical Enrage",
    "EXPLORE_LOG": "Explore Log",
    "EXPLORE_PRI": "Explore Primary",
    "FACTORY": "Factory",
    "FACT_SE_WEAPGUY2": "Factory SE Weapon Specialist 2",
    "FLEET_DAMAGE_CHOICE": "Fleet Damage Choice",
    "FOS_MADE": "Fossil Discovery Progress Key",
    "FLOAT_NEXUS": "Float Nexus",
    "FOURTH_2": "Fourth 2",
    "GAMEPLAY_ATLASSTATION": "Gameplay Atlas Station",
    "GAMEPLAY_BLACKHOLE": "Gameplay Black Hole",
    "GAMEPLAY_MISSION": "Gameplay Mission",
    "GAMESTARTSPAWN": "Game Start Spawn",
    "GO_FISH": "Go Fish",
    "HOMEPLANETBASE": "Home Planet Base",
    "HOLO_DISCO_0": "Holographic Disco 0",
    "INTRCT_NOROOM_L": "Interact No Room L",
    "INVULN_TER_2": "Invulnerable Tertiary 2",
    "INVALID_EVENT": "Invalid Event",
    "KILL_CREATURES": "Kill Creatures",
    "KILL_PREDATORS": "Kill Predators",
    "KILL_ROBOTS": "Kill Robots",
    "LEJOPETIDE": "Lejopetide",
    "MAINTENANCEOBJECT": "Maintenance Object",
    "MECH_ARM_L_SEN": "Minotaur Left Arm Sentinel",
    "MECH_ARM_R_SEN": "Minotaur Right Arm Sentinel",
    "MECH_BODY_SEN": "Minotaur Body Sentinel",
    "MECH_LEGS_SEN": "Minotaur Legs Sentinel",
    "MECH_SCAN_SEN": "Minotaur Scanner Sentinel",
    "MISSIONGIVER": "Mission Giver",
    "MISSIONGIVERREFERENCE": "Mission Giver Reference",
    "MP_FULL_15PL": "Multiplayer Full 15 Players",
    "MP_FULL_16PL": "Multiplayer Full 16 Players",
    "MP_FULL_5PL": "Multiplayer Full 5 Players",
    "MP_FULL_PLAYERS": "Multiplayer Full Players",
    "MUS_RECURSIVE_SIMULATION": "Recursive Simulation Music",
    "NIKRAIDER": "Nikraider",
    "NONE": "None",
    "NORMAL": "Normal",
    "PASSIVE": "Passive",
    "PCG": "PCG",
    "PLAQUE": "Plaque",
    "PLAYERSHIPBASE": "Player Ship Base",
    "PRIMARY": "Primary",
    "PROC_JOB": "Procedural Job",
    "RECKSTERS": "Recksters",
    "REDEEMED": "Redeemed",
    "ROBOT_CAMP_TERMINAL": "Robot Camp Terminal",
    "SCAN_MIN": "Scan Minimum",
    "SE_DELIVER_MB": "SE Deliver MB",
    "SE_DIG_CLUE": "SE Dig Clue",
    "SE_PARTY_PLANET1": "SE Party Planet 1",
    "SE_PARTY_PLANET2": "SE Party Planet 2",
    "SE_PARTY_PLANET3": "SE Party Planet 3",
    "SE_PARTY_PLANET4": "SE Party Planet 4",
    "SE_PARTY_PLANET5": "SE Party Planet 5",
    "SE_SETTLE_MGR_RETURN": "SE Settlement Manager Return",
    "SE_TREE_SCAN_CONTROL": "SE Tree Scan Control",
    "SENTINELDISTRESSSIGNAL": "Sentinel Distress Signal",
    "SETTLEMENT_HUB": "Settlement Hub",
    "SETTLEMENT_SMALLINDUSTRIAL": "Settlement Small Industrial",
    "SETTLE_MGR": "Settlement Manager",
    "SETTLE_TUT_JUDG": "Settlement Tutorial Judgement",
    "SIGYN": "Sigyn",
    "SNOWFIOUS": "Snowfious",
    "SPEED_TER_4": "Speed Tertiary 4",
    "ST": "Settlement",
    "TECHNOLOGY": "Technology",
    "TGA_SHIP1": "TGA Ship 1",
    "TOBYGENTLEMANE": "Tobygentlemane",
    "TRA_SCAVENGER_GENERIC": "Trader Scavenger Generic",
    "UPGRADE_COUNT": "Upgrade Count",
    "UPGRADE_TIME": "Upgrade Time",
    "USER": "User",
    "VOLDSOY": "Voldsoy",
    "WEAPON_UPGRADE": "Weapon Upgrade",
}


def builtin_display_name(base: str) -> str:
    exact = BUILTIN_DISPLAY_NAME_OVERRIDES.get(base)
    if exact:
        return exact

    match = re.fullmatch(r"BASE_UPGRADE([0-9]+)", base)
    if match:
        return f"Base Upgrade Mission Key {match.group(1)}"

    match = re.fullmatch(r"FOS_([A-Z0-9_]+)_MADE", base)
    if match:
        return f"Fossil {humanize_plain_id_fragment(match.group(1))} Discovery Progress Key"

    match = re.fullmatch(r"STARTING_NEG([0-9]+)", base)
    if match:
        return f"Starting Negative {match.group(1)}"

    match = re.fullmatch(r"STARTING_POS([0-9]+)", base)
    if match:
        return f"Starting Positive {match.group(1)}"

    match = re.fullmatch(r"SECONDARY([0-9]*)", base)
    if match:
        suffix = match.group(1)
        return f"Secondary {suffix}".strip()

    match = re.fullmatch(r"TERTIARY([0-9]*)", base)
    if match:
        suffix = match.group(1)
        return f"Tertiary {suffix}".strip()

    match = re.fullmatch(r"RECIPE_([0-9]+)", base)
    if match:
        return f"Recipe {match.group(1)}"

    match = re.fullmatch(r"REFINERECIPE_([0-9]+)", base)
    if match:
        return f"Refiner Recipe {match.group(1)}"

    match = re.fullmatch(r"RS_S19_S([0-9]+)M([0-9]+)", base)
    if match:
        return f"Expedition 19 Stage {match.group(1)} Milestone {match.group(2)} Reward"

    match = re.fullmatch(r"RS_S19_PHASE([0-9]+)", base)
    if match:
        return f"Expedition 19 Phase {match.group(1)} Reward"

    match = re.fullmatch(r"RS_S19_PARTY([0-9]+)", base)
    if match:
        return f"Expedition 19 Community Milestone {match.group(1)} Reward"

    return ""


def humanize_plain_id_fragment(value: str) -> str:
    words = []
    for token in value.split("_"):
        if not token:
            continue

        alpha, numeric = split_alpha_numeric_token(token)
        text = TOKEN_LABELS.get(alpha, ACRONYM_LABELS.get(alpha, alpha.title()))

        if numeric and alpha == "PL":
            text = f"{numeric} Players"
        elif numeric:
            text = f"{text} {numeric}"

        words.append(text)

    return " ".join(words)


def humanize_directional_id_fragment(value: str) -> str:
    words = []
    for token in value.split("_"):
        if not token:
            continue

        alpha, numeric = split_alpha_numeric_token(token)
        if alpha in DIRECTION_LABELS:
            text = DIRECTION_LABELS[alpha]
        else:
            text = TOKEN_LABELS.get(alpha, ACRONYM_LABELS.get(alpha, alpha.title()))

        if numeric and alpha == "PL":
            text = f"{numeric} Players"
        elif numeric:
            text = f"{text} {numeric}"

        words.append(text)

    return " ".join(words)


def humanize_id_fragment(value: str) -> str:
    return humanize_directional_id_fragment(value)


WORD_GROUP_PREFIX_LABELS = {
    "TRA": "TRA Word Group",
    "EXP": "EXP Word Group",
    "WAR": "WAR Word Group",
    "ATLAS": "Atlas Word Group",
}


def word_group_display_name(base: str) -> str:
    if "_" not in base:
        return humanize_plain_id_fragment(base)

    prefix, suffix = base.split("_", 1)
    label = WORD_GROUP_PREFIX_LABELS.get(prefix)
    if not label:
        return humanize_plain_id_fragment(base)

    suffix_name = humanize_plain_id_fragment(suffix)
    if not suffix_name:
        return label

    return f"{label} {suffix_name}"


def structural_module_display_name(base: str) -> str | None:
    match = re.fullmatch(r"B_STR_([A-Z]+)_([A-Z0-9_]+)", base)
    if not match:
        return None

    module = match.group(1)
    variant = match.group(2)
    tokens = [token for token in variant.split("_") if token]

    color = ""
    direction = ""
    suffix = ""

    normalized_tokens = []
    for token in tokens:
        alpha, numeric = split_alpha_numeric_token(token)
        normalized_tokens.append((token, alpha, numeric))

    for token, alpha, numeric in normalized_tokens:
        if alpha == "Y":
            color = "Yellow "
            continue

        if alpha in DIRECTION_LABELS:
            direction = DIRECTION_LABELS[alpha]
            suffix = numeric
            continue

        if token in {"NETB", "NWTB", "SETB", "SWTB"}:
            direction = humanize_id_fragment(token)
            continue

    name = f"Structural Module {module}"
    if color or direction:
        name = f"{color}{name}"
    if direction:
        name = f"{name} {direction}"
    if suffix:
        name = f"{name} Variant {suffix}"

    return name


GENERATED_BUILDING_PREFIX_LABELS = (
    ("B_ALK_", "Alkove Module"),
    ("B_COK_", "Cooker Module"),
    ("B_DECO_", "Decorative Module"),
    ("B_TRU_", "Truss Module"),
    ("B_STAIRS", "Stairs"),
    ("B_FLOOR_", "Floor Module"),
    ("B_ROOF_", "Roof Module"),
    ("B_RAMP_", "Ramp Module"),
    ("B_DOOR_", "Door Module"),
    ("B_WINDOW_", "Window Module"),
)


def generated_building_prefix_display_name(base: str) -> str | None:
    for prefix, label in GENERATED_BUILDING_PREFIX_LABELS:
        if not base.startswith(prefix):
            continue

        suffix = base.removeprefix(prefix)
        if not suffix:
            return label

        return f"{label} {humanize_directional_id_fragment(suffix)}"

    match = re.fullmatch(r"BUILDDECALVIS([0-9]+)", base)
    if match:
        return f"Visible Decal {match.group(1)}"

    match = re.fullmatch(r"CONTAINER([0-9]+)", base)
    if match:
        return f"Storage Container {match.group(1)}"

    match = re.fullmatch(r"SPEC_FIREWORK([0-9]+)", base)
    if match:
        return f"Special Firework {match.group(1)}"

    if base.startswith("BUILD"):
        return f"Build Part: {humanize_plain_id_fragment(base.removeprefix('BUILD'))}"

    if base.startswith("CUBE"):
        return f"Cube Build Part: {humanize_plain_id_fragment(base.removeprefix('CUBE'))}"

    return None

def generated_structural_display_name(base: str) -> str:
    structural_name = structural_module_display_name(base)
    if structural_name:
        return structural_name

    generated_building_name = generated_building_prefix_display_name(base)
    if generated_building_name:
        return generated_building_name

    match = re.fullmatch(r"FRE_ROOM_STORE([0-9]+)", base)
    if match:
        return f"Freighter Storage Room {match.group(1)}"

    exact_labels = {
        "ARCHIVE": "Archive",
        "BASE_STARJOINT": "Base Star Joint",
        "BIOROOM": "Bio Room",
        "COOKER": "Nutrient Processor",
        "CREATURE_FEED": "Creature Feeder",
        "CRATEFRAME": "Crate Frame",
        "CURVEDCUBEROOF": "Curved Cube Roof",
        "FLAG1": "Flag 1",
        "FRE_ROOM_REFINE": "Freighter Refiner Room",
        "HEALTHSTATION": "Health Station",
        "HOLO_DISCO_0": "Holographic Disco 0",
        "LIGHT_TALL": "Tall Light",
        "MAINROOMFRAME": "Main Room Frame",
        "MAINROOM_WATER": "Main Room Water",
        "NOISEBOX": "ByteBeat Device",
        "PLANTPOT2": "Plant Pot 2",
        "PLANTPOT3": "Plant Pot 3",
        "RACE_RAMP": "Race Ramp",
        "SHIELDSTATION": "Shield Station",
        "TECHPANEL": "Technology Panel",
        "TELEPORTER_F": "Freighter Teleporter",
        "VIEWSPHERE": "View Sphere",
        "WATERBUBBLE": "Water Bubble",
    }

    exact = exact_labels.get(base)
    if exact:
        return exact

    if base.startswith("FRE_ROOM_"):
        return f"Freighter Room: {humanize_directional_id_fragment(base.removeprefix('FRE_ROOM_'))}"
    if base.startswith("B_WALL_"):
        return f"Wall Module {humanize_directional_id_fragment(base.removeprefix('B_WALL_'))}"
    if base.startswith("B_WNG_"):
        return f"Wing Module {humanize_directional_id_fragment(base.removeprefix('B_WNG_'))}"
    if base.startswith("B_CON_"):
        return f"Connector Module {humanize_directional_id_fragment(base.removeprefix('B_CON_'))}"
    if base.startswith("B_HAB1_"):
        return f"Habitation Module 1 {humanize_directional_id_fragment(base.removeprefix('B_HAB1_'))}"
    if base.startswith("B_HAB_"):
        return f"Habitation Module {humanize_directional_id_fragment(base.removeprefix('B_HAB_'))}"
    if base.startswith("B_LND_"):
        return f"Landing Structure {humanize_directional_id_fragment(base.removeprefix('B_LND_'))}"
    if base.startswith("B_SHL_"):
        return f"Shelter Module {humanize_directional_id_fragment(base.removeprefix('B_SHL_'))}"
    if base.startswith("B_TUR_"):
        return f"Tower Module {humanize_directional_id_fragment(base.removeprefix('B_TUR_'))}"
    if base.startswith("B_GEN_"):
        return f"Generated Structure Module {humanize_directional_id_fragment(base.removeprefix('B_GEN_'))}"
    if base.startswith("GARAGE_"):
        return f"Exocraft Garage {humanize_directional_id_fragment(base.removeprefix('GARAGE_'))}"
    if base.startswith("BASE_"):
        return f"Base Build Part: {humanize_plain_id_fragment(base.removeprefix('BASE_'))}"
    if base.startswith("BLD_"):
        return f"Building Part: {humanize_plain_id_fragment(base.removeprefix('BLD_'))}"
    if base.startswith("FOS_"):
        return f"Fossil Build Part: {humanize_plain_id_fragment(base.removeprefix('FOS_'))}"
    if base.startswith(("S_", "T_", "F_", "U_", "B_")):
        return f"Generated Build Part: {humanize_plain_id_fragment(base)}"

    return f"Generated Structural Build Part: {humanize_plain_id_fragment(base)}"
def stat_display_name(base: str) -> str:
    labels = {
        "SHIP_DAMAGE": "Ship Damage Potential",
        "SHIP_SHIELD": "Ship Shield Strength",
        "SHIP_HYPERDRIVE": "Ship Hyperdrive Range",
        "SHIP_AGILE": "Ship Maneuverability",
        "WEAPON_DAMAGE": "Multi-Tool Damage Potential",
        "WEAPON_MINING": "Multi-Tool Mining Potential",
        "WEAPON_SCAN": "Multi-Tool Scanner Range",
        "FREI_HYPERDRIVE": "Freighter Hyperdrive Range",
        "FREI_FLEET": "Fleet Coordination",
        "ALIEN_SHIP": "Living Ship Marker",
        "ROBOT_SHIP": "Robot Ship Marker",
    }

    return labels.get(base, base.replace("_", " ").title())


def maintenance_display_name(base: str) -> str:
    labels = {
        "MAINT_REFINER": "Refiner Maintenance",
        "MAINT_FUEL1": "Fuel Maintenance",
        "MAINT_FUEL3": "Fuel Maintenance",
        "MAINT_FUEL4": "Fuel Maintenance",
        "MAINT_FARM5": "Farm Maintenance",
    }

    if base.startswith("MAINT_PORTAL"):
        suffix = base.removeprefix("MAINT_PORTAL")
        return f"Portal Glyph Maintenance {suffix}" if suffix else "Portal Glyph Maintenance"

    return labels.get(base, base.replace("_", " ").title())


def repair_requirement_display_name(base: str) -> str:
    match = re.fullmatch(r"R([0-9]+)_(.+)", base)
    if not match:
        return base.replace("_", " ").title()

    slot_index = match.group(1)
    requirement_id = match.group(2)

    if requirement_id.startswith("VEHICL"):
        return f"Repair Requirement {slot_index}: Vehicle Component {requirement_id.removeprefix('VEHICL')}"
    if requirement_id.startswith("UT_LAU"):
        return f"Repair Requirement {slot_index}: Launch Thruster Component {requirement_id.removeprefix('UT_LAU')}"

    return f"Repair Requirement {slot_index}: {requirement_id}"


def reward_display_name(base: str) -> str:
    if base.startswith("RS_S19_S"):
        match = re.fullmatch(r"RS_S19_S([0-9]+)M([0-9]+)", base)
        if match:
            return f"Expedition 19 Stage {match.group(1)} Milestone {match.group(2)} Reward"

    match = re.fullmatch(r"RS_S19_PHASE([0-9]+)", base)
    if match:
        return f"Expedition 19 Phase {match.group(1)} Reward"

    match = re.fullmatch(r"RS_S19_PARTY([0-9]+)", base)
    if match:
        return f"Expedition 19 Community Milestone {match.group(1)} Reward"

    labels = {
        "RS_S19_COMPLETE": "Expedition 19 Final Reward",
        "RS_S19_TURRET": "Expedition 19 Account Reward: Turret",
        "RS_S19_EGG": "Expedition 19 Account Reward: Companion Egg",
        "RS_S19_TRAIL": "Expedition 19 Account Reward: Trail",
    }

    return labels.get(base, base.replace("_", " ").title())


def localisation_key_label(base: str) -> str:
    return humanize_plain_id_fragment(base)


def loc_display_name(base: str) -> str:
    labels = {
        "BUILDERS_INTRO": "Builders Intro Progress Key",
        "BUILDING_HINT": "Building Hint Mission Key",
        "CV_AUTO_HINT": "Corvette Auto Hint Mission Key",
        "EXPEDITIONS": "Expeditions Progress Key",
        "EXPED_DIED": "Expedition Death Progress Key",
        "EXPED_DIST": "Expedition Distance Progress Key",
        "EXPED_PLAQUES": "Expedition Plaques Progress Key",
        "FREI_COLOURHINT": "Freighter Colour Hint Mission Key",
        "FREI_INVHINT": "Freighter Inventory Hint Mission Key",
        "GAMEMODE_SEASONAL": "Seasonal Game Mode Localisation Key",
        "GAMEMODE_SEASONAL_SUBTITLE": "Seasonal Game Mode Subtitle Localisation Key",
        "NOT_TECH_S19": "Expedition 19 Excluded Technology Key",
        "PROC_PRODS": "Procedural Products Progress Key",
        "PROC_TECH_COUNT": "Procedural Technology Count Progress Key",
        "PROC_TECH_HINT": "Procedural Technology Hint Mission Key",
        "SHIPFUEL_WIKI": "Ship Fuel Wiki Mission Key",
        "SHIPS_BOUGHT": "Ships Bought Progress Key",
        "SHIPSLOTREPAIRS": "Ship Slot Repairs Progress Key",
        "SHIPSWAP_HINT": "Ship Swap Hint Mission Key",
        "SHIP_SUMMON": "Ship Summon Progress Key",
        "TECH_PRODS": "Technology Products Localisation Key",
        "T_CHART_USED": "Chart Used Progress Key",
        "T_DEFAULT": "Default Tutorial Key",
        "T_WORDSTONE_TUT": "Translator Wordstone Tutorial Mission Key",
        "W_WORDSTONE_TUT": "Wordstone Tutorial Mission Key",
    }

    if base in labels:
        return labels[base]

    if base.startswith("UI_S19_"):
        label = localisation_key_label(base.removeprefix("UI_S19_"))
        return f"Expedition 19 UI Localisation Key: {label}"
    if base.startswith("UI_EXPED19_"):
        label = localisation_key_label(base.removeprefix("UI_EXPED19_"))
        return f"Expedition 19 UI Localisation Key: {label}"
    if base.startswith("UI_EXPED_"):
        label = localisation_key_label(base.removeprefix("UI_EXPED_"))
        return f"Expedition UI Localisation Key: {label}"
    if base.startswith("UI_SEASON_19_"):
        label = localisation_key_label(base.removeprefix("UI_SEASON_19_"))
        return f"Season 19 UI Localisation Key: {label}"
    if base.startswith("UI_"):
        label = localisation_key_label(base.removeprefix("UI_"))
        return f"UI Localisation Key: {label}"
    if base == "F_TELE_BP":
        return "Teleporter Blueprint Mission Key"
    if base.startswith("EXPED"):
        return f"Expedition Progress or Localisation Key: {localisation_key_label(base)}"
    if base.startswith("GAMEMODE_"):
        return f"Game Mode Localisation Key: {localisation_key_label(base.removeprefix('GAMEMODE_'))}"
    if re.fullmatch(r"BASE_UPGRADE[0-9]+", base):
        return builtin_display_name(base)
    if base == "BASE_SAFETY":
        return "Base Safety Mission Key"
    if base.startswith("S_CLASS_"):
        label = localisation_key_label(base.removeprefix("S_CLASS_"))
        return f"Ship Class Mission Key: {label}"
    if base == "S_MILESTONES":
        return "Milestones Progress Key"
    if base == "FOS_MADE":
        return "Fossil Discovery Progress Key"
    if re.fullmatch(r"FOS_[A-Z0-9_]+_MADE", base):
        return builtin_display_name(base)
    if base.startswith("PROC_"):
        return f"Procedural Progress Key: {localisation_key_label(base.removeprefix('PROC_'))}"
    if base.startswith("SHIP"):
        return f"Ship Progress or Hint Key: {localisation_key_label(base)}"
    if base.startswith("FREI_"):
        return f"Freighter Hint Key: {localisation_key_label(base.removeprefix('FREI_'))}"

    return localisation_key_label(base)

def loc_context_from_examples(row: dict[str, Any]) -> str:
    for ex in row.get("examples", []):
        if not isinstance(ex, dict):
            continue

        path = str(ex.get("path") or "")
        parent = ex.get("parent")

        if path.startswith("<h0.Rol"):
            return "Seasonal expedition definition"
        if ".dwb[" in path:
            return "Mission progress/history entry"
        if ".gUR[" in path:
            return "Save progress/stat dictionary"
        if path.endswith(".aNF"):
            return "Save default tutorial/state key"
        if path.endswith(".HhX"):
            return "Creature species localisation key"
        if path.startswith("_meta."):
            return "Decoded save metadata"

        if isinstance(parent, dict):
            if any(key in parent for key in ("Title", "TitleUpper", "Description", "DescriptionDone")):
                return "Mission or milestone localisation"
            if "MarkerLabel" in parent:
                return "Mission marker localisation"
            if "Value" in parent:
                return "Save progress/stat dictionary"

    return "Localisation or save-progress key"


def procedural_placeholder_display_name(base: str) -> str:
    labels = {
        "PROC_BAR": "Procedural Bar Placeholder",
        "PROC_BOTT": "Procedural Bottle Placeholder",
        "PROC_FARM": "Procedural Farm Placeholder",
        "PROC_FUN": "Procedural Function Placeholder",
        "PROC_ITEM": "Procedural Item Placeholder",
        "PROC_JOB": "Procedural Job Placeholder",
        "PROC_LOOT": "Procedural Loot Placeholder",
        "PROC_PLNT": "Procedural Plant Placeholder",
        "PROC_SALV": "Procedural Salvage Placeholder",
        "PROC_TECH": "Procedural Technology Placeholder",
    }

    return labels.get(base, f"Procedural Placeholder: {base}")


def procedural_placeholder_context_from_examples(row: dict[str, Any]) -> str:
    for ex in row.get("examples", []):
        if not isinstance(ex, dict):
            continue

        path = str(ex.get("path") or "")

        if ".GQA[" in path:
            return "Procedural generation table entry"
        if ".b69[" in path:
            return "Product history or save product table entry"

    return "Procedural save placeholder"


def classify_hit(base: str, path: str, parent: Any) -> str:
    if is_noise_id(base):
        return "noise"
    if base.startswith(LOC_PREFIXES) or is_mission_or_progress_key(base) or is_name_loc_key_hit(base, path):
        return "loc_like"
    if base in CUSTOMIZATION_EXACT_IDS:
        return "customization_like"
    if is_discovery_name_hit(path):
        return "discovery_name_like"
    if is_progress_stat_key_hit(path):
        return "progress_stat_like"
    if is_mission_history_key_hit(path):
        return "mission_key_like"
    if is_mission_reference_hit(base, path):
        return "mission_reference_like"
    if is_dialog_key_hit(path):
        return "dialog_key_like"
    if is_word_group_hit(base, path):
        return "word_group_like"
    if is_recipe_key_hit(base, path):
        return "recipe_key_like"
    if is_event_key_hit(path):
        return "event_key_like"
    if is_milestone_objective_hit(path):
        return "milestone_objective_like"
    if is_mission_id_hit(path):
        return "mission_id_like"
    if is_procedural_generation_key_hit(path):
        return "procedural_generation_key_like"
    if is_preset_id_hit(path):
        return "preset_like"
    if is_creature_config_hit(path):
        return "creature_config_like"
    if is_metadata_hit(path):
        return "metadata_like"
    if is_generated_unique_id_hit(path):
        return "generated_unique_id_like"
    if is_generated_hash_hit(path):
        return "generated_unique_id_like"
    if is_generated_name_hit(path):
        return "generated_name_like"
    if is_generated_label_hit(path):
        return "generated_name_like"
    if is_waypoint_type_hit(path):
        return "waypoint_type_like"
    if is_settlement_state_hit(path):
        return "settlement_state_like"
    if is_terminal_state_hit(path):
        return "terminal_state_like"
    if is_loadout_config_hit(path):
        return "loadout_config_like"
    if is_player_state_config_hit(path):
        return "player_state_config_like"
    if is_account_config_hit(path):
        return "account_config_like"
    if is_graphics_config_hit(path):
        return "graphics_config_like"
    if is_persistent_base_type_hit(path):
        return "persistent_base_type_like"
    if is_building_class_hit(path):
        return "building_class_like"
    if is_frigate_config_hit(path):
        return "frigate_config_like"
    if is_seasonal_config_hit(path):
        return "seasonal_config_like"
    if is_difficulty_config_hit(path):
        return "difficulty_config_like"
    if is_save_enum_hit(path):
        return "save_enum_like"
    if is_stat_hit(parent):
        return "stat_like"
    if is_maintenance_slot_id(base):
        return "maintenance_slot_like"
    if is_repair_requirement_slot_id(base):
        return "repair_requirement_slot_like"
    if is_placed_buildable_path(path) and is_generated_structural_building_id(base):
        return "generated_structural_building_like"
    if is_building_slot_id(base):
        return "building_like"
    if is_base_object_hit(path, parent):
        return "building_like"
    if is_inventory_slot_hit(path, parent):
        return "inventory_slot_like"
    if base.startswith("PROC_"):
        return "procedural_placeholder_like"
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


def write_building_family_report(
    report: dict[str, Any],
    out_path: Path,
    rows_key: str,
    title: str,
    summary_label: str,
) -> None:
    rows = report.get(rows_key, [])
    if not isinstance(rows, list):
        rows = []

    family_counts: Counter[str] = Counter()
    family_ids: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for row in rows:
        if not isinstance(row, dict):
            continue

        base = base_id(row.get("base_id"))
        if not base:
            continue

        count = int(row.get("count") or 0)
        family = building_family_id(base)
        family_counts[family] += count
        family_ids[family].append(row)

    total_occurrences = sum(int(row.get("count") or 0) for row in rows if isinstance(row, dict))

    lines: list[str] = []
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"Source: `{report.get('input', '')}`")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- {summary_label} unique IDs: `{len(rows)}`")
    lines.append(f"- {summary_label} total occurrences: `{total_occurrences}`")
    lines.append(f"- Family groups: `{len(family_counts)}`")
    lines.append("")
    lines.append("## Family counts")
    lines.append("")
    lines.append("| Family | Occurrences | Unique IDs |")
    lines.append("|---|---:|---:|")

    for family, count in family_counts.most_common():
        lines.append(f"| `{family}` | {count} | {len(family_ids[family])} |")

    lines.append("")
    lines.append("## Top IDs by family")
    lines.append("")

    for family, count in family_counts.most_common():
        lines.append(f"### `{family}`")
        lines.append("")
        lines.append(f"- Occurrences: `{count}`")
        lines.append(f"- Unique IDs: `{len(family_ids[family])}`")
        lines.append("")
        has_generated_display_names = any(
            isinstance(row, dict) and row.get("generated_display_name")
            for row in family_ids[family]
        )

        if has_generated_display_names:
            lines.append("| ID | Display name | Count | Example paths |")
            lines.append("|---|---|---:|---|")
        else:
            lines.append("| ID | Count | Example paths |")
            lines.append("|---|---:|---|")

        for row in family_ids[family]:
            examples = []
            for ex in row.get("examples", [])[:3]:
                if not isinstance(ex, dict):
                    continue
                path = ex.get("path")
                if path:
                    examples.append(f"`{path}`")

            example_text = "<br>".join(examples)
            if has_generated_display_names:
                display_name = row.get("generated_display_name") or ""
                lines.append(
                    f"| `{row.get('base_id', '')}` | {display_name} | {row.get('count', 0)} | {example_text} |"
                )
            else:
                lines.append(f"| `{row.get('base_id', '')}` | {row.get('count', 0)} | {example_text} |")

        lines.append("")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")

def write_stat_report(report: dict[str, Any], out_path: Path) -> None:
    rows = report.get("unresolved_stat_like_ids", [])
    if not isinstance(rows, list):
        rows = []

    total_occurrences = sum(int(row.get("count") or 0) for row in rows if isinstance(row, dict))

    lines: list[str] = []
    lines.append("# Save Stat-like IDs")
    lines.append("")
    lines.append(f"Source: `{report.get('input', '')}`")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Stat-like unique IDs: `{len(rows)}`")
    lines.append(f"- Stat-like total occurrences: `{total_occurrences}`")
    lines.append("")
    lines.append("| ID | Display name | Count | Example values | Example paths |")
    lines.append("|---|---|---:|---|---|")

    for row in rows:
        if not isinstance(row, dict):
            continue

        values = []
        paths = []
        for ex in row.get("examples", [])[:5]:
            if not isinstance(ex, dict):
                continue

            parent = ex.get("parent")
            if isinstance(parent, dict) and "Value" in parent:
                values.append(f"`{parent['Value']}`")

            path = ex.get("path")
            if path:
                paths.append(f"`{path}`")

        lines.append(
            f"| `{row.get('base_id', '')}` | {row.get('stat_display_name', '')} | "
            f"{row.get('count', 0)} | {'<br>'.join(values)} | {'<br>'.join(paths)} |"
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")


def write_maintenance_and_repair_report(report: dict[str, Any], out_path: Path) -> None:
    maintenance_rows = report.get("unresolved_maintenance_slot_like_ids", [])
    repair_rows = report.get("unresolved_repair_requirement_slot_like_ids", [])

    if not isinstance(maintenance_rows, list):
        maintenance_rows = []
    if not isinstance(repair_rows, list):
        repair_rows = []

    lines: list[str] = []
    lines.append("# Maintenance and Repair-like IDs")
    lines.append("")
    lines.append(f"Source: `{report.get('input', '')}`")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Maintenance slot-like unique IDs: `{len(maintenance_rows)}`")
    lines.append(f"- Repair requirement slot-like unique IDs: `{len(repair_rows)}`")
    lines.append("")

    report_sections = [
        (
            "Maintenance slot-like IDs",
            maintenance_rows,
            "maintenance_display_name",
        ),
        (
            "Repair requirement slot-like IDs",
            repair_rows,
            "repair_requirement_display_name",
        ),
    ]

    for title, rows, display_key in report_sections:
        lines.append(f"## {title}")
        lines.append("")
        lines.append("| ID | Display name | Count | Example amounts | Example paths |")
        lines.append("|---|---|---:|---|---|")

        for row in rows:
            if not isinstance(row, dict):
                continue

            amounts = []
            paths = []
            for ex in row.get("examples", [])[:5]:
                if not isinstance(ex, dict):
                    continue

                parent = ex.get("parent")
                if isinstance(parent, dict):
                    amount = parent.get("Amount")
                    required = parent.get("F9q")
                    if amount is not None and required is not None:
                        amounts.append(f"`{amount}/{required}`")
                    elif amount is not None:
                        amounts.append(f"`{amount}`")

                path = ex.get("path")
                if path:
                    paths.append(f"`{path}`")

            lines.append(
                f"| `{row.get('base_id', '')}` | {row.get(display_key, '')} | "
                f"{row.get('count', 0)} | {'<br>'.join(amounts)} | {'<br>'.join(paths)} |"
            )

        lines.append("")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")


def write_reward_report(report: dict[str, Any], out_path: Path) -> None:
    rows = report.get("unresolved_reward_like_ids", [])
    if not isinstance(rows, list):
        rows = []

    total_occurrences = sum(int(row.get("count") or 0) for row in rows if isinstance(row, dict))

    lines: list[str] = []
    lines.append("# Reward-like IDs")
    lines.append("")
    lines.append(f"Source: `{report.get('input', '')}`")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Reward-like unique IDs: `{len(rows)}`")
    lines.append(f"- Reward-like total occurrences: `{total_occurrences}`")
    lines.append("")
    lines.append("| ID | Display name | Count | Mission | Reward description | Example paths |")
    lines.append("|---|---|---:|---|---|---|")

    for row in rows:
        if not isinstance(row, dict):
            continue

        paths = []
        mission = ""
        description = ""

        for ex in row.get("examples", [])[:5]:
            if not isinstance(ex, dict):
                continue

            parent = ex.get("parent")
            if isinstance(parent, dict):
                if not mission:
                    mission_value = parent.get("Mission") or parent.get("Title") or parent.get("SeasonName")
                    if isinstance(mission_value, str):
                        mission = mission_value
                if not description:
                    description_value = parent.get("RewardDescription") or parent.get("FinalRewardDescription")
                    if isinstance(description_value, str):
                        description = description_value

            path = ex.get("path")
            if path:
                paths.append(f"`{path}`")

        lines.append(
            f"| `{row.get('base_id', '')}` | {row.get('reward_display_name', '')} | "
            f"{row.get('count', 0)} | `{mission}` | {description} | {'<br>'.join(paths)} |"
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")


def write_loc_report(report: dict[str, Any], out_path: Path) -> None:
    rows = report.get("unresolved_other_loc_like_ids", [])
    if not isinstance(rows, list):
        rows = []

    total_occurrences = sum(int(row.get("count") or 0) for row in rows if isinstance(row, dict))

    lines: list[str] = []
    lines.append("# Loc-like IDs")
    lines.append("")
    lines.append(f"Source: `{report.get('input', '')}`")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Loc-like unique IDs: `{len(rows)}`")
    lines.append(f"- Loc-like total occurrences: `{total_occurrences}`")
    lines.append("")
    lines.append("| ID | Display name | Count | Context | Example paths |")
    lines.append("|---|---|---:|---|---|")

    for row in rows:
        if not isinstance(row, dict):
            continue

        paths = []
        for ex in row.get("examples", [])[:5]:
            if not isinstance(ex, dict):
                continue

            path = ex.get("path")
            if path:
                paths.append(f"`{path}`")

        lines.append(
            f"| `{row.get('base_id', '')}` | {row.get('loc_display_name', '')} | "
            f"{row.get('count', 0)} | {row.get('loc_context', '')} | {'<br>'.join(paths)} |"
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")

def customization_display_name(base: str) -> str:
    labels = {
        "FIGHT_COCKE": "Fighter Cockpit Customisation E",
        "FIGHT_COCKF": "Fighter Cockpit Customisation F",
        "FOS_BI_TAIL_AN": "Fossil Biped Tail Customisation",
        "FOS_HEAD_KG": "Fossil Head Customisation",
        "FOS_LIMBS_F": "Fossil Limbs Customisation F",
    }

    return labels.get(base, base.replace("_", " ").title())


def customization_context_from_examples(row: dict[str, Any]) -> str:
    for ex in row.get("examples", []):
        if not isinstance(ex, dict):
            continue

        path = str(ex.get("path") or "")

        if ".<IP." in path:
            return "Ship customisation or part-choice entry"
        if ".;l5." in path:
            return "Fossil customisation or part-choice entry"

    return "Customisation or part-choice entry"


def write_customization_report(report: dict[str, Any], out_path: Path) -> None:
    rows = report.get("unresolved_customization_like_ids", [])
    if not isinstance(rows, list):
        rows = []

    total_occurrences = sum(int(row.get("count") or 0) for row in rows if isinstance(row, dict))

    lines: list[str] = []
    lines.append("# Customization-like IDs")
    lines.append("")
    lines.append(f"Source: `{report.get('input', '')}`")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Customization-like unique IDs: `{len(rows)}`")
    lines.append(f"- Customization-like total occurrences: `{total_occurrences}`")
    lines.append("")
    lines.append("| ID | Display name | Count | Context | Example paths |")
    lines.append("|---|---|---:|---|---|")

    for row in rows:
        if not isinstance(row, dict):
            continue

        paths = []
        for ex in row.get("examples", [])[:5]:
            if not isinstance(ex, dict):
                continue

            path = ex.get("path")
            if path:
                paths.append(f"`{path}`")

        lines.append(
            f"| `{row.get('base_id', '')}` | {row.get('customization_display_name', '')} | "
            f"{row.get('count', 0)} | {row.get('customization_context', '')} | {'<br>'.join(paths)} |"
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")

def other_family_id(base: str) -> str:
    if not base:
        return "empty"

    if re.fullmatch(r"[A-Z]+[0-9]+", base):
        return re.sub(r"[0-9]+$", "*", base)

    if "_" in base:
        return base.split("_", 1)[0] + "_*"

    match = re.match(r"^([A-Z]+)", base)
    if match:
        return match.group(1) + "*"

    return "other"


def other_context_from_examples(row: dict[str, Any]) -> str:
    for ex in row.get("examples", []):
        if not isinstance(ex, dict):
            continue

        path = str(ex.get("path") or "")

        if "USN" in path:
            return "Discovery/player-name-like string"
        if "_meta" in path:
            return "Decoded metadata value"
        if "Title" in path or "Description" in path or "Subtitle" in path:
            return "Text/localisation-like value"
        if "Mission" in path:
            return "Mission/history-like value"

    return "Broad discovery value"


def display_name_for_class(
    base: str,
    class_name: str,
    row: dict[str, Any],
    display_overrides: dict[str, dict[str, Any]],
) -> str:
    override = display_overrides.get(base)
    if isinstance(override, dict):
        name = str(override.get("displayName") or "").strip()
        if name:
            return name

    if class_name == "generated_unique_id_like":
        return base

    builtin_name = builtin_display_name(base)
    if builtin_name:
        return builtin_name

    if class_name == "word_group_like":
        return word_group_display_name(base)
    if class_name == "generated_structural_building_like":
        return generated_structural_display_name(base)
    if class_name == "stat_like":
        return stat_display_name(base)
    if class_name == "maintenance_slot_like":
        return maintenance_display_name(base)
    if class_name == "repair_requirement_slot_like":
        return repair_requirement_display_name(base)
    if class_name == "reward_like":
        return reward_display_name(base)
    if class_name == "loc_like":
        return loc_display_name(base)
    if class_name == "customization_like":
        return customization_display_name(base)
    if class_name == "procedural_placeholder_like":
        return procedural_placeholder_display_name(base)

    return humanize_plain_id_fragment(base)


def format_id_with_display_name(row: dict[str, Any]) -> str:
    base = str(row.get("base_id") or "")
    display_name = str(row.get("display_name") or "").strip()

    if not base:
        return ""

    if not display_name or display_name == base:
        return f"`{base}`"

    safe_display_name = display_name.replace("|", "\\|")
    return f"`{base}` ({safe_display_name})"


def diagnostic_class_title(class_name: str) -> str:
    labels = {
        "maintenance_slot_like": "Maintenance Slot-like IDs",
        "repair_requirement_slot_like": "Repair Requirement Slot-like IDs",
        "procedural_placeholder_like": "Procedural Placeholder-like IDs",
        "stat_like": "Save Stat-like IDs",
        "customization_like": "Customization-like IDs",
        "discovery_name_like": "Discovery Name-like IDs",
        "progress_stat_like": "Progress Stat-like IDs",
        "mission_key_like": "Mission Key-like IDs",
        "mission_reference_like": "Mission Reference-like IDs",
        "dialog_key_like": "Dialog Key-like IDs",
        "word_group_like": "Word Group-like IDs",
        "recipe_key_like": "Recipe Key-like IDs",
        "event_key_like": "Event Key-like IDs",
        "milestone_objective_like": "Milestone Objective-like IDs",
        "mission_id_like": "Mission ID-like IDs",
        "procedural_generation_key_like": "Procedural Generation Key-like IDs",
        "preset_like": "Preset-like IDs",
        "creature_config_like": "Creature Config-like IDs",
        "metadata_like": "Metadata-like IDs",
        "generated_unique_id_like": "Generated Unique ID-like IDs",
        "generated_name_like": "Generated Name-like IDs",
        "waypoint_type_like": "Waypoint Type-like IDs",
        "settlement_state_like": "Settlement State-like IDs",
        "terminal_state_like": "Terminal State-like IDs",
        "loadout_config_like": "Loadout Config-like IDs",
        "player_state_config_like": "Player State Config-like IDs",
        "account_config_like": "Account Config-like IDs",
        "graphics_config_like": "Graphics Config-like IDs",
        "persistent_base_type_like": "Persistent Base Type-like IDs",
        "building_class_like": "Building Class-like IDs",
        "frigate_config_like": "Frigate Config-like IDs",
        "seasonal_config_like": "Seasonal Config-like IDs",
        "difficulty_config_like": "Difficulty Config-like IDs",
        "save_enum_like": "Save Enum-like IDs",
        "generated_structural_building_like": "Generated Structural Building-like IDs",
        "reward_like": "Reward-like IDs",
        "loc_like": "Loc-like IDs",
        "noise": "Ignored Noise Strings",
    }

    return labels.get(class_name, class_name.replace("_", " ").title())


def row_key_for_class(class_name: str) -> str:
    labels = {
        "maintenance_slot_like": "unresolved_maintenance_slot_like_ids",
        "repair_requirement_slot_like": "unresolved_repair_requirement_slot_like_ids",
        "procedural_placeholder_like": "procedural_placeholder_like_ids",
        "customization_like": "unresolved_customization_like_ids",
        "discovery_name_like": "unresolved_discovery_name_like_ids",
        "progress_stat_like": "unresolved_progress_stat_like_ids",
        "mission_key_like": "unresolved_mission_key_like_ids",
        "mission_reference_like": "unresolved_mission_reference_like_ids",
        "dialog_key_like": "unresolved_dialog_key_like_ids",
        "word_group_like": "unresolved_word_group_like_ids",
        "recipe_key_like": "unresolved_recipe_key_like_ids",
        "event_key_like": "unresolved_event_key_like_ids",
        "milestone_objective_like": "unresolved_milestone_objective_like_ids",
        "mission_id_like": "unresolved_mission_id_like_ids",
        "procedural_generation_key_like": "unresolved_procedural_generation_key_like_ids",
        "preset_like": "unresolved_preset_like_ids",
        "creature_config_like": "unresolved_creature_config_like_ids",
        "metadata_like": "unresolved_metadata_like_ids",
        "generated_unique_id_like": "unresolved_generated_unique_id_like_ids",
        "generated_name_like": "unresolved_generated_name_like_ids",
        "waypoint_type_like": "unresolved_waypoint_type_like_ids",
        "settlement_state_like": "unresolved_settlement_state_like_ids",
        "terminal_state_like": "unresolved_terminal_state_like_ids",
        "loadout_config_like": "unresolved_loadout_config_like_ids",
        "player_state_config_like": "unresolved_player_state_config_like_ids",
        "account_config_like": "unresolved_account_config_like_ids",
        "graphics_config_like": "unresolved_graphics_config_like_ids",
        "persistent_base_type_like": "unresolved_persistent_base_type_like_ids",
        "building_class_like": "unresolved_building_class_like_ids",
        "frigate_config_like": "unresolved_frigate_config_like_ids",
        "seasonal_config_like": "unresolved_seasonal_config_like_ids",
        "difficulty_config_like": "unresolved_difficulty_config_like_ids",
        "save_enum_like": "unresolved_save_enum_like_ids",
        "generated_structural_building_like": "generated_structural_building_like_ids",
        "reward_like": "unresolved_reward_like_ids",
        "loc_like": "unresolved_other_loc_like_ids",
        "noise": "ignored_noise_strings",
    }

    return labels.get(class_name, f"unresolved_{class_name}_ids")


def write_diagnostic_summary_report(report: dict[str, Any], out_path: Path) -> None:
    actionable = report.get("catalogue_actionable_unresolved_unique_by_class", {})
    diagnostic = report.get("diagnostic_non_catalogue_unique_by_class", {})
    broad_other = int(report.get("broad_discovery_other_unique_base_ids") or 0)
    actionable_clean = bool(report.get("catalogue_actionable_unresolved_is_clean"))
    broad_other_clean = bool(report.get("broad_discovery_other_is_clean"))

    if not isinstance(actionable, dict):
        actionable = {}
    if not isinstance(diagnostic, dict):
        diagnostic = {}

    lines: list[str] = []
    lines.append("# Unresolved ID Diagnostic Summary")
    lines.append("")
    lines.append(f"Source: `{report.get('input', '')}`")
    lines.append("")
    lines.append("## Catalogue-actionable checkpoint")
    lines.append("")
    lines.append("| Class | Unique IDs |")
    lines.append("|---|---:|")

    for class_name in CATALOGUE_ACTIONABLE_CLASS_NAMES:
        lines.append(f"| `{class_name}` | {int(actionable.get(class_name) or 0)} |")

    lines.append("")
    lines.append(f"- Catalogue-actionable checkpoint clean: `{actionable_clean}`")
    lines.append(f"- Broad discovery other unique IDs: `{broad_other}`")
    lines.append(f"- Broad discovery checkpoint clean: `{broad_other_clean}`")
    lines.append("")
    lines.append("## Diagnostic / non-catalogue classes")
    lines.append("")
    lines.append("| Class | Unique IDs | Top IDs / names |")
    lines.append("|---|---:|---|")

    sorted_classes = sorted(
        ((str(key), int(value or 0)) for key, value in diagnostic.items()),
        key=lambda item: (-item[1], item[0]),
    )

    for class_name, count in sorted_classes:
        rows = report.get(row_key_for_class(class_name), [])
        if not isinstance(rows, list):
            rows = []

        top_ids = []
        for row in rows[:8]:
            if isinstance(row, dict) and row.get("base_id"):
                top_ids.append(format_id_with_display_name(row))

        lines.append(
            f"| `{class_name}` | {count} | {', '.join(top_ids)} |"
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")



def write_other_discovery_report(report: dict[str, Any], out_path: Path) -> None:
    rows = report.get("unresolved_other_strings", [])
    if not isinstance(rows, list):
        rows = []

    family_counts: dict[str, dict[str, int]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue

        base = str(row.get("base_id") or "")
        family = other_family_id(base)
        if family not in family_counts:
            family_counts[family] = {"occurrences": 0, "unique": 0}

        family_counts[family]["occurrences"] += int(row.get("count") or 0)
        family_counts[family]["unique"] += 1

    total_occurrences = sum(int(row.get("count") or 0) for row in rows if isinstance(row, dict))
    sorted_families = sorted(
        family_counts.items(),
        key=lambda item: (-item[1]["occurrences"], item[0]),
    )

    lines: list[str] = []
    lines.append("# Broad Discovery Other IDs")
    lines.append("")
    lines.append(f"Source: `{report.get('input', '')}`")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Other unique IDs: `{len(rows)}`")
    lines.append(f"- Other total occurrences: `{total_occurrences}`")
    lines.append(f"- Family groups: `{len(sorted_families)}`")
    lines.append("")
    lines.append("## Family counts")
    lines.append("")
    lines.append("| Family | Occurrences | Unique IDs |")
    lines.append("|---|---:|---:|")

    for family, counts in sorted_families[:80]:
        lines.append(f"| `{family}` | {counts['occurrences']} | {counts['unique']} |")

    lines.append("")
    lines.append("## Top IDs")
    lines.append("")
    lines.append("| ID | Count | Context | Alias candidates | Example paths |")
    lines.append("|---|---:|---|---|---|")

    for row in rows[:250]:
        if not isinstance(row, dict):
            continue

        candidates = ", ".join(f"`{x}`" for x in row.get("alias_candidates", [])[:8])

        paths = []
        for ex in row.get("examples", [])[:5]:
            if not isinstance(ex, dict):
                continue

            path = ex.get("path")
            if path:
                paths.append(f"`{path}`")

        lines.append(
            f"| `{row.get('base_id', '')}` | {row.get('count', 0)} | "
            f"{other_context_from_examples(row)} | {candidates} | {'<br>'.join(paths)} |"
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")

def assert_class_registry_consistent(report: dict[str, Any]) -> None:
    class_names = set(UNRESOLVED_CLASS_NAMES)

    if len(class_names) != len(UNRESOLVED_CLASS_NAMES):
        raise ValueError("UNRESOLVED_CLASS_NAMES contains duplicate class names")

    missing_actionable = [
        key for key in CATALOGUE_ACTIONABLE_CLASS_NAMES
        if key not in class_names
    ]
    if missing_actionable:
        raise ValueError(
            "CATALOGUE_ACTIONABLE_CLASS_NAMES contains unknown classes: "
            + ", ".join(missing_actionable)
        )

    missing_diagnostic = [
        key for key in DIAGNOSTIC_NON_CATALOGUE_CLASS_NAMES
        if key not in class_names
    ]
    if missing_diagnostic:
        raise ValueError(
            "DIAGNOSTIC_NON_CATALOGUE_CLASS_NAMES contains unknown classes: "
            + ", ".join(missing_diagnostic)
        )

    overlapping = sorted(
        set(CATALOGUE_ACTIONABLE_CLASS_NAMES)
        & set(DIAGNOSTIC_NON_CATALOGUE_CLASS_NAMES)
    )
    if overlapping:
        raise ValueError(
            "catalogue-actionable and diagnostic class registries overlap: "
            + ", ".join(overlapping)
        )

    if "other" not in class_names:
        raise ValueError("UNRESOLVED_CLASS_NAMES must include other")

    if "other" in CATALOGUE_ACTIONABLE_CLASS_NAMES:
        raise ValueError("other must not be catalogue-actionable")

    if "other" in DIAGNOSTIC_NON_CATALOGUE_CLASS_NAMES:
        raise ValueError("other must not be diagnostic non-catalogue")

    unique_by_class = report.get("unresolved_unique_by_class", {})
    if not isinstance(unique_by_class, dict):
        raise ValueError("unresolved_unique_by_class must be an object")

    missing_report_classes = [
        key for key in UNRESOLVED_CLASS_NAMES
        if key not in unique_by_class
    ]
    if missing_report_classes:
        raise ValueError(
            "unresolved_unique_by_class is missing classes: "
            + ", ".join(missing_report_classes)
        )

    extra_report_classes = sorted(
        str(key) for key in unique_by_class
        if str(key) not in class_names
    )
    if extra_report_classes:
        raise ValueError(
            "unresolved_unique_by_class contains unknown classes: "
            + ", ".join(extra_report_classes)
        )

    diagnostic = report.get("diagnostic_non_catalogue_unique_by_class", {})
    if not isinstance(diagnostic, dict):
        raise ValueError("diagnostic_non_catalogue_unique_by_class must be an object")

    missing_row_keys = []
    for class_name in DIAGNOSTIC_NON_CATALOGUE_CLASS_NAMES:
        count = int(diagnostic.get(class_name) or 0)
        rows = report.get(row_key_for_class(class_name), [])
        if count > 0 and not isinstance(rows, list):
            missing_row_keys.append(f"{class_name}:{row_key_for_class(class_name)}")
        elif count > 0 and len(rows) == 0:
            missing_row_keys.append(f"{class_name}:{row_key_for_class(class_name)}")

    if missing_row_keys:
        raise ValueError(
            "diagnostic class counts do not have matching row lists: "
            + ", ".join(missing_row_keys)
        )


def assert_report_clean_flags(report: dict[str, Any]) -> None:
    assert_class_registry_consistent(report)

    actionable = report.get("catalogue_actionable_unresolved_unique_by_class", {})
    if not isinstance(actionable, dict):
        raise ValueError("catalogue_actionable_unresolved_unique_by_class must be an object")

    expected_actionable_clean = all(
        int(actionable.get(key) or 0) == 0
        for key in CATALOGUE_ACTIONABLE_CLASS_NAMES
    )

    actual_actionable_clean = bool(report.get("catalogue_actionable_unresolved_is_clean"))
    if actual_actionable_clean != expected_actionable_clean:
        raise ValueError(
            "catalogue_actionable_unresolved_is_clean does not match "
            "catalogue_actionable_unresolved_unique_by_class"
        )

    other_rows = report.get("unresolved_other_strings", [])
    if not isinstance(other_rows, list):
        raise ValueError("unresolved_other_strings must be a list")

    expected_other_count = len(other_rows)
    actual_other_count = int(report.get("broad_discovery_other_unique_base_ids") or 0)
    if actual_other_count != expected_other_count:
        raise ValueError(
            "broad_discovery_other_unique_base_ids does not match unresolved_other_strings"
        )

    expected_other_clean = expected_other_count == 0
    actual_other_clean = bool(report.get("broad_discovery_other_is_clean"))
    if actual_other_clean != expected_other_clean:
        raise ValueError(
            "broad_discovery_other_is_clean does not match unresolved_other_strings"
        )


def write_procedural_placeholder_report(report: dict[str, Any], out_path: Path) -> None:
    rows = report.get("procedural_placeholder_like_ids", [])
    if not isinstance(rows, list):
        rows = []

    total_occurrences = sum(int(row.get("count") or 0) for row in rows if isinstance(row, dict))

    lines: list[str] = []
    lines.append("# Procedural Placeholder-like IDs")
    lines.append("")
    lines.append(f"Source: `{report.get('input', '')}`")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Procedural placeholder-like unique IDs: `{len(rows)}`")
    lines.append(f"- Procedural placeholder-like total occurrences: `{total_occurrences}`")
    lines.append("")
    lines.append("| ID | Display name | Count | Context | Example paths |")
    lines.append("|---|---|---:|---|---|")

    for row in rows:
        if not isinstance(row, dict):
            continue

        paths = []
        for ex in row.get("examples", [])[:5]:
            if not isinstance(ex, dict):
                continue

            path = ex.get("path")
            if path:
                paths.append(f"`{path}`")

        lines.append(
            f"| `{row.get('base_id', '')}` | {row.get('procedural_placeholder_display_name', '')} | "
            f"{row.get('count', 0)} | {row.get('procedural_placeholder_context', '')} | {'<br>'.join(paths)} |"
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    fullparse = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_FULLPARSE
    catalogue_path = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_CATALOGUE
    out_path = Path(sys.argv[3]) if len(sys.argv) > 3 else DEFAULT_OUT
    display_overrides_path = Path(sys.argv[4]) if len(sys.argv) > 4 else DEFAULT_DISPLAY_OVERRIDES

    data = load_json(fullparse)
    catalogue = load_json(catalogue_path)
    display_overrides = load_display_overrides(display_overrides_path)

    if not isinstance(catalogue, dict):
        raise SystemExit(f"catalogue is not an object: {catalogue_path}")

    hits: list[dict[str, Any]] = []
    walk(data, "", None, hits)

    all_counts: Counter[str] = Counter()
    unresolved_counts: Counter[str] = Counter()
    unresolved_by_class: dict[str, Counter[str]] = {
        key: Counter()
        for key in UNRESOLVED_CLASS_NAMES
    }
    resolved_by_alias: dict[str, dict[str, Any]] = {}
    examples: dict[str, list[dict[str, Any]]] = defaultdict(list)
    examples_by_class: dict[str, dict[str, list[dict[str, Any]]]] = {
        key: defaultdict(list)
        for key in UNRESOLVED_CLASS_NAMES
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
            row = {
                "base_id": key,
                "class": cls,
                "count": counter[key],
                "examples": examples_by_class.get(cls, {}).get(key, examples.get(key, [])),
                "alias_candidates": alias_candidates(key),
            }

            row["display_name"] = display_name_for_class(key, cls, row, display_overrides)

            if cls == "generated_structural_building_like":
                row["generated_display_name"] = row["display_name"]
            elif cls == "stat_like":
                row["stat_display_name"] = row["display_name"]
            elif cls == "maintenance_slot_like":
                row["maintenance_display_name"] = row["display_name"]
            elif cls == "repair_requirement_slot_like":
                row["repair_requirement_display_name"] = row["display_name"]
            elif cls == "reward_like":
                row["reward_display_name"] = row["display_name"]
            elif cls == "loc_like":
                row["loc_display_name"] = row["display_name"]
                row["loc_context"] = loc_context_from_examples(row)
            elif cls == "customization_like":
                row["customization_display_name"] = row["display_name"]
                row["customization_context"] = customization_context_from_examples(row)
            elif cls == "procedural_placeholder_like":
                row["procedural_placeholder_display_name"] = row["display_name"]
                row["procedural_placeholder_context"] = procedural_placeholder_context_from_examples(row)

            out.append(row)
        return out

    report = {
        "input": str(fullparse),
        "catalogue": str(catalogue_path),
        "display_overrides": str(display_overrides_path),
        "total_candidate_strings": len(hits),
        "unique_candidate_base_ids": len(all_counts),
        "unresolved_unique_base_ids": len(unresolved_counts),
        "unresolved_unique_by_class": {
            key: len(counter)
            for key, counter in unresolved_by_class.items()
        },
        "catalogue_actionable_unresolved_unique_by_class": {
            key: len(unresolved_by_class[key])
            for key in CATALOGUE_ACTIONABLE_CLASS_NAMES
        },
        "catalogue_actionable_unresolved_is_clean": all(
            len(unresolved_by_class[key]) == 0
            for key in CATALOGUE_ACTIONABLE_CLASS_NAMES
        ),
        "broad_discovery_other_is_clean": len(unresolved_by_class["other"]) == 0,
        "diagnostic_non_catalogue_unique_by_class": {
            key: len(unresolved_by_class[key])
            for key in DIAGNOSTIC_NON_CATALOGUE_CLASS_NAMES
        },
        "broad_discovery_other_unique_base_ids": len(unresolved_by_class["other"]),
        "resolved_by_alias_unique_base_ids": len(resolved_by_alias),
        "resolved_by_alias": dict(sorted(resolved_by_alias.items())),
        "unresolved_inventory_slot_like_ids": rows_for(unresolved_by_class["inventory_slot_like"], "inventory_slot_like"),
        "unresolved_maintenance_slot_like_ids": rows_for(unresolved_by_class["maintenance_slot_like"], "maintenance_slot_like"),
        "unresolved_repair_requirement_slot_like_ids": rows_for(unresolved_by_class["repair_requirement_slot_like"], "repair_requirement_slot_like"),
        "unresolved_inventory_like_ids": rows_for(unresolved_by_class["inventory_like"], "inventory_like"),
        "procedural_placeholder_like_ids": rows_for(
            unresolved_by_class["procedural_placeholder_like"],
            "procedural_placeholder_like",
        ),
        "unresolved_stat_like_ids": rows_for(unresolved_by_class["stat_like"], "stat_like"),
        "unresolved_customization_like_ids": rows_for(unresolved_by_class["customization_like"], "customization_like"),
        "unresolved_discovery_name_like_ids": rows_for(unresolved_by_class["discovery_name_like"], "discovery_name_like"),
        "unresolved_progress_stat_like_ids": rows_for(unresolved_by_class["progress_stat_like"], "progress_stat_like"),
        "unresolved_mission_key_like_ids": rows_for(unresolved_by_class["mission_key_like"], "mission_key_like"),
        "unresolved_mission_reference_like_ids": rows_for(unresolved_by_class["mission_reference_like"], "mission_reference_like"),
        "unresolved_dialog_key_like_ids": rows_for(unresolved_by_class["dialog_key_like"], "dialog_key_like"),
        "unresolved_word_group_like_ids": rows_for(unresolved_by_class["word_group_like"], "word_group_like"),
        "unresolved_recipe_key_like_ids": rows_for(unresolved_by_class["recipe_key_like"], "recipe_key_like"),
        "unresolved_event_key_like_ids": rows_for(unresolved_by_class["event_key_like"], "event_key_like"),
        "unresolved_milestone_objective_like_ids": rows_for(unresolved_by_class["milestone_objective_like"], "milestone_objective_like"),
        "unresolved_mission_id_like_ids": rows_for(unresolved_by_class["mission_id_like"], "mission_id_like"),
        "unresolved_procedural_generation_key_like_ids": rows_for(unresolved_by_class["procedural_generation_key_like"], "procedural_generation_key_like"),
        "unresolved_preset_like_ids": rows_for(unresolved_by_class["preset_like"], "preset_like"),
        "unresolved_creature_config_like_ids": rows_for(unresolved_by_class["creature_config_like"], "creature_config_like"),
        "unresolved_metadata_like_ids": rows_for(unresolved_by_class["metadata_like"], "metadata_like"),
        "unresolved_generated_unique_id_like_ids": rows_for(unresolved_by_class["generated_unique_id_like"], "generated_unique_id_like"),
        "unresolved_generated_name_like_ids": rows_for(unresolved_by_class["generated_name_like"], "generated_name_like"),
        "unresolved_waypoint_type_like_ids": rows_for(unresolved_by_class["waypoint_type_like"], "waypoint_type_like"),
        "unresolved_settlement_state_like_ids": rows_for(unresolved_by_class["settlement_state_like"], "settlement_state_like"),
        "unresolved_terminal_state_like_ids": rows_for(unresolved_by_class["terminal_state_like"], "terminal_state_like"),
        "unresolved_loadout_config_like_ids": rows_for(unresolved_by_class["loadout_config_like"], "loadout_config_like"),
        "unresolved_player_state_config_like_ids": rows_for(unresolved_by_class["player_state_config_like"], "player_state_config_like"),
        "unresolved_account_config_like_ids": rows_for(unresolved_by_class["account_config_like"], "account_config_like"),
        "unresolved_graphics_config_like_ids": rows_for(unresolved_by_class["graphics_config_like"], "graphics_config_like"),
        "unresolved_persistent_base_type_like_ids": rows_for(unresolved_by_class["persistent_base_type_like"], "persistent_base_type_like"),
        "unresolved_building_class_like_ids": rows_for(unresolved_by_class["building_class_like"], "building_class_like"),
        "unresolved_frigate_config_like_ids": rows_for(unresolved_by_class["frigate_config_like"], "frigate_config_like"),
        "unresolved_seasonal_config_like_ids": rows_for(unresolved_by_class["seasonal_config_like"], "seasonal_config_like"),
        "unresolved_difficulty_config_like_ids": rows_for(unresolved_by_class["difficulty_config_like"], "difficulty_config_like"),
        "unresolved_save_enum_like_ids": rows_for(unresolved_by_class["save_enum_like"], "save_enum_like"),
        "unresolved_building_like_ids": rows_for(unresolved_by_class["building_like"], "building_like"),
        "generated_structural_building_like_ids": rows_for(
            unresolved_by_class["generated_structural_building_like"],
            "generated_structural_building_like",
        ),
        "unresolved_reward_like_ids": rows_for(unresolved_by_class["reward_like"], "reward_like"),
        "unresolved_other_loc_like_ids": rows_for(unresolved_by_class["loc_like"], "loc_like"),
        "unresolved_other_strings": rows_for(unresolved_by_class["other"], "other"),
        "ignored_noise_strings": rows_for(unresolved_by_class["noise"], "noise"),
        "all_unresolved_strings": rows_for(unresolved_counts),
        "unresolved": rows_for(unresolved_counts),
    }

    assert_report_clean_flags(report)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    building_family_report_path = out_path.with_name("unresolved_building_families.md")
    write_building_family_report(
        report,
        building_family_report_path,
        "unresolved_building_like_ids",
        "Unresolved Building-like ID Families",
        "Unresolved building-like",
    )

    generated_structural_report_path = out_path.with_name("generated_structural_building_families.md")
    write_building_family_report(
        report,
        generated_structural_report_path,
        "generated_structural_building_like_ids",
        "Generated Structural Building-like ID Families",
        "Generated structural building-like",
    )

    stat_report_path = out_path.with_name("unresolved_stat_like.md")
    write_stat_report(report, stat_report_path)

    maintenance_and_repair_report_path = out_path.with_name("unresolved_maintenance_and_repair_like.md")
    write_maintenance_and_repair_report(report, maintenance_and_repair_report_path)

    reward_report_path = out_path.with_name("unresolved_reward_like.md")
    write_reward_report(report, reward_report_path)

    loc_report_path = out_path.with_name("unresolved_loc_like.md")
    write_loc_report(report, loc_report_path)

    procedural_placeholder_report_path = out_path.with_name("unresolved_procedural_placeholders.md")
    write_procedural_placeholder_report(report, procedural_placeholder_report_path)

    customization_report_path = out_path.with_name("unresolved_customization_like.md")
    write_customization_report(report, customization_report_path)

    other_discovery_report_path = out_path.with_name("unresolved_other_discovery.md")
    write_other_discovery_report(report, other_discovery_report_path)

    diagnostic_summary_report_path = out_path.with_name("unresolved_diagnostic_summary.md")
    write_diagnostic_summary_report(report, diagnostic_summary_report_path)

    print(out_path)
    print(building_family_report_path)
    print(generated_structural_report_path)
    print(stat_report_path)
    print(maintenance_and_repair_report_path)
    print(reward_report_path)
    print(loc_report_path)
    print(procedural_placeholder_report_path)
    print(customization_report_path)
    print(other_discovery_report_path)
    print(diagnostic_summary_report_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())