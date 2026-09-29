"""Isolate which non-ASCII path component breaks the ASR binary."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(r"D:\Work\asr_mm")
MODELS = ROOT / ".asrhome" / "models"
RUNTIME = ROOT / ".asrhome" / "runtime"
WORK = ROOT / "tools" / "enc_stress"
LOG = ROOT / "tools" / "enc_isolate.txt"
EXE = "llama-funasr-paraformer.exe"

out: list[str] = []


def say(m: str = "") -> None:
    out.append(m)
    LOG.write_text("\n".join(out), encoding="utf-8")


def run(exe: Path, model: Path, vad: Path, wav: Path, label: str) -> None:
    cmd = [str(exe), "-m", str(model), "--vad", str(vad), "-a", str(wav),
           "--srt", "--vad-maxseg", "10000"]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=600)
        ok = r.returncode == 0 and "-->" in r.stdout.decode("utf-8", "replace")
        say(f"[{'PASS' if ok else 'FAIL'}] {label}")
        if not ok:
            say(f"        rc={r.returncode}")
            for line in r.stderr.decode("utf-8", "replace").strip().splitlines()[-8:]:
                say(f"        | {line}")
    except Exception as e:
        say(f"[FAIL] {label}  {e}")


JP = WORK / "日本語ユーザー" / "動画 フォルダ"
WAV = JP / "音声 抽出" / "音声データ-抽取-音频.wav"
if not WAV.exists():
    say("prerequisite WAV missing — run enc_stress.py first")
    sys.exit(1)

shutil.rmtree(WORK / "iso", ignore_errors=True)
ISO = WORK / "iso"
ISO.mkdir(parents=True, exist_ok=True)

# Case A: everything ASCII except the WAV (already known good, re-baseline)
run(RUNTIME / EXE, MODELS / "paraformer-q8.gguf", MODELS / "fsmn-vad.gguf",
    WAV, "A baseline: ascii runtime + ascii models + non-ascii WAV")

# Case B: only the model path is non-ASCII
mdir = ISO / "モデル"
mdir.mkdir(exist_ok=True)
for f in ("paraformer-q8.gguf", "fsmn-vad.gguf"):
    try:
        os.link(MODELS / f, mdir / f)
    except OSError:
        shutil.copy2(MODELS / f, mdir / f)
run(RUNTIME / EXE, mdir / "paraformer-q8.gguf", mdir / "fsmn-vad.gguf",
    WAV, "B non-ascii model dir only")

# Case C: only the exe path is non-ASCII
edir = ISO / "実行ファイル"
edir.mkdir(exist_ok=True)
shutil.copy2(RUNTIME / EXE, edir / EXE)
run(edir / EXE, MODELS / "paraformer-q8.gguf", MODELS / "fsmn-vad.gguf",
    WAV, "C non-ascii exe path only")

# Case D: non-ascii exe dir but ascii-named files copied to an ascii dir,
#         invoked through a junction-free relative path from a non-ascii cwd
try:
    r = subprocess.run([str(RUNTIME / EXE), "-m", str(MODELS / "paraformer-q8.gguf"),
                        "--vad", str(MODELS / "fsmn-vad.gguf"), "-a", str(WAV),
                        "--srt", "--vad-maxseg", "10000"],
                       capture_output=True, cwd=str(ISO / "実行ファイル"), timeout=600)
    ok = r.returncode == 0 and "-->" in r.stdout.decode("utf-8", "replace")
    say(f"[{'PASS' if ok else 'FAIL'}] D ascii exe + non-ascii CWD"
        + ("" if ok else f"  rc={r.returncode}"))
    if not ok:
        for line in r.stderr.decode("utf-8", "replace").strip().splitlines()[-8:]:
            say(f"        | {line}")
except Exception as e:
    say(f"[FAIL] D  {e}")

# Case E: does a *relative* path from a non-ascii cwd work?
say("")
say("--- relative-path invocation from a non-ascii CWD ---")
alt = ISO / "相対"
alt.mkdir(exist_ok=True)
shutil.copy2(MODELS / "fsmn-vad.gguf", alt / "vad.gguf")
try:
    os.link(MODELS / "paraformer-q8.gguf", alt / "model.gguf")
except OSError:
    shutil.copy2(MODELS / "paraformer-q8.gguf", alt / "model.gguf")
shutil.copy2(WAV, alt / "in.wav")
run(RUNTIME / EXE, Path("model.gguf"), Path("vad.gguf"), Path("in.wav"),
    "E all-relative ascii paths, non-ascii CWD")

print("WROTE", LOG)
