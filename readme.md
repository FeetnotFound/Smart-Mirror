# Smart Mirror Voice Assistant

A voice-driven smart mirror. It listens for the wake word, transcribes speech
locally (Whisper via RealtimeSTT), routes the request with a fast keyword
router, generates a spoken reply with a local LLM (Ollama), and speaks it back
(Piper). The UI is a fullscreen black screen with a terminal in the corner that
shows the live pipeline logs, leaving room for future modules.

## Structure

```
.
├── main.py             Entry point — window, stdout→terminal bridge, threads
├── config.py           Shared config: model names, paths, timeouts, log colors
├── model_names.py      Piper voice model paths
├── requirements.txt
├── readme.md
├── models/             All local model files live here (see Setup)
│   ├── router_models/  Qwen router LoRA + base (only if using ai/router.py)
│   └── voice_models/   Piper .onnx voices (+ .onnx.json)
├── ai/                 Speech + LLM pipeline
│   ├── stt.py          Wake-word loop + Whisper transcription
│   ├── tts.py          Streaming Piper → aplay playback
│   ├── llm.py          Model preload + route-then-stream entry point
│   ├── executer.py     Ollama streaming, sentence splitting, command dispatch
│   ├── keyword_router.py   Active router (rule-based, near-zero latency)
│   └── router.py       Legacy LLM router (unused by default)
└── ui/                 Display modules
    └── terminal.py     Log terminal widget + ANSI→HTML + stdout bridge
```

## Requirements

Python packages: see `requirements.txt`.

System dependencies (not pip):
- **Ollama** running locally, with the response model pulled:
  `ollama pull qwen3:1.7b`
- **Piper** (TTS) available on `PATH` as `piper`.
- **aplay** (ALSA, package `alsa-utils`) for audio playback.
- A **CUDA GPU** is assumed (`device="cuda"` in `ai/stt.py`; Ollama also benefits).
  On CPU-only hardware, change that to `"cpu"` and expect higher latency.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
ollama pull qwen3:1.7b
```

Put model files in `models/`:
- **Piper voices** — the `.onnx` files (and matching `.onnx.json`) referenced in
  `model_names.py`, in `models/voice_models/`, e.g.
  `models/voice_models/jarvis-high.onnx`.
- **Whisper STT** — downloaded automatically by RealtimeSTT on first run
  (default `distil-small.en`); no manual placement needed.
- **Legacy router** (optional, only if you re-enable `ai/router.py`) — in
  `models/router_models/`: `qwen-local-instruct` and `Qwen-Local-Folder`.

Ollama-managed models are stored by Ollama, not in this folder.

## Run

From the project root:

```bash
python main.py
```

Run from the root — `config.py` and `model_names.py` use paths relative to the
working directory. To run a submodule for testing, use module form, e.g.
`python -m ai.stt`.

**Controls:** press **Esc** or **Q** to quit.

## Configuration

- **Wake word** — `HOT_WORDS` in `ai/stt.py` (default `miller`).
- **Whisper model** — `model=` in `ai/stt.py` `_make_recorder()`.
- **Voice** — the model id passed to `speak_sentences(...)` in `ai/stt.py`,
  mapped to a Piper voice in `ai/tts.py` (`_MODEL_MAP`).
- **Response model / Ollama URL / timeouts / paths** — `config.py`.

## Notes

- The active router is `ai/keyword_router.py`. `ai/router.py` (LLM-based) is kept
  for reference but nothing imports it; remove it and its `config.py` paths if
  you're sure you won't revert.
- Unimplemented commands (timers, lights, calendar, …) currently fall back to a
  spoken stub or a normal LLM answer — see `execution_stream` in `ai/executer.py`.
- The terminal uses **SF Mono** with fallbacks; on non-Apple hosts install the
  font or it falls back to DejaVu Sans Mono.