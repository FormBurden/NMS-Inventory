# -*- coding: utf-8 -*-
"""Data extractors for fullparse/decoded content."""
from collections import Counter
from .io_utils import safe_get

# ------------------------- Items -------------------------

def build_top_items(decoded_obj):
    items = safe_get(decoded_obj, ('vLc','6f=','b69'), [])
    ctr = Counter(); total = 0
    for it in items:
        if isinstance(it, dict):
            code = it.get('JWK')
            if isinstance(code, str):
                ctr[code] += 1; total += 1
    return [{'code':k, 'count':v} for k,v in ctr.most_common(200)], total, len(ctr)

# ------------------------- PM slots/caps ------------------

def _hl_len(owner_dict, section):
    try:
        v = owner_dict.get(section, {}).get('hl?')
        return len(v) if isinstance(v, list) else 0
    except Exception:
        return 0

def find_pm_slots(decoded_obj):
    vLc6f = safe_get(decoded_obj, ('vLc','6f='), {})
    pm = vLc6f.get('P;m')
    out = []
    if isinstance(pm, list):
        for idx, owner in enumerate(pm):
            if isinstance(owner, dict):
                out.append({
                    'index': idx,
                    'general_cap': _hl_len(owner,';l5'),
                    'tech_cap':    _hl_len(owner,'PMT'),
                    'cargo_cap':   _hl_len(owner,'gan'),
                })
    return out

# ------------------------- PM usage -----------------------

def _extract_coords_from_list(lst):
    coords = set()
    if not isinstance(lst, list):
        return coords
    for it in lst:
        if not isinstance(it, dict): 
            continue
        if (">Qh" in it and "XJ>" in it
            and isinstance(it[">Qh"], int) and isinstance(it["XJ>"], int)):
            coords.add((it[">Qh"], it["XJ>"]))
        elif ("3ZH" in it and "Vn8" in it
              and isinstance(it["3ZH"], dict) and isinstance(it["Vn8"], dict)
              and isinstance(it["3ZH"].get(">Qh"), int) and isinstance(it["3ZH"].get("XJ>"), int)):
            coords.add((it["3ZH"][">Qh"], it["3ZH"]["XJ>"]))
    return coords

def _section_used(owner_section):
    """
    Heuristic:
      1) Union coordinate pairs across lists (except 'hl?').
      2) If none found, fallback to MAX length of any list of dicts (except 'hl?').
    """
    if not isinstance(owner_section, dict):
        return 0
    coord_union = set(); max_len = 0
    for k, v in owner_section.items():
        if k == 'hl?':
            continue
        if isinstance(v, list) and v and isinstance(v[0], dict):
            coord_union |= _extract_coords_from_list(v)
            cur_len = len(v)
            if cur_len > max_len:
                max_len = cur_len
    return len(coord_union) if coord_union else max_len

def compute_pm_usage(decoded_obj):
    vLc6f = safe_get(decoded_obj, ('vLc','6f='), {})
    pm = vLc6f.get('P;m')
    out = []
    if isinstance(pm, list):
        for idx, owner in enumerate(pm):
            if not isinstance(owner, dict):
                continue
            gc = _hl_len(owner,';l5'); tc = _hl_len(owner,'PMT'); cc = _hl_len(owner,'gan')
            gu = _section_used(owner.get(';l5'))
            tu = _section_used(owner.get('PMT'))
            cu = _section_used(owner.get('gan'))
            # clamp to capacity
            if gc and gu > gc: gu = gc
            if tc and tu > tc: tu = tc
            if cc and cu > cc: cu = cc
            out.append({'index': idx, 'general_used': gu, 'tech_used': tu, 'cargo_used': cu})
    return out

# ------------------------- Shapes ------------------------

def find_top_shapes(decoded_obj):
    vLc6f = safe_get(decoded_obj, ('vLc','6f='), {})
    shapes = {}
    if isinstance(vLc6f, dict):
        for k, v in vLc6f.items():
            if isinstance(v, dict) and 'hl?' in v and isinstance(v['hl?'], list):
                shapes[k] = len(v['hl?'])
    return shapes

def discover_storage_container_count(shapes):
    return max([cnt for _, cnt in shapes.items() if cnt == 48], default=0)

# ------------------------- Owner guesses ------------------

def guess_pm_labels(pm_slots, pm_usage):
    """
    Return list of {index, label} for each P;m owner:
      - MultiTool: tech_cap==30 && cargo_cap==0 && general_cap>=50
      - ShipCandidate: tech_cap>=26 && cargo_cap==0 && general_cap>=30
        -> among candidates, the one with largest (general_used+tech_used) becomes 'ShipCurrent',
           the rest become 'Ship'
      - Else: 'Unknown'
    """
    idx = {}
    for s in pm_slots:
        idx.setdefault(s['index'], {}).update({
            'g_cap': s.get('general_cap',0),
            't_cap': s.get('tech_cap',0),
            'c_cap': s.get('cargo_cap',0),
        })
    for u in pm_usage:
        idx.setdefault(u['index'], {}).update({
            'g_used': u.get('general_used',0),
            't_used': u.get('tech_used',0),
            'c_used': u.get('cargo_used',0),
        })

    labels = {i:'Unknown' for i in idx.keys()}
    ship_candidates = []

    for i, v in idx.items():
        gc, tc, cc = v.get('g_cap',0), v.get('t_cap',0), v.get('c_cap',0)
        if tc == 30 and cc == 0 and gc >= 50:
            labels[i] = 'MultiTool'
        elif tc >= 26 and cc == 0 and gc >= 30:
            labels[i] = 'ShipCandidate'
            ship_candidates.append(i)

    # pick current ship = max (g_used+t_used)
    if ship_candidates:
        def used_sum(i):
            vi = idx[i]; return int(vi.get('g_used',0)) + int(vi.get('t_used',0))
        ship_candidates.sort(key=lambda i: (-used_sum(i), i))
        if used_sum(ship_candidates[0]) > 0:
            labels[ship_candidates[0]] = 'ShipCurrent'
            for i in ship_candidates[1:]:
                labels[i] = 'Ship'
        else:
            for i in ship_candidates:
                labels[i] = 'Ship'

    return [{'index': i, 'label': labels[i]} for i in sorted(labels.keys())]

# ------------------------- Owner items --------------------

def collect_owner_items(decoded_obj):
    """
    Returns {index: {'general': Counter, 'tech': Counter, 'cargo': Counter}}
    by scanning P;m[IDX] sections for per-slot item dicts with codes under 'b2n'.
    """
    vLc6f = safe_get(decoded_obj, ('vLc','6f='), {})
    pm = vLc6f.get('P;m')
    result = {}
    if isinstance(pm, list):
        for idx, owner in enumerate(pm):
            per = {'general': Counter(), 'tech': Counter(), 'cargo': Counter()}
            for cat, key in (('general',';l5'),('tech','PMT'),('cargo','gan')):
                sec = owner.get(key, {})
                for subk, arr in list(sec.items()):
                    if subk == 'hl?': 
                        continue
                    if isinstance(arr, list):
                        for it in arr:
                            if isinstance(it, dict):
                                code = it.get('b2n') or it.get('JWK')
                                if isinstance(code, str):
                                    per[cat][code] += 1
            result[idx] = per
    return result
