# Smart Mirror

A fullscreen smart mirror UI with optional AI voice control. Runs on any x86 PC or can be flashed as a standalone OS image.

## Features

- **Widgets** — clock, calendar, tasks, timers, alarms, system stats, AirPlay music
- **Voice control** (optional) — wake word → Whisper STT → keyword router → local LLM (Ollama) → Piper TTS, all offline
- **Web config** — configure everything at `http://mirror.local` from your phone or any device on the same network
- **OTA updates** — one-click update from GitHub in the web config
- **Mirror OS** — bootable image you can flash with Balena Etcher or Raspberry Pi Imager

## Quick Start

```bash
git clone https://github.com/FeetnotFound/Smart-Mirror.git
cd Smart-Mirror
bash install.sh           # installs system packages + Python venv
# edit variables.env      # add iCloud credentials
source .mirror/bin/activate
python main.py
```

Web config opens automatically at `http://<your-ip>` (port 80) or falls back to `http://<your-ip>:8080`.

To add voice control:
```bash
bash install_ai.sh
```

## Project Structure

```
.
├── main.py                  Entry point — Qt window, layout, threads
├── config.py                Ollama URL, model name, timeouts, log colors
├── model_names.py           Piper voice model paths
├── settings.json            Web-editable settings (name, widgets, layout, colors)
├── variables.env            Secrets — iCloud credentials, Hue bridge (not in git)
├── requirements-base.txt    Core dependencies (no AI)
├── requirements.txt         Full dependencies including AI voice pipeline
├── install.sh               Base setup — venv + core packages
├── install_ai.sh            Add voice control (Ollama, Whisper, Piper)
├── install_shairport.sh     Add AirPlay audio (shairport-sync)
│
├── ai/                      Voice pipeline
│   ├── stt.py               Wake-word loop + Whisper transcription
│   ├── tts.py               Piper → aplay streaming playback
│   ├── llm.py               Ollama streaming entry point
│   ├── executer.py          Response streaming + command dispatch
│   ├── keyword_router.py    Fast rule-based intent router (default)
│   └── router.py            Legacy LLM router (unused by default)
│
├── ui/                      Qt widgets
│   ├── base_widget.py       Shared base class and theme constants
│   ├── terminal.py          Live log + ANSI→HTML + stdout bridge
│   ├── calendar_widget.py   Day-column calendar (reads SQLite)
│   ├── clock_widget.py      Day / time / date with auto-scaling font
│   ├── task_widget.py       Tap-to-complete task list
│   ├── timer_widget.py      Countdown timer
│   ├── alarm_widget.py      Alarm clock
│   ├── next_up_widget.py    Next calendar event summary
│   ├── system_info_widget.py CPU, RAM, temp, uptime
│   └── music_widget.py      AirPlay now-playing (replaces system info)
│
├── ui_backend/              Data and control
│   ├── calendar_backend.py  iCloud CalDAV → SQLite sync
│   ├── task_backend.py      SQLite task CRUD
│   ├── timer_backend.py     Countdown logic
│   ├── alarm_backend.py     Alarm scheduling
│   ├── music_backend.py     MPRIS D-Bus client for shairport-sync
│   ├── system_info_backend.py psutil stats
│   ├── light_backend.py     Hue / LIFX / Home Assistant (wire up _dispatch)
│   ├── plug_backend.py      Kasa / Tapo smart plugs (wire up _dispatch)
│   ├── web_search_backend.py DuckDuckGo search (wire up _dispatch)
│   └── ui_control_backend.py Qt signal bus for widget commands
│
├── web_config/
│   ├── server.py            HTTP REST API (Python built-in http.server)
│   └── static/index.html   Single-page dark config UI
│
└── models/
    ├── voice_models/        Piper .onnx voices (not in git — add your own)
    └── router_models/       Legacy router weights (not in git)
```

## Configuration

### variables.env

```
ICLOUD_USERNAME=your@icloud.com
ICLOUD_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx   # app-specific password from appleid.apple.com
ICLOUD_CALENDARS=Home,Work                # optional: comma-separated names (blank = all)
HUE_BRIDGE_IP=192.168.x.x                # optional
HUE_USERNAME=<hue-api-key>               # optional
```

### Wake word

Default is `mirror` (`HOT_WORDS` in `ai/stt.py`). Change it to whatever you want — the mirror strips it before sending to the LLM.

### Voice models

Drop Piper `.onnx` + `.onnx.json` pairs into `models/voice_models/` and reference them in `model_names.py`. Download voices from [github.com/rhasspy/piper/releases](https://github.com/rhasspy/piper/releases).

### LLM model

Default is `qwen3:1.7b`. Change it in the web config → AI Model section, or edit `settings.json`. Any Ollama model works.

## Web Config

Visit `http://mirror.local` (or the mirror's IP) from any device on the same network. The config page lets you:

- Mirror name and accent colors
- Widget visibility and layout (drag-and-drop)
- Calendar days shown
- iCloud calendar colors
- AI model selection (shows installed Ollama models)
- OTA updates (checks GitHub, one-click update + restart)
- Add-on installation (voice control)

Settings save to `settings.json`. Most take effect immediately without restart.

## Mirror OS (Bootable Image)

Build a standalone bootable image (no host OS required):

```bash
sudo bash build_distro.sh
```

Flash with **Balena Etcher** or **Raspberry Pi Imager** (Use Custom Image). After flashing a `MIRRORCFG` partition appears — edit `wifi.conf` and `mirror.env` there before first boot.

With **Raspberry Pi Imager**: click the ⚙ gear icon before writing to pre-configure WiFi without touching the partition.

## System Requirements

| Component | Minimum | Recommended |
|---|---|---|
| OS | Debian 12 / Ubuntu 22.04+ | Mirror OS image |
| Python | 3.11 | 3.11 |
| RAM | 2 GB | 4 GB |
| GPU | CPU (high latency) | NVIDIA CUDA (for voice) |

Voice control works on CPU but expect 3–8 s latency. On a modern NVIDIA GPU it's under 1 s.

## Dependencies

| Package | Purpose | Install |
|---|---|---|
| **Ollama** | Local LLM inference | `bash install_ai.sh` or [ollama.com](https://ollama.com) |
| **aplay** | Audio output for TTS | `sudo apt install alsa-utils` |
| **libdbus-1-dev** | AirPlay music widget | `sudo apt install libdbus-1-dev` |
| **shairport-sync** | AirPlay receiver | `bash install_shairport.sh` |

## License

See [LICENSE](LICENSE).
