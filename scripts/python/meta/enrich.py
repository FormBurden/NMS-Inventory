from __future__ import annotations
from typing import Any, Dict
from scripts.python.utils.paths import find_first_scalar, has_key

Json = Any

def detect_expedition(data: Dict[str, Any]) -> Dict[str, Any]:
    """Flag expedition and surface season fields."""
    meta = {"is_expedition": False, "season": {}}

    ctx   = find_first_scalar(data, ("ActiveContext",))
    sid   = find_first_scalar(data, ("SeasonId","Season_ID","Season","SeasonIndex"))
    sfrom = find_first_scalar(data, ("SeasonStartUTC","StartTimeUTC","Season_Start_UTC"))
    sto   = find_first_scalar(data, ("SeasonEndUTC","EndTimeUTC","Season_End_UTC"))

    if isinstance(sid, (int, float)): meta["season"]["id"] = int(sid)
    if sfrom is not None: meta["season"]["start_utc"] = sfrom
    if sto   is not None: meta["season"]["end_utc"]   = sto

    ctx_is_season   = (isinstance(ctx, str) and ctx.strip().lower() == "season")
    has_season_obj  = has_key(data, "SeasonData")
    meta["is_expedition"] = bool(ctx_is_season or isinstance(sid, (int,float)) or has_season_obj)
    return meta

def enrich_meta(data: Dict[str, Any]) -> Dict[str, Any]:
    meta = detect_expedition(data)
    meta["version"]        = find_first_scalar(data, ("Version",))
    meta["platform"]       = find_first_scalar(data, ("Platform",))
    meta["save_name"]      = find_first_scalar(data, ("SaveName",))
    meta["total_playtime"] = find_first_scalar(data, ("TotalPlayTime",))
    meta["active_context"] = find_first_scalar(data, ("ActiveContext",))
    meta["game_mode"]      = find_first_scalar(data, ("PresetGameMode","GameMode","Mode"))
    meta["difficulty"]     = find_first_scalar(data, ("DifficultyPreset","DifficultySettingPreset","Difficulty"))
    meta["units"]          = find_first_scalar(data, ("Units","Money","Credits"))
    meta["nanites"]        = find_first_scalar(data, ("Nanites","Nanores","Nanolytics"))
    meta["quicksilver"]    = find_first_scalar(data, ("Quicksilver","QS","QuickSilver"))
    meta["reality_index"]  = find_first_scalar(data, ("RealityIndex",))
    meta["title"]          = find_first_scalar(data, ("PlayerTitle","Title","CurrentTitle"))
    return meta
