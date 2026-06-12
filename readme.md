# Smart Mirror

A fullscreen smart mirror UI for any x86 PC or Raspberry Pi. Runs as a regular app or can be set up as a dedicated always-on kiosk with a single script.

## Features

- **Widgets** — clock, calendar, tasks, timers, alarms, system stats, AirPlay music
- **Alarms** — repeating daily alarms, looping alert sound until dismissed, dismiss from web or voice
- **Voice commands** (optional) — wake word → Whisper STT → keyword router → local LLM (Ollama) → Piper TTS, fully offline
- **Web config** — configure everything at `http://mirror.local` from any device on the network
- **AirPlay** — stream audio to the mirror via shairport-sync; now-playing widget shows track info
- **OTA updates** — one-click update from GitHub in the web config

## Install

### On your existing machine (development / testing)

```bash
git clone https://github.com/FeetnotFound/Smart-Mirror.git
cd Smart-Mirror
bash install.sh
```

Edit `variables.env` with your credentials, then:

```bash
source .mirror/bin/activate
python main.py
```

The web config is at `http://localhost` (port 80, requires `setcap`) or falls back to `http://localhost:8080`.

### Dedicated machine (kiosk / Raspberry Pi)

Turns a fresh **Ubuntu 22.04+ Server** or **Raspberry Pi OS Lite** install into a Mirror OS kiosk — autologin, X11, mirror app on boot:

```bash
sudo bash setup_mirror_os.sh
sudo reboot
```

After reboot the mirror starts automatically. SSH in at `mirror.local`.

## Add-Ons

### Voice commands (speech recognition only)

Wake word → timers, lights, alarms, tasks. No TTS, no LLM.

```bash
bash install_voice.sh
```

Downloads ~1–2 GB (Whisper model). No GPU required. Toggle STT on/off from the web config → Add-Ons.

### AI responses (voice + TTS + LLM)

Adds Piper TTS (spoken replies) and Ollama (conversational AI). Install voice commands first.

```bash
bash install_ai.sh
```

Downloads ~3–5 GB. GPU strongly recommended. Toggle TTS on/off from the web config → Add-Ons.

### AirPlay receiver

```bash
bash install_shairport.sh
```

Streams audio to the mirror and shows now-playing info on screen.  
**AIY Voice HAT users**: set `output_device = "plughw:2,0"` in `/etc/shairport-sync.conf` and omit `mixer_control_name` (the HAT has no hardware volume controls).

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

Default is `mirror` (`HOT_WORDS` in `ai/stt.py`). Change it to anything — the mirror strips it before routing the command.

### Custom alarm sound

Drop a file named `sounds/klaxon_custom.wav` (also `.mp3`, `.ogg`, `.flac`) into the project and it will be used for all alarm and timer alerts. If no custom file is present, the gentle ascending chime plays instead.

### Voice models

Drop Piper `.onnx` + `.onnx.json` pairs into `models/voice_models/` and reference them in `model_names.py`. Download voices from [github.com/rhasspy/piper/releases](https://github.com/rhasspy/piper/releases).

### LLM model

Default is `qwen3:1.7b`. Change it in the web config → AI Model section, or edit `settings.json`. Any Ollama model works.

## Web Config

Visit `http://mirror.local` (or the mirror's IP) from any device on the same network. The config page lets you:

- Mirror name and accent colors
- Widget visibility and layout
- Calendar days shown and per-calendar colors
- Alarms — set, cancel, daily repeat, dismiss active alert
- iCloud / Hue / plug credentials
- AI model selection
- Add-Ons — install voice commands and AI responses; toggle STT and TTS independently
- OTA updates

Settings save to `settings.json`. Most take effect immediately without restart.

## Project Structure

```
.
├── main.py                  Entry point — Qt window, layout, threads
├── config.py                Ollama URL, model name, timeouts, log colors
├── model_names.py           Piper voice model paths
├── settings.json            Web-editable settings (auto-created)
├── variables.env            Secrets — iCloud, Hue credentials (not in git)
├── install.sh               Base setup — venv + core Python packages
├── install_voice.sh         Add speech recognition (RealtimeSTT / Whisper)
├── install_ai.sh            Add AI responses (Ollama + Piper TTS)
├── install_shairport.sh     Add AirPlay receiver (shairport-sync)
├── setup_mirror_os.sh       Turn a fresh Ubuntu/Pi OS install into a kiosk
├── requirements-base.txt    Core Python dependencies
│
├── ai/                      Voice pipeline
│   ├── stt.py               Wake-word loop + Whisper transcription
│   ├── tts.py               Piper → aplay streaming playback
│   ├── llm.py               Ollama streaming entry point
│   ├── executer.py          Response streaming + command dispatch
│   ├── keyword_router.py    Fast rule-based intent router (default)
│   └── router.py            LLM router (fallback)
│
├── ui/                      Qt widgets
│   ├── base_widget.py       Shared base class and theme constants
│   ├── terminal.py          Live log + ANSI→HTML + stdout bridge
│   ├── calendar_widget.py   Day-column calendar (reads SQLite)
│   ├── clock_widget.py      Day / time / date with auto-scaling font
│   ├── task_widget.py       Tap-to-complete task list
│   ├── timer_widget.py      Countdown timer (auto-removes when done)
│   ├── alarm_widget.py      Alarms with daily-repeat indicator
│   ├── next_up_widget.py    Next calendar event summary
│   ├── system_info_widget.py CPU, RAM, temp, uptime
│   └── music_widget.py      AirPlay now-playing
│
├── ui_backend/              Data and control
│   ├── calendar_backend.py  iCloud CalDAV → SQLite sync
│   ├── task_backend.py      SQLite task CRUD
│   ├── timer_backend.py     Countdown logic
│   ├── alarm_backend.py     Alarm scheduling with daily repeat
│   ├── audio_backend.py     Looping alert sounds with dismiss
│   ├── music_backend.py     MPRIS D-Bus client for shairport-sync
│   ├── system_info_backend.py psutil stats
│   ├── light_backend.py     Hue / LIFX / Home Assistant
│   ├── plug_backend.py      Kasa / Tapo smart plugs
│   └── ui_control_backend.py Qt signal bus for widget commands
│
├── web_config/
│   ├── server.py            HTTP REST API (Python built-in http.server)
│   └── static/index.html   Single-page dark config UI
│
├── sounds/                  Alert audio (auto-generated on first run)
│   └── klaxon_custom.*      Drop your own alarm sound here (optional)
│
└── models/
    └── voice_models/        Piper .onnx voices (not in git — add your own)
```

## System Requirements

| Component | Minimum |
|-----------|---------|
| OS | Ubuntu 22.04+ or Raspberry Pi OS (64-bit) |
| Python | 3.11+ |
| RAM | 2 GB (4 GB recommended for AI) |
| GPU | Not required — voice control works on CPU (3–8 s latency) |

## License

Copyright © 2026 Theodor Schermann. All rights reserved.

No part of this software, including the source code, documentation, and design,
may be reproduced, distributed, or transmitted in any form or by any means,
including photocopying, recording, or other electronic or mechanical methods,
without the prior written permission of the copyright holder.
See [LICENSE](LICENSE).
