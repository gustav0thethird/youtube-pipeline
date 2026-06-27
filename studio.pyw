#!/usr/bin/env python3
"""
Faceless YouTube Studio - paste a script, get a video.

Double-click this file (studio.pyw) OR run "Make Video.bat".
Paste your script into the box, pick a voice, click Make Video.
On first launch it installs anything missing and downloads the voice model.
Your Pexels key is remembered after the first time (config.json).
"""

import importlib.util
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

HERE = Path(__file__).resolve().parent
PIPELINE = HERE / "youtube_pipeline.py"
CONFIG = HERE / "config.json"
TMP_SCRIPT = HERE / "_pasted_script.txt"
RVC_DIR = HERE / "rvc_models"

KOKORO_VOICES = [
    "af_heart", "af_bella", "af_nicole",
    "am_michael", "am_fenrir",
    "bf_emma", "bm_george",
    "af_sarah", "am_adam"
]
WHISPER_SIZES = ["tiny", "base", "small"]


def rvc_voice_names():
    """Names of installed RVC voices (one per <name>.pth in rvc_models/)."""
    if not RVC_DIR.exists():
        return []
    return sorted(p.stem for p in RVC_DIR.glob("*.pth"))


def all_voice_choices():
    rvc = rvc_voice_names()
    return KOKORO_VOICES + ([f"RVC: {n}" for n in rvc] if rvc else [])


def load_config():
    if CONFIG.exists():
        try:
            return json.loads(CONFIG.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_config(cfg):
    try:
        CONFIG.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    except Exception:
        pass


class Studio:
    def __init__(self, root):
        self.root = root
        self.q = queue.Queue()
        self.proc = None
        cfg = load_config()

        root.title("Faceless YouTube Studio")
        root.geometry("820x720")
        root.minsize(680, 600)

        pad = {"padx": 10, "pady": 4}

        tk.Label(root, text="Paste your script below  (TITLE: ... then [VISUAL: ...] blocks)",
                 font=("Segoe UI", 11, "bold")).pack(anchor="w", **pad)

        self.text = tk.Text(root, height=20, wrap="word", font=("Consolas", 10), undo=True)
        self.text.pack(fill="both", expand=True, padx=10)
        self.text.insert("1.0", "TITLE: \n\n[VISUAL: ]\n")

        # ---- options row ----
        opt = tk.Frame(root)
        opt.pack(fill="x", **pad)

        tk.Label(opt, text="Voice:").grid(row=0, column=0, sticky="e")
        self.voice = ttk.Combobox(opt, values=all_voice_choices(), width=16, state="readonly")
        self.voice.set(cfg.get("voice", "af_heart"))
        self.voice.grid(row=0, column=1, padx=(4, 6))
        tk.Button(opt, text="+ Add RVC voice", command=self.add_rvc_voice).grid(
            row=0, column=2, padx=(0, 16))

        tk.Label(opt, text="Captions:").grid(row=0, column=4, sticky="e")
        self.whisper = ttk.Combobox(opt, values=WHISPER_SIZES, width=8, state="readonly")
        self.whisper.set(cfg.get("whisper", "base"))
        self.whisper.grid(row=0, column=5, padx=(4, 16))

        self.captions_on = tk.BooleanVar(value=cfg.get("captions", True))
        tk.Checkbutton(opt, text="Burn captions", variable=self.captions_on).grid(
            row=0, column=6, padx=(0, 16))

        # second options row
        opt2 = tk.Frame(root)
        opt2.pack(fill="x", **pad)

        tk.Label(opt2, text="Speed:").grid(row=0, column=0, sticky="e")
        self.speed = ttk.Combobox(opt2, values=["0.9", "1.0", "1.05", "1.1", "1.15", "1.2"],
                                  width=6, state="readonly")
        self.speed.set(cfg.get("speed", "1.1"))
        self.speed.grid(row=0, column=1, padx=(4, 16))

        self.shorts_on = tk.BooleanVar(value=cfg.get("shorts", False))
        tk.Checkbutton(opt2, text="Shorts (vertical 9:16)", variable=self.shorts_on).grid(
            row=0, column=2, padx=(0, 16))

        # ---- pexels key ----
        keyf = tk.Frame(root)
        keyf.pack(fill="x", **pad)
        tk.Label(keyf, text="Pexels API key:").pack(side="left")
        self.key = tk.Entry(keyf, show="*")
        self.key.insert(0, cfg.get("pexels_key", ""))
        self.key.pack(side="left", fill="x", expand=True, padx=6)

        # ---- music ----
        musf = tk.Frame(root)
        musf.pack(fill="x", **pad)
        tk.Label(musf, text="Music (optional):").pack(side="left")
        self.music = tk.Entry(musf)
        self.music.insert(0, cfg.get("music", ""))
        self.music.pack(side="left", fill="x", expand=True, padx=6)
        tk.Button(musf, text="Browse", command=self.pick_music).pack(side="left")

        # ---- buttons ----
        btnf = tk.Frame(root)
        btnf.pack(fill="x", **pad)
        self.run_btn = tk.Button(btnf, text="  Make Video  ", command=self.start,
                                 bg="#cc0000", fg="white", font=("Segoe UI", 11, "bold"),
                                 state="disabled")
        self.run_btn.pack(side="left")
        self.open_btn = tk.Button(btnf, text="Open output folder", command=self.open_output)
        self.open_btn.pack(side="left", padx=8)

        # ---- log ----
        self.log = tk.Text(root, height=9, bg="#111", fg="#0f0",
                           font=("Consolas", 9), state="disabled")
        self.log.pack(fill="both", expand=False, padx=10, pady=(4, 10))

        self.root.after(120, self.drain)
        self.root.after(300, self.bootstrap)

    # ---------- RVC voice library ----------
    def add_rvc_voice(self):
        pth = filedialog.askopenfilename(title="Select the RVC model (.pth)",
                                         filetypes=[("RVC model", "*.pth"), ("All", "*.*")])
        if not pth:
            return
        index = filedialog.askopenfilename(
            title="Select the matching .index (optional — Cancel to skip)",
            filetypes=[("RVC index", "*.index"), ("All", "*.*")])
        win = tk.Toplevel(self.root)
        win.title("Name this voice")
        win.geometry("340x120")
        win.transient(self.root)
        tk.Label(win, text="Voice name (e.g. Narrator):").pack(anchor="w", padx=12, pady=(12, 2))
        name_var = tk.StringVar()
        ent = tk.Entry(win, textvariable=name_var)
        ent.pack(fill="x", padx=12)
        ent.focus_set()

        def save():
            import re
            import shutil
            name = re.sub(r"[^A-Za-z0-9 _-]", "", name_var.get()).strip()
            if not name:
                messagebox.showwarning("Name needed", "Please type a name.")
                return
            RVC_DIR.mkdir(exist_ok=True)
            try:
                shutil.copyfile(pth, RVC_DIR / f"{name}.pth")
                if index:
                    shutil.copyfile(index, RVC_DIR / f"{name}.index")
            except Exception as e:
                messagebox.showerror("Copy failed", str(e))
                return
            self.voice.configure(values=all_voice_choices())
            self.voice.set(f"RVC: {name}")
            self.logline(f">>> Added RVC voice '{name}'. Selected it.")
            win.destroy()

        tk.Button(win, text="Save", command=save).pack(pady=10)
        win.bind("<Return>", lambda e: save())

    # ---------- helpers ----------
    def pick_music(self):
        f = filedialog.askopenfilename(
            title="Pick a background music file",
            filetypes=[("Audio", "*.mp3 *.wav *.m4a *.aac"), ("All", "*.*")])
        if f:
            self.music.delete(0, "end")
            self.music.insert(0, f)

    def open_output(self):
        out = HERE / "output"
        out.mkdir(exist_ok=True)
        try:
            os.startfile(str(out))  # Windows
        except AttributeError:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(out)])

    def logline(self, s):
        self.log.configure(state="normal")
        self.log.insert("end", s + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    # ---------- first-run setup ----------
    def is_ready(self):
        models = ((HERE / "kokoro-v1.0.onnx").exists()
                  and (HERE / "voices-v1.0.bin").exists())
        try:
            deps = all(importlib.util.find_spec(m) is not None
                       for m in ("kokoro_onnx", "faster_whisper", "numpy"))
        except Exception:
            deps = False
        ff = bool(shutil.which("ffmpeg"))
        if not ff:
            try:
                ff = importlib.util.find_spec("imageio_ffmpeg") is not None
            except Exception:
                ff = False
        return models and deps and ff

    def bootstrap(self):
        try:
            ready = self.is_ready()
        except Exception:
            ready = False
        if ready:
            self.run_btn.configure(state="normal")
            self.logline(">>> Ready. Paste a script and click Make Video.")
            return
        self.run_btn.configure(state="disabled", text="  Setting up...  ")
        self.logline(">>> First-time setup: installing packages and downloading the "
                     "voice model (a few minutes, one time only)...")
        threading.Thread(target=self._setup_worker, daemon=True).start()

    def _setup_worker(self):
        try:
            steps = [
                [sys.executable, "-m", "pip", "install", "-r", str(HERE / "requirements.txt")],
                [sys.executable, "-c", "import youtube_pipeline as p; p.ensure_models()"],
            ]
            for cmd in steps:
                p = subprocess.Popen(
                    cmd, cwd=str(HERE),
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=1,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                for line in p.stdout:
                    self.q.put(("log", line.rstrip()))
                p.wait()
                if p.returncode != 0:
                    self.q.put(("setup", 1))
                    return
            self.q.put(("setup", 0))
        except Exception as e:
            self.q.put(("log", f"setup error: {e}"))
            self.q.put(("setup", 1))

    # ---------- render ----------
    def start(self):
        if self.proc is not None:
            messagebox.showinfo("Busy", "A video is already rendering.")
            return
        script = self.text.get("1.0", "end").strip()
        if "TITLE:" not in script.upper() or "[VISUAL" not in script.upper():
            messagebox.showwarning(
                "Check the script",
                "The script needs a 'TITLE:' line and at least one [VISUAL: ...] tag.\n\n"
                "Use the prompt in SCRIPT_PROMPT.md to generate one.")
            return
        if not PIPELINE.exists():
            messagebox.showerror("Missing file",
                                 f"Can't find youtube_pipeline.py next to this app:\n{PIPELINE}")
            return

        TMP_SCRIPT.write_text(script, encoding="utf-8")

        cfg = {
            "voice": self.voice.get(),
            "whisper": self.whisper.get(),
            "captions": self.captions_on.get(),
            "pexels_key": self.key.get().strip(),
            "music": self.music.get().strip(),
            "speed": self.speed.get(),
            "shorts": self.shorts_on.get(),
        }
        save_config(cfg)

        sel = cfg["voice"]
        if sel.startswith("RVC: "):
            # RVC voice: Kokoro speaks with a neutral base, then convert to the model.
            rvc_name = sel[len("RVC: "):]
            cmd = [sys.executable, str(PIPELINE), str(TMP_SCRIPT),
                   "--voice", "af_heart", "--speed", str(cfg["speed"]),
                   "--rvc", rvc_name]
            self.logline(f">>> RVC voice '{rvc_name}' (GPU). First run downloads "
                         f"RVC helper models, so it may take longer.")
        else:
            cmd = [sys.executable, str(PIPELINE), str(TMP_SCRIPT),
                   "--voice", sel, "--speed", str(cfg["speed"])]
        if not cfg["captions"]:
            cmd.append("--no-captions")
        if cfg["shorts"]:
            cmd.append("--shorts")
        if cfg["music"] and Path(cfg["music"]).exists():
            cmd += ["--music", cfg["music"]]

        env = dict(os.environ)
        env["PEXELS_API_KEY"] = cfg["pexels_key"]
        env["WHISPER_SIZE"] = cfg["whisper"]

        self.run_btn.configure(state="disabled", text="  Working...  ")
        self.logline(">>> starting render - this can take a few minutes...")
        if not cfg["pexels_key"]:
            self.logline("!!! No Pexels key - backgrounds will be plain gradients.")

        threading.Thread(target=self._worker, args=(cmd, env), daemon=True).start()

    def _worker(self, cmd, env):
        try:
            self.proc = subprocess.Popen(
                cmd, cwd=str(HERE), env=env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            for line in self.proc.stdout:
                self.q.put(("log", line.rstrip()))
            self.proc.wait()
            self.q.put(("done", self.proc.returncode))
        except Exception as e:
            self.q.put(("log", f"ERROR: {e}"))
            self.q.put(("done", 1))

    def drain(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "log":
                    self.logline(payload)
                elif kind == "setup":
                    if payload == 0:
                        self.run_btn.configure(state="normal", text="  Make Video  ")
                        self.logline(">>> Setup complete. Ready to make videos.")
                    else:
                        self.run_btn.configure(state="disabled", text="  Setup failed  ")
                        self.logline(">>> Setup failed - see messages above. "
                                     "Try running setup.bat in a terminal.")
                        messagebox.showerror(
                            "Setup failed",
                            "Couldn't finish first-time setup. Make sure you have "
                            "internet access, then try running setup.bat.")
                elif kind == "done":
                    self.proc = None
                    self.run_btn.configure(state="normal", text="  Make Video  ")
                    if payload == 0:
                        self.logline(">>> DONE. Check the output folder.")
                        self.open_output()
                    else:
                        self.logline(">>> Failed. See the messages above.")
                        messagebox.showerror(
                            "Render failed",
                            "Something went wrong - read the log at the bottom.")
        except queue.Empty:
            pass
        self.root.after(120, self.drain)


if __name__ == "__main__":
    root = tk.Tk()
    Studio(root)
    root.mainloop()
