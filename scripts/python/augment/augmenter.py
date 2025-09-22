# -*- coding: utf-8 -*-
"""High-level augment assembly."""
from .io_utils import load_json, save_json, read_json_lenient
from .extractors import (
    build_top_items, find_pm_slots, compute_pm_usage,
    find_top_shapes, discover_storage_container_count,
    guess_pm_labels
)

def _owners_aggregate(idxmap, labels):
    """
    Build owner aggregates:
      owners_guess[label] = {
        g_cap, t_cap, c_cap, g_used, t_used, c_used,
        g_empty, t_empty, c_empty
      }
    """
    out = {}
    for row in labels:
        i   = row['index']
        lab = row['label']
        v = idxmap.get(i, {})
        gc, tc, cc = int(v.get('g_cap',0)), int(v.get('t_cap',0)), int(v.get('c_cap',0))
        gu, tu, cu = int(v.get('g_used',0)), int(v.get('t_used',0)), int(v.get('c_used',0))
        o = out.setdefault(lab, {
            'g_cap':0,'t_cap':0,'c_cap':0,
            'g_used':0,'t_used':0,'c_used':0,
            'g_empty':0,'t_empty':0,'c_empty':0
        })
        o['g_cap'] += gc; o['t_cap'] += tc; o['c_cap'] += cc
        o['g_used']+= gu; o['t_used']+= tu; o['c_used']+= cu
        o['g_empty'] += max(gc-gu, 0)
        o['t_empty'] += max(tc-tu, 0)
        o['c_empty'] += max(cc-cu, 0)
    return out

def build_augments(decoded_obj):
    # currencies
    vLc6f = decoded_obj.get('vLc', {}).get('6f=', {})
    units   = vLc6f.get('wGS')
    nanites = vLc6f.get('7QL')
    quick   = None  # TODO

    # inventory bits
    top_items, total_items, distinct_items = build_top_items(decoded_obj)
    pm_slots = find_pm_slots(decoded_obj)
    pm_usage = compute_pm_usage(decoded_obj)
    shapes   = find_top_shapes(decoded_obj)
    storage_cnt = discover_storage_container_count(shapes)

    # index map for aggregates
    idxmap = {}
    for s in pm_slots:
        idxmap.setdefault(s['index'], {}).update({
            'g_cap': s.get('general_cap',0),
            't_cap': s.get('tech_cap',0),
            'c_cap': s.get('cargo_cap',0),
        })
    for u in pm_usage:
        idxmap.setdefault(u['index'], {}).update({
            'g_used': u.get('general_used',0),
            't_used': u.get('tech_used',0),
            'c_used': u.get('cargo_used',0),
        })

    pm_labels = guess_pm_labels(pm_slots, pm_usage)
    owners_guess = _owners_aggregate(idxmap, pm_labels)

    return {
        'currencies': {
            **({'Units': units} if isinstance(units,(int,float)) else {}),
            **({'Nanites': nanites} if isinstance(nanites,(int,float)) else {}),
            **({'Quicksilver': quick} if isinstance(quick,(int,float)) else {}),
        },
        'inventory': {
            'top_items': top_items,
            'total_items_flat': total_items,
            'distinct_items': distinct_items,
            'pm_slots': pm_slots,
            'pm_usage': pm_usage,
            'pm_labels': pm_labels,
            'owners_guess': owners_guess,
            'top_shapes': shapes,
            'storage_container_count': storage_cnt
        }
    }

def augment_one(full_path, decoded_path, in_place=False, out_path=None):
    full    = load_json(full_path)
    decoded = read_json_lenient(decoded_path)
    aug = build_augments(decoded)

    full.setdefault('_rollup', {})
    full['_rollup'].setdefault('currencies', {})
    for k,v in aug['currencies'].items():
        full['_rollup']['currencies'][k] = v

    inv = full['_rollup'].setdefault('inventory', {})
    for k in ('top_items','total_items_flat','distinct_items',
              'pm_slots','pm_usage','pm_labels','owners_guess',
              'top_shapes','storage_container_count'):
        inv[k] = aug['inventory'][k]

    if in_place:
        save_json(full_path, full)
        return full_path
    else:
        import os
        name, ext = os.path.splitext(full_path)
        out_path = out_path or (name + '.aug' + ext)
        save_json(out_path, full)
        return out_path
