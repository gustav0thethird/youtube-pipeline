#!/usr/bin/env python3
"""
Faceless YouTube video pipeline (100% free / local).

Paste a script (format below) -> get a finished, captioned 1080p MP4.

Stages:
  1. Parse script into segments (split on [VISUAL: ...] tags, [PAUSE] -> silence)
  2. Kokoro TTS  -> per-segment + full voiceover WAV
  3. Pexels      -> download stock clip per [VISUAL] tag (fallback: gradient + text)
  4. Whisper     -> auto SRT captions from the voiceover
  5. FFmpeg      -> time each clip to its narration, concat, mix music, burn captions

SCRIPT FORMAT (plain .txt):
---------------------------------------------------
TITLE: How Compound Interest Quietly Makes You Rich

[VISUAL: aerial city skyline at sunrise, cinematic]
Most people think getting rich takes luck. [PAUSE] It doesn't.

[VISUAL: close up of gold coins stacking on a table]
It takes one boring idea that almost nobody uses on purpose.
---------------------------------------------------

Usage:
  set PEXELS_API_KEY=xxxx            (Windows)  /  export on mac/linux
  python youtube_pipeline.py script.txt --voice af_heart --music bg.mp3
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
import wave
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import numpy as np

# Quiet a harmless Windows-only warning from huggingface_hub about symlinks.
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")


# ----------------------------- ffmpeg locator ------------------------------
def _resolve_ffmpeg():
    """Use system ffmpeg if on PATH, else the one bundled with imageio-ffmpeg."""
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"  # last resort; will error clearly if truly missing


FFMPEG = _resolve_ffmpeg()

# Kokoro model files (auto-downloaded on first run if missing)
_KOKORO_BASE = ("https://github.com/thewh1teagle/kokoro-onnx/releases/download/"
                "model-files-v1.0/")

# RVC voice library: each named voice is <name>.pth (+ optional <name>.index) here.
RVC_DIR = Path(__file__).resolve().parent / "rvc_models"

# ----------------------------- config defaults -----------------------------
W, H, FPS = 1920, 1080, 30    # overwritten to 1080x1920 in --shorts mode
ORIENTATION = "landscape"     # Pexels search orientation; "portrait" for shorts
PAUSE_SECONDS = 0.45          # silence inserted for each [PAUSE]
SENTENCE_GAP = 0.12           # tiny gap between sentences
MUSIC_VOLUME = 0.12           # background music level (0-1)
KOKORO_MODEL = os.environ.get("KOKORO_MODEL", "kokoro-v1.0.onnx")
KOKORO_VOICES = os.environ.get("KOKORO_VOICES", "voices-v1.0.bin")
WHISPER_SIZE = os.environ.get("WHISPER_SIZE", "base")   # tiny/base/small/medium

# Caption look. Horizontal = lower-third; vertical/shorts = big, centred, punchy.
CAPTION_STYLE_H = (
    "FontName=Arial,Fontsize=15,Bold=1,PrimaryColour=&H00FFFFFF,"
    "OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=1,"
    "Alignment=2,MarginV=60"
)
CAPTION_STYLE_V = (
    "FontName=Arial,Fontsize=13,Bold=1,PrimaryColour=&H0000FFFF,"
    "OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=1,"
    "Alignment=2,MarginV=45"
)
# Words per caption line. Fewer = punchier; Shorts uses fewer (set in main()).
CAPTION_MAX_WORDS = 7
CAPTION_STYLE = CAPTION_STYLE_H

# Karaoke captions: the spoken word lights up as it's said (TikTok/Shorts style).
CAPTIONS_KARAOKE = True
CAP_FONT = "Arial"
CAP_SIZE = 15            # landscape; main() sets 13 for shorts
CAP_OUTLINE = 2
CAP_ALIGN = 2            # 2 = bottom-centre
CAP_MARGINV = 60         # landscape; main() sets 45 for shorts
CAP_BASE_BGR = "FFFFFF"  # inactive word colour (white)  -- ASS is &HBBGGRR
CAP_HI_BGR = "00FFFF"    # active word colour (yellow)

# Voiceover "polish": light compression + gentle high-shelf for clarity, then
# loudness-normalise to a consistent, punchy level. This is the single biggest
# thing that makes a Kokoro voice sound produced rather than flat.
VOICE_POLISH = ("acompressor=threshold=-18dB:ratio=3:attack=12:release=120,"
                "highpass=f=70,treble=g=2.5:f=6000,"
                "loudnorm=I=-15:TP=-1.5:LRA=11")


# ============================== 1. PARSER ==================================
def parse_script(text: str):
    """Return (title, [ {visual, narration} ])."""
    title = "video"
    m = re.search(r"^\s*TITLE\s*:\s*(.+)$", text, re.IGNORECASE | re.MULTILINE)
    if m:
        title = m.group(1).strip()
        text = text[m.end():]

    # Split on [VISUAL: ...] keeping the query.
    parts = re.split(r"\[VISUAL\s*:\s*(.*?)\]", text, flags=re.IGNORECASE | re.DOTALL)
    segments = []
    # parts = [pre, query1, body1, query2, body2, ...]
    leading = parts[0].strip()
    rest = parts[1:]
    if leading and not rest:
        # No visual tags at all -> single segment using the title as query.
        segments.append({"visual": title, "narration": clean_narration(leading)})
        return title, segments
    if leading:
        # Narration before the first visual -> attach to a title-based visual.
        segments.append({"visual": title, "narration": clean_narration(leading)})
    for i in range(0, len(rest) - 1, 2):
        query = rest[i].strip()
        body = clean_narration(rest[i + 1])
        if body:
            segments.append({"visual": query, "narration": body})
    return title, segments


def clean_narration(s: str) -> str:
    """Strip markdown / stray metadata lines, keep [PAUSE] markers."""
    out_lines = []
    for line in s.splitlines():
        st = line.strip()
        # Drop obvious metadata lines that sometimes ride along with scripts.
        if re.match(r"^(ESTIMATED RUNTIME|THUMBNAIL|TITLE OPTION|TAGS?|DESCRIPTION|"
                    r"CHAPTER|RUNTIME|\d+\s+thumbnail|\d+\s+title)\b", st, re.IGNORECASE):
            continue
        out_lines.append(line)
    s = "\n".join(out_lines)
    s = re.sub(r"\*\*(.*?)\*\*", r"\1", s)        # bold
    s = re.sub(r"[#*_`>]", "", s)                  # md symbols
    s = re.sub(r"\(\s*[A-Z ]{3,}\s*\)", "", s)     # (STAGE DIRECTIONS)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{2,}", "\n", s)
    return s.strip()


def split_sentences(s: str):
    """Split into (text, pause_after) chunks, honoring [PAUSE]."""
    chunks = []
    for piece in re.split(r"\[PAUSE\]", s, flags=re.IGNORECASE):
        piece = piece.strip()
        if not piece:
            # A [PAUSE] with nothing before it -> extend previous pause.
            if chunks:
                chunks[-1] = (chunks[-1][0], chunks[-1][1] + PAUSE_SECONDS)
            continue
        sents = re.split(r"(?<=[.!?])\s+", piece)
        for snt in sents:
            snt = snt.strip()
            if snt:
                chunks.append((snt, SENTENCE_GAP))
        # pause requested right after this piece
        if chunks:
            chunks[-1] = (chunks[-1][0], chunks[-1][1] + PAUSE_SECONDS)
    return chunks


# ============================== 2. KOKORO TTS ===============================
_KOKORO = None


def _download(url, dest):
    print(f"   downloading {Path(dest).name} ...", flush=True)
    tmp = str(dest) + ".part"

    def hook(blocks, bs, total):
        if total > 0:
            pct = min(100, blocks * bs * 100 // total)
            sys.stdout.write(f"\r   {Path(dest).name}: {pct}%")
            sys.stdout.flush()

    urllib.request.urlretrieve(url, tmp, hook)
    os.replace(tmp, dest)
    print(f"\r   {Path(dest).name}: done.        ", flush=True)


def ensure_models():
    """Download the Kokoro model + voices on first run if they're missing."""
    targets = [(KOKORO_MODEL, _KOKORO_BASE + "kokoro-v1.0.onnx"),
               (KOKORO_VOICES, _KOKORO_BASE + "voices-v1.0.bin")]
    for path, url in targets:
        if not Path(path).exists() or Path(path).stat().st_size == 0:
            try:
                _download(url, path)
            except Exception as e:
                sys.exit(f"[FATAL] Could not download {Path(path).name}: {e}\n"
                         f"Download it manually from:\n  {url}\nand put it next "
                         f"to youtube_pipeline.py")


def get_kokoro():
    global _KOKORO
    if _KOKORO is None:
        from kokoro_onnx import Kokoro
        ensure_models()
        _KOKORO = Kokoro(KOKORO_MODEL, KOKORO_VOICES)
    return _KOKORO


def tts_segment(narration: str, voice: str, speed: float):
    """Return (float32 mono samples, samplerate) for one segment."""
    kok = get_kokoro()
    sr = 24000
    audio = []
    for text, pause in split_sentences(narration):
        samples, sr = kok.create(text, voice=voice, speed=speed, lang="en-us")
        audio.append(np.asarray(samples, dtype=np.float32))
        if pause > 0:
            audio.append(np.zeros(int(sr * pause), dtype=np.float32))
    if not audio:
        audio = [np.zeros(int(sr * 0.3), dtype=np.float32)]
    return np.concatenate(audio), sr


def write_wav(path: Path, samples: np.ndarray, sr: int):
    pcm = np.clip(samples, -1, 1)
    pcm = (pcm * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


# ----------------------------- RVC voice conversion ------------------------
def list_rvc_voices():
    """Names of RVC voices available (one per <name>.pth in rvc_models/)."""
    if not RVC_DIR.exists():
        return []
    return sorted(p.stem for p in RVC_DIR.glob("*.pth"))


def rvc_convert(in_wav: Path, out_wav: Path, name: str, pitch: int, device: str):
    """Convert a wav into the named RVC voice. Returns out_wav, or None on any
    failure (caller then falls back to the raw Kokoro voice)."""
    try:
        from rvc_python.infer import RVCInference
    except Exception as e:
        print(f"[!] RVC not installed ({e}). Run setup_rvc.bat. Using Kokoro voice.")
        return None
    pth = RVC_DIR / f"{name}.pth"
    if not pth.exists():
        print(f"[!] RVC model '{name}.pth' not found in {RVC_DIR}. Using Kokoro voice.")
        return None
    try:
        print(f"[i] RVC: converting voice -> '{name}' on {device} ...")
        rvc = RVCInference(models_dir=str(RVC_DIR), device=device)
        rvc.load_model(name)
        # best-effort param set (API names vary slightly between versions)
        for setter in ("set_params",):
            fn = getattr(rvc, setter, None)
            if fn:
                try:
                    fn(f0method="rmvpe", f0up_key=int(pitch), index_rate=0.66)
                except Exception:
                    pass
        rvc.infer_file(str(in_wav), str(out_wav))
        if Path(out_wav).exists() and Path(out_wav).stat().st_size > 0:
            return out_wav
        print("[!] RVC produced no output. Using Kokoro voice.")
        return None
    except Exception as e:
        print(f"[!] RVC conversion failed ({e}). Using Kokoro voice.")
        return None


# ============================== 3. PEXELS ===================================
# A real browser User-Agent — Pexels' CDN/edge rejects the default urllib UA
# with HTTP 403, so we must send our own.
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


# Filler/style words that hurt Pexels matching — stripped to find core subject.
_STOP = {"a", "an", "the", "of", "with", "shot", "very", "slow", "fast", "closeup",
         "close", "up", "cinematic", "clean", "minimal", "style", "footage", "shallow",
         "depth", "field", "warm", "cool", "morning", "evening", "golden", "light",
         "over", "time", "content", "beautiful", "view", "scene", "background",
         "aerial", "drone", "animated", "abstract", "and", "in", "on", "at"}


def _query_variants(query: str):
    """From a rich [VISUAL] description, produce progressively simpler queries."""
    base = query.split(",")[0].strip()                      # drop style clause
    words = [w for w in re.findall(r"[a-zA-Z]+", query.lower()) if len(w) > 2]
    keep = [w for w in words if w not in _STOP]
    out = []
    for v in (base, " ".join(keep[:4]), " ".join(keep[:2]), keep[0] if keep else ""):
        v = v.strip()
        if v and v not in out:
            out.append(v)
    return out or [query.strip()]


def _pexels_search(query: str, orientation: str, api_key: str):
    import urllib.request, urllib.parse, json
    url = ("https://api.pexels.com/videos/search?per_page=10&size=medium&query="
           + urllib.parse.quote(query))
    if orientation:
        url += "&orientation=" + orientation
    req = urllib.request.Request(
        url, headers={"Authorization": api_key, "User-Agent": _UA,
                      "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode())
    best, best_score = None, -10 ** 9
    for vid in data.get("videos", []):
        for f in vid.get("video_files", []):
            if f.get("file_type") != "video/mp4":
                continue
            score = -abs((f.get("width") or 0) - W)   # prefer files near our width
            if score > best_score:
                best_score, best = score, f.get("link")
    return best


def fetch_pexels_clip(query: str, out_path: Path, api_key: str) -> bool:
    import urllib.request
    import urllib.error
    # Try our orientation first, then ANY orientation (we crop to fit anyway).
    orients = [ORIENTATION, ""] if ORIENTATION else [""]
    link = None
    try:
        for q in _query_variants(query):
            for orient in orients:
                try:
                    link = _pexels_search(q, orient, api_key)
                except urllib.error.HTTPError as he:
                    if getattr(he, "code", None) == 403:
                        print("   [pexels] 403 Forbidden — your API key is being "
                              "rejected. Recopy it from pexels.com/api.")
                        return False
                    raise
                if link:
                    break
            if link:
                break
        if not link:
            print(f"   [pexels] no clip found for '{query}' (using gradient).")
            return False
        dreq = urllib.request.Request(link, headers={"User-Agent": _UA})
        with urllib.request.urlopen(dreq, timeout=60) as resp, open(out_path, "wb") as fh:
            fh.write(resp.read())
        return out_path.exists() and out_path.stat().st_size > 0
    except Exception as e:
        print(f"   [pexels] '{query}' failed: {e}")
        return False


# ============================== 4. WHISPER ==================================
def srt_time(t: float) -> str:
    h = int(t // 3600); t -= h * 3600
    m = int(t // 60); t -= m * 60
    s = int(t); ms = int((t - s) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _ass_time(t: float) -> str:
    if t < 0:
        t = 0
    h = int(t // 3600); t -= h * 3600
    m = int(t // 60); t -= m * 60
    s = int(t); cs = int(round((t - s) * 100))
    if cs == 100:
        cs = 0; s += 1
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def _ass_header() -> str:
    base = f"&H00{CAP_BASE_BGR}"
    return (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "PlayResX: 384\n"
        "PlayResY: 288\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, "
        "ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
        "MarginL, MarginR, MarginV, Encoding\n"
        f"Style: K,{CAP_FONT},{CAP_SIZE},{base},{base},&H00000000,&H64000000,"
        f"1,0,0,0,100,100,0,0,1,{CAP_OUTLINE},1,{CAP_ALIGN},24,24,{CAP_MARGINV},1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, Effect, Text\n"
    )


def _ass_line(words, active_idx):
    """Render a caption line with one word highlighted."""
    parts = []
    for k, w in enumerate(words):
        # Strip brackets, whitespace, AND any lingering punctuation from the word
        txt = w.replace("{", "").replace("}", "").strip(" ,.;:!?…-—\"'")
        
        if k == active_idx:
            parts.append(f"{{\\c&H{CAP_HI_BGR}&}}{txt}{{\\c&H{CAP_BASE_BGR}&}}")
        else:
            parts.append(txt)
    return " ".join(parts)
def make_captions(voiceover: Path, srt_path: Path, max_words=None, ass_path=None):
    if max_words is None:
        max_words = CAPTION_MAX_WORDS
    from faster_whisper import WhisperModel
    model = WhisperModel(WHISPER_SIZE, device="cpu", compute_type="int8")
    segments, _ = model.transcribe(str(voiceover), word_timestamps=True)

    groups = []   # each: list of (word, start, end)
    plain = []    # each: (start, end, text)  for the SRT fallback
    for seg in segments:
        words = []

        for w in (seg.words or []):
            if not w.word:
                continue

            t = w.word

            # normalize unicode weirdness + strip spaces
            t = t.strip()

            # remove punctuation attached to word boundaries
            t = re.sub(r"^\W+|\W+$", "", t)

            # final safety: keep only word characters + apostrophes
            t = re.sub(r"[^\w']", "", t)

            if not re.search(r"[a-zA-Z0-9]", t):
                continue

            words.append((t, float(w.start), float(w.end)))
        if not words:
            txt = seg.text.strip().lstrip(",.;:!?…-— ")
            if txt:
                plain.append((seg.start, seg.end, txt))
            continue
        for i in range(0, len(words), max_words):
                    g = words[i:i + max_words]
                    groups.append(g)
                    start = g[0][1]
                    end = g[-1][2]
                    # Clean up any leading commas or spaces from the final joined phrase
                    joined_text = " ".join(t for t, _, _ in g).lstrip(", ")
                    plain.append((start, end, joined_text))

    # plain SRT (always written; used as a fallback and as a YouTube upload file)
    with open(srt_path, "w", encoding="utf-8") as f:
        for n, (a, b, txt) in enumerate((p for p in plain if p[2]), 1):
            f.write(f"{n}\n{srt_time(a)} --> {srt_time(b)}\n{txt}\n\n")

    # karaoke ASS (one event per word: the line shown with that word highlighted)
    if ass_path is not None and CAPTIONS_KARAOKE and groups:
        with open(ass_path, "w", encoding="utf-8") as f:
            f.write(_ass_header())
            for g in groups:
                wordsonly = [t for t, _, _ in g]
                for j, (_, ws, we) in enumerate(g):
                    end = g[j + 1][1] if j + 1 < len(g) else we   # hold until next word
                    if end <= ws:
                        end = ws + 0.05
                    text = _ass_line(wordsonly, j)
                    f.write(f"Dialogue: 0,{_ass_time(ws)},{_ass_time(end)},K,,0,0,0,,{text}\n")
        return ass_path
    return srt_path


# ============================== 5. FFMPEG ===================================
def run(cmd, **kw):
    p = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if p.returncode != 0:
        print("FFMPEG ERROR:\n", " ".join(str(c) for c in cmd))
        print(p.stderr[-1500:])
        raise RuntimeError("ffmpeg failed")
    return p


def wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / float(w.getframerate())


def make_segment_video(clip, out: Path, duration: float, label: str):
    """Normalize a clip to 1080p/30fps and set it to exactly `duration` sec."""
    if clip and Path(clip).exists() and Path(clip).stat().st_size > 0:
        vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase,"
              f"crop={W}:{H},fps={FPS},setsar=1")
        run([FFMPEG, "-y", "-stream_loop", "-1", "-i", str(clip),
             "-t", f"{duration:.3f}", "-vf", vf, "-an",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)])
    else:
        # Fallback: a slowly shifting dark-blue gradient (no text, so no font
        # dependency). Used when Pexels has no clip for this [VISUAL].
        run([FFMPEG, "-y", "-f", "lavfi",
             "-i", (f"gradients=s={W}x{H}:c0=0x14213d:c1=0x0a0a23:"
                    f"x0=0:y0=0:x1={W}:y1={H}:d={duration:.3f}:speed=0.02"),
             "-t", f"{duration:.3f}", "-vf", f"fps={FPS},setsar=1", "-an",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)])


def concat_videos(seg_files, out: Path, build: Path):
    listf = build / "concat.txt"
    listf.write_text("".join(f"file '{f.name}'\n" for f in seg_files), encoding="utf-8")
    run([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", listf.name,
         "-c", "copy", out.name], cwd=build)


def build_audio(voiceover: Path, music, out: Path, build: Path):
    if music and Path(music).exists():
        # polish the voice, duck-mix the (quieter) music under it.
        run([FFMPEG, "-y", "-i", voiceover.name,
             "-stream_loop", "-1", "-i", str(Path(music).resolve()),
             "-filter_complex",
             f"[0:a]{VOICE_POLISH}[v];[1:a]volume={MUSIC_VOLUME}[m];"
             f"[v][m]amix=inputs=2:duration=first:dropout_transition=2[a]",
             "-map", "[a]", out.name], cwd=build)
    else:
        run([FFMPEG, "-y", "-i", voiceover.name, "-af", VOICE_POLISH,
             "-c:a", "pcm_s16le", out.name], cwd=build)


def final_render(video: Path, audio: Path, subs: Path, out: Path, build: Path):
    # .ass already carries its own styling (karaoke); .srt needs force_style.
    if subs.suffix.lower() == ".ass":
        vf = f"subtitles={subs.name}"
    else:
        vf = f"subtitles={subs.name}:force_style='{CAPTION_STYLE}'"
    run([FFMPEG, "-y", "-i", video.name, "-i", audio.name,
         "-vf", vf, "-map", "0:v", "-map", "1:a",
         "-c:v", "libx264", "-preset", "medium", "-crf", "20",
         "-c:a", "aac", "-b:a", "192k", "-pix_fmt", "yuv420p",
         "-shortest", out.name], cwd=build)


# ============================== ORCHESTRATION ===============================
def apply_layout(shorts: bool):
    """Set the global video/caption layout for landscape vs vertical (shorts)."""
    global W, H, ORIENTATION, CAPTION_STYLE, CAPTION_MAX_WORDS, CAP_SIZE, CAP_MARGINV
    if shorts:
        W, H = 1080, 1920
        ORIENTATION = "portrait"
        CAPTION_STYLE = CAPTION_STYLE_V
        CAPTION_MAX_WORDS = 4
        CAP_SIZE, CAP_MARGINV = 13, 45
        print("[i] SHORTS mode: vertical 1080x1920, portrait footage, bottom captions.")


def render_from_voiceover(slug, seg_durs, voiceover, outdir, build,
                          pexels_key, music, no_captions):
    """Build footage to the saved per-segment durations, then caption + render.
    `voiceover` is the audio to use (raw Kokoro, or an Applio-converted file)."""
    if not pexels_key:
        print("[!] No Pexels key -> gradient backgrounds.")
    seg_videos = [None] * len(seg_durs)

    def process_seg(i):
        seg = seg_durs[i]
        visual = seg["visual"]
        print(f"[{i+1}/{len(seg_durs)}] footage: {visual[:50]}")

        clip = build / f"clip_{i:03d}.mp4"
        ok = False

        if pexels_key:
            ok = fetch_pexels_clip(seg["visual"], clip, pexels_key)

        seg_vid = build / f"segvid_{i:03d}.mp4"
        make_segment_video(
            clip if ok else None,
            seg_vid,
            float(seg["dur"]),
            seg["visual"]
        )

        seg_videos[i] = seg_vid

    with ThreadPoolExecutor(max_workers=6) as ex:
        ex.map(process_seg, range(len(seg_durs)))

    video_track = build / "video_track.mp4"
    concat_videos(seg_videos, video_track, build)

    srt = build / "subs.srt"
    ass = build / "subs.ass"
    burn = srt
    if not no_captions:
        print("[i] transcribing captions with Whisper...")
        burn = make_captions(Path(voiceover), srt, ass_path=ass)
    else:
        srt.write_text("", encoding="utf-8")

    final_audio = build / "final_audio.wav"
    build_audio(Path(voiceover), music, final_audio, build)

    final = outdir / f"{slug}.mp4"

    def render_plain():
        run([FFMPEG, "-y", "-i", video_track.name, "-i", final_audio.name,
             "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-crf", "20",
             "-c:a", "aac", "-b:a", "192k", "-pix_fmt", "yuv420p", "-shortest",
             str(final)], cwd=build)

    if no_captions:
        render_plain()
    else:
        try:
            final_render(video_track, final_audio, burn, build / final.name, build)
            (build / final.name).replace(final)
        except Exception as e:
            print(f"[!] burning captions failed ({e}). Exporting WITHOUT burned-in "
                  f"captions and saving the subtitle file instead.")
            render_plain()
            try:
                shutil.copyfile(srt, outdir / f"{slug}.srt")
                print(f"[i] subtitles saved: {outdir / (slug + '.srt')}")
            except Exception:
                pass

    print(f"\n[DONE] {final}")


def main():
    ap = argparse.ArgumentParser(description="Faceless YouTube video pipeline")
    ap.add_argument("script", nargs="?", help="path to the script .txt file")
    ap.add_argument("--voice", default="af_heart", help="Kokoro voice id")
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--music", default=None, help="background music file (optional)")
    ap.add_argument("--outdir", default="output")
    ap.add_argument("--no-captions", action="store_true")
    ap.add_argument("--shorts", action="store_true",
                    help="vertical 1080x1920 output for YouTube Shorts / Reels / TikTok")
    # Applio (external GPU voice conversion) two-phase flow:
    ap.add_argument("--voiceover-only", action="store_true",
                    help="phase 1: make the Kokoro voiceover + project file, then stop "
                         "so you can convert it in Applio")
    ap.add_argument("--finish-audio", default=None,
                    help="phase 2: finish the video using this (Applio-converted) wav "
                         "plus the saved project file")
    args = ap.parse_args()

    pexels_key = os.environ.get("PEXELS_API_KEY", "").strip()
    outdir = Path(args.outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    proj_path = outdir / "_applio_project.json"
    applio_wav = outdir / "_applio_voiceover.wav"

    # ---------- PHASE 2: finish with an externally-converted voice ----------
    if args.finish_audio:
        if not proj_path.exists():
            sys.exit("[FATAL] No project file. Run the voiceover step first.")
        proj = json.loads(proj_path.read_text(encoding="utf-8"))
        apply_layout(proj.get("shorts", False))
        slug = proj["slug"]
        build = outdir / f"build_{slug}"
        build.mkdir(parents=True, exist_ok=True)
        print(f"[i] finishing '{proj['title']}' with converted voice: {args.finish_audio}")
        render_from_voiceover(slug, proj["segments"], args.finish_audio, outdir, build,
                              pexels_key, proj.get("music"), proj.get("no_captions", False))
        return

    # ---------- shared: read + voice the script ----------
    if not args.script:
        sys.exit("[FATAL] No script provided.")
    apply_layout(args.shorts)
    text = Path(args.script).read_text(encoding="utf-8")
    title, segments = parse_script(text)
    if not segments:
        sys.exit("[FATAL] No narration found in script.")
    slug = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")[:50] or "video"
    build = outdir / f"build_{slug}"
    build.mkdir(parents=True, exist_ok=True)
    print(f"[i] '{title}'  ->  {len(segments)} segments")

    full_audio, sr = [], 24000
    seg_durs = []
    for i, seg in enumerate(segments):
        print(f"[{i+1}/{len(segments)}] voicing: {seg['visual'][:50]}")
        samples, sr = tts_segment(seg["narration"], args.voice, args.speed)
        full_audio.append(samples)
        seg_durs.append({"visual": seg["visual"], "dur": len(samples) / sr})

    # ---------- PHASE 1: make voiceover + project, then stop (Applio) ----------
    if args.voiceover_only:
        write_wav(applio_wav, np.concatenate(full_audio), sr)
        proj_path.write_text(json.dumps({
            "title": title, "slug": slug, "shorts": args.shorts,
            "no_captions": args.no_captions, "music": args.music,
            "segments": seg_durs}, indent=2), encoding="utf-8")
        total = wav_duration(applio_wav)
        print(f"[i] voiceover ready ({total:.1f}s): {applio_wav}")
        print("[i] Convert this WAV in Applio with your voice model, then run the "
              "finish step with the converted file.")
        return

    # ---------- normal one-shot run (Kokoro voice) ----------
    voiceover = build / "voiceover.wav"
    write_wav(voiceover, np.concatenate(full_audio), sr)
    print(f"[i] total voiceover: {wav_duration(voiceover):.1f}s")
    render_from_voiceover(slug, seg_durs, voiceover, outdir, build,
                          pexels_key, args.music, args.no_captions)


if __name__ == "__main__":
    main()
