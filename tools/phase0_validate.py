"""Phase 0 validation: verify the FunASR llama.cpp binary end-to-end on a real video.

Checks:
  1. ffmpeg sub-range extraction -> 16k mono wav
  2. Paraformer q8 + fsmn-vad, plain text and --srt output
  3. SenseVoice q8 for comparison
  4. Sub-range vs full-video consistency (does "only transcribe a slice" match?)
  5. Wall-clock speed
"""
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ffutil import ffmpeg_exe  # noqa: E402

ROOT = r"D:\Work\asr_mm"
VENDOR = os.path.join(ROOT, "vendor")
MODELS = os.path.join(VENDOR, "models")
BIN = os.path.join(VENDOR, "avx2")
WORK = os.path.join(ROOT, "tools", "phase0")
VIDEO = os.path.join(ROOT, "课堂录像示例.mp4")

os.makedirs(WORK, exist_ok=True)


def extract(src, dst, start=None, end=None):
    args = []
    if start is not None:
        args += ["-ss", f"{start:.3f}"]
    if end is not None:
        args += ["-to", f"{end:.3f}"]
    args += ["-i", src, "-vn", "-ac", "1", "-ar", "16000",
             "-c:a", "pcm_s16le", "-y", dst]
    p = subprocess.run([ffmpeg_exe(), "-hide_banner", *args],
                       capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if p.returncode != 0:
        print("FFMPEG FAILED:\n", p.stderr[-3000:])
        sys.exit(1)
    return os.path.getsize(dst)


def asr(binary, model, wav, srt=False, threads=None):
    exe = os.path.join(BIN, binary)
    cmd = [exe, "-m", os.path.join(MODELS, model),
           "--vad", os.path.join(MODELS, "fsmn-vad.gguf"),
           "-a", wav]
    if srt:
        cmd.append("--srt")
    if threads:
        cmd += ["-t", str(threads)]
    t0 = time.time()
    p = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return {"stdout": p.stdout, "stderr": p.stderr,
            "rc": p.returncode, "secs": time.time() - t0}


def audio_secs(wav):
    p = subprocess.run([ffmpeg_exe(), "-hide_banner", "-i", wav],
                       capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", p.stderr)
    if not m:
        return None
    h, mnt, s = m.groups()
    return int(h) * 3600 + int(mnt) * 60 + float(s)


report = {}

# --- 1. extract a 30s slice and the full video -------------------------
slice_wav = os.path.join(WORK, "slice_15_45.wav")
full_wav = os.path.join(WORK, "full.wav")
extract(VIDEO, slice_wav, 15, 45)
extract(VIDEO, full_wav)
slice_dur = audio_secs(slice_wav)
full_dur = audio_secs(full_wav)
print(f"slice 15-45s -> {slice_dur:.2f}s audio")
print(f"full        -> {full_dur:.2f}s audio")

# --- 2. Paraformer on the slice ---------------------------------------
print("\n=== Paraformer q8 + fsmn-vad, slice 15-45s ===")
r = asr("llama-funasr-paraformer.exe", "paraformer-q8.gguf", slice_wav)
print(f"rc={r['rc']}  {r['secs']:.2f}s  RTF={r['secs']/slice_dur:.3f}")
print("--- stdout ---")
print(r["stdout"][:2000])
print("--- stderr (tail) ---")
print(r["stderr"][-800:])
report["paraformer_slice_text"] = r["stdout"]
report["paraformer_slice_secs"] = r["secs"]

# --- 3. SRT output ----------------------------------------------------
print("\n=== Paraformer --srt ===")
r2 = asr("llama-funasr-paraformer.exe", "paraformer-q8.gguf", slice_wav, srt=True)
print(f"rc={r2['rc']}  {r2['secs']:.2f}s")
print(r2["stdout"][:3000])
report["paraformer_slice_srt"] = r2["stdout"]

# --- 4. SenseVoice comparison ----------------------------------------
print("\n=== SenseVoice q8, slice 15-45s ===")
r3 = asr("llama-funasr-sensevoice.exe", "sensevoice-small-q8.gguf", slice_wav, srt=True)
print(f"rc={r3['rc']}  {r3['secs']:.2f}s  RTF={r3['secs']/slice_dur:.3f}")
print(r3["stdout"][:2000])
report["sensevoice_slice_srt"] = r3["stdout"]

# --- 5. sub-range vs full-video consistency ---------------------------
print("\n=== Full video (Paraformer + srt) — for slice consistency check ===")
r4 = asr("llama-funasr-paraformer.exe", "paraformer-q8.gguf", full_wav, srt=True)
print(f"rc={r4['rc']}  {r4['secs']:.2f}s  RTF={r4['secs']/full_dur:.3f}")
report["paraformer_full_srt"] = r4["stdout"]
with open(os.path.join(WORK, "full.srt"), "w", encoding="utf-8") as f:
    f.write(r4["stdout"])
with open(os.path.join(WORK, "slice.srt"), "w", encoding="utf-8") as f:
    f.write(r2["stdout"])
with open(os.path.join(WORK, "sensevoice_slice.srt"), "w", encoding="utf-8") as f:
    f.write(r3["stdout"])

with open(os.path.join(WORK, "report.json"), "w", encoding="utf-8") as f:
    json.dump({k: v for k, v in report.items()}, f, ensure_ascii=False, indent=2)

print("\nDONE")
