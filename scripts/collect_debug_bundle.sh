#!/usr/bin/env bash
# NMS-Inventory: Collect a reproducible debug bundle (ledger append to .nmsinventory.scope.txt)
# Usage (required): --name <bundle_name> --from .nmsinventory-files.txt
# Optional flags  : --no-defaults --no-logs --decode-logs --no-network --probes-stdin --capture-sec N
# Ledger file     : .nmsinventory.scope.txt (append-only; EDTB-style)
# URL is pinned to http://localhost:8080/*

set -Eeuo pipefail
shopt -s dotglob nullglob extglob globstar

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

BIG_CHUNKS=0
CHUNK_LINES_DEFAULT=300000
CHUNK_CHARS_DEFAULT=500000
CHUNK_LINES_BIG=750000
CHUNK_CHARS_BIG=900000
CHUNK_BYTES_DEFAULT=$((10*1024*1024))  # 10 MB default
CHUNK_BYTES=$CHUNK_BYTES_DEFAULT
PREFER_LINES=0

JSON_FAST_MIN_BYTES=$((4*1024*1024))  # trigger fast path for .json ≥ 4 MiB
JSON_FAST_MAX_BYTES="10m"              # per-output cap for split -C (line-preserving)



MISSING_FILES=()

# -------- Helpers --------

# ---- Code/numbering helpers ----
is_code_path() {
  # Return 0 (true) if the path should be line-numbered, else 1.
  # NOTE: meta/structure.txt (and any */structure.txt) must remain UN-numbered.
  local p="$1"
  case "$p" in
    meta/structure.txt|*/structure.txt) return 1;;
    *.php|*.phpt|*.phtml|*.inc|*.php8|*.php7|*.js|*.mjs|*.cjs|*.jsx|*.ts|*.tsx|\
    *.css|*.scss|*.sass|*.less|\
    *.sh|*.bash|*.zsh|*.ksh|\
    *.py|*.rb|*.pl|*.go|*.rs|*.java|*.kt|*.swift|*.c|*.h|*.hpp|*.cpp|*.cc|*.m|*.mm|\
    *.sql|*.ini|*.conf|*.cfg|*.toml|*.yaml|*.yml|*.json|*.xml|*.html|*.htm|\
    *.md|*.rst|*.adoc|*.csv|*.tsv|\
    Dockerfile|Makefile|makefile|*.service|*.timer|*.socket|*.env|*.env.*|.*rc) return 0;;
    *) return 1;;
  esac
}

emit_stream_for_pack() {
  # Reads file content on stdin and writes either raw or line-numbered output to stdout.
  # Format: zero-padded width 6 + TAB + original line (blank lines are numbered too).
  local rel="$1"
  if is_code_path "$rel"; then
    nl -ba -w6 -s $'\t'
  else
    cat
  fi
}

# ---- Chunked writers (split single files across parts by line/char/byte caps) ----

_write_text_chunked() {
  # $1=rel $2=abs $3=sha $4=size
  local rel="$1" abs="$2" sha="$3" size="$4"
  local first=1 seg=1
  local hdr_lines hdr_chars need_bytes line_len b4_bytes

  open_seg() {

    # finalize part if writing header would breach byte cap
    hdr_lines=8
    hdr_chars=$(( 64 + ${#rel} + ${#sha} + 3 + ${#size} )) # rough header chars
    b4_bytes=0
    [[ -f "$pack_file" ]] && b4_bytes=$(wc -c < "$pack_file" | tr -d ' ')
    if (( b4_bytes > 0 && b4_bytes + hdr_chars > CHUNK_BYTES )); then
      local psha
      psha="$(sha256sum "$pack_file" | awk '{print $1}')"
      echo "$(basename "$pack_file")  $psha" >> "$sha_file"
      pack_idx=$((pack_idx+1))
      _new_pack
    fi
    {
      if (( first )); then
        echo "===== BEGIN FILE: $rel ====="
      else
        echo "===== BEGIN FILE: $rel (CONT $seg) ====="
      fi
      echo "SHA256: $sha"
      echo "SIZE:   $size"
      echo "ENCODING: raw"
      echo
    } >> "$pack_file"
    PACK_LINES=$((PACK_LINES + hdr_lines))
    PACK_CHARS=$((PACK_CHARS + hdr_chars))
  }

  close_seg() {
    {
      echo
      echo "===== END FILE: $rel ====="
      echo
    } >> "$pack_file"
    PACK_LINES=$((PACK_LINES + 3))
    PACK_CHARS=$((PACK_CHARS + 3)) # minimal count for markers/newlines
  }

  open_seg
  # IMPORTANT: process substitution keeps while in current shell (no subshell), so counters persist.
  while IFS= read -r line; do
    line_len=$(( ${#line} + 1 ))   # include newline
    # roll if line would breach any cap (line/char/byte)
    if (( PACK_LINES + 1 > CHUNK_LINES || PACK_CHARS + line_len > CHUNK_CHARS )); then
      close_seg
      local psha
      psha="$(sha256sum "$pack_file" | awk '{print $1}')"
      echo "$(basename "$pack_file")  $psha" >> "$sha_file"
      pack_idx=$((pack_idx+1))
      _new_pack
      first=0; seg=$((seg+1))
      open_seg
    else
      # also guard byte cap
      need_bytes=$line_len
      b4_bytes=0
      [[ -f "$pack_file" ]] && b4_bytes=$(wc -c < "$pack_file" | tr -d ' ')
      if (( b4_bytes + need_bytes > CHUNK_BYTES )); then
        close_seg
        local psha
        psha="$(sha256sum "$pack_file" | awk '{print $1}')"
        echo "$(basename "$pack_file")  $psha" >> "$sha_file"
        pack_idx=$((pack_idx+1))
        _new_pack
        first=0; seg=$((seg+1))
        open_seg
      fi
    fi
    printf '%s\n' "$line" >> "$pack_file"
    PACK_LINES=$((PACK_LINES + 1))
    PACK_CHARS=$((PACK_CHARS + line_len))
  done < <(emit_stream_for_pack "$rel" < "$abs")

  close_seg
}

_write_b64_chunked() {
  # $1=rel $2=abs $3=sha $4=size
  local rel="$1" abs="$2" sha="$3" size="$4"
  local first=1 seg=1
  local hdr_lines hdr_chars chunk_len rest len b4_bytes
  # We'll write base64 in fixed-size slices that respect both char and byte caps.

  open_seg() {

    hdr_lines=8
    hdr_chars=$(( 64 + ${#rel} + ${#sha} + 6 + ${#size} ))
    b4_bytes=0
    [[ -f "$pack_file" ]] && b4_bytes=$(wc -c < "$pack_file" | tr -d ' ')
    if (( b4_bytes > 0 && b4_bytes + hdr_chars > CHUNK_BYTES )); then
      local psha
      psha="$(sha256sum "$pack_file" | awk '{print $1}')"
      echo "$(basename "$pack_file")  $psha" >> "$sha_file"
      pack_idx=$((pack_idx+1))
      _new_pack
    fi
    {
      if (( first )); then
        echo "===== BEGIN FILE: $rel ====="
      else
        echo "===== BEGIN FILE: $rel (CONT $seg) ====="
      fi
      echo "SHA256: $sha"
      echo "SIZE:   $size"
      echo "ENCODING: base64"
      echo
    } >> "$pack_file"
    PACK_LINES=$((PACK_LINES + hdr_lines))
    PACK_CHARS=$((PACK_CHARS + hdr_chars))
  }

  close_seg() {

    {
      echo
      echo "===== END FILE: $rel ====="
      echo
    } >> "$pack_file"
    PACK_LINES=$((PACK_LINES + 3))
    PACK_CHARS=$((PACK_CHARS + 3))
  }

  # Max safe chars we can write before tripping caps in this segment
  local max_seg_chars
  # leave some breathing room for END/footer
  local reserve=256

  open_seg
  # single-line base64
  local b64
  b64="$(base64 -w 0 < "$abs")"
  len=${#b64}
  local pos=0

  while (( pos < len )); do
    # recompute segment allowance each loop
    max_seg_chars=$(( CHUNK_CHARS - PACK_CHARS - reserve ))
    if (( max_seg_chars <= 0 )); then
      close_seg
      local psha
      psha="$(sha256sum "$pack_file" | awk '{print $1}')"
      echo "$(basename "$pack_file")  $psha" >> "$sha_file"
      pack_idx=$((pack_idx+1))
      _new_pack
      first=0; seg=$((seg+1))
      open_seg
      max_seg_chars=$(( CHUNK_CHARS - PACK_CHARS - reserve ))
    fi

    chunk_len=$(( len - pos ))
    if (( chunk_len > max_seg_chars )); then
      chunk_len=$max_seg_chars
    fi
    # byte cap guard
    b4_bytes=0
    [[ -f "$pack_file" ]] && b4_bytes=$(wc -c < "$pack_file" | tr -d ' ')
    if (( b4_bytes + chunk_len > CHUNK_BYTES )); then
      close_seg
      local psha
      psha="$(sha256sum "$pack_file" | awk '{print $1}')"
      echo "$(basename "$pack_file")  $psha" >> "$sha_file"
      pack_idx=$((pack_idx+1))
      _new_pack
      first=0; seg=$((seg+1))
      open_seg
    fi

    printf '%s\n' "${b64:pos:chunk_len}" >> "$pack_file"
    PACK_LINES=$((PACK_LINES + 1))
    PACK_CHARS=$((PACK_CHARS + chunk_len + 1))
    pos=$((pos + chunk_len))
  done

  close_seg
}


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
  --no-defaults    Skip default includes (env mask, structure, lightweight outputs, migrations).
  --no-logs        Skip logs capture (skips logs/DEV selection).
  --decode-logs    Include decoder/import logs from .cache/** and decoded debug blobs.
  --no-network     Skip browser/probes capture.
  --probes-stdin   Read curl probes from stdin (here-doc after the command).
  --capture-sec N  If FF attach runs: capture for N seconds; else: wait N seconds before logs/network (default 15).
  --big-chunks     Raise per-part caps to 750k lines / 900k chars (default 300k/500k).
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
      # Build a header-only variant that works whether the probe used -s or -sS (or neither).
      header_line="$line"
      # Prefer converting "-sS" → "-sSI"; otherwise try "-s" → "-sI"; finally append "-I" if absent.
      if [[ "$header_line" == *" -sS "* ]]; then
        header_line="${header_line/ -sS / -sSI }"
      elif [[ "$header_line" == *" -s "* ]]; then
        header_line="${header_line/ -s / -sI }"
      fi
      if [[ "$header_line" != *" -I"* && "$header_line" != *"-I "* && "$header_line" != *" -D "* ]]; then
        header_line="$header_line -I"
      fi
      bash -lc "$header_line" >"$outdir/probes/${i}.headers" 2>>"$outdir/probes/${i}.stderr" || true
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

# New: collect top-level logs/* by 2-minute window (directory name timestamp)
collect_project_logs_windowed() {
  local outroot="$1"
  local base="logs"
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
  # Write a plain-text assistant pack instead of a tarball.
  # Layout: bundles/<NAME>/ap/{<NAME>.part-001.txt, <NAME>.part-002.txt, ...,
  #          <NAME>.index.txt, <NAME>.sha256}
  BUNDLE_DIR="${BUNDLES_ROOT}/${NAME}"
  PACK_DIR="${BUNDLE_DIR}/ap"
  mkdir -p "$PACK_DIR"

  echo "[*] Creating assistant pack: ${NAME}/ap ($((CHUNK_BYTES/1024/1024))MB chunks)"
  # Ensure the staged workspace is fully redacted before packaging
  final_redact_pass "$TMP_WORK"
  if [[ "${DO_NETWORK:-1}" -eq 1 ]]; then
    [[ -d "$TMP_WORK/network" ]] || emit_network_scaffold "$TMP_WORK"
  fi

    local CHUNK_BYTES=$((50*1024*1024)) # 10 MB per pack file
  local CHUNK_LINES CHUNK_CHARS
  if [[ "${BIG_CHUNKS:-0}" -eq 1 ]]; then
    CHUNK_LINES=750000
    CHUNK_CHARS=900000
    # If caller prefers line target, set an effectively "infinite" char cap
    if [[ "${PREFER_LINES:-0}" -eq 1 ]]; then
      CHUNK_CHARS=1000000000
    fi
    echo "[*] Creating assistant pack: ${NAME}/ap ($((CHUNK_BYTES/1024/1024))MB chunks)"
  else
    CHUNK_LINES=300000
    CHUNK_CHARS=500000
  fi

  local TOTAL_LINES=0
  local TOTAL_CHARS=0
  local PACK_LINES=0
  local PACK_CHARS=0

  local pack_idx=1
  local pack_file
  local index_file="$PACK_DIR/${NAME}.index.txt"
  local sha_file="$PACK_DIR/${NAME}.sha256"
  : > "$index_file"
  : > "$sha_file"


  _new_pack() {
    pack_file=$(printf "%s/%s.part-%03d.txt" "$PACK_DIR" "${NAME}" "$pack_idx")
    : > "$pack_file"
    PACK_LINES=0
    PACK_CHARS=0
  }


  _ensure_room_for() {
    # $1 = approx bytes to append; roll to next pack if current pack would exceed CHUNK_BYTES
    local need="${1:-0}"
    local cur=0
    if [[ -f "$pack_file" ]]; then
      cur=$(wc -c < "$pack_file" | tr -d ' ')
    fi
    if (( cur > 0 && cur + need > CHUNK_BYTES )); then
      # finalize current pack (sha)
      local psha
      psha="$(sha256sum "$pack_file" | awk '{print $1}')"
      echo "$(basename "$pack_file")  $psha" >> "$sha_file"
      pack_idx=$((pack_idx+1))
      _new_pack
    fi
  }

  _ensure_room_for_text() {
    # $1 = needed_lines (text only), $2 = needed_chars (text only), $3 = approx_bytes (header+body)
    local need_lines="${1:-0}"
    local need_chars="${2:-0}"
    local need_bytes="${3:-0}"
    local cur_bytes=0
    if [[ -f "$pack_file" ]]; then
      cur_bytes=$(wc -c < "$pack_file" | tr -d ' ')
    fi
    if (( (PACK_LINES > 0 && PACK_LINES + need_lines > CHUNK_LINES) \
       || (PACK_CHARS > 0 && PACK_CHARS + need_chars > CHUNK_CHARS) \
       || (cur_bytes > 0 && cur_bytes + need_bytes > CHUNK_BYTES) )); then
      # finalize current pack (sha) and start a new one
      local psha
      psha="$(sha256sum "$pack_file" | awk '{print $1}')"
      echo "$(basename "$pack_file")  $psha" >> "$sha_file"
      pack_idx=$((pack_idx+1))
      _new_pack
    fi
  }


  _new_pack

    {
    echo "name: ${NAME}"
    echo "generated_utc: ${NOW_UTC}"
    echo "chunk_limit_bytes: ${CHUNK_BYTES}"
    echo "chunk_limit_lines: __CHUNK_LINES__"
    echo "chunk_limit_chars: __CHUNK_CHARS__"
    echo "total_parts: __TOTAL_PARTS__"
    echo "total_lines: __TOTAL_LINES__"
    echo "total_chars: __TOTAL_CHARS__"
    echo "root: ${BUNDLES_ROOT}/${NAME}/ap"
    echo
    echo "files:"
  } >> "$index_file"


  # Iterate every staged file (what would have gone into the tar)
  while IFS= read -r -d '' rel; do
    rel="${rel#./}"
    abs="$TMP_WORK/$rel"
    size="$(wc -c < "$abs" | tr -d ' ')"
    sha="$(sha256sum "$abs" | awk '{print $1}')"

        # ---- FAST PATH for huge JSON (≥ 4 MiB): one-pass, line-preserving byte split to ~10 MB parts
    if [[ "${rel,,}" == *.json && "$size" -ge "$JSON_FAST_MIN_BYTES" ]]; then
      base="$(basename "$rel")"
      prefix="$PACK_DIR/${base}.part-"

      # Stream once: number lines (6-digit + TAB), then split by ~10 MB while preserving whole lines
      LC_ALL=C nl -ba -w6 -s $'\t' "$abs" \
        | split -d -a 4 -C "$JSON_FAST_MAX_BYTES" - --additional-suffix=.txt "$prefix"

      # For each produced part: record sha, per-part counts, index rows, and accumulate totals
      shopt -s nullglob
      for pf in "${prefix}"*.txt; do
        psha="$(sha256sum "$pf" | awk '{print $1}')"
        echo "$(basename "$pf")  $psha" >> "$sha_file"

        plines="$(wc -l < "$pf" | tr -d ' ')"
        pchars="$(wc -c < "$pf" | tr -d ' ')"

        TOTAL_LINES=$((TOTAL_LINES + plines))
        TOTAL_CHARS=$((TOTAL_CHARS + pchars))

        printf "  - path: %s (fast-split)\n    size: %s\n    sha256: %s\n    encoding: raw\n    lines: %s\n    chars: %s\n    pack: %s\n" \
          "$rel" "$size" "$psha" "$plines" "$pchars" "$(basename "$pf")" >> "$index_file"
      done
      shopt -u nullglob

      # Skip normal packer for this file
      continue
    fi


    if is_text_file "$abs"; then
            encoding="raw"
      # Counts after numbering (exactly what will be written)
      # Faster counts without re-numbering: raw counts + 7 bytes/line for "000000<TAB>"
      lc="$(wc -l < "$abs" | tr -d ' ')"
      cc_raw="$(wc -c < "$abs" | tr -d ' ')"
      cc=$(( cc_raw + lc * 7 ))

      approx=$(( cc + 256 ))  # header/footer overhead
      # compute additions for counters/index (text case)
      f_lines="$lc"
      f_chars="$cc"
      hdr_lines=8
      hdr_chars=$(( 64 + ${#rel} + ${#sha} + ${#encoding} + ${#size} ))
      add_lines=$(( f_lines + hdr_lines ))
      add_chars=$(( f_chars + hdr_chars ))

      # Ensure current part won’t exceed caps (lines, chars, bytes)
      _ensure_room_for_text "$lc" "$cc" "$approx"
      _ensure_room_for "$approx"

      _write_text_chunked "$rel" "$abs" "$sha" "$size"
      TOTAL_LINES=$((TOTAL_LINES + lc))
      TOTAL_CHARS=$((TOTAL_CHARS + cc))


    else
      encoding="base64"
      # compute exact base64 length and line/char additions before writing
      f_lines=1
      f_chars=$(base64 -w 0 < "$abs" | wc -c | tr -d ' ')
      hdr_lines=8
      hdr_chars=$(( 64 + ${#rel} + ${#sha} + ${#encoding} + ${#size} ))
      add_lines=$(( f_lines + hdr_lines ))
      add_chars=$(( f_chars + hdr_chars ))
      approx=$(( f_chars + 256 ))  # header/footer overhead
      _ensure_room_for_text "$f_lines" "$f_chars" "$approx"
      _ensure_room_for "$approx"

      _write_b64_chunked "$rel" "$abs" "$sha" "$size"
      TOTAL_LINES=$((TOTAL_LINES + f_lines))
      TOTAL_CHARS=$((TOTAL_CHARS + f_chars))


    fi


    # index entry
    printf "  - path: %s\n    size: %s\n    sha256: %s\n    encoding: %s\n    lines: %s\n    chars: %s\n    pack: %s\n" \
      "$rel" "$size" "$sha" "$encoding" "$f_lines" "$f_chars" "$(basename "$pack_file")" >> "$index_file"


  done < <(cd "$TMP_WORK" && find . -type f ! -path "./.tools/*" -print0)


  # finalize last pack sha
  if [[ -f "$pack_file" ]]; then
    psha="$(sha256sum "$pack_file" | awk '{print $1}')"
    echo "$(basename "$pack_file")  $psha" >> "$sha_file"
  fi

    # Compute totals into the index header placeholders
  local TOTAL_PARTS
    TOTAL_PARTS="$(ls -1 "$PACK_DIR"/*'.part-'*.txt 2>/dev/null | wc -l | tr -d ' ')"

  sed -i \
    -e "s/__CHUNK_LINES__/${CHUNK_LINES}/" \
    -e "s/__CHUNK_CHARS__/${CHUNK_CHARS}/" \
    -e "s/__TOTAL_PARTS__/${TOTAL_PARTS}/" \
    -e "s/__TOTAL_LINES__/${TOTAL_LINES}/" \
    -e "s/__TOTAL_CHARS__/${TOTAL_CHARS}/" \
    "$index_file"

  # Compute checksum of the index file for the ledger entry
  BUNDLE_SHA="$(sha256sum "$index_file" | awk '{print $1}')"
  ABS_INDEX="$(cd "$(dirname "$index_file")" && pwd)/$(basename "$index_file")"

  echo "Assistant pack created: $ABS_INDEX"
  echo "Index SHA256: $BUNDLE_SHA"
  echo "Upload the ap/${NAME}.part-*.txt files here."
}


append_ledger_entry() {
  local bundle_file="$BUNDLES_ROOT/${NAME}/ap/${NAME}.index.txt"
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
    echo "bundle: ${NAME}"
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
    --big-chunks) BIG_CHUNKS=1; shift;;
    --prefer-lines) PREFER_LINES=1; shift;;
    -h|--help) usage; exit 0;;

    *) die "Unknown arg: $1";;
  esac
done



[[ -n "$NAME" ]] || { usage; die "--name is required"; }
[[ -n "$FROM_MANIFEST" ]] || { usage; die "--from is required (use .nmsinventory-files.txt)"; }
[[ "$FROM_MANIFEST" == ".nmsinventory-files.txt" ]] || echo "[WARN] --from should be .nmsinventory-files.txt (continuing)"

# -------- Work area --------
TMP_WORK="$(mktemp -d -p "${TMPDIR:-/tmp}" "nms_bundle_${NAME}_XXXX")"
mkdir -p "$TMP_WORK"/{meta,sys,defaults,db,probes,public_data}

# -------- Metadata / Health / Git --------
git_info "$TMP_WORK/meta/git_info.txt"
health_info "$TMP_WORK/meta/health.txt"

# -------- Structure snapshot --------
if command -v tree >/dev/null 2>&1; then
  command tree -a -n -I ".git|node_modules|vendor|.idea|__pycache__|cache|logs|.edtb-venv" -o structure.txt .
  cp -a "structure.txt" "$TMP_WORK/meta/structure.txt"
else
  : > "$TMP_WORK/meta/structure.txt"
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
    output/reports output/scan output/deepdebug output/*.csv \
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
    # trim leading/trailing whitespace and any Windows CR (avoid glob mismatches)
    rel="${rel#"${rel%%[![:space:]]*}"}"   # ltrim
    rel="${rel%"${rel##*[![:space:]]}"}"   # rtrim
    rel="${rel//$'\r'/}"                   # strip CR

    # --no-logs affects only top-level logs/* manifest entries
    case "$rel" in
      ./logs/*|logs/*)
        if [[ "$DO_LOGS" -eq 0 ]]; then
          echo "[INFO] skipping per --no-logs: $rel"
          continue
        fi
        ;;
    esac


    # If the manifest entry contains glob characters, expand it.
    if [[ "$rel" == *[\*\?\[]* ]]; then
      mapfile -t _matches < <(compgen -G -- "$rel" || true)

      # Fallback: if the pattern ends with ".log", also allow compressed suffixes (e.g., ".log.gz")
      if (( ${#_matches[@]} == 0 )) && [[ "$rel" == *.log ]]; then
        mapfile -t _matches < <(compgen -G -- "${rel}*" || true)
      fi

      if (( ${#_matches[@]} == 0 )); then
        echo "[WARN] listed pattern had no matches: $rel"
        MISSING_FILES+=("$rel")
        continue
      fi

      for m in "${_matches[@]}"; do
        copy_rel "$m" "$TMP_WORK"
      done
      continue
    fi

    # Non-glob path
    if [[ -e "$rel" ]]; then
      copy_rel "$rel" "$TMP_WORK"
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


# --no-logs applies only to top-level logs/* and networking (manifest items elsewhere unaffected)
if [[ "$DO_LOGS" -eq 1 ]]; then
  # Include timestamped top-level logs/* by 2-minute window (dir name-based)
  collect_project_logs_windowed "$TMP_WORK/sys"

  # Include DEV logs by 2-minute window
  collect_dev_logs_windowed "$TMP_WORK/sys"

  # Decoder/import logs only when explicitly requested
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
    run_probes_stdin "$TMP_WORK/network"
  fi

fi



# -------- REDACT everything in workspace --------
redact_workspace "$TMP_WORK"

# -------- Bundle + checksum --------
pack_bundle "$TMP_WORK" "${NAME}"

# -------- Append ledger entry (EDTB-style) --------
append_ledger_entry
