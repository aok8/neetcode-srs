"""Local HTTP server powering the --ui browser interface."""
from __future__ import annotations

import json
import threading
import webbrowser
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from neetcode_srs import db, selector
from neetcode_srs.srs import schedule

# ── embedded single-page app ──────────────────────────────────────────────

_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NeetCode SRS</title>
<style>
:root {
  --bg: #f6f5f2; --surface: #ffffff; --raised: #f0eee9;
  --border: #e2dfd8; --text: #1a1918; --muted: #8c8882;
  --accent: #5b5bd6;
  --easy: #15803d; --easy-bg: rgba(21,128,61,.1);
  --medium: #b45309; --medium-bg: rgba(180,83,9,.1);
  --hard: #b91c1c; --hard-bg: rgba(185,28,28,.1);
  --shadow: 0 1px 2px rgba(0,0,0,.05), 0 4px 14px rgba(0,0,0,.04);
  --r: 12px;
}
@media (prefers-color-scheme: dark) { :root {
  --bg: #0d0c0c; --surface: #161514; --raised: #1c1b1a;
  --border: #242220; --text: #e8e6e2; --muted: #655f5a;
  --shadow: 0 1px 2px rgba(0,0,0,.4), 0 4px 14px rgba(0,0,0,.25);
}}
:root[data-theme=light] {
  --bg:#f6f5f2;--surface:#ffffff;--raised:#f0eee9;--border:#e2dfd8;
  --text:#1a1918;--muted:#8c8882;
  --shadow:0 1px 2px rgba(0,0,0,.05),0 4px 14px rgba(0,0,0,.04);
}
:root[data-theme=dark] {
  --bg:#0d0c0c;--surface:#161514;--raised:#1c1b1a;--border:#242220;
  --text:#e8e6e2;--muted:#655f5a;
  --shadow:0 1px 2px rgba(0,0,0,.4),0 4px 14px rgba(0,0,0,.25);
}
*,*::before,*::after { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
  background: var(--bg); color: var(--text);
  min-height: 100vh; display: flex; flex-direction: column; align-items: center;
}

/* ── header ── */
header {
  width: 100%; padding: 11px 18px;
  display: flex; align-items: center; gap: 12px;
  border-bottom: 1px solid var(--border);
  background: var(--surface);
  position: sticky; top: 0; z-index: 10;
}
#seen-count {
  font-size: 12px; color: var(--muted);
  white-space: nowrap; min-width: 90px;
  font-variant-numeric: tabular-nums;
}
#prog-track {
  flex: 1; height: 3px; background: var(--border);
  border-radius: 2px; overflow: hidden;
}
#prog-fill {
  height: 100%; background: var(--accent); width: 0%;
  transition: width .5s cubic-bezier(.4,0,.2,1);
}
#hdr-right { display: flex; align-items: center; gap: 7px; }
.pill {
  font-size: 11px; font-weight: 600; letter-spacing: .03em;
  padding: 2px 8px; border-radius: 20px;
  border: 1px solid var(--border); color: var(--muted); background: var(--raised);
}
.pill.on {
  background: rgba(91,91,214,.1);
  border-color: rgba(91,91,214,.3); color: var(--accent);
}
#today-count {
  font-size: 12px; color: var(--muted);
  white-space: nowrap; font-variant-numeric: tabular-nums;
}

/* ── main layout ── */
main {
  flex: 1; width: 100%; max-width: 576px;
  padding: 28px 18px 40px;
  display: flex; flex-direction: column; gap: 12px;
  justify-content: center;
}

/* ── card ── */
#card {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: var(--r); padding: 26px 24px;
  box-shadow: var(--shadow);
  transition: opacity .14s ease, transform .14s ease;
}
#card.out { opacity: 0; transform: translateY(6px); }
#card-kind {
  font-size: 11px; font-weight: 700; letter-spacing: .1em;
  text-transform: uppercase; color: var(--muted); margin-bottom: 12px;
}
#card-kind.review { color: var(--accent); }
#card-title {
  font-size: 21px; font-weight: 700; line-height: 1.3;
  text-wrap: balance; margin-bottom: 12px;
}
#card-meta {
  display: flex; align-items: center; gap: 9px;
  flex-wrap: wrap; margin-bottom: 16px;
}
.badge {
  font-size: 12px; font-weight: 600;
  padding: 3px 10px; border-radius: 20px; flex-shrink: 0;
}
.Easy   { color: var(--easy);   background: var(--easy-bg); }
.Medium { color: var(--medium); background: var(--medium-bg); }
.Hard   { color: var(--hard);   background: var(--hard-bg); }
#card-topics { font-size: 13px; color: var(--muted); }
#lc-link {
  display: inline-flex; align-items: center; gap: 5px;
  font-size: 13px; font-weight: 500; color: var(--accent);
  text-decoration: none; padding: 6px 12px; border-radius: 8px;
  border: 1px solid rgba(91,91,214,.22);
  background: rgba(91,91,214,.06);
  transition: background .12s, border-color .12s;
  width: fit-content;
}
#lc-link:hover { background: rgba(91,91,214,.13); border-color: rgba(91,91,214,.38); }
#lc-link:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
#srs-row {
  display: none; margin-top: 14px; padding-top: 14px;
  border-top: 1px solid var(--border); gap: 18px;
}
#srs-row.show { display: flex; }
.srs-item { display: flex; flex-direction: column; gap: 2px; }
.srs-label {
  font-size: 10px; font-weight: 700; letter-spacing: .09em;
  text-transform: uppercase; color: var(--muted);
}
.srs-val {
  font-size: 14px; font-weight: 700;
  font-variant-numeric: tabular-nums;
}
#src-note { margin-top: 10px; font-size: 11px; color: var(--muted); }

/* ── action buttons ── */
#actions {
  display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px;
}
.btn {
  display: flex; flex-direction: column; align-items: center; gap: 5px;
  padding: 13px 8px 11px;
  border: 1px solid var(--border); border-radius: var(--r);
  background: var(--surface); color: var(--text);
  cursor: pointer; font-family: inherit;
  font-size: 13px; font-weight: 600; line-height: 1;
  transition: background .12s, border-color .12s, transform .1s;
  box-shadow: var(--shadow);
  -webkit-user-select: none; user-select: none;
}
.btn:hover  { transform: translateY(-1px); }
.btn:active { transform: scale(.97); }
.btn:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.btn-icon { font-size: 17px; }
.btn-key {
  font-size: 10px; font-weight: 500; color: var(--muted);
  width: 17px; height: 17px;
  border: 1px solid var(--border); border-radius: 4px;
  display: flex; align-items: center; justify-content: center;
  font-family: 'SF Mono', 'Cascadia Code', 'Fira Code', monospace;
}
.btn-y { border-color: rgba(21,128,61,.22); }
.btn-y:hover { background: rgba(21,128,61,.07); border-color: rgba(21,128,61,.38); }
.btn-n { border-color: rgba(185,28,28,.22); }
.btn-n:hover { background: rgba(185,28,28,.07); border-color: rgba(185,28,28,.38); }
.btn-e { border-color: rgba(91,91,214,.22); }
.btn-e:hover { background: rgba(91,91,214,.07); border-color: rgba(91,91,214,.38); }
.btn-s:hover { background: var(--raised); }

/* ── done / empty state ── */
#done { display: none; }
#done.show {
  display: flex; flex: 1; flex-direction: column;
  align-items: center; justify-content: center;
  text-align: center; padding: 48px 20px; gap: 10px;
  width: 100%; max-width: 576px;
}
#done h2 { font-size: 23px; font-weight: 700; }
#done p {
  font-size: 15px; color: var(--muted);
  line-height: 1.65; max-width: 320px;
}
#done code {
  font-family: 'SF Mono', 'Cascadia Code', 'Fira Code', monospace;
  font-size: 13px; background: var(--surface);
  border: 1px solid var(--border);
  padding: 2px 6px; border-radius: 5px; color: var(--text);
}

/* ── loading spinner ── */
#spinner {
  flex: 1; display: flex; align-items: center;
  justify-content: center; color: var(--muted); font-size: 14px;
}
</style>
</head>
<body>

<header>
  <span id="seen-count">— / — seen</span>
  <div id="prog-track"><div id="prog-fill"></div></div>
  <div id="hdr-right">
    <span class="pill" id="pill-shuffle">shuffle</span>
    <span class="pill" id="pill-extra">extra</span>
    <span id="today-count"></span>
  </div>
</header>

<div id="spinner">Loading…</div>

<main id="main" style="display:none">
  <div id="card">
    <div id="card-kind"></div>
    <div id="card-title"></div>
    <div id="card-meta">
      <span id="card-badge" class="badge"></span>
      <span id="card-topics"></span>
    </div>
    <a id="lc-link" href="#" target="_blank" rel="noopener">
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none"
           stroke="currentColor" stroke-width="2.5"
           stroke-linecap="round" stroke-linejoin="round">
        <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>
        <polyline points="15 3 21 3 21 9"/>
        <line x1="10" y1="14" x2="21" y2="3"/>
      </svg>
      Open on LeetCode
    </a>
    <div id="srs-row">
      <div class="srs-item">
        <span class="srs-label">Streak</span>
        <span class="srs-val" id="srs-streak"></span>
      </div>
      <div class="srs-item">
        <span class="srs-label">Last interval</span>
        <span class="srs-val" id="srs-interval"></span>
      </div>
      <div class="srs-item">
        <span class="srs-label">Ease</span>
        <span class="srs-val" id="srs-ease"></span>
      </div>
    </div>
    <div id="src-note"></div>
  </div>

  <div id="actions">
    <button class="btn btn-y" onclick="act('y')">
      <span class="btn-icon">✓</span>
      Solved
      <span class="btn-key">Y</span>
    </button>
    <button class="btn btn-n" onclick="act('n')">
      <span class="btn-icon">✗</span>
      Couldn’t
      <span class="btn-key">N</span>
    </button>
    <button class="btn btn-e" onclick="act('e')">
      <span class="btn-icon">⚡</span>
      Trivial
      <span class="btn-key">E</span>
    </button>
    <button class="btn btn-s" onclick="act('skip')">
      <span class="btn-icon">→</span>
      Skip
      <span class="btn-key">S</span>
    </button>
  </div>
</main>

<div id="done"></div>

<script>
"use strict";
var cur = null;

function esc(s) {
  return String(s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

async function load() {
  var r = await fetch("/api/state");
  cur = await r.json();
  document.getElementById("spinner").style.display = "none";
  render(cur);
}

async function act(outcome) {
  var card = document.getElementById("card");
  card.classList.add("out");
  await new Promise(function(r) { setTimeout(r, 140); });
  var r = await fetch("/api/answer", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ outcome: outcome })
  });
  cur = await r.json();
  render(cur);
  card.classList.remove("out");
}

function render(s) {
  var pct = s.total > 0 ? (s.seen / s.total * 100).toFixed(1) : "0";
  document.getElementById("prog-fill").style.width = pct + "%";
  document.getElementById("seen-count").textContent =
    s.seen + " / " + s.total + " seen";
  document.getElementById("today-count").textContent =
    s.done_today + " / " + s.daily_target + " today";
  document.getElementById("pill-shuffle").className =
    "pill" + (s.shuffle ? " on" : "");
  document.getElementById("pill-extra").className =
    "pill" + (s.extra ? " on" : "");

  var mainEl = document.getElementById("main");
  var doneEl = document.getElementById("done");

  if (s.kind === "empty") {
    mainEl.style.display = "none";
    doneEl.className = "show";
    doneEl.innerHTML =
      "<h2>All caught up!</h2>" +
      "<p>No unseen cards remain.<br>" +
      "Run <code>neetcode setup</code> to add more problems.</p>";
    return;
  }
  if (s.kind === "quota_hit") {
    mainEl.style.display = "none";
    doneEl.className = "show";
    var pl = s.daily_target !== 1 ? "s" : "";
    doneEl.innerHTML =
      "<h2>Done for today!</h2>" +
      "<p>" + esc(s.done_today) + " / " + esc(s.daily_target) +
      " card" + pl + " reviewed.<br>" +
      "Come back tomorrow, or raise your limit:<br>" +
      "<code>neetcode config daily N</code></p>";
    return;
  }

  mainEl.style.display = "flex";
  doneEl.className = "";

  var c = s.card;
  var kindEl = document.getElementById("card-kind");
  kindEl.textContent = s.kind === "review" ? "Review due" : "New problem";
  kindEl.className = s.kind === "review" ? "review" : "";

  document.getElementById("card-title").textContent = c.title;

  var badge = document.getElementById("card-badge");
  badge.textContent = c.difficulty;
  badge.className = "badge " + c.difficulty;
  document.getElementById("card-topics").textContent = c.topics.join(", ");

  document.getElementById("lc-link").href = c.leetcode_url;

  var srsRow = document.getElementById("srs-row");
  if (s.kind === "review") {
    document.getElementById("srs-streak").textContent = c.reps;
    document.getElementById("srs-interval").textContent = c.interval_days + "d";
    document.getElementById("srs-ease").textContent = c.ease.toFixed(2);
    srsRow.className = "show";
  } else {
    srsRow.className = "";
  }

  document.getElementById("src-note").textContent = s.extra
    ? ("· from " + (c.source === "secondary" ? "secondary list" : "NeetCode 250"))
    : "";
}

document.addEventListener("keydown", function(e) {
  if (!cur || !cur.card) return;
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;
  var map = { y: "y", n: "n", e: "e", s: "skip" };
  if (map[e.key.toLowerCase()]) act(map[e.key.toLowerCase()]);
});

load();
</script>
</body>
</html>
"""

# ── app state (thread-safe) ───────────────────────────────────────────────


def _card_to_dict(card: db.Card) -> dict:
    return {
        "id": card.id,
        "title": card.title,
        "difficulty": card.difficulty,
        "topics": card.topics,
        "leetcode_url": card.leetcode_url,
        "source": card.source,
        "ease": card.ease,
        "interval_days": card.interval_days,
        "reps": card.reps,
    }


class _AppState:
    def __init__(self, db_path: Path, cfg: dict) -> None:
        self._conn = db.connect(db_path, check_same_thread=False)
        self._cfg = cfg
        self._lock = threading.Lock()
        self._pick = selector.pick_today(
            self._conn, date.today(),
            daily_target=cfg["daily_target"],
            shuffle=cfg["shuffle"],
            extra=cfg["extra"],
        )

    def _refresh(self) -> None:
        self._pick = selector.pick_today(
            self._conn, date.today(),
            daily_target=self._cfg["daily_target"],
            shuffle=self._cfg["shuffle"],
            extra=self._cfg["extra"],
        )

    def _snapshot(self) -> dict:
        pick = self._pick
        s = db.stats(self._conn, date.today())
        return {
            "card": _card_to_dict(pick.card) if pick.card else None,
            "kind": pick.kind,
            "done_today": pick.done_today,
            "daily_target": pick.daily_target,
            "total": s["total"],
            "seen": s["total"] - s["new"],
            "shuffle": self._cfg["shuffle"],
            "extra": self._cfg["extra"],
        }

    def get_state(self) -> dict:
        with self._lock:
            return self._snapshot()

    def answer(self, outcome: str) -> dict:
        today = date.today()
        with self._lock:
            card = self._pick.card
            if card is not None:
                if outcome == "skip":
                    db.postpone(self._conn, card, today + timedelta(days=1))
                elif outcome in ("y", "n", "e"):
                    result = schedule(card.state, outcome, today)
                    db.apply_review(self._conn, card, outcome, result.state, result.next_due, today)
            self._refresh()
            return self._snapshot()


# ── HTTP request handler ──────────────────────────────────────────────────


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # silence per-request logs
        pass

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            body = _HTML.encode("utf-8")
            self._send(200, "text/html; charset=utf-8", body)
        elif self.path == "/api/state":
            self._json(self.server.app_state.get_state())
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == "/api/answer":
            length = int(self.headers.get("Content-Length", 0))
            try:
                body = json.loads(self.rfile.read(length))
            except Exception:
                self.send_error(400, "invalid JSON")
                return
            outcome = body.get("outcome", "")
            if outcome not in ("y", "n", "e", "skip"):
                self.send_error(400, "outcome must be y/n/e/skip")
                return
            self._json(self.server.app_state.answer(outcome))
        else:
            self.send_error(404)

    def _send(self, code: int, content_type: str, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data: dict) -> None:
        self._send(200, "application/json", json.dumps(data).encode("utf-8"))


# ── public entry point ────────────────────────────────────────────────────


def start_ui(db_path: Path, cfg: dict, port: int = 0) -> None:
    """Start a local HTTP server and open the browser UI.  Blocks until Ctrl-C."""
    state = _AppState(db_path, cfg)
    server = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    server.app_state = state
    actual_port = server.server_address[1]
    url = f"http://127.0.0.1:{actual_port}"
    print(f"\n  Browser UI → {url}")
    print("  Press Ctrl-C to quit.\n")
    threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
