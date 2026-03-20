#!/usr/bin/env python3
"""
FocusTrack — Active Window Tracker + HTTP Server
Tracks active window title and application, with idle and suspend detection.
Automatically rolls over at midnight and keeps per-day history files.
Serves the dashboard at http://localhost:7070

Requirements:
    sudo apt install xdotool x11-utils xprintidle

Usage:
    python3 tracker.py                 # start tracker + web server
    python3 tracker.py --port 8080     # custom port
    python3 tracker.py --no-browser    # don't auto-open browser
    python3 tracker.py --no-server     # tracker only, no HTTP
    python3 tracker.py --idle 300      # idle threshold in seconds (default 300)
    python3 tracker.py --reset         # clear today's data

HTTP endpoints:
    GET  /                        → dashboard.html
    GET  /data                    → today's live JSON
    GET  /data?date=YYYY-MM-DD    → specific day's JSON
    GET  /history                 → JSON list of available dates
    GET  /categories              → current categories config JSON
    POST /categories              → save new categories config JSON
    GET  /editor                  → categories_editor.html
    GET  /active-window           → current active window info (for editor live-test)
"""

import subprocess
import json
import time
import datetime
import os
import sys
import signal
import threading
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# ── Config ────────────────────────────────────────────────────────────────────
DATA_DIR        = os.path.expanduser("~/.focustrack")
SCRIPT_DIR      = os.path.dirname(os.path.abspath(__file__))
DASHBOARD_FILE  = os.path.join(SCRIPT_DIR, "dashboard.html")
EDITOR_FILE     = os.path.join(SCRIPT_DIR, "categories_editor.html")
CATEGORIES_FILE = os.path.join(DATA_DIR, "categories.json")
POLL_INTERVAL   = 1
DEFAULT_PORT    = 7070
DEFAULT_IDLE    = 300
SUSPEND_THRESHOLD = 10

os.makedirs(DATA_DIR, exist_ok=True)

DEFAULT_CATEGORIES = [
    {
        "name": "Deep Work",
        "color": "#60c8f0",
        "rules": [
            {"app": "code|cursor|vim|nvim|emacs|jetbrains|pycharm|intellij|clion|rider|goland",
             "title": ""},
            {"app": "", "title": "GitHub.*Pull Request|Stack Overflow|MDN|documentation|docs\\."}
        ]
    },
    {
        "name": "Communication",
        "color": "#c8f060",
        "rules": [
            {"app": "Slack|Teams|Discord|Thunderbird|Evolution|Geary", "title": ""},
            {"app": "", "title": "Gmail|Outlook|Inbox|Matrix|Telegram"}
        ]
    },
    {
        "name": "Procrastination",
        "color": "#f06090",
        "rules": [
            {"app": "", "title": "YouTube|Reddit|Twitter|Netflix|Twitch|Instagram|TikTok|Facebook|Hacker News"}
        ]
    },
    {
        "name": "Uncategorised",
        "color": "#6a7080",
        "rules": []
    }
]

def day_file(date_str: str) -> str:
    return os.path.join(DATA_DIR, f"{date_str}.json")

# Shared in-memory state
_data_lock        = threading.Lock()
_shared_data      = {}
_categories_lock  = threading.Lock()
_active_info_lock = threading.Lock()
_active_info      = {"title": "", "app": ""}


# ── X11 helpers ───────────────────────────────────────────────────────────────

def get_active_window_info() -> dict:
    try:
        win_id = subprocess.check_output(
            ["xdotool", "getactivewindow"], stderr=subprocess.DEVNULL
        ).decode().strip()
        title = subprocess.check_output(
            ["xdotool", "getwindowname", win_id], stderr=subprocess.DEVNULL
        ).decode().strip() or "Unknown"
        app = "Unknown"
        try:
            xprop_out = subprocess.check_output(
                ["xprop", "-id", win_id, "WM_CLASS"], stderr=subprocess.DEVNULL
            ).decode().strip()
            if "=" in xprop_out:
                parts  = xprop_out.split("=", 1)[1].strip()
                tokens = [t.strip().strip('"') for t in parts.split(",")]
                app    = tokens[-1] if len(tokens) >= 2 else (tokens[0] if tokens else "Unknown")
        except Exception:
            pass
        if app and app != "Unknown":
            app = app[0].upper() + app[1:]
        return {"title": title, "app": app, "win_id": win_id}
    except Exception:
        return {"title": "Unknown", "app": "Unknown", "win_id": ""}


def get_idle_ms() -> int:
    try:
        return int(subprocess.check_output(
            ["xprintidle"], stderr=subprocess.DEVNULL
        ).decode().strip())
    except Exception:
        return 0


# ── Data helpers ──────────────────────────────────────────────────────────────

def make_blank_data(date_str: str = None) -> dict:
    return {
        "date":        date_str or datetime.date.today().isoformat(),
        "windows":     {},
        "apps":        {},
        "app_windows": {},
        "timeline":    [],
        "idle_total":  0,
    }


def load_today() -> dict:
    today = datetime.date.today().isoformat()
    path  = day_file(today)
    if os.path.exists(path):
        try:
            with open(path) as f:
                data = json.load(f)
            if data.get("date") != today:
                data = make_blank_data(today)
            data.setdefault("apps", {})
            data.setdefault("app_windows", {})
            data.setdefault("idle_total", 0)
            return data
        except (json.JSONDecodeError, KeyError):
            pass
    return make_blank_data(today)


def load_date(date_str: str) -> dict | None:
    path = day_file(date_str)
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def save_data(data: dict):
    path = day_file(data["date"])
    tmp  = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def list_history() -> list:
    dates = []
    for fname in os.listdir(DATA_DIR):
        if fname.endswith(".json") and len(fname) == 15:
            dates.append(fname[:-5])
    return sorted(dates, reverse=True)


# ── Categories helpers ────────────────────────────────────────────────────────

def load_categories() -> list:
    if os.path.exists(CATEGORIES_FILE):
        try:
            with open(CATEGORIES_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    # Write defaults on first run
    save_categories(DEFAULT_CATEGORIES)
    return DEFAULT_CATEGORIES


def save_categories(cats: list):
    tmp = CATEGORIES_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cats, f, indent=2)
    os.replace(tmp, CATEGORIES_FILE)


def reset_data():
    today = datetime.date.today().isoformat()
    blank = make_blank_data(today)
    save_data(blank)
    with _data_lock:
        _shared_data.clear()
        _shared_data.update(blank)
        _shared_data["status"] = "active"
    print("Data reset for today.")


def accumulate(data: dict, info: dict, elapsed: float):
    title, app = info["title"], info["app"]
    data["windows"][title]  = data["windows"].get(title, 0) + elapsed
    data["apps"][app]       = data["apps"].get(app, 0) + elapsed
    data["app_windows"].setdefault(app, {})
    data["app_windows"][app][title] = data["app_windows"][app].get(title, 0) + elapsed


# ── HTTP Server ───────────────────────────────────────────────────────────────

class FocusHandler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        parsed = urlparse(self.path)
        path   = parsed.path
        params = parse_qs(parsed.query)

        if path in ("/", "/dashboard", "/dashboard.html"):
            self._serve_file(DASHBOARD_FILE, "text/html; charset=utf-8")
        elif path in ("/editor", "/categories_editor.html"):
            self._serve_file(EDITOR_FILE, "text/html; charset=utf-8")
        elif path == "/data":
            date_param = params.get("date", [None])[0]
            if date_param and date_param != datetime.date.today().isoformat():
                self._serve_history_data(date_param)
            else:
                self._serve_today()
        elif path == "/history":
            self._send_response(json.dumps(list_history()).encode(), "application/json")
        elif path == "/categories":
            cats = load_categories()
            self._send_response(json.dumps(cats, indent=2).encode(), "application/json")
        elif path == "/active-window":
            with _active_info_lock:
                info = dict(_active_info)
            self._send_response(json.dumps(info).encode(), "application/json")
        else:
            self.send_error(404)

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/categories":
            length = int(self.headers.get("Content-Length", 0))
            body   = self.rfile.read(length)
            try:
                cats = json.loads(body)
                if not isinstance(cats, list):
                    raise ValueError("Expected a JSON array")
                save_categories(cats)
                self._send_response(b'{"ok": true}', "application/json")
                print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] "
                      f"Categories updated ({len(cats)} categories)")
            except Exception as e:
                self.send_error(400, str(e))
        else:
            self.send_error(404)

    def do_OPTIONS(self):
        # CORS preflight
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _serve_file(self, filepath, content_type):
        if not os.path.exists(filepath):
            self.send_error(404, f"{os.path.basename(filepath)} not found next to tracker.py")
            return
        with open(filepath, "rb") as f:
            body = f.read()
        self._send_response(body, content_type)

    def _serve_today(self):
        with _data_lock:
            body = json.dumps(_shared_data, indent=2).encode()
        self._send_response(body, "application/json")

    def _serve_history_data(self, date_str: str):
        data = load_date(date_str)
        if data is None:
            self.send_error(404, f"No data for {date_str}")
            return
        self._send_response(json.dumps(data, indent=2).encode(), "application/json")

    def _send_response(self, body: bytes, content_type: str):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", len(body))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)


def start_server(port: int):
    server = HTTPServer(("127.0.0.1", port), FocusHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


# ── Tracker loop ──────────────────────────────────────────────────────────────

def run(port: int, open_browser: bool, idle_threshold: int):
    data       = load_today()
    last_info  = None
    last_time  = time.time()
    last_save  = time.time()
    prev_tick  = time.time()
    is_idle    = False
    idle_since = None

    with _data_lock:
        _shared_data.update(data)
        _shared_data["status"] = "active"

    server = None
    try:
        server = start_server(port)
        url    = f"http://localhost:{port}"
        print(f"FocusTrack running  →  {url}")
        print(f"Data dir:       {DATA_DIR}")
        print(f"Categories:     {CATEGORIES_FILE}")
        print(f"Idle after:     {idle_threshold}s of no input")
        print(f"Rule editor:    {url}/editor")
        print("Press Ctrl+C to stop.\n")
        if open_browser:
            threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    except OSError as e:
        print(f"WARNING: Could not start HTTP server on port {port}: {e}")

    def handle_exit(sig, frame):
        save_data(data)
        if server:
            server.shutdown()
        print("\nFocusTrack stopped. Data saved.")
        sys.exit(0)

    signal.signal(signal.SIGINT,  handle_exit)
    signal.signal(signal.SIGTERM, handle_exit)

    while True:
        now       = time.time()
        tick_gap  = now - prev_tick
        prev_tick = now

        # ── Midnight rollover ────────────────────────────────────────────────
        today = datetime.date.today().isoformat()
        if data["date"] != today:
            print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] "
                  f"Midnight rollover: saving {data['date']}, starting {today}")
            save_data(data)
            data       = make_blank_data(today)
            last_info  = None
            last_time  = now
            last_save  = now
            is_idle    = False
            idle_since = None
            with _data_lock:
                _shared_data.clear()
                _shared_data.update(data)
                _shared_data["status"] = "active"

        # ── Suspend detection ────────────────────────────────────────────────
        was_suspended = tick_gap > SUSPEND_THRESHOLD
        if was_suspended:
            gap_str = str(datetime.timedelta(seconds=int(tick_gap)))
            print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] "
                  f"Resumed after suspend (gap: {gap_str}) — discarding gap")
            last_time  = now
            is_idle    = False
            idle_since = None

        # ── Idle detection ───────────────────────────────────────────────────
        idle_ms      = get_idle_ms()
        idle_seconds = idle_ms / 1000.0

        if not is_idle and idle_seconds >= idle_threshold:
            is_idle        = True
            idle_since     = now - idle_seconds
            active_elapsed = max(0.0, (now - idle_seconds) - last_time)
            if last_info is not None and active_elapsed > 0:
                accumulate(data, last_info, active_elapsed)
                data["timeline"].append({
                    "title":   last_info["title"],
                    "app":     last_info["app"],
                    "start":   datetime.datetime.fromtimestamp(last_time).isoformat(),
                    "end":     datetime.datetime.fromtimestamp(now - idle_seconds).isoformat(),
                    "seconds": round(active_elapsed, 1),
                    "event":   "active",
                })
            last_time = now
            print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] "
                  f"Idle — pausing (idle {int(idle_seconds)}s)")

        elif is_idle and idle_seconds < idle_threshold:
            is_idle       = False
            idle_duration = now - idle_since if idle_since else 0
            data["idle_total"] = data.get("idle_total", 0) + idle_duration
            data["timeline"].append({
                "title":   "— idle —",
                "app":     "",
                "start":   datetime.datetime.fromtimestamp(idle_since).isoformat(),
                "end":     datetime.datetime.fromtimestamp(now).isoformat(),
                "seconds": round(idle_duration, 1),
                "event":   "idle",
            })
            idle_since = None
            last_time  = now
            print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Active — resuming")

        # ── Window accumulation ──────────────────────────────────────────────
        if not is_idle and not was_suspended:
            info    = get_active_window_info()
            changed = (
                last_info is None or
                info["title"] != last_info["title"] or
                info["app"]   != last_info["app"]
            )
            if last_info is not None and changed:
                elapsed = now - last_time
                if elapsed > 0:
                    accumulate(data, last_info, elapsed)
                    data["timeline"].append({
                        "title":   last_info["title"],
                        "app":     last_info["app"],
                        "start":   datetime.datetime.fromtimestamp(last_time).isoformat(),
                        "end":     datetime.datetime.fromtimestamp(now).isoformat(),
                        "seconds": round(elapsed, 1),
                        "event":   "active",
                    })
                last_time = now
            if changed:
                last_info = info
                last_time = now
            # Keep active window info available for the editor's live-test endpoint
            with _active_info_lock:
                _active_info["title"] = info.get("title", "")
                _active_info["app"]   = info.get("app", "")

        if len(data["timeline"]) > 500:
            data["timeline"] = data["timeline"][-500:]

        # ── Periodic save + shared state ─────────────────────────────────────
        status = "suspended" if was_suspended else ("idle" if is_idle else "active")
        if now - last_save >= 10:
            data["last_updated"] = datetime.datetime.now().isoformat()
            save_data(data)
            last_save = now

        with _data_lock:
            _shared_data.clear()
            _shared_data.update(data)
            _shared_data["status"]         = status
            _shared_data["idle_seconds"]   = int(idle_seconds) if is_idle else 0
            _shared_data["idle_threshold"] = idle_threshold
            _shared_data["last_updated"]   = datetime.datetime.now().isoformat()

        time.sleep(POLL_INTERVAL)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    args = sys.argv[1:]

    if "--reset" in args:
        reset_data()
        sys.exit(0)

    missing = []
    for tool in ["xdotool", "xprop"]:
        try:
            subprocess.check_output(["which", tool], stderr=subprocess.DEVNULL)
        except subprocess.CalledProcessError:
            missing.append(tool)
    if missing:
        print(f"ERROR: Missing tools: {', '.join(missing)}")
        print("Install with:  sudo apt install xdotool x11-utils")
        sys.exit(1)

    try:
        subprocess.check_output(["which", "xprintidle"], stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        print("WARNING: xprintidle not found — idle detection disabled.")
        print("Install with:  sudo apt install xprintidle\n")

    port = DEFAULT_PORT
    if "--port" in args:
        idx = args.index("--port")
        try:
            port = int(args[idx + 1])
        except (IndexError, ValueError):
            print("ERROR: --port requires a number"); sys.exit(1)

    idle_threshold = DEFAULT_IDLE
    if "--idle" in args:
        idx = args.index("--idle")
        try:
            idle_threshold = int(args[idx + 1])
        except (IndexError, ValueError):
            print("ERROR: --idle requires a number of seconds"); sys.exit(1)

    no_server    = "--no-server"  in args
    open_browser = "--no-browser" not in args

    if no_server:
        print(f"FocusTrack daemon (no HTTP server). Data dir: {DATA_DIR}\n")

    run(port=port, open_browser=open_browser, idle_threshold=idle_threshold)