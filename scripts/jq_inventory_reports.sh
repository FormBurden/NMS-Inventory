#!/usr/bin/env bash
# jq-based inventory summaries for output/fullparse/*.full.json
# Usage:
#   scripts/jq_inventory_reports.sh table
#   scripts/jq_inventory_reports.sh delta <BASE.json> <TARGET.json>
#   scripts/jq_inventory_reports.sh delta-breakdown <BASE.json> <TARGET.json>
#   scripts/jq_inventory_reports.sh pivot
#   scripts/jq_inventory_reports.sh owner-category
#   scripts/jq_inventory_reports.sh fields
#   scripts/jq_inventory_reports.sh currencies
#   scripts/jq_inventory_reports.sh items-top [N]
#   scripts/jq_inventory_reports.sh items-stats
#   scripts/jq_inventory_reports.sh pm-slots
#   scripts/jq_inventory_reports.sh pm-usage
#   scripts/jq_inventory_reports.sh pm-capacity-usage
#   scripts/jq_inventory_reports.sh pm-guess-owners
#   scripts/jq_inventory_reports.sh pm-labels
#   scripts/jq_inventory_reports.sh owners-guess
#   scripts/jq_inventory_reports.sh shapes
#   scripts/jq_inventory_reports.sh storage-count

set -euo pipefail
JQ_BIN="${JQ:-jq}"
die(){ echo "ERROR: $*" >&2; exit 1; }
command -v "$JQ_BIN" >/dev/null 2>&1 || die "jq not found. Install jq or set JQ=/path/to/jq"
[ -d output/fullparse ] || die "output/fullparse not found. Run your pipeline first."

mode="${1:-table}"

case "$mode" in
  table)
    for f in output/fullparse/*.full.json; do F="$(basename "$f")"
      OUT="$("$JQ_BIN" --arg F "$F" -r '
        def r2(x): if (x|type)=="number" then ((x*100)|round)/100 else x end;
        ((._rollup? // {} ).inventory? // {} ).by_category // {}
        | to_entries[]
        | . as $e | $e.value as $v
        | $v.total as $tot | $v.containers as $c
        | [
            $F, $e.key, ($c // 0),
            ($v.general // 0), ($v.tech // 0), ($v.cargo // 0), ($tot // 0),
            (if $tot>0 then ((100 * ($v.general // 0) / $tot)|round) else 0 end),
            (if $tot>0 then ((100 * ($v.tech    // 0) / $tot)|round) else 0 end),
            (if $tot>0 then ((100 * ($v.cargo   // 0) / $tot)|round) else 0 end),
            (if ($c // 0) > 0 then r2(($tot // 0) / $c) else 0 end)
          ] | @tsv
      ' "$f")"
      if [ -n "$OUT" ]; then
        echo "== $F"
        echo -e "file\tcategory\tcontainers\tgeneral\ttech\tcargo\ttotal\tg_%\tt_%\tc_%\ttotal_per_container"
        echo "$OUT"; echo
      fi
    done
  ;;

  delta)
    BASE="${2:-}"; TARGET="${3:-}"
    [ -n "${BASE}" ] && [ -n "${TARGET}" ] || die "delta requires BASE and TARGET"
    "$JQ_BIN" -s -r '
      def totmap(o):
        ((o._rollup? // {}).inventory? // {}).by_category? // {}
        | to_entries | map({(.key): (.value.total // 0)}) | add // {};
      .[0] as $A | .[1] as $B
      | (totmap($A)) as $base | (totmap($B)) as $curr
      | ([$base,$curr] | add | keys | sort) as $cats
      | "category\tbase\ttarget\tdelta",
        ( $cats[] as $k
          | [ $k, ($base[$k]//0), ($curr[$k]//0), (($curr[$k]//0) - ($base[$k]//0)) ]
          | @tsv )
    ' "$BASE" "$TARGET"
  ;;

  delta-breakdown)
    BASE="${2:-}"; TARGET="${3:-}"
    [ -n "${BASE}" ] && [ -n "${TARGET}" ] || die "delta-breakdown requires BASE and TARGET"
    "$JQ_BIN" -s -r '
      def catmap(o):
        ((o._rollup? // {}).inventory? // {}).by_category? // {}
        | to_entries
        | map({ (.key): {general: (.value.general // 0), tech: (.value.tech // 0), cargo: (.value.cargo // 0)} })
        | add // {};
      .[0] as $A | .[1] as $B
      | (catmap($A)) as $base | (catmap($B)) as $curr
      | ([$base,$curr] | add | keys | sort) as $cats
      | "category\tbase_general\tbase_tech\tbase_cargo\ttarget_general\ttarget_tech\ttarget_cargo\tdelta_general\tdelta_tech\tdelta_cargo",
        ( $cats[] as $k
          | ($base[$k] // {general:0,tech:0,cargo:0}) as $bg
          | ($curr[$k] // {general:0,tech:0,cargo:0}) as $cg
          | [ $k, $bg.general, $bg.tech, $bg.cargo, $cg.general, $cg.tech, $cg.cargo,
              ($cg.general - $bg.general), ($cg.tech - $bg.tech), ($cg.cargo - $bg.cargo) ]
          | @tsv )
    ' "$BASE" "$TARGET"
  ;;

  pivot)
    mapfile -t FILES < <(printf "%s\n" output/fullparse/*.full.json)
    [ "${#FILES[@]}" -gt 0 ] || die "No files in output/fullparse"
    NAMES_JSON="$(printf "%s\n" "${FILES[@]}" | xargs -n1 basename | jq -R . | jq -s .)"
    "$JQ_BIN" -s --argjson NAMES "$NAMES_JSON" -r '
      def totmap(o):
        ((o._rollup? // {}).inventory? // {}).by_category? // {}
        | to_entries | map({(.key): (.value.total // 0)}) | add // {};
      . as $arr | ($arr | map(totmap(.))) as $maps
      | (reduce $maps[] as $m ({}; . + $m) | keys | sort) as $cats
      | "category\t" + ($NAMES | join("\t")),
        ( $cats[] as $k | [ $k ] + ( $maps | map( .[$k] // 0 ) ) | @tsv )
    ' "${FILES[@]}"
  ;;

  owner-category)
    for f in output/fullparse/*.full.json; do F="$(basename "$f")"
      OUT="$("$JQ_BIN" -r '
        ((._rollup? // {}).inventory? // {}).by_owner_by_category? // {}
        | to_entries[]? as $own
        | $own.value | to_entries[]
        | [ "'"$F"'", $own.key, .key, (.value.total // 0) ] | @tsv
      ' "$f")"
      if [ -n "$OUT" ]; then
        echo "== $F"; echo -e "file\towner\tcategory\ttotal"; echo "$OUT"; echo
      fi
    done
  ;;

  fields)
    for f in output/fullparse/*.full.json; do F="$(basename "$f")"
      OUT="$("$JQ_BIN" -r '
        ((._rollup? // {} ).inventory? // {} ).by_category // {}
        | to_entries[] | [ .key, (.value | keys | sort | join(",")) ] | @tsv
      ' "$f")"
      if [ -n "$OUT" ]; then echo "== $F"; echo "$OUT"; echo; fi
    done
  ;;

  currencies)
    printed_header=0
    for f in output/fullparse/*.full.json; do F="$(basename "$f")"
      LINE="$("$JQ_BIN" -r '
        (._rollup?.currencies? // {}) as $c
        | [ "'"$F"'", ($c.Units // 0), ($c.Nanites // 0), ($c.Quicksilver // 0) ] | @tsv
      ' "$f")"
      if [ $printed_header -eq 0 ]; then echo -e "file\tUnits\tNanites\tQuicksilver"; printed_header=1; fi
      echo "$LINE"
    done
  ;;

  items-top)
    N="${2:-25}"
    for f in output/fullparse/*.full.json; do F="$(basename "$f")"
      OUT="$("$JQ_BIN" --argjson N "$N" -r '
        (._rollup?.inventory?.top_items? // [])[:$N]
        | to_entries[]? | [ "'"$F"'", .value.code, (.value.count // 0) ] | @tsv
      ' "$f")"
      if [ -n "$OUT" ]; then echo "== $F (top $N)"; echo -e "file\tcode\tcount"; echo "$OUT"; echo; fi
    done
  ;;

  items-stats)
    printed_header=0
    for f in output/fullparse/*.full.json; do F="$(basename "$f")"
      LINE="$("$JQ_BIN" -r '
        (._rollup?.inventory? // {}) as $i
        | [ "'"$F"'", ($i.total_items_flat // 0), ($i.distinct_items // 0) ] | @tsv
      ' "$f")"
      if [ $printed_header -eq 0 ]; then echo -e "file\ttotal_items_flat\tdistinct_items"; printed_header=1; fi
      echo "$LINE"
    done
  ;;

  pm-slots)
    for f in output/fullparse/*.full.json; do F="$(basename "$f")"
      OUT="$("$JQ_BIN" -r '
        (._rollup?.inventory?.pm_slots? // []) | to_entries[]?
        | [ "'"$F"'", (.value.index // 0), (.value.general_cap // 0), (.value.tech_cap // 0), (.value.cargo_cap // 0) ] | @tsv
      ' "$f")"
      if [ -n "$OUT" ]; then echo "== $F"; echo -e "file\tindex\tgeneral_cap\ttech_cap\tcargo_cap"; echo "$OUT"; echo; fi
    done
  ;;

  pm-usage)
    for f in output/fullparse/*.full.json; do F="$(basename "$f")"
      OUT="$("$JQ_BIN" -r '
        (._rollup?.inventory?.pm_usage? // []) | to_entries[]?
        | [ "'"$F"'", (.value.index // 0), (.value.general_used // 0), (.value.tech_used // 0), (.value.cargo_used // 0) ] | @tsv
      ' "$f")"
      if [ -n "$OUT" ]; then echo "== $F"; echo -e "file\tindex\tgeneral_used\ttech_used\tcargo_used"; echo "$OUT"; echo; fi
    done
  ;;

  pm-capacity-usage)
    for f in output/fullparse/*.full.json; do F="$(basename "$f")"
      OUT="$("$JQ_BIN" -r '
        def idxmap:
          (._rollup?.inventory?.pm_slots // []) as $S
          | (._rollup?.inventory?.pm_usage // []) as $U
          | reduce ($S + $U)[] as $e ({}; .[$e.index|tostring] += $e );
        idxmap as $M
        | ($M | to_entries | sort_by(.key|tonumber)[]) as $e
        | ($e.value.general_cap // 0)  as $gc
        | ($e.value.tech_cap // 0)     as $tc
        | ($e.value.cargo_cap // 0)    as $cc
        | ($e.value.general_used // 0) as $gu
        | ($e.value.tech_used // 0)    as $tu
        | ($e.value.cargo_used // 0)   as $cu
        | ((($gc - $gu)|if .>0 then . else 0 end)) as $ge
        | ((($tc - $tu)|if .>0 then . else 0 end)) as $te
        | ((($cc - $cu)|if .>0 then . else 0 end)) as $ce
        | [ "'"$F"'", ($e.key|tonumber),
            $gc, $gu, (if $gc>0 then (100*($gu|tonumber)/$gc)|round else 0 end), $ge,
            $tc, $tu, (if $tc>0 then (100*($tu|tonumber)/$tc)|round else 0 end), $te,
            $cc, $cu, (if $cc>0 then (100*($cu|tonumber)/$cc)|round else 0 end), $ce ] | @tsv
      ' "$f")"
      if [ -n "$OUT" ]; then
        echo "== $F"
        echo -e "file\tindex\tg_cap\tg_used\tg_%\tg_empty\tt_cap\tt_used\tt_%\tt_empty\tc_cap\tc_used\tc_%\tc_empty"
        echo "$OUT"; echo
      fi
    done
  ;;

  pm-guess-owners)
    for f in output/fullparse/*.full.json; do F="$(basename "$f")"
      OUT="$("$JQ_BIN" -r '
        def idxmap:
          (._rollup?.inventory?.pm_slots // []) as $S
          | (._rollup?.inventory?.pm_usage // []) as $U
          | reduce ($S + $U)[] as $e ({}; .[$e.index|tostring] += $e );
        idxmap as $M
        | ($M | to_entries | sort_by(.key|tonumber)[]) as $e
        | ($e.value.general_cap // 0)  as $gc
        | ($e.value.tech_cap // 0)     as $tc
        | ($e.value.cargo_cap // 0)    as $cc
        | ($e.value.general_used // 0) as $gu
        | ($e.value.tech_used // 0)    as $tu
        | ($e.value.cargo_used // 0)   as $cu
        | ( if ($tu>0 and $cu>0) then "Exosuit"
            elif ($tc==30 and $cc==0 and $gc>=50) then "MultiTool"
            elif ($tc>=28 and $cc==0 and $gu>0) then "ShipLike"
            else "Unknown"
          end ) as $guess
        | [ "'"$F"'", ($e.key|tonumber), $gc, $tc, $cc, $gu, $tu, $cu, $guess ] | @tsv
      ' "$f")"
      if [ -n "$OUT" ]; then
        echo "== $F"; echo -e "file\tindex\tg_cap\tt_cap\tc_cap\tg_used\tt_used\tc_used\tguess"; echo "$OUT"; echo
      fi
    done
  ;;

  pm-labels)
    for f in output/fullparse/*.full.json; do F="$(basename "$f")"
      OUT="$("$JQ_BIN" -r '
        (._rollup?.inventory?.pm_labels // []) | sort_by(.index)
        | to_entries[]?
        | [ "'"$F"'", (.value.index // 0), (.value.label // "Unknown") ] | @tsv
      ' "$f")"
      if [ -n "$OUT" ]; then echo "== $F"; echo -e "file\tindex\tlabel"; echo "$OUT"; echo; fi
    done
  ;;

  owners-guess)
    for f in output/fullparse/*.full.json; do F="$(basename "$f")"
      OUT="$("$JQ_BIN" -r '
        (._rollup?.inventory?.owners_guess // {}) as $O
        | $O | to_entries | sort_by(.key)
        | .[] as $e
        | ($e.value) as $v
        | [ "'"$F"'", $e.key,
            ($v.g_cap//0),  ($v.g_used//0),  ($v.g_empty//0),
            ($v.t_cap//0),  ($v.t_used//0),  ($v.t_empty//0),
            ($v.c_cap//0),  ($v.c_used//0),  ($v.c_empty//0) ] | @tsv
      ' "$f")"
      if [ -n "$OUT" ]; then
        echo "== $F"
        echo -e "file\towner\tg_cap\tg_used\tg_empty\tt_cap\tt_used\tt_empty\tc_cap\tc_used\tc_empty"
        echo "$OUT"; echo
      fi
    done
  ;;

  shapes)
    for f in output/fullparse/*.full.json; do F="$(basename "$f")"
      OUT="$("$JQ_BIN" -r '
        (._rollup?.inventory?.top_shapes? // {}) | to_entries[]?
        | [ "'"$F"'", .key, (.value // 0) ] | @tsv
      ' "$f")"
      if [ -n "$OUT" ]; then echo "== $F"; echo -e "file\tkey\tslots"; echo "$OUT"; echo; fi
    done
  ;;

  storage-count)
    for f in output/fullparse/*.full.json; do F="$(basename "$f")"
      LINE="$("$JQ_BIN" -r '
        (._rollup?.inventory?.storage_container_count // 0) as $n
        | [ "'"$F"'", $n ] | @tsv
      ' "$f")"
      echo -e "file\tstorage_containers"; echo "$LINE"
    done
  ;;

  *)
    cat >&2 <<USAGE
Usage:
  $0 table
  $0 delta <BASE.json> <TARGET.json>
  $0 delta-breakdown <BASE.json> <TARGET.json>
  $0 pivot
  $0 owner-category
  $0 fields
  $0 currencies
  $0 items-top [N]
  $0 items-stats
  $0 pm-slots
  $0 pm-usage
  $0 pm-capacity-usage
  $0 pm-guess-owners
  $0 pm-labels
  $0 owners-guess
  $0 shapes
  $0 storage-count
USAGE
    exit 2
  ;;
esac
