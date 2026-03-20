# Focus Track

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

## DIY - you can build this app yourself with your favorite LLM
Here in the repo there is a file with the prompt PROMPT.md

You can put this prompt into your favorite LLM (I tested with Claude Sonnet 4.6) and it will create the app for you.
