# FocusTrack

> Automatically tracks which application and window you're focused on — and for how long.

FocusTrack runs silently in the background on Linux, recording your active window every second. It detects idleness, handles system suspend/resume, rolls over at midnight, and serves a live dashboard in your browser.

---

## Features

- **Active window tracking** — records app name and window title every second
- **Per-app breakdown** — see how long you spent in each application and each window within it
- **Category rules** — split time by custom categories (Work, Procrastination, etc.) using regexp rules on window titles and app names
- **Idle detection** — pauses tracking after a configurable period of no keyboard/mouse input
- **Suspend/resume detection** — discards gaps caused by sleep or hibernation
- **Midnight rollover** — automatically starts a new day file at midnight
- **History browser** — view any past day via a calendar picker in the dashboard
- **Live web dashboard** — auto-refreshing dashboard served at `http://localhost:7070`
- **Rule editor** — visual editor for category rules at `http://localhost:7070/editor`

---

## Requirements

```bash
sudo apt install xdotool x11-utils xprintidle
```

| Tool | Purpose | Required |
|------|---------|----------|
| `xdotool` | Get active window ID and title | ✅ Required |
| `xprop` (x11-utils) | Get application name via `WM_CLASS` | ✅ Required |
| `xprintidle` | Detect keyboard/mouse idle time | ⚠️ Optional (idle detection disabled without it) |

---

## Files

| File | Description |
|------|-------------|
| `tracker.py` | Background daemon — tracks windows, serves HTTP |
| `dashboard.html` | Live dashboard UI |
| `categories_editor.html` | Visual rule editor |

Data is stored in `~/.focustrack/` — one JSON file per day (`YYYY-MM-DD.json`) plus `categories.json` for your rules.

---

## Usage

```bash
# Start tracker + open dashboard in browser
python3 tracker.py

# Custom options
python3 tracker.py --port 8080        # use a different port (default: 7070)
python3 tracker.py --idle 120         # idle threshold in seconds (default: 300)
python3 tracker.py --no-browser       # don't auto-open the browser
python3 tracker.py --no-server        # tracker only, no HTTP server

# Data management
python3 tracker.py --reset            # clear today's data and start fresh
```

---

## HTTP API

The tracker exposes a simple REST API used by the dashboard and editor.

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Serve `dashboard.html` |
| `GET` | `/data` | Today's live tracking data (JSON) |
| `GET` | `/data?date=YYYY-MM-DD` | A specific historical day's data |
| `GET` | `/history` | List of all available dates |
| `GET` | `/categories` | Current category rules |
| `POST` | `/categories` | Save updated category rules |
| `GET` | `/editor` | Serve `categories_editor.html` |
| `GET` | `/active-window` | Currently focused window (used by editor) |

---

## Category Rules

Rules live in `~/.focustrack/categories.json` and are evaluated **client-side at render time** — so editing rules instantly re-categorises all your historical data without touching the raw files.

Each category has a name, a colour, and an ordered list of rules. Each rule matches on `app` (regexp) and/or `title` (regexp), case-insensitively. The **first matching category wins**. A category with no rules acts as the catch-all fallback.

```json
[
  {
    "name": "Deep Work",
    "color": "#60c8f0",
    "rules": [
      { "app": "code|cursor|vim", "title": "" },
      { "app": "", "title": "GitHub.*Pull Request|Stack Overflow" }
    ]
  },
  {
    "name": "Procrastination",
    "color": "#f06090",
    "rules": [
      { "app": "", "title": "YouTube|Reddit|Twitter|Netflix" }
    ]
  },
  {
    "name": "Uncategorised",
    "color": "#6a7080",
    "rules": []
  }
]
```

Use the visual editor at `http://localhost:7070/editor` to manage rules — it includes a live test bar showing which category your current window matches.

---

## Build It Yourself

A prompt file (`PROMPT.md`) is included in this repo. Drop it into any capable LLM and it will generate the full application from scratch.

> Tested with **Claude Sonnet 4.6** — produces all three files in a single shot.

---

## License

MIT
