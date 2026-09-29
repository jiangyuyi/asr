"""Encoding stress test.

Goal: prove (or disprove) that the whole pipeline survives filenames and
directory paths containing Chinese, Japanese, Cyrillic, emoji and spaces —
on a system whose ANSI code page may be CP932 (Japanese Windows).

Checks, in order of how likely they are to break:
  1. Python file I/O on those paths
  2. ffmpeg (bundled static build) reading them
  3. the llama.cpp ASR binary receiving them via argv
  4. the ASR binary reading a WAV that lives under a Japanese directory
  5. ASR result text, which is Chinese, written back to a Japanese-named file
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(r"D:\Work\asr_mm")
MODELS = ROOT / ".asrhome" / "models"
RUNTIME = ROOT / ".asrhome" / "runtime"
SRC = ROOT / "20250912 哲商現代実験学校 MR1 part1.avi"
WORK = ROOT / "tools" / "enc_stress"
LOG = ROOT / "tools" / "enc_stress.txt"

sys.path.insert(0, str(ROOT))
from asr_mm import media  # noqa: E402

NAMES = {
    "zh": "中文文件名-测试视频",
    "ja": "日本語のファイル名-テスト動画",
    "mixed": "日本語中文English-混在 動画 2026",
    "cyrillic": "Русский-тест-ролик",
    "emoji": "🎬-测试-えむじー-🎥",
    "spaces": "  前后有空格  spaced  name  ",
}

out: list[str] = []
failures: list[str] = []


def say(m: str = "") -> None:
    out.append(m)
    LOG.write_text("\n".join(out), encoding="utf-8")


def step(label: str, ok: bool, detail: str = "") -> None:
    mark = "PASS" if ok else "FAIL"
    say(f"[{mark}] {label}" + (f"  — {detail}" if detail else ""))
    if not ok:
        failures.append(label)


shutil.rmtree(WORK, ignore_errors=True)
WORK.mkdir(parents=True, exist_ok=True)
# A directory whose every component is non-ASCII, mimicking a Japanese profile.
JP_DIR = WORK / "日本語ユーザー" / "動画 フォルダ"
CN_DIR = WORK / "中文用户" / "视频 文件夹"
JP_DIR.mkdir(parents=True, exist_ok=True)
CN_DIR.mkdir(parents=True, exist_ok=True)

say("=" * 72)
say("ENCODING STRESS TEST")
say("=" * 72)
say(f"filesystem encoding : {sys.getfilesystemencoding()}")
say(f"stdout encoding     : {sys.stdout.encoding}")
say(f"locale              : {os.environ.get('LANG') or os.environ.get('LC_ALL') or '(unset)'}")
say(f"ACP codepage        : {__import__('ctypes').windll.kernel32.GetACP()}")
say()

# --- 1. copy the source under every name -----------------------------------
copies: list[Path] = []
for key, name in NAMES.items():
    dst = (JP_DIR / f"{name}.avi")
    try:
        shutil.copy2(SRC, dst)
        copies.append(dst)
        step(f"copy as {key}: {name}.avi", dst.exists() and dst.stat().st_size > 0,
             f"{dst.stat().st_size:,} bytes")
    except OSError as e:
        step(f"copy as {key}", False, str(e))
say()

# --- 2. python file I/O -----------------------------------------------------
probe_file = JP_DIR / "テスト-読み書き-数据.txt"
try:
    probe_file.write_text("日本語と中文とEnglish\n", encoding="utf-8")
    back = probe_file.read_text(encoding="utf-8")
    step("python UTF-8 write/read round-trip", back == "日本語と中文とEnglish\n")
except OSError as e:
    step("python UTF-8 write/read round-trip", False, str(e))
say()

# --- 3. ffmpeg probe on those paths ----------------------------------------
say("--- ffmpeg probe ---")
for p in copies:
    try:
        info = media.probe(p)
        ok = info.duration > 60 and info.has_audio
        step(f"ffmpeg probe: {p.name[:40]}", ok,
             f"{info.duration:.2f}s {info.audio_codec} {info.sample_rate}Hz")
    except Exception as e:
        step(f"ffmpeg probe: {p.name[:40]}", False, str(e)[:120])
say()

# --- 4. ffmpeg extract to a Japanese-named WAV -----------------------------
say("--- ffmpeg extract into a Japanese-named directory ---")
wav_dir = JP_DIR / "音声 抽出"
wav_dir.mkdir(parents=True, exist_ok=True)
wav_name = "音声データ-抽取-音频.wav"
wav_path = wav_dir / wav_name
try:
    media.extract_audio(copies[-1], wav_path, 15, 30)
    size = wav_path.stat().st_size
    step("ffmpeg extract to Japanese-named WAV", size > 100_000, f"{size:,} bytes")
except Exception as e:
    step("ffmpeg extract to Japanese-named WAV", False, str(e)[:200])
say()

# --- 5. ASR binary given a Japanese path via argv --------------------------
say("--- ASR binary with non-ASCII argv ---")
exe = RUNTIME / "llama-funasr-paraformer.exe"
cmd = [
    str(exe),
    "-m", str(MODELS / "paraformer-q8.gguf"),
    "--vad", str(MODELS / "fsmn-vad.gguf"),
    "-a", str(wav_path),          # <-- the risky part
    "--srt", "--vad-maxseg", "10000",
]
if not wav_path.exists():
    step("ASR binary accepts non-ASCII -a path", False, "wav missing, skipped")
else:
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=600)
        text = r.stdout.decode("utf-8", "replace")
        err = r.stderr.decode("utf-8", "replace")
        ok = r.returncode == 0 and text.strip() and "-->" in text
        step("ASR binary accepts non-ASCII -a path", ok,
             (text.strip().splitlines()[2][:60] if ok else err.strip()[-160:]))
    except Exception as e:
        step("ASR binary accepts non-ASCII -a path", False, str(e)[:200])
say()

# --- 6. ASR binary in a Japanese-named working directory --------------------
say("--- ASR binary with CWD under a Japanese path ---")
try:
    r = subprocess.run(cmd, capture_output=True, cwd=str(wav_dir), timeout=600)
    text = r.stdout.decode("utf-8", "replace")
    ok = r.returncode == 0 and "-->" in text
    step("ASR binary with Japanese CWD", ok,
         f"rc={r.returncode} {len(text)} bytes")
except Exception as e:
    step("ASR binary with Japanese CWD", False, str(e)[:200])
say()

# --- 7. model + exe paths under a Japanese home -----------------------------
say("--- runtime/model located under a non-ASCII home ---")
fake_home = JP_DIR / "asr-mm-ホーム"
(fake_home / "models").mkdir(parents=True, exist_ok=True)
(fake_home / "runtime").mkdir(parents=True, exist_ok=True)
for m in ("paraformer-q8.gguf", "fsmn-vad.gguf"):
    src_m, dst_m = MODELS / m, fake_home / "models" / m
    try:
        os.link(src_m, dst_m)          # same volume, so a link is instant
    except OSError:
        shutil.copy2(src_m, dst_m)
for e in ("llama-funasr-paraformer.exe",):
    src_e = RUNTIME / e
    dst_e = fake_home / "runtime" / e
    try:
        shutil.copy2(src_e, dst_e)
    except OSError as exc:
        say(f"  (copy runtime failed: {exc})")
if (fake_home / "runtime" / "llama-funasr-paraformer.exe").exists():
    cmd2 = [
        str(fake_home / "runtime" / "llama-funasr-paraformer.exe"),
        "-m", str(fake_home / "models" / "paraformer-q8.gguf"),
        "--vad", str(fake_home / "models" / "fsmn-vad.gguf"),
        "-a", str(wav_path), "--srt", "--vad-maxseg", "10000",
    ]
    try:
        r = subprocess.run(cmd2, capture_output=True, timeout=600)
        text = r.stdout.decode("utf-8", "replace")
        ok = r.returncode == 0 and "-->" in text
        step("runtime+models under Japanese home", ok,
             f"rc={r.returncode} {len(text)} bytes")
    except Exception as e:
        step("runtime+models under Japanese home", False, str(e)[:200])
else:
    step("runtime+models under Japanese home", False, "could not stage runtime")
say()

# --- 8. writing the transcript under a Japanese filename --------------------
say("--- writing output under non-ASCII names ---")
from asr_mm.srt import parse_srt, render_srt  # noqa: E402
sample = "1\n00:00:00,300 --> 00:00:05,000\n日本語の字幕、中文的字幕、English.\n"
for dirname in (JP_DIR, CN_DIR):
    for fname in ("字幕-結果-字幕.srt", "résultat-字幕.srt"):
        target = dirname / fname
        try:
            target.write_text(render_srt(parse_srt(sample)), encoding="utf-8")
            ok = target.read_text(encoding="utf-8").strip() == \
                render_srt(parse_srt(sample)).strip()
            step(f"write {target.parent.name}/{fname}", ok)
        except OSError as e:
            step(f"write {target.parent.name}/{fname}", False, str(e)[:120])
say()

say("=" * 72)
say(f"RESULT: {len(failures)} failure(s)")
for f in failures:
    say(f"  FAILED: {f}")
say("=" * 72)
print("WROTE", LOG)
