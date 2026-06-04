# Smart Mirror Voice Assistant

A voice-driven smart mirror. It listens for a wake word, transcribes speech
locally (Whisper via RealtimeSTT), routes the request with a fast keyword
router, generates a spoken reply with a local LLM (Ollama), and speaks it back
(Piper). The UI is a fullscreen Qt panel displaying widgets for calendar,
clock, tasks, timers, alarms, system stats, and music — with a live log
terminal in the corner showing the voice pipeline.

A built-in web server lets you configure the mirror (calendar colors, widget
visibility, mirror name) from your phone or any device on the same network.

## Structure

```
.
├── main.py               Entry point — window layout, stdout→terminal, threads
├── config.py             Shared config: Ollama URL, model, timeouts, log colors
├── model_names.py        Piper voice model paths
├── settings.json         Web-editable settings (mirror name, widget visibility…)
├── variables.env         Secrets — iCloud credentials, Hue bridge IP/key
├── requirements.txt
│
├── ai/                   Speech + LLM pipeline
│   ├── stt.py            Wake-word loop + Whisper transcription
│   ├── tts.py            Streaming Piper → aplay playback
│   ├── llm.py            Model preload + route-then-stream entry point
│   ├── executer.py       Ollama streaming, sentence splitting, command dispatch
│   ├── keyword_router.py Active router (rule-based, near-zero latency)
│   └── router.py         Legacy LLM router (unused by default)
│
├── ui/                   Qt widgets
│   ├── base_widget.py    Shared base class and style constants
│   ├── terminal.py       Live log terminal + ANSI→HTML + stdout bridge
│   ├── calendar_widget.py  7-day column calendar (reads from SQLite)
│   ├── clock_widget.py   Day / time / date, auto-scaling font
│   ├── task_widget.py    To-do list, tap to toggle done
│   ├── timer_widget.py   Countdown timer with voice control
│   ├── alarm_widget.py   Alarm clock with voice control
│   ├── next_up_widget.py Next calendar event summary
│   ├── system_info_widget.py  CPU, RAM, temp, uptime
│   └── music_widget.py   AirPlay now-playing (replaces system info when active)
│
├── ui_backend/           Data and control backends
│   ├── calendar_backend.py   iCloud CalDAV → SQLite sync; create/cancel events
│   ├── task_backend.py       SQLite task list; add/complete/list
│   ├── timer_backend.py      Countdown logic
│   ├── alarm_backend.py      Alarm scheduling
│   ├── music_backend.py      MPRIS D-Bus client for shairport-sync
│   ├── system_info_backend.py  psutil stats
│   ├── light_backend.py      Philips Hue / LIFX light control (stub — wire up)
│   ├── plug_backend.py       TP-Link / Tapo smart plug control (stub — wire up)
│   ├── web_search_backend.py DuckDuckGo search (stub — wire up)
│   └── ui_control_backend.py Qt signal bus for show/hide/refresh widget commands
│
├── web_config/           Remote configuration web server
│   ├── server.py         Flask REST API + LAN IP printer
│   └── static/
│       └── index.html    Dark-themed single-page config UI
│
└── models/               Local model files (not in git)
    ├── voice_models/     Piper .onnx voices + matching .onnx.json files
    └── router_models/    Qwen router LoRA + base (only if using ai/router.py)
```

## Requirements

Python packages: see `requirements.txt`.

System packages (not pip):

| Dependency | Purpose | Install |
|---|---|---|
| **Ollama** | Local LLM inference | [ollama.ai](https://ollama.ai) |
| **Piper** | Text-to-speech | [github.com/rhasspy/piper](https://github.com/rhasspy/piper) |
| **aplay** | Audio playback | `sudo apt install alsa-utils` |
| **libdbus-1-dev** | D-Bus for music widget | `sudo apt install libdbus-1-dev` |
| **shairport-sync** | AirPlay receiver | `bash install_shairport.sh` |

A **CUDA GPU** is assumed (`device="cuda"` in `ai/stt.py`). On CPU-only
hardware change that to `"cpu"` and expect higher latency.

## Setup

```bash
# 1. Create and activate the virtual environment
python -m venv .mirror && source .mirror/bin/activate

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. Pull the response model
ollama pull qwen3:1.7b

# 4. Set up credentials (iCloud calendar + Philips Hue)
cp variables.env.example variables.env   # or edit variables.env directly
```

### variables.env

```
ICLOUD_USERNAME=you@icloud.com
ICLOUD_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx   # app-specific password from appleid.apple.com
ICLOUD_CALENDARS=Home,Work                # optional: comma-separated names to sync (blank = all)
HUE_BRIDGE_IP=192.168.x.x
HUE_USERNAME=<hue-api-key>
```

### Model files

Place these in `models/`:

- **Piper voices** — `.onnx` + `.onnx.json` pairs referenced in `model_names.py`,
  inside `models/voice_models/`.
- **Whisper STT** — downloaded automatically by RealtimeSTT on first run; no
  manual placement needed.
- **Legacy router** (optional) — `models/router_models/qwen-local-instruct` and
  `models/router_models/Qwen-Local-Folder`, only if re-enabling `ai/router.py`.

## Run

```bash
source .mirror/bin/activate
python main.py
```

Run from the project root — relative paths in `config.py` and `model_names.py`
depend on it. Press **Esc** or **Q** to quit.

## Web Config

When the mirror starts, the terminal widget prints:

```
[WebConfig] config page started at: http://192.168.x.x:5000
```

Open that URL on your phone or any computer on the same network. From there you can:

- **Calendar colors** — pick a color for each iCloud calendar (live, no restart)
- **Widget visibility** — show or hide individual widgets (live, no restart)
- **Mirror name** — the text shown in the accent bar (takes effect on restart)
- **Calendar days** — how many day columns the calendar shows (takes effect on restart)

Settings are saved to `settings.json`.

## Configuration

| What | Where |
|---|---|
| Wake word | `HOT_WORDS` in `ai/stt.py` (default `miller`) |
| Whisper model size | `model=` in `ai/stt.py` `_make_recorder()` |
| TTS voice | model id passed to `speak_sentences()` in `ai/stt.py`, mapped in `ai/tts.py` `_MODEL_MAP` |
| Response model / Ollama URL / timeouts | `config.py` |
| Mirror name / calendar days / widget visibility | `settings.json` or the web config page |
| iCloud account / Hue bridge | `variables.env` |

## Notes

- The active router is `ai/keyword_router.py`. `ai/router.py` (LLM-based) is
  kept for reference but nothing imports it.
- Calendar events are synced from iCloud into a local SQLite database
  (`ui_backend/data/calendar.db`) once per day. The widget reads only from
  SQLite so the UI is instant and works offline between syncs.
- The music widget auto-replaces the system info widget when AirPlay is active.
- The terminal uses **SF Mono** with fallbacks; on non-Apple hosts install the
  font or it falls back to DejaVu Sans Mono.
- `light_backend.py`, `plug_backend.py`, and `web_search_backend.py` are
  present but not wired to hardware by default — edit `_dispatch` in each to
  connect your devices.
