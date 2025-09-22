#!/usr/bin/env bash
set -euo pipefail

# jq helper for NMS rollup reports (extras)
# Usage:
#   scripts/jq_inventory_reports_extra.sh list-owners <FILE.json>
#   scripts/jq_inventory_reports_extra.sh owner-category-share <FILE.json>
#   scripts/jq_inventory_reports_extra.sh items-top [N] <FILE.json>
#   scripts/jq_inventory_reports_extra.sh items-top-delta [N] <BASE.json> <TARGET.json>
#   scripts/jq_inventory_reports_extra.sh owners-compare <BASE.json> <TARGET.json>
#
# Notes:
# - Aggregations are resilient to category values being either numbers or {total: N} objects.
# - items-top sums per-code across owners using the per-owner "top items" maps.
# - items-top-delta shows global code movement between two files (sorted by |delta| desc).

JQ_BIN="${JQ_BIN:-jq}"

die(){ echo "ERROR: $*" >&2; exit 1; }

mode="${1:-}"; shift || true

case "$mode" in
  list-owners)
    F="${1:-}"; [ -n "$F" ] || die "list-owners requires <FILE.json>"
    OUT="$("$JQ_BIN" -r '
      def owners:
        (((._rollup? // {}).inventory? // {}).by_owner_by_category? // {}) | keys | sort;
      owners[] | .
    ' "$F")"
    echo "== $(basename "$F") (owners)"; echo "$OUT"; echo
  ;;

  owner-category-share)
    F="${1:-}"; [ -n "$F" ] || die "owner-category-share requires <FILE.json>"
    OUT="$("$JQ_BIN" -r --arg FILE "$(basename "$F")" '
      def as_total(v): if (v|type)=="number" then v else (v.total // 0) end;
      def owners_map:
        ((._rollup? // {}).inventory? // {}).by_owner_by_category? // {};
      # pct as a pure function with explicit total arg to avoid scoping quirks
      def pct(x; total): if (total|tonumber) > 0 then (100.0 * (x|tonumber) / (total|tonumber)) else 0 end;

      owners_map
      | to_entries[]
      | { owner: .key,
          g: (as_total(.value.general // 0)),
          t: (as_total(.value.tech // 0)),
          c: (as_total(.value.cargo // 0)),
          sum: (as_total(.value.total // 0)) } as $x
      | [ $FILE,
          $x.owner,
          $x.g, (pct($x.g; $x.sum) | tostring),
          $x.t, (pct($x.t; $x.sum) | tostring),
          $x.c, (pct($x.c; $x.sum) | tostring),
          $x.sum ] | @tsv
    ' "$F")"
    echo "== $(basename "$F") (owner category shares)"
    echo -e "file\towner\tgeneral\tgeneral%\ttech\ttech%\tcargo\tcargo%\ttotal"
    echo "$OUT"; echo
  ;;

  items-top)
    # items-top [N] <FILE.json>
    if [ "$#" -eq 1 ]; then N=25; F="$1"; else N="${1:-25}"; F="${2:-}"; fi
    [ -n "${F:-}" ] || die "items-top requires <FILE.json> (optionally N first)"
    OUT="$("$JQ_BIN" -r --arg FILE "$(basename "$F")" --argjson N "$N" '
      # Sum per-code counts across owners using per-owner top maps.
      def to_map(arr): reduce arr[]? as $e ({}; .[$e.code] = ($e.count // 0));
      def topmap(o):
        (o._rollup?.inventory?.by_owner_top_items // {}) as $M
        | ($M | to_entries
            | map({ (.key): ( to_map(.value) ) })
            | add) // {};
      (topmap(.)) as $per_owner
      | reduce ($per_owner|to_entries|map(.value))[] as $m ({};
          reduce ($m|to_entries[]) as $e (.;
            .[$e.key] = ((.[$e.key] // 0) + ($e.value // 0)) ))
      | to_entries | sort_by(-.value) | .[0:$N]
      | map([ $FILE, .key, .value ] | @tsv) | .[]
    ' "$F")"
    echo "== $(basename "$F") (global top $N codes)"
    echo -e "file\tcode\ttotal_count"
    echo "$OUT"; echo
  ;;

  items-top-delta)
    # items-top-delta [N] <BASE.json> <TARGET.json>
    if [ "$#" -eq 2 ]; then N=25; BASE="$1"; TARGET="$2"; else N="${1:-25}"; BASE="${2:-}"; TARGET="${3:-}"; fi
    [ -n "${BASE:-}" ] && [ -n "${TARGET:-}" ] || die "items-top-delta requires <BASE.json> <TARGET.json> (optionally N first)"
    OUT="$("$JQ_BIN" -s -r --arg BASE "$(basename "$BASE")" --arg TARGET "$(basename "$TARGET")" --argjson N "$N" '
      def to_map(arr): reduce arr[]? as $e ({}; .[$e.code] = ($e.count // 0));
      def topmap(o):
        (o._rollup?.inventory?.by_owner_top_items // {}) as $M
        | ($M | to_entries
            | map({ (.key): ( to_map(.value) ) })
            | add) // {};
      def sum_codes(m):
        reduce (m|to_entries|map(.value))[] as $x ({};
          reduce ($x|to_entries[]) as $e (.;
            .[$e.key] = ((.[$e.key] // 0) + ($e.value // 0)) ));

      .[0] as $A | .[1] as $B
      | (sum_codes(topmap($A))) as $base
      | (sum_codes(topmap($B))) as $curr
      | ( ([$base,$curr] | map(keys) | add | unique) ) as $codes
      | [ $codes[] as $c
          | { code: $c,
              b: ($base[$c] // 0),
              t: ($curr[$c] // 0),
              d: (($curr[$c] // 0) - ($base[$c] // 0)) } ]
      # sort by |delta| descending without using .[] inside sort_by
      | sort_by( ( .d | if . < 0 then -. else . end ) ) | reverse
      | .[0:$N]
      | map([ .code, .b, .t, .d ] | @tsv) | .[]
    ' "$BASE" "$TARGET")"
    echo "== $TARGET vs $BASE (global top $N code deltas)"
    echo -e "code\tbase_count\ttarget_count\tdelta"
    echo "$OUT"; echo
  ;;

  owners-compare)
    BASE="${1:-}"; TARGET="${2:-}"
    [ -n "$BASE" ] && [ -n "$TARGET" ] || die "owners-compare requires <BASE.json> <TARGET.json>"
    OUT="$("$JQ_BIN" -s -r '
      def owners(o):
        (((o._rollup? // {}).inventory? // {}).by_owner_by_category? // {}) | keys | sort;
      .[0] as $A | .[1] as $B
      | (owners($A)) as $oa
      | (owners($B)) as $ob
      | ( ($oa - $ob) | map([ "only_in_base", . ] | @tsv ) ),
        ( ($ob - $oa) | map([ "only_in_target", . ] | @tsv ) )
      | .[]
    ' "$BASE" "$TARGET")"
    echo "== $(basename "$TARGET") vs $(basename "$BASE") (owners compare)"
    echo -e "where\towner"
    echo "$OUT"; echo
  ;;

  *)
    cat <<USAGE
Usage:
  $0 list-owners <FILE.json>
  $0 owner-category-share <FILE.json>
  $0 items-top [N] <FILE.json>
  $0 items-top-delta [N] <BASE.json> <TARGET.json>
  $0 owners-compare <BASE.json> <TARGET.json>
USAGE
    exit 2
  ;;
esac
