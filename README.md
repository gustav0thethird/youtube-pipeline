# YouTubePipeline

> **Experimental** - This project is a work in progress. Expect rough edges and breaking changes.

A local, fully free pipeline for generating faceless YouTube videos from a plain-text script. No subscriptions, no cloud rendering, no SaaS. Everything runs on your machine.

---

## What it does

You write (or generate) a script. The pipeline handles the rest:

```
Script (.txt)
    │
    ├─ 1. TTS        Kokoro ONNX generates the voiceover locally
    ├─ 2. Footage    Pexels API pulls matching stock clips per scene
    ├─ 3. Captions   Whisper transcribes and builds karaoke-style subtitles
    └─ 4. Render     FFmpeg assembles everything into a finished MP4
```

Output: a captioned 1080p MP4 (or 1080×1920 for Shorts/Reels/TikTok), typically in 3–8 minutes on a normal laptop.

---

## Use case

This is aimed at people who want to produce faceless educational or informational YouTube content - explainers, finance, history, tech - without paying for voiceover artists, footage subscriptions, or video editors. The pipeline automates the production bottleneck so you can focus on writing good scripts and publishing consistently.

It does **not** guarantee views or revenue. Treat it as a tool that removes friction, not a magic money machine.

---

## What you need

- Python 3.10–3.12
- FFmpeg on your PATH
- A free [Pexels API key](https://www.pexels.com/api/) - optional, plain gradient backgrounds are used as fallback
- ~500 MB disk space for the Kokoro model files (downloaded automatically on first run)

**[Full setup guide → SETUP_WINDOWS.md](SETUP_WINDOWS.md)**

---

## Quick start

```bash
# 1. Install dependencies
setup.bat          # Windows one-click
# or: pip install -r requirements.txt

# 2. Set your Pexels key (optional)
set PEXELS_API_KEY=your_key_here

# 3. Run on a script
python youtube_pipeline.py example_script.txt --voice am_adam --speed 1.1
```

Output lands in `output/<title>.mp4`.

### GUI

Double-click `studio.pyw` (or `Make Video.bat`). Paste your script, pick a voice, click **Make Video**.

---

## Script format

Scripts are plain `.txt` files. Use `[VISUAL: ...]` tags to mark scene changes and `[PAUSE]` for natural beats. See `SCRIPT_PROMPT.md` for a prompt you can paste into any LLM to generate a correctly-formatted script.

```
TITLE: How Compound Interest Quietly Makes You Rich

[VISUAL: aerial city skyline at sunrise, cinematic]
Most people think getting rich takes luck. [PAUSE] It doesn't.

[VISUAL: close up of gold coins stacking on a table]
It takes one boring idea that almost nobody uses on purpose.
```

`example_script.txt` is a ready-to-run sample.

---

## Voices

Kokoro ships with several built-in voices:

| ID | Style |
|---|---|
| `af_heart`, `af_bella`, `af_nicole` | US female |
| `am_michael`, `am_fenrir`, `am_adam` | US male |
| `bf_emma` | UK female |
| `bm_george` | UK male |

You can also drop in an RVC `.pth` model for a custom voice - the GUI detects it automatically, or use `--voiceover-only` / `--finish-audio` on the CLI.

---

## Options

| Flag | Description |
|---|---|
| `--voice` | Kokoro voice ID (default `af_heart`) |
| `--speed` | Speech speed multiplier (default `1.0`) |
| `--shorts` | Vertical 1080×1920 output |
| `--no-captions` | Skip caption generation |
| `--music` | Background music file (MP3/WAV, loops to fit) |
| `--voiceover-only` | Phase 1: export voiceover WAV, stop before rendering |
| `--finish-audio` | Phase 2: finish render with a pre-converted voiceover |

---

## Troubleshooting

See the **[Troubleshooting section in SETUP_WINDOWS.md](SETUP_WINDOWS.md#if-something-breaks)** for common errors (FFmpeg not found, missing model files, gradient fallback, caption drift).

---

## License

MIT
