# FocusTrack — One-Shot Generation Prompt

---

Build a Linux desktop productivity application called **FocusTrack** that automatically tracks which application and window the user has focused on, and for how long, throughout the day. The application consists of two files: a Python backend daemon (`tracker.py`) and an HTML dashboard (`dashboard.html`).

---

## OVERVIEW

- `tracker.py` — a background Python process that polls the active X11 window every second, accumulates time per application and window title, detects idleness and system suspend/resume, auto-saves per-day JSON files, and serves an HTTP server for the dashboard.
- `dashboard.html` — a single-file HTML/CSS/JS dashboard (no frameworks, no bundler) served by the tracker's HTTP server, which auto-fetches live data and renders it visually.

Both files must be complete and fully functional as delivered. No placeholders, no TODOs.

---

## PART 1: tracker.py

### System requirements
- Python 3 standard library only — no pip dependencies
- Requires three Linux CLI tools: `xdotool`, `xprop`, `xprintidle` (from packages `xdotool`, `x11-utils`, `xprintidle`)
- On startup, check for `xdotool` and `xprop` (required, exit with error if missing). Check for `xprintidle` separately (optional, warn but continue if missing — idle detection will be disabled)

### CLI usage
```
python3 tracker.py                 # start tracker + HTTP server, auto-open browser
python3 tracker.py --port 8080     # custom HTTP port (default: 7070)
python3 tracker.py --no-browser    # don't auto-open browser on start
python3 tracker.py --no-server     # tracker only, no HTTP server
python3 tracker.py --idle 300      # idle threshold in seconds (default: 300 = 5 minutes)
python3 tracker.py --reset         # clear today's data file and exit
```

### Window tracking
Use `xdotool getactivewindow` to get the active window ID, then:
- `xdotool getwindowname <id>` → window title string
- `xprop -id <id> WM_CLASS` → parse the second quoted token as the application name (e.g. `WM_CLASS(STRING) = "Navigator", "firefox"` → app = `"Firefox"`). Capitalise the first letter.

Poll every 1 second. On each poll, if the active window (title + app pair) has changed, record the elapsed time for the previous window and start timing the new one.

### Data structures accumulated
For each day, maintain:
- `windows: dict[str, float]` — total seconds per window title
- `apps: dict[str, float]` — total seconds per application name
- `app_windows: dict[str, dict[str, float]]` — per-app breakdown: app → window title → seconds
- `timeline: list[dict]` — ordered list of events (see schema below)
- `idle_total: float` — total idle seconds accumulated today

### Timeline event schema
Each event is a dict:
```json
{
  "title":   "window title string",
  "app":     "Application name",
  "start":   "2026-03-04T09:12:00.123456",
  "end":     "2026-03-04T09:14:30.654321",
  "seconds": 150.5,
  "event":   "active"
}
```
For idle periods, use `"title": "— idle —"`, `"app": ""`, `"event": "idle"`.
Keep the timeline trimmed to the last 500 events.

### Idle detection
Use `xprintidle` which returns milliseconds since last keyboard/mouse input.

- When idle time crosses the threshold (default 300s):
  - Mark as idle
  - Back-date the idle start: `idle_since = now - (idle_ms / 1000)`
  - Accumulate only the active portion up to `idle_since` (not the full elapsed time)
  - Append an `"active"` timeline event ending at `idle_since`
  - Print a log line to stdout: `[HH:MM:SS] Idle — pausing (idle Xs)`
- When idle time drops back below threshold (user returns):
  - Calculate idle duration: `now - idle_since`
  - Add to `idle_total`
  - Append an `"idle"` timeline event
  - Reset `last_time = now`
  - Print: `[HH:MM:SS] Active — resuming`

If `xprintidle` is not available, skip idle detection entirely (always return 0ms).

### Suspend/resume detection
On every tick, compare `time.time()` against the previous tick timestamp. If the gap is greater than 10 seconds (much larger than the 1-second poll interval), the system was suspended/hibernated. When detected:
- Discard the entire gap (do not accumulate it)
- Reset `last_time = now`
- Clear idle state
- Print: `[HH:MM:SS] Resumed after suspend (gap: H:MM:SS) — discarding gap`

### Midnight rollover
On every tick, check `datetime.date.today().isoformat()`. If it differs from `data["date"]`:
- Save the current day's data to disk
- Replace `data` with a fresh blank structure for the new date
- Reset all tracking state (`last_info`, `last_time`, `is_idle`, `idle_since`)
- Print: `[HH:MM:SS] Midnight rollover: saving YYYY-MM-DD, starting YYYY-MM-DD`

### File storage
- Data directory: `~/.focustrack/` (create if it doesn't exist)
- One JSON file per day: `~/.focustrack/YYYY-MM-DD.json`
- Save atomically: write to `path + ".tmp"`, then `os.replace(tmp, path)`
- Auto-save every 10 seconds during the tracking loop
- On `SIGINT` / `SIGTERM`: save current data, shutdown server, exit cleanly

### JSON file schema
```json
{
  "date": "2026-03-04",
  "windows": {"Firefox — GitHub": 3721.4},
  "apps": {"Firefox": 3721.4},
  "app_windows": {"Firefox": {"Firefox — GitHub": 3721.4}},
  "timeline": [...],
  "idle_total": 420.0,
  "last_updated": "2026-03-04T14:22:05.123"
}
```

### HTTP server
Run a `threading`-based `http.server.HTTPServer` on `127.0.0.1:<port>` in a daemon thread.

Endpoints:
- `GET /` or `GET /dashboard.html` → serve `dashboard.html` from the same directory as `tracker.py`
- `GET /data` → serve today's live JSON from shared in-memory state (protected by `threading.Lock`)
- `GET /data?date=YYYY-MM-DD` → serve a historical day's JSON from disk (`~/.focustrack/YYYY-MM-DD.json`); return HTTP 404 if file doesn't exist
- `GET /history` → return a JSON array of available date strings (all `.json` files in `~/.focustrack/`), sorted newest-first

All responses: set `Cache-Control: no-cache` and `Access-Control-Allow-Origin: *`.

Shared in-memory state must include, beyond the data fields: `"status"` (`"active"`, `"idle"`, or `"suspended"`), `"idle_seconds"` (current idle duration if idle, else 0), `"idle_threshold"` (configured threshold), and `"last_updated"` (ISO timestamp, updated every 10 seconds).

Auto-open the dashboard in the default browser 0.5 seconds after the server starts (use `threading.Timer` + `webbrowser.open`), unless `--no-browser` is passed.

Suppress all default HTTP request logging (`log_message` → no-op).

---

## PART 2: dashboard.html

A single self-contained HTML file. No external JS frameworks. Google Fonts are fine. All CSS and JS inline.

### Design aesthetic
Dark terminal theme. Colour palette:
- Background: `#0d0f12`
- Surface: `#14171c`
- Surface2: `#1c2028`
- Border: `#252a34`
- Text: `#e8eaf0`
- Muted: `#6a7080`
- Accent (green): `#c8f060`
- Accent2 (cyan): `#60c8f0`
- Accent3 (pink): `#f06090`
- Accent4 (amber): `#f0c060`

Use `DM Mono` (monospace) as the body font and `Instrument Serif` (serif) for large numerical values and the logo. Import both from Google Fonts.

### Auto-refresh
On load, immediately fetch `/data`. Then auto-refresh every **10 seconds** using a `setInterval`. Show a circular SVG countdown ring in the header (radius 12, circumference ≈75.4) that animates `stroke-dashoffset` from full to 0 over 10 seconds and resets on each fetch. The ring is clickable to trigger an immediate refresh.

Do **not** use a manual file picker — all data comes from the HTTP API.

### Connecting state
While no data has been received yet (or the server is unreachable), show a centred "waiting" state with a breathing animation on a large `◎` character, the URL being polled, and instructions to start `tracker.py`. Retry every 10 seconds silently.

### Header (sticky)
- Left: logo — `FocusTrack` in serif + `WINDOW ACTIVITY` subtitle in small caps
- Right (left to right): status pill, date picker button, refresh ring

**Status pill**: a rounded pill with a coloured dot + label. States:
- `active` → green dot with pulse animation + `● Active`
- `idle` → amber dot + `⏸ Idle Xm Xs` (showing current idle duration)
- `suspended` → pink dot + `⏻ Resumed`
- `error` → pink dot + `✕ Offline`
- Historical view → no dot, `📁 Historical`

**Date picker button**: shows `Today` normally, or the selected date string in cyan when viewing history. Clicking opens the calendar popup.

### Calendar popup
A modal overlay (dark backdrop with blur) containing:
- Month/year header with `‹` / `›` navigation buttons to shift months
- 7-column grid: Mon–Sun day-of-week headers, then day cells
- Day cells:
  - If a date exists in the `/history` list (or is today): clickable, highlighted background
  - If no data: greyed out, not clickable
  - Today's date: outlined with accent green
  - Currently selected date: filled with accent cyan
- Footer: `Jump to Today` button + close `✕` button
- Clicking outside the popup closes it

When a historical date is selected:
- Fetch `/data?date=YYYY-MM-DD`
- Show a blue info banner below the tabs: `Viewing: YYYY-MM-DD` with a `Back to Today` button
- Dim and disable the refresh ring (no auto-refresh for historical data)
- Hide the idle toast banner

### Tabs (sticky, below header)
Three tabs: **Applications** | **Windows** | **Timeline**

### Stats row (4 cards)
Always visible above the tab content. Each card has a 2px coloured top border:
1. **Active Time** (green border) — total tracked seconds today (formatted as `Xh Ym` or `Xm Ys`)
2. **Top App** or **Top Window** (cyan border) — label changes based on active tab; shows time + name
3. **Apps Used** or **Windows Visited** (pink border) — count, label changes with tab
4. **Idle Time** (amber border) — total idle seconds; if zero, dim the card (muted colours)

Format all times: `Xh Ym` if ≥ 1 hour, `Xm Ys` if ≥ 1 minute, `Xs` otherwise.

### Applications tab
Grid of app cards (`repeat(auto-fill, minmax(340px, 1fr))`). Each card shows:
- App name (large), time (serif), window count + percentage of active time
- A horizontal bar (linear scale, relative to top app)
- Preview of top 2 window titles (truncated to 36 chars)
- Staggered fade-in animation on load

Clicking a card opens a **drill-down panel** (above the grid, below the section title):
- Cyan border, header showing `AppName — window breakdown` + close button
- List of all window titles for that app, sorted by time, each with time, percentage of app total, and a proportional bar
- Panel persists across auto-refreshes (re-renders with updated data)

### Windows tab
Ranked list of top 30 window titles. Each row:
- Rank number, app name badge (small pill), window title (truncated, full title in tooltip)
- Proportional bar (linear scale, relative to top window)
- Time + percentage of total active time on the right

### Timeline tab
- **Filter**: only show events with `seconds >= 10` (hide anything shorter)
- **Count**: show last 50 events after filtering, newest first
- **Bar scale**: logarithmic — use `Math.log1p(seconds) / Math.log1p(maxSeconds) * 100` for bar width. This prevents one long idle block from making all other bars invisible.
- Show a `log scale` label in the section header
- Each row: time (HH:MM), app name (cyan), window title, duration, log-scale bar
- Idle rows: dimmed to 55% opacity, amber app label showing `— idle —`, title showing `no input`
- Timeline grid columns: `80px 110px 130px 60px 1fr`

### Idle toast banner
A fixed bottom-centre toast (`position: fixed; bottom: 24px`) that slides up with animation when `data.status === "idle"`. Shows `⏸ Tracking paused — idle for Xm Ys`. Hidden for historical views and when active.

### Colour assignment
Use a deterministic colour-from-string function for consistent app colours across renders:
```js
function colourFor(s) {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return COLOURS[h % COLOURS.length];
}
```
Palette of 15 colours cycling through the accent colours.

### Historical mode behaviour
- History list fetched from `/history` on calendar open
- Auto-refresh paused (the setInterval still runs, but skips fetch when `viewingDate` is set)
- Refresh ring dimmed (`opacity: 0.3`, `pointer-events: none`)
- "Back to Today" banner shown
- Status pill shows `📁 Historical` (no dot animation)
- Returning to today restores live mode

---

## BEHAVIOUR EDGE CASES TO HANDLE

- If `xprintidle` is unavailable, idle detection is fully disabled (always treat as active)
- If the HTTP server port is already in use, print a warning and continue running the tracker without a server
- If `dashboard.html` is missing when the HTTP server tries to serve it, return a helpful 404 message
- Timeline events must never be accumulated during idle or suspended periods
- When the user returns from idle, `last_time` must be reset to `now` so the idle gap is not double-counted
- Back-dating idle start: when idle is first detected, `idle_since = now - (idle_ms / 1000)` — this gives the true start of inactivity
- Midnight rollover must correctly save the day's final state before resetting
- Historical JSON files on disk do not have a `status` field — the dashboard must handle missing `status` gracefully (default to `"active"`)
- `new Date("2026-03-04")` in JS parses as UTC midnight which can show the wrong day in local time — use `new Date(dateStr + "T12:00:00")` for display

---

## DELIVERABLES

Produce exactly two files:

1. **`tracker.py`** — complete, runnable Python 3 script with all tracking, idle detection, suspend detection, midnight rollover, per-day file storage, and HTTP server logic.

2. **`dashboard.html`** — complete, self-contained HTML file with all CSS and JS inline. Must work when opened from `http://localhost:7070` served by the tracker. No external dependencies except Google Fonts.

Do not truncate either file. Do not add placeholder comments like `// ... rest of implementation`. Both files must be fully implemented and immediately usable.
