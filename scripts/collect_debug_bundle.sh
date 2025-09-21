#!/usr/bin/env bash
# NMS-Inventory: Collect a reproducible debug bundle (ledger append to .nmsinventory.scope.txt)
# Usage (required): --name <bundle_name> --from .nmsinventory-files.txt
# Optional flags  : --no-defaults --no-logs --decode-logs --no-network --probes-stdin --capture-sec N
# Ledger file     : .nmsinventory.scope.txt (append-only; EDTB-style)
# URL is pinned to http://localhost:8080/*

set -Eeuo pipefail
shopt -s dotglob nullglob extglob

# -------- Defaults / Env --------
NMS_URL_PREFIX="${NMS_URL_PREFIX:-http://localhost:8080}"
NOW_UTC="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
NOW_EPOCH="$(date +%s)"
DEV_LOG_WINDOW_SEC="${DEV_LOG_WINDOW_SEC:-120}"   # 2-minute window for logs/DEV selection
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"


BUNDLES_DIR="${BUNDLES_DIR:-bundles}"
mkdir -p "$BUNDLES_DIR"

NAME=""
FROM_MANIFEST=""
DO_DEFAULTS=1
DO_LOGS=1
DO_DECODE_LOGS=0
DO_NETWORK=1
USE_PROBES_STDIN=0
CAPTURE_SEC=15
TMP_WORK=""
BUNDLE_SHA=""
LEDGER_FILE=".nmsinventory.scope.txt"
BUNDLES_ROOT="${BUNDLES_ROOT:-bundles}"
BUNDLE_DIR=""



MISSING_FILES=()

# -------- Helpers --------
usage() {
  cat <<USAGE
Usage:
  bash scripts/collect_debug_bundle.sh --name <bundle_name> --from .nmsinventory-files.txt [options]

Notes:
  • All text files are redacted before packaging (built-in rules + optional .nms-redact.txt).
  • To add custom redactions, create .nms-redact.txt with lines: REGEX<TAB>REPLACEMENT


Required:
  --name NAME                      Bundle base name (no spaces).
  --from .nmsinventory-files.txt   File list to include (exact filename preferred).

Options:
  --no-defaults    Skip default includes (env mask, structure, outputs, migrations).
  --no-logs        Skip logs capture (skips logs/DEV selection).
  --decode-logs    Include decoder/import logs from .cache/** and decoded debug blobs.
  --no-network     Skip browser/probes capture.
  --probes-stdin   Read curl probes from stdin (here-doc after the command).
    --capture-sec N  If FF attach runs: capture for N seconds; else: wait N seconds before logs/network (default 15).
  -h, --help       This help.


Env:
  NMS_URL_PREFIX        Defaults to http://localhost:8080 (must remain on this origin).
  DEV_LOG_WINDOW_SEC    Seconds to match logs/DEV folders around start time (default 120).

USAGE
}

die(){ echo "[ERR] $*" >&2; exit 1; }

mask_env() {
  local src="$1" out="$2"
  [[ -f "$src" ]] || return 0
  awk '
    BEGIN{ IGNORECASE=1; pats="(PASS|PASSWORD|TOKEN|SECRET|KEY|API|ACCESS|PRIVATE)" }
    /^[[:space:]]*#/ || /^[[:space:]]*$/ { print; next }
    {
      split($0,a,"="); k=a[1];
      if (k ~ pats) print k"=********"; else print $0;
    }
  ' "$src" > "$out"
}

copy_rel() {
  # Copy $1 into $2 preserving relative structure, with redaction for text files.
  local src="$1"
  local outroot="$2"
  local rel="${src#./}"
  [[ "$rel" == "$src" ]] && rel="$src"  # handle paths without leading ./

  # Normalize any leading ./ segments for consistent layout
  rel="${rel#./}"

  # Lazily build the redactor once
  ensure_redactor

  # Ensure parent dir
  local dest="$outroot/$rel"
  mkdir -p "$(dirname "$dest")"

  if is_text_file "$src"; then
    redact_stream < "$src" > "$dest"
  else
    # Binary or unknown: copy byte-for-byte
    cp -a "$src" "$dest"
  fi
}


_git_branch() { git rev-parse --abbrev-ref HEAD 2>/dev/null || echo main; }
_git_commit() { git rev-parse --short=7 HEAD 2>/dev/null || echo unknown; }

_escape_sed() { printf '%s' "$1" | sed 's/[.[\*^$()+{}?|\\]/\\&/g'; }

health_info() {
  local out="$1"
  local kernel_raw host esc
  kernel_raw="$(uname -a 2>/dev/null || true)"
  host="$(hostname -s 2>/dev/null || true)"
  if [[ -n "$host" ]]; then
    esc="$(_escape_sed "$host")"
    # redact any whole-word occurrence of the hostname
    kernel_raw="$(printf '%s' "$kernel_raw" | sed -E "s/\b${esc}\b/HOST_REDACTED/g")"
  fi
  {
    echo "timestamp_utc: $NOW_UTC"
    echo "kernel: ${kernel_raw:-unknown}"
    echo "php: $(php -v 2>/dev/null | head -n1 || echo none)"
    echo "python: $(python3 -V 2>/dev/null || echo none)"
    echo "mariadb: $(mariadb --version 2>/dev/null || echo none)"
    echo "jq: $(jq -V 2>/dev/null || echo none)"
  } > "$out"
}

git_info() {
  local out="$1"
  {
    echo "timestamp_utc: $NOW_UTC"
    if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
      echo "git_branch: $(_git_branch)"
      echo "git_commit: $(git rev-parse HEAD || echo unknown)"
      echo "git_status:"
      git status --porcelain=v1 || true
      echo "git_remotes:"
      git remote -v || true
    else
      echo "git: not a repo"
    fi
  } > "$out"
}

# SAFE .env loader: only export DB_* keys, preserve spaces
load_dotenv_db_only() {
  local f=".env"
  [[ -f "$f" ]] || return 0
  while IFS= read -r line; do
    [[ "$line" =~ ^[[:space:]]*# ]] && continue
    [[ -z "${line// }" ]] && continue
    case "$line" in
      DB_HOST=*|DB_NAME=*|DB_USER=*|DB_PASS=*|DB_PORT=*)
        local key="${line%%=*}"
        local val="${line#*=}"
        export "$key=$val"
        ;;
    esac
  done < "$f"
}

db_snapshot() {
  local outdir="$1"
  load_dotenv_db_only
  local host="${DB_HOST:-127.0.0.1}"
  local name="${DB_NAME:-nms_database}"
  local user="${DB_USER:-nms_user}"
  local pass="${DB_PASS:-}"
  local port_opt=()
  [[ -n "${DB_PORT:-}" ]] && port_opt=(-P "${DB_PORT}")

  local cli=(mariadb -h "$host" "${port_opt[@]}" -u "$user" -D "$name")
  [[ -n "$pass" ]] && cli+=(-p"$pass")

  {
    echo "-- NMS DB snapshot @ $NOW_UTC"
    printf "SELECT COUNT(*) AS snapshots FROM nms_snapshots;\\n"
    printf "SELECT COUNT(*) AS items FROM nms_items;\\n"
    printf "SELECT snapshot_id, save_root, DATE_FORMAT(source_mtime,'%%Y-%%m-%%d %%H:%%i:%%s') AS src_mtime FROM nms_snapshots ORDER BY imported_at DESC LIMIT 10;\\n"
    printf "SELECT resource_id, SUM(amount) AS total FROM nms_items GROUP BY resource_id ORDER BY total DESC LIMIT 20;\\n"
  } > "$outdir/db_queries.sql"

  "${cli[@]}" < "$outdir/db_queries.sql" > "$outdir/db_results.txt" 2>&1 || true
}

# ---- Redaction pipeline (quiet; workspace-only) ----
redact_workspace() {
  local root="$1"
  # Single heredoc — nothing echoed to stdout
  while IFS= read -r -d '' f; do
    ROOT_DIR="$ROOT_DIR" python3 - "$f" <<'PY'
import os, re, sys

path = sys.argv[1]
try:
  data = open(path,'rb').read()
except Exception:
  sys.exit(0)

# crude binary detection
if b'\x00' in data or (len(data) and sum(c<9 or 13<c<32 for c in data[:2048]) > 300):
  sys.exit(0)

try:
  text = data.decode('utf-8', errors='replace')
except Exception:
  sys.exit(0)

# --- Default redactions ---
kv = r'(?im)^\s*(?P<key>(?:db_)?(?:password|pass|pwd|token|secret|api[_-]?key|access[_-]?key|private[_-]?key|username|user|host|hostname|db_host))\s*(?P<sep>[:=])\s*(?P<val>".*?"|\'.*?\'|[^\s#;]+)'
def repl_kv(m):
  k = m.group('key').lower()
  sep = m.group('sep')
  if 'host' in k:
    return f"{m.group('key')}{sep} host.redacted.local"
  if k in ('username','user'):
    return f"{m.group('key')}{sep} user_redacted"
  return f"{m.group('key')}{sep} ********"

# URL credentials, auth headers, query secrets, emails
text = re.sub(r'(?i)([a-z][a-z0-9+.-]*://)([^:@/\s]+):([^@/\s]+)@', r'\1USER:********@', text)
text = re.sub(r'(?im)^(\s*Authorization\s*:\s*)(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+', r'\1\2 ********', text)
text = re.sub(r'(?i)([?&])(token|access_token|apikey|api_key|pass|password)=([^&\s]+)', r'\1\2=********', text)
text = re.sub(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', 'user@redacted.local', text)

text = re.sub(kv, repl_kv, text)

# --- Optional extra redactions from .nms-redact.txt ---
extra=[]
try:
  root = os.environ.get("ROOT_DIR",".")
  p = os.path.join(root, ".nms-redact.txt")
  if os.path.exists(p):
    with open(p,"r",encoding="utf-8",errors="ignore") as fh:
      for ln in fh:
        ln = ln.rstrip("\n")
        if not ln or ln.lstrip().startswith("#"):
          continue
        if "\t" in ln:
          rgx, rep = ln.split("\t",1)
          try:
            extra.append((re.compile(rgx, re.IGNORECASE), rep))
          except Exception:
            pass
  for rx, rep in extra:
    try:
      text = rx.sub(rep, text)
    except Exception:
      pass
except Exception:
  pass

try:
  with open(path,'w',encoding='utf-8',newline='') as fh:
    fh.write(text)
except Exception:
  pass
PY
  done < <(find "$root" -type f \( -name "*.env" -o -name "*.txt" -o -name "*.md" -o -name "*.php" -o -name "*.js" -o -name "*.json" -o -name "*.yaml" -o -name "*.yml" -o -name "*.ini" -o -name "*.conf" -o -name "*.sql" -o -name "*.csv" -o -name "*.log" -o -name "*.sh" \) -print0)
}

run_probes_stdin() {
  local outdir="$1"
  mkdir -p "$outdir/probes"
  local i=0
  while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    [[ "$line" =~ ^[[:space:]]*# ]] && continue
    if [[ "$line" != *"$NMS_URL_PREFIX"* ]]; then
      echo "[WARN] Skipping probe (wrong origin): $line" | tee -a "$outdir/probes/_probes.log"
      continue
    fi
    i=$((i+1))
    local rc=0
    bash -lc "$line" >"$outdir/probes/${i}.body" 2>"$outdir/probes/${i}.stderr" || rc=$?
    if [[ "$line" == curl* ]]; then
      bash -lc "${line/ -sS / -sSI }" >"$outdir/probes/${i}.headers" 2>>"$outdir/probes/${i}.stderr" || true
    fi
    printf '{"i":%d,"cmd":%s,"rc":%d,"t":"%s"}\n' \
      "$i" "$(printf '%s' "$line" | jq -Rs .)" "$rc" "$NOW_UTC" \
      >> "$outdir/probes/_probes.ndjson"
  done
}

# -------- Redaction pipeline (built-ins + optional .nms-redact.txt) --------
# We redact any text file as it is staged, and also run a final sweep before packaging.

ensure_redactor() {
  # Build once per bundle
  [[ -n "${REDACTOR_READY:-}" ]] && return 0
  local tooldir="$TMP_WORK/.tools"
  mkdir -p "$tooldir"

  REDACT_AWK="$tooldir/redact.awk"

  # Hostname / user for token replacement
  HOST_ACTUAL="$(hostname 2>/dev/null || uname -n 2>/dev/null || true)"
  USER_ACTUAL="$(id -un 2>/dev/null || true)"

  # Optional user-provided rule list (regex<TAB>replacement per line)
  if [[ -f ".nms-redact.txt" ]]; then
    USER_RULES_CONTENT="$(cat .nms-redact.txt)"
  else
    USER_RULES_CONTENT=""
  fi

  # Create the awk redactor (ERE, case-insensitive)
  cat > "$REDACT_AWK" <<'AWK'
BEGIN {
  IGNORECASE=1
  host = ENVIRON["HOST_ACTUAL"]
  user = ENVIRON["USER_ACTUAL"]
  usrules_raw = ENVIRON["USER_RULES"]
  n_rules = split(usrules_raw, RULES, /\n/)
}
{
  line = $0

  # .env style KEY=VALUE (non-comment)
  if (match(line, /^[[:space:]]*[^#[:space:]][^=]*=/)) {
    key = line; sub(/=.*/, "", key)
    low = tolower(key)
    if (low ~ /(pass|password|secret|token|api[_-]?key|private|credential|auth|session|pwd)/) {
      sub(/=.*/, "= \"***\"", line)
    }
  }

  # JSON-like "password": "value"
  line = gensub(/"((pass|password|secret|token|api[_-]?key|private|credential|auth|session)[^"]*)"[[:space:]]*:[[:space:]]*"[^"]*"/,
                "\"\\1\": \"***\"", "g", line)

  # YAML-like password: value
  line = gensub(/((pass|password|secret|token|api[_-]?key|private|credential|auth|session)[^:]*):[[:space:]]*[^,#]+/,
                "\\1: ***", "g", line)

  # URL creds: scheme://user:pass@host
  line = gensub(/([a-zA-Z][a-zA-Z0-9+.-]*:\/\/[^:@\/\s]+:)[^@\/\s]+@/, "\\1***@", "g", line)

  # Emails
  line = gensub(/([[:alnum:]\._%+\-]+)@([[:alnum:]\.\-]+\.[A-Za-z]{2,})/, "***@\\2", "g", line)

  # Host/user tokens
  if (length(host) > 0) gsub(host, "<HOST>", line)
  if (length(user) > 0) gsub(user, "<USER>", line)

  # Home paths
  line = gensub(/\/home\/[A-Za-z0-9._-]+/, "/home/<USER>", "g", line)

  # Private IPs
  line = gensub(/\b(10\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}|192\.168\.[0-9]{1,3}\.[0-9]{1,3}|172\.(1[6-9]|2[0-9]|3[0-1])\.[0-9]{1,3}\.[0-9]{1,3})\b/,
                "<PRIVATE_IP>", "g", line)

  # User rules from ENV USER_RULES ("regex<TAB>replacement" per line)
  for (i = 1; i <= n_rules; i++) {
    rule = RULES[i]
    if (rule ~ /^[[:space:]]*$/ || rule ~ /^[[:space:]]*#/) continue
    split(rule, pair, /\t/)
    if (length(pair[1]) > 0 && length(pair[2]) > 0) {
      rgx = pair[1]; rep = pair[2]
      gsub(rgx, rep, line)
    }
  }

  print line
}
AWK

  export HOST_ACTUAL USER_ACTUAL
  # Preserve newlines for awk via env var
  export USER_RULES="$USER_RULES_CONTENT"

  REDACTOR_READY=1
}

is_text_file() {
  # Return 0 for text-like, 1 for binary
  local f="$1"
  # Grep heuristic is fast & adequate here
  LC_ALL=C grep -Iq . "$f"
}

redact_stream() {
  # Usage: redact_stream < input > output
  awk -f "$REDACT_AWK"
}

redact_and_copy() {
  # Back-compat shim if something calls this name directly
  copy_rel "$@"
}

final_redact_pass() {
  # Sweep TMP_WORK to ensure anything written directly (e.g., probes) is redacted too.
  local root="$1"
  ensure_redactor
  (cd "$root" && find . -type f ! -path "./.tools/*" -print0) | \
  while IFS= read -r -d '' rel; do
    local abs="$root/${rel#./}"
    if is_text_file "$abs"; then
      awk -f "$REDACT_AWK" < "$abs" > "$abs.tmp" && mv -f "$abs.tmp" "$abs"
    fi
  done
}


# -------- network scaffold (metadata even if no probes) --------
emit_network_scaffold() {
  # Create a small metadata footprint so bundles show that networking was enabled
  # even when no explicit probes were provided.
  local outroot="$1"
  local out="$outroot/network"
  mkdir -p "$out"
  {
    echo "origin=${NMS_URL_PREFIX:-http://localhost:8080}"
    echo "network_enabled=1"
    echo "started_at_utc=${NOW_UTC}"
  } > "$out/_meta.txt"
  # Record allow-list / reminder
  {
    echo "# Allowed origin for network capture"
    echo "${NMS_URL_PREFIX:-http://localhost:8080}"
    echo
    echo "# No probes were supplied."
    echo "# To capture HTTP bodies/headers, re-run with --probes-stdin and provide curl commands."
  } > "$out/README.txt"
}

# -------- capture python bootstrap (auto-venv for geckordp) --------
ensure_capture_python() {
  # $1 = outdir for notes (e.g., $TMP_WORK/network/ff)
  local outdir="$1"
  mkdir -p "$outdir"
  : > "$outdir/_venv_setup.txt"
  {
    echo "time_utc=${NOW_UTC}"
    echo "requested_CAPTURE_PY=${CAPTURE_PY:-<unset>}"
  } >> "$outdir/_venv_setup.txt"

  local py="${CAPTURE_PY:-python3}"
  if "$py" -c 'import geckordp,sys;print(getattr(geckordp,"__version__","unknown"))' >/dev/null 2>&1; then
    echo "using=${py}" >> "$outdir/_venv_setup.txt"
    CAPTURE_PY="$py"; export CAPTURE_PY
    return 0
  fi

  # Bootstrap lightweight venv under .cache/.venv-capture
  local vdir=".cache/.venv-capture"
  python3 -m venv "$vdir" >/dev/null 2>&1 || true
  if [[ ! -x "$vdir/bin/python" ]]; then
    echo "venv_create_failed=1" >> "$outdir/_venv_setup.txt"
    CAPTURE_PY=""
    return 1
  fi

  "$vdir/bin/python" -m pip install --upgrade pip >/dev/null 2>&1 || true
  "$vdir/bin/python" -m pip install geckordp >/dev/null 2>&1 || true

  if "$vdir/bin/python" -c 'import geckordp,sys;print(getattr(geckordp,"__version__","unknown"))' >/dev/null 2>&1; then
    CAPTURE_PY="$vdir/bin/python"; export CAPTURE_PY
    echo "using=${CAPTURE_PY}" >> "$outdir/_venv_setup.txt"
    return 0
  else
    echo "install_failed=1" >> "$outdir/_venv_setup.txt"
    CAPTURE_PY=""
    return 1
  fi
}


# -------- logs/DEV helper (name-based timestamp window) --------
# Accepts common patterns like YYYYMMDD_HHMMSS, YYYY-MM-DD_HH-MM-SS, YYYYMMDD_HHMM, etc.
_dirname_to_epoch() {
  local name="$1"
  local digits="${name//[^0-9]/}"
  local ts epoch y m d H M S
  if (( ${#digits} >= 14 )); then
    ts="${digits:0:14}"; y=${ts:0:4}; m=${ts:4:2}; d=${ts:6:2}; H=${ts:8:2}; M=${ts:10:2}; S=${ts:12:2}
  elif (( ${#digits} >= 12 )); then
    ts="${digits:0:12}"; y=${ts:0:4}; m=${ts:4:2}; d=${ts:6:2}; H=${ts:8:2}; M=${ts:10:2}; S="00"
  else
    return 1
  fi
  epoch=$(date -d "${y}-${m}-${d} ${H}:${M}:${S}" +%s 2>/dev/null) || return 1
  printf '%s\n' "$epoch"
}

collect_dev_logs_windowed() {
  local outroot="$1"
  local base="logs/DEV"
  [[ -d "$base" ]] || return 0
  local start="${NOW_EPOCH}"
  local window="${DEV_LOG_WINDOW_SEC:-120}"
  shopt -s nullglob
  for dir in "$base"/*; do
    [[ -d "$dir" ]] || continue
    local dn="$(basename "$dir")"
    local epoch="$(_dirname_to_epoch "$dn" || true)"
    [[ -n "$epoch" ]] || continue
    local diff=$(( epoch - start ))
    (( diff < 0 )) && diff=$(( -diff ))
    if (( diff <= window )); then
      copy_rel "$dir" "$outroot"
    fi
  done
  shopt -u nullglob
}

collect_decode_logs() {
  local outroot="$1"
  # .cache logs / errors / outs
  while IFS= read -r -d '' f; do
    copy_rel "$f" "$outroot"
  done < <(find .cache -type f \( -name "*.log" -o -name "*.err" -o -name "*.out" \) -print0 2>/dev/null)

  # Decoder debug blobs
  for p in .cache/decoded/.dbg/raw_decompressed.bin; do
    [[ -e "$p" ]] && copy_rel "$p" "$outroot"
  done
}


    # -------- Package --------
pack_bundle() {
  # Put the bundle into its own folder: bundles/<NAME>/<NAME>.tar.gz
  BUNDLE_DIR="${BUNDLES_ROOT}/${NAME}"
  mkdir -p "$BUNDLE_DIR"

  OUT="${BUNDLE_DIR}/${NAME}.tar.gz"
  echo "[*] Creating bundle: ${NAME}/${NAME}.tar.gz"
  # Final redaction sweep over staged files (probes, logs, .env, etc.)
  final_redact_pass "$TMP_WORK"
  if [[ "${DO_NETWORK:-1}" -eq 1 ]]; then
   [[ -d "$TMP_WORK/network" ]] || emit_network_scaffold "$TMP_WORK"
  fi
  tar -czf "$OUT" -C "$TMP_WORK" .

  # Compute checksum and print absolute path
  BUNDLE_SHA="$(sha256sum "$OUT" | awk '{print $1}')"
  ABS_OUT="$(cd "$(dirname "$OUT")" && pwd)/$(basename "$OUT")"
  echo "Bundle created: $ABS_OUT"
  echo "SHA256: $BUNDLE_SHA"
  echo "Upload that tar.gz here."

}

append_ledger_entry() {
  local bundle_file="$BUNDLES_DIR/${NAME}.tar.gz"
  local branch commit_prev mode_prev notes_prev sources="files"
  branch="$(_git_branch)"

  # files_only if truly files-only bundle
  if (( DO_DEFAULTS==0 && DO_LOGS==0 && DO_NETWORK==0 )); then
    sources="files_only"
  fi

  if [[ -f "$LEDGER_FILE" ]]; then
    commit_prev="$(awk -F': ' '/^commit:/{x=$2} END{print x}' "$LEDGER_FILE")"
    mode_prev="$(awk -F': ' '/^mode:/{x=$2} END{print x}' "$LEDGER_FILE")"
    notes_prev="$(awk -F': ' '/^notes:/{x=$0} END{print substr(x, index(x,":")+2)}' "$LEDGER_FILE")"
  fi
  [[ -z "$commit_prev" ]] && commit_prev="$(_git_commit)"
  [[ -z "$mode_prev" ]] && mode_prev="INFO"
  [[ -z "$notes_prev" ]] && notes_prev="Reference checksum for correct bundle and files."

  {
    echo "bundle: $(basename "$bundle_file")"
    echo "bundle checksum: $BUNDLE_SHA"
    echo "branch: $branch"
    echo "commit: $commit_prev"
    echo "mode: $mode_prev"
    echo "SOURCES: $sources"
    if (( ${#MISSING_FILES[@]} > 0 )); then
      echo "missing files:"
      # print unique entries in the order first seen
      printf "%s\n" "${MISSING_FILES[@]}" | awk '(!seen[$0]++){print "  - "$0}'
    fi

    echo "db_migrations: none"
    echo "notes: $notes_prev"
    echo
  } | tee -a "$LEDGER_FILE" > "${BUNDLE_DIR}/${NAME}.txt"
}

cleanup() { [[ -n "${TMP_WORK:-}" && -d "$TMP_WORK" ]] && rm -rf "$TMP_WORK"; }
trap cleanup EXIT

# -------- Arg Parse --------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --name) NAME="${2:-}"; shift 2;;
    --from) FROM_MANIFEST="${2:-}"; shift 2;;
    --no-defaults) DO_DEFAULTS=0; shift;;
    --no-logs) DO_LOGS=0; shift;;
    --decode-logs) DO_DECODE_LOGS=1; shift;;
    --no-network) DO_NETWORK=0; shift;;
    --probes-stdin) USE_PROBES_STDIN=1; shift;;
    --capture-sec)
      CAPTURE_SEC="${2:-}"
      [[ "$CAPTURE_SEC" =~ ^[0-9]+$ ]] || die "Invalid --capture-sec: ${CAPTURE_SEC:-<missing>}"
      shift 2
      ;;
    -h|--help) usage; exit 0;;
    *) die "Unknown arg: $1";;
  esac
done



[[ -n "$NAME" ]] || { usage; die "--name is required"; }
[[ -n "$FROM_MANIFEST" ]] || { usage; die "--from is required (use .nmsinventory-files.txt)"; }
[[ "$FROM_MANIFEST" == ".nmsinventory-files.txt" ]] || echo "[WARN] --from should be .nmsinventory-files.txt (continuing)"

# -------- Work area --------
TMP_WORK="$(mktemp -d -p "${TMPDIR:-/tmp}" "nms_bundle_${NAME}_XXXX")"
mkdir -p "$TMP_WORK"/{src,meta,sys,defaults,db,probes,public_data}

# -------- Metadata / Health / Git --------
git_info "$TMP_WORK/meta/git_info.txt"
health_info "$TMP_WORK/meta/health.txt"

# -------- Structure snapshot --------
if [[ -f "structure.txt" ]]; then
  cp -a "structure.txt" "$TMP_WORK/meta/structure.txt"
else
  command -v tree >/dev/null 2>&1 && tree -a -L 3 -I '.git|node_modules|vendor|cache|storage/icons' > "$TMP_WORK/meta/structure.txt" || true
fi

# -------- Defaults (unless disabled) --------
if [[ "$DO_DEFAULTS" -eq 1 ]]; then
  [[ -f ".env" ]] && mask_env ".env" "$TMP_WORK/defaults/env_masked.txt"
  [[ -f ".env.example" ]] && cp -a ".env.example" "$TMP_WORK/defaults/env.example"
  for p in \
    README.md \
    includes/bootstrap.php includes/db.php includes/icon_map.php \
    public/index.php public/Inventory/index.php \
    public/api/inventory.php public/api/item_meta.php public/api/icon.php \
    assets/css/app.css assets/js/inventory.js \
    public/data/items_local.json \
    db/migrations \
    .cache/initial_import.log .cache/initial_import.sql \
    output \
  ; do
    [[ -e "$p" ]] && copy_rel "$p" "$TMP_WORK/defaults"
  done
fi

# -------- Manifest files (required) --------
if [[ -f "$FROM_MANIFEST" ]]; then
  while IFS= read -r rel; do
    # skip blanks/comments
    [[ -z "${rel// }" ]] && continue
    [[ "$rel" =~ ^# ]] && continue
    # normalize CRLF
    rel="${rel%$'\r'}"

    # If the manifest entry contains glob characters, expand it.
    if [[ "$rel" == *[\*\?\[]* ]]; then
      mapfile -t _matches < <(compgen -G -- "$rel" || true)
      if (( ${#_matches[@]} == 0 )); then
        echo "[WARN] listed pattern had no matches: $rel"
        MISSING_FILES+=("$rel")
        continue
      fi
      for m in "${_matches[@]}"; do
        copy_rel "$m" "$TMP_WORK/src"
      done
      continue
    fi

    # Non-glob path
    if [[ -e "$rel" ]]; then
      copy_rel "$rel" "$TMP_WORK/src"
    else
      echo "[WARN] listed path not found: $rel"
      MISSING_FILES+=("$rel")
    fi
  done < "$FROM_MANIFEST"

else
  echo "[WARN] manifest not found: $FROM_MANIFEST"
fi

# -------- DB snapshot --------
db_snapshot "$TMP_WORK/db" || true

# -------- Capture window (EDTB-style) --------
# Avoid double-waiting: if Firefox attach will run, we skip the pre-sleep and let it capture for CAPTURE_SEC.
if { [[ "${CAPTURE_SEC:-0}" -gt 0 ]] && { [[ "${DO_NETWORK:-1}" -eq 1 ]] || [[ "${DO_LOGS:-1}" -eq 1 ]]; }; }; then
  WILL_FF_ATTACH=0
  if [[ "${DO_NETWORK:-1}" -eq 1 ]] && [[ -f "scripts/capture_ff_attach.py" ]]; then
    WILL_FF_ATTACH=1
  fi
  if [[ "$WILL_FF_ATTACH" -eq 1 ]]; then
    echo "[*] Using Firefox attach for ${CAPTURE_SEC}s (no pre-sleep)"
  else
    echo "[*] Pre-capture wait: ${CAPTURE_SEC}s"
    sleep "${CAPTURE_SEC}"
  fi
fi



# -------- Logs (DEV window + optional decode/import) --------
# --no-logs disables ALL logs, including --decode-logs.
if [[ "$DO_LOGS" -eq 1 ]]; then
  # Always include DEV logs when logs are enabled (windowed by dir name).
  collect_dev_logs_windowed "$TMP_WORK/sys"

  # Include decoder/import logs only when explicitly requested.
  if [[ "${DO_DECODE_LOGS:-0}" -eq 1 ]]; then
    collect_decode_logs "$TMP_WORK/sys"
  fi
fi


# -------- Network / Probes --------
# Always create a network/ scaffold when network is enabled.
if [[ "${DO_NETWORK:-1}" -eq 1 ]]; then
  emit_network_scaffold "$TMP_WORK"

  # Optional: attach to a running Firefox DevTools server (geckordp) to capture console/network/DOM
  # Captures into: $TMP_WORK/network/ff/{console.ndjson,network.ndjson,dom.html,perf.json}
    if [[ -f "scripts/capture_ff_attach.py" ]]; then
    FF_OUT="$TMP_WORK/network/ff"
    mkdir -p "$FF_OUT"

    # Auto-bootstrap a Python interpreter with geckordp (no manual venv needed)
    ensure_capture_python "$FF_OUT"

    (
      set +e
      if [[ -n "${CAPTURE_PY:-}" ]]; then
        EDTB_CAPTURE_URL_PREFIX="${NMS_URL_PREFIX:-http://localhost:8080}" \
        FF_CAPTURE_WINDOW_SEC="${CAPTURE_SEC:-15}" \
        "${CAPTURE_PY}" scripts/capture_ff_attach.py "$FF_OUT" \
          >"$FF_OUT/_attach.stdout" 2>"$FF_OUT/_attach.stderr"
        echo "$?" > "$FF_OUT/_attach.exit"
      else
        echo "geckordp unavailable; skipped Firefox attach capture." >"$FF_OUT/_attach.stderr"
        echo "127" > "$FF_OUT/_attach.exit"
      fi
    ) || true
  fi


  # Probes (if provided)
  if [[ "${USE_PROBES_STDIN:-0}" -eq 1 ]]; then
    run_probes_stdin "$TMP_WORK"
  fi
fi



# -------- REDACT everything in workspace --------
redact_workspace "$TMP_WORK"

# -------- Bundle + checksum --------
pack_bundle "$TMP_WORK" "${NAME}"

# -------- Append ledger entry (EDTB-style) --------
append_ledger_entry
