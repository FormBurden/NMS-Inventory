#!/usr/bin/env python3
# Attach to a running Firefox via DevTools RDP (no new window),
# then capture Console, Network, and a DOM HTML snapshot for ~N seconds.
# Requires: pip install --user geckordp   (Python >= 3.10)
#
# Env knobs:
#   FF_RDP_HOST (default 127.0.0.1)
#   FF_RDP_PORT (default 6000)
#   EDTB_CAPTURE_URL_PREFIX (default http://localhost:8080)
#   FF_CAPTURE_WINDOW_SEC (default 120)

import os, sys, json, time, threading
from datetime import datetime, timezone

from geckordp.rdp_client import RDPClient
from geckordp.actors.root import RootActor
from geckordp.actors.descriptors.tab import TabActor
from geckordp.actors.web_console import WebConsoleActor
from geckordp.actors.watcher import WatcherActor
from geckordp.actors.resources import Resources
from geckordp.actors.events import Events

OUTDIR = sys.argv[1] if len(sys.argv) > 1 else "browser"
os.makedirs(OUTDIR, exist_ok=True)
console_path = os.path.join(OUTDIR, "console.ndjson")
network_path = os.path.join(OUTDIR, "network.ndjson")
dom_path     = os.path.join(OUTDIR, "dom.html")
perf_path    = os.path.join(OUTDIR, "perf.json")

HOST = os.environ.get("FF_RDP_HOST", "127.0.0.1")
PORT = int(os.environ.get("FF_RDP_PORT", "6000"))
URLP = os.environ.get("EDTB_CAPTURE_URL_PREFIX", "http://localhost:8080")
WIN  = int(os.environ.get("FF_CAPTURE_WINDOW_SEC", "15"))

def now_iso():
    return datetime.now(timezone.utc).isoformat()

client = RDPClient()
resp = client.connect(HOST, PORT)
if resp is None:
    print(f"[capture_ff_attach] No Firefox debug server at {HOST}:{PORT}", file=sys.stderr)
    sys.exit(2)

root = RootActor(client)
tabs = root.list_tabs()

tab_desc = next((t for t in tabs if t.get("url","").startswith(URLP)), None)
if tab_desc is None:
    selected_idx = root.get_root().get("selected", 0)
    tab_desc = tabs[selected_idx]

tab = TabActor(client, tab_desc["actor"])
target = tab.get_target()
console_actor_id = target["consoleActor"]
watcher_ctx = tab.get_watcher()
watcher_actor_id = watcher_ctx["actor"]

console = WebConsoleActor(client, console_actor_id)

try:
    cached = console.get_cached_messages([WebConsoleActor.MessageTypes.CONSOLE_API, WebConsoleActor.MessageTypes.PAGE_ERROR]) or {}
    with open(console_path, "a", encoding="utf-8") as f:
        for key in ("consoleMessages", "pageErrors", "messages"):
            for m in cached.get(key, []):
                m["_cached"] = True
                m["_t"] = now_iso()
                f.write(json.dumps(m, ensure_ascii=False) + "\n")
except Exception:
    pass

console.start_listeners([WebConsoleActor.Listeners.CONSOLE_API, WebConsoleActor.Listeners.PAGE_ERROR])

def write_ndjson(path, obj):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")

def on_console_event(data: dict):
    data = dict(data)
    data["_t"] = now_iso()
    write_ndjson(console_path, data)

client.add_event_listener(console_actor_id, Events.WebConsole.CONSOLE_API_CALL, on_console_event)
client.add_event_listener(console_actor_id, Events.WebConsole.PAGE_ERROR, on_console_event)
client.add_event_listener(console_actor_id, Events.WebConsole.LOG_MESSAGE, on_console_event)

watcher = WatcherActor(client, watcher_actor_id)
watcher.watch_resources([
    Resources.NETWORK_EVENT,
    Resources.NETWORK_EVENT_STACKTRACE,
])

def on_net_available(data: dict):
    obj = dict(data)
    obj["_t"] = now_iso()
    write_ndjson(network_path, obj)

client.add_event_listener(watcher.actor_id, Events.Watcher.RESOURCES_AVAILABLE_ARRAY, on_net_available)

def _fetch_longstring(actor_id: str, length: int, chunk: int = 65536) -> str:
    parts = []
    pos = 0
    while pos < length:
        end = pos + min(chunk, length - pos)
        res = client.send_receive({
            "to": actor_id,
            "type": "substring",
            "start": pos,
            "end": end
        }) or {}
        parts.append(res.get("substring", ""))
        pos = end
    try:
        client.send_receive({"to": actor_id, "type": "release"})
    except Exception:
        pass
    return "".join(parts)

def _eval_js_to_string(expr: str, timeout_sec: float = 5.0) -> str:
    done = threading.Event()
    state = {"type": "", "actor": "", "length": 0, "text": ""}

    def _on_eval(payload):
        if isinstance(payload, str):
            state["text"] = payload
            done.set()
            return
        if not isinstance(payload, dict):
            done.set()
            return

        res = payload.get("result")
        if isinstance(res, str):
            state["text"] = res
            done.set()
            return

        grip = res.get("result") if isinstance(res, dict) and isinstance(res.get("result"), dict) else res
        if not isinstance(grip, dict):
            state["text"] = ""
            done.set()
            return

        gtype = grip.get("type")
        if gtype == "longString" and "actor" in grip:
            state["type"] = "longString"
            state["actor"] = grip["actor"]
            state["length"] = int(grip.get("length", 0))
        elif gtype == "string":
            state["text"] = grip.get("value") or ""
        else:
            state["text"] = grip.get("text") or grip.get("value") or ""
        done.set()

    client.add_event_listener(console_actor_id, Events.WebConsole.EVALUATION_RESULT, _on_eval)
    console.evaluate_js_async(expr)
    done.wait(timeout_sec)
    client.remove_event_listener(console_actor_id, Events.WebConsole.EVALUATION_RESULT, _on_eval)

    if state["type"] == "longString" and state["actor"]:
        return _fetch_longstring(state["actor"], state["length"])
    return state["text"]

dom_html_text = _eval_js_to_string("(() => document.documentElement.outerHTML)();")
with open(dom_path, "w", encoding="utf-8") as f:
    f.write(dom_html_text if isinstance(dom_html_text, str) else "")

perf_json_text = _eval_js_to_string(f"""
(() => {{
  const now = performance.now();
  const win = {WIN} * 1000;
  const norm = (e) => ({{
    name: e.name,
    initiatorType: e.initiatorType,
    startTime: e.startTime,
    duration: e.duration,
    transferSize: e.transferSize,
    encodedBodySize: e.encodedBodySize,
    decodedBodySize: e.decodedBodySize,
    nextHopProtocol: e.nextHopProtocol
  }});
  const obj = {{
    navigation: performance.getEntriesByType('navigation').map(norm),
    resources: performance.getEntriesByType('resource')
      .filter(e => (now - e.startTime) <= win)
      .map(norm),
  }};
  return JSON.stringify(obj);
}})();
""", timeout_sec=8.0)

try:
    perf_val = json.loads(perf_json_text) if perf_json_text else {}
except Exception:
    perf_val = {}

with open(perf_path, "w", encoding="utf-8") as f:
  json.dump(perf_val if isinstance(perf_val, dict) else {}, f, ensure_ascii=False, indent=2)

end_at = time.time() + WIN
while time.time() < end_at:
    time.sleep(0.2)

try:
    console.stop_listeners([WebConsoleActor.Listeners.CONSOLE_API, WebConsoleActor.Listeners.PAGE_ERROR])
except Exception:
    pass
try:
    watcher.unwatch_resources([Resources.NETWORK_EVENT, Resources.NETWORK_EVENT_STACKTRACE])
except Exception:
    pass

client.disconnect()
