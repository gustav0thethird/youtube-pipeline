# Faceless YouTube Pipeline - Windows Setup

Paste a script → get a finished, captioned 1080p MP4. Everything here is free.

## What's in the box

| File | What it is |
|------|-----------|
| `youtube_pipeline.py` | the pipeline (TTS → footage → captions → render) |
| `SCRIPT_PROMPT.md` | the prompt you paste into Claude to generate a script |
| `example_script.txt` | a ready-to-run sample script (correct format) |
| `make_video.bat` | one-click runner (set your key once, then double-clickable) |
| `requirements.txt` | Python packages |

---

## One-time setup (about 15 minutes)

### 1. Install Python
Download Python 3.10–3.12 from https://www.python.org/downloads/
**On the first install screen, tick "Add python.exe to PATH."**

### 2. Install FFmpeg
- Download a build from https://www.gyan.dev/ffmpeg/builds/ (the "release essentials" zip).
- Unzip it, e.g. to `C:\ffmpeg`, so that `C:\ffmpeg\bin\ffmpeg.exe` exists.
- Add `C:\ffmpeg\bin` to your PATH:
  Start → "Edit the system environment variables" → Environment Variables →
  under *User variables* edit **Path** → New → `C:\ffmpeg\bin` → OK.
- Open a **new** Command Prompt and confirm: `ffmpeg -version`

### 3. Install the Python packages
Open Command Prompt in this folder (type `cmd` in the folder's address bar) and run:
```
pip install -r requirements.txt
```

### 4. Download the Kokoro voice model (two files)
Put both in this same folder, next to `youtube_pipeline.py`:
- `kokoro-v1.0.onnx`  (~310 MB)
- `voices-v1.0.bin`   (~27 MB)

Get them from the kokoro-onnx releases page:
https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.0
(Click `kokoro-v1.0.onnx` and `voices-v1.0.bin` to download.)

### 5. Get a free Pexels API key
- Sign up at https://www.pexels.com/api/ (free, no card).
- Copy your key.
- Open `make_video.bat` in Notepad and paste it into the `PEXELS_API_KEY=` line.

That's it. The Whisper caption model downloads itself automatically the first time.

---

## Making a video

1. **Write the script.** Open `SCRIPT_PROMPT.md`, copy the prompt, paste it into
   Claude, fill in your topic/niche/length. Claude returns a formatted script.
2. **Save it** as a plain text file, e.g. `my_script.txt` (everything from the
   `TITLE:` line down to the last narration line - drop any metadata section).
3. **Run it.** Drag your script onto `make_video.bat`, or in Command Prompt:
   ```
   make_video.bat my_script.txt
   ```
   With background music:
   ```
   make_video.bat my_script.txt music.mp3
   ```
4. Your finished video appears in the `output` folder as `<title>.mp4`.

First run downloads the Whisper model (~140 MB for `base`) once. After that a
typical 5-minute video renders in roughly 3–8 minutes on a normal laptop.

---

## Picking a voice
Pass any of these after `--voice` (or set `VOICE=` in the .bat). A few good ones:
- `af_heart`, `af_bella`, `af_nicole` - US female
- `am_michael`, `am_fenrir` - US male
- `bf_emma` - UK female, `bm_george` - UK male

Use the **same** voice on every video so your channel sounds consistent - that's
the thing the guide warns about (don't sound like every other AI channel).

---

## Tuning (top of `youtube_pipeline.py`)
- `PAUSE_SECONDS` - how long each `[PAUSE]` lasts (default 0.45s)
- `MUSIC_VOLUME` - background music level (default 0.12)
- `CAPTION_STYLE` - caption font/size/colour (ASS style string)
- `WHISPER_SIZE` env var - `tiny` (fastest) → `base` → `small` (most accurate)

Command-line flags:
- `--voice af_bella` pick a voice
- `--speed 1.1` speak faster/slower
- `--music bg.mp3` background track (loops to fit)
- `--no-captions` skip burned captions

---

## If something breaks
- **`ffmpeg is not recognized`** → FFmpeg isn't on PATH. Redo step 2, open a new terminal.
- **`Kokoro model files not found`** → the two model files aren't in this folder (step 4).
- **Gradient backgrounds instead of footage** → Pexels key missing/invalid, or that
  `[VISUAL]` phrase returned no clips. Make the visual descriptions more generic.
- **espeak / phonemizer error** (rare) → install espeak-ng from
  https://github.com/espeak-ng/espeak-ng/releases and reboot.
- **Captions slightly off** → use a larger `WHISPER_SIZE` (`small`).

---

## Honest expectations
This automates the *production* bottleneck - voice, footage, captions, assembly.
It does **not** guarantee views or income; the revenue figures in guides like the
one you read are best-case marketing numbers. Treat this as a tool that lets you
publish consistently and cheaply, which is the part that actually matters early on.
Always check that your music is cleared for monetization (YouTube Audio Library
is safest) and review each video before uploading.
