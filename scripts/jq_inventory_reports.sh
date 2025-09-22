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

set -euo pipefail
JQ_BIN="${JQ:-jq}"

die(){ echo "ERROR: $*" >&2; exit 1; }
command -v "$JQ_BIN" >/dev/null 2>&1 || die "jq not found. Install jq or set JQ=/path/to/jq"
[ -d output/fullparse ] || die "output/fullparse not found. Run your pipeline first."

mode="${1:-table}"

case "$mode" in
  table)
    for f in output/fullparse/*.full.json; do
      F="$(basename "$f")"
      OUT="$("$JQ_BIN" --arg F "$F" -r '
        def r2(x): if (x|type)=="number" then ((x*100)|round)/100 else x end;
        ((._rollup? // {} ).inventory? // {} ).by_category // {}
        | to_entries[]
        | . as $e | $e.value as $v
        | $v.total as $tot
        | $v.containers as $c
        | [
            $F, $e.key, ($c // 0),
            ($v.general // 0), ($v.tech // 0), ($v.cargo // 0), ($tot // 0),
            (if $tot>0 then ((100 * ($v.general // 0) / $tot)|round) else 0 end),
            (if $tot>0 then ((100 * ($v.tech    // 0) / $tot)|round) else 0 end),
            (if $tot>0 then ((100 * ($v.cargo   // 0) / $tot)|round) else 0 end),
            (if ($c // 0) > 0 then r2(($tot // 0) / $c) else 0 end)
          ]
        | @tsv
      ' "$f")"
      if [ -n "$OUT" ]; then
        echo "== $F"
        echo -e "file\tcategory\tcontainers\tgeneral\ttech\tcargo\ttotal\tg_%\tt_%\tc_%\ttotal_per_container"
        echo "$OUT"
        echo
      fi
    done
  ;;

  delta)
    BASE="${2:-}"; TARGET="${3:-}"
    [ -n "${BASE}" ]   || die "delta mode requires BASE json path"
    [ -n "${TARGET}" ] || die "delta mode requires TARGET json path"
    [ -f "${BASE}" ]   || die "BASE not found: ${BASE}"
    [ -f "${TARGET}" ] || die "TARGET not found: ${TARGET}"
    "$JQ_BIN" -s -r '
      def totmap(o):
        ((o._rollup? // {}).inventory? // {}).by_category? // {}
        | to_entries
        | map({(.key): (.value.total // 0)}) | add // {};
      .[0] as $A | .[1] as $B
      | (totmap($A)) as $base
      | (totmap($B)) as $curr
      | ([$base,$curr] | add | keys | sort) as $cats
      | "category\tbase\ttarget\tdelta",
        ( $cats[] as $k
          | [ $k, ($base[$k]//0), ($curr[$k]//0), (($curr[$k]//0) - ($base[$k]//0)) ]
          | @tsv )
    ' "$BASE" "$TARGET"
  ;;

  delta-breakdown)
    BASE="${2:-}"; TARGET="${3:-}"
    [ -n "${BASE}" ]   || die "delta-breakdown requires BASE json path"
    [ -n "${TARGET}" ] || die "delta-breakdown requires TARGET json path"
    [ -f "${BASE}" ]   || die "BASE not found: ${BASE}"
    [ -f "${TARGET}" ] || die "TARGET not found: ${TARGET}"
    "$JQ_BIN" -s -r '
      def catmap(o):
        ((o._rollup? // {}).inventory? // {}).by_category? // {}
        | to_entries
        | map({ (.key): {
            general: (.value.general // 0),
            tech:    (.value.tech    // 0),
            cargo:   (.value.cargo   // 0)
          }})
        | add // {};
      .[0] as $A | .[1] as $B
      | (catmap($A)) as $base
      | (catmap($B)) as $curr
      | ([$base,$curr] | add | keys | sort) as $cats
      | "category\tbase_general\tbase_tech\tbase_cargo\ttarget_general\ttarget_tech\ttarget_cargo\tdelta_general\tdelta_tech\tdelta_cargo",
        ( $cats[] as $k
          | ($base[$k] // {general:0,tech:0,cargo:0}) as $bg
          | ($curr[$k] // {general:0,tech:0,cargo:0}) as $cg
          | [
              $k,
              $bg.general, $bg.tech, $bg.cargo,
              $cg.general, $cg.tech, $cg.cargo,
              ($cg.general - $bg.general),
              ($cg.tech    - $bg.tech),
              ($cg.cargo   - $bg.cargo)
            ] | @tsv )
    ' "$BASE" "$TARGET"
  ;;

  pivot)
    mapfile -t FILES < <(printf "%s\n" output/fullparse/*.full.json)
    [ "${#FILES[@]}" -gt 0 ] || die "No files in output/fullparse"
    NAMES_JSON="$(printf "%s\n" "${FILES[@]}" | xargs -n1 basename | jq -R . | jq -s .)"
    "$JQ_BIN" -s --argjson NAMES "$NAMES_JSON" -r '
      def totmap(o):
        ((o._rollup? // {}).inventory? // {}).by_category? // {}
        | to_entries
        | map({(.key): (.value.total // 0)}) | add // {};
      . as $arr
      | ($arr | map(totmap(.))) as $maps
      | (reduce $maps[] as $m ({}; . + $m) | keys | sort) as $cats
      | "category\t" + ($NAMES | join("\t")),
        ( $cats[] as $k
          | [ $k ] + ( $maps | map( .[$k] // 0 ) )
          | @tsv )
    ' "${FILES[@]}"
  ;;

  owner-category)
    for f in output/fullparse/*.full.json; do
      F="$(basename "$f")"
      OUT="$("$JQ_BIN" -r '
        ((._rollup? // {}).inventory? // {}).by_owner_by_category? // {}
        | to_entries[]? as $own
        | $own.value | to_entries[]
        | [ "'"$F"'", $own.key, .key, (.value.total // 0) ]
        | @tsv
      ' "$f")"
      if [ -n "$OUT" ]; then
        echo "== $F"
        echo -e "file\towner\tcategory\ttotal"
        echo "$OUT"
        echo
      fi
    done
  ;;

  fields)
    for f in output/fullparse/*.full.json; do
      F="$(basename "$f")"
      OUT="$("$JQ_BIN" -r '
        ((._rollup? // {} ).inventory? // {} ).by_category // {}
        | to_entries[]
        | [ .key, (.value | keys | sort | join(",")) ]
        | @tsv
      ' "$f")"
      if [ -n "$OUT" ]; then
        echo "== $F"
        echo "$OUT"
        echo
      fi
    done
  ;;

  currencies)
    for f in output/fullparse/*.full.json; do
      F="$(basename "$f")"
      OUT="$("$JQ_BIN" -r '
        (._rollup?.currencies? // {}) as $c
        | [ "'"$F"'", ($c.Units // 0), ($c.Nanites // 0), ($c.Quicksilver // 0) ]
        | @tsv
      ' "$f")"
      if [ -n "$OUT" ]; then
        echo -e "file\tUnits\tNanites\tQuicksilver"
        echo "$OUT"
      fi
    done
  ;;

  items-top)
    N="${2:-25}"
    for f in output/fullparse/*.full.json; do
      F="$(basename "$f")"
      OUT="$("$JQ_BIN" --argjson N "$N" -r '
        (._rollup?.inventory?.top_items? // [])[:$N]
        | to_entries[]?
        | [ "'"$F"'", .value.code, (.value.count // 0) ]
        | @tsv
      ' "$f")"
      if [ -n "$OUT" ]; then
        echo "== $F (top $N)"
        echo -e "file\tcode\tcount"
        echo "$OUT"
        echo
      fi
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
USAGE
    exit 2
  ;;
esac
