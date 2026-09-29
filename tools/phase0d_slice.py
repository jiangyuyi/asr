"""Phase 0d: primary use-case check — sub-range slice, Nano vs Paraformer."""
import os
import subprocess
import time

B = r"D:\Work\asr_mm\vendor\avx2"
M = r"D:\Work\asr_mm\vendor\models"
VAD = os.path.join(M, "fsmn-vad.gguf")
SLICE = r"D:\Work\asr_mm\tools\phase0\slice_15_45.wav"


def nano(wav, maxseg="10000"):
    cmd = [os.path.join(B, "llama-funasr-cli.exe"),
           "--enc", os.path.join(M, "funasr-encoder-f16.gguf"),
           "-m", os.path.join(M, "qwen3-0.6b-q4km.gguf"),
           "--vad", VAD, "-a", wav, "--srt", "--vad-maxseg", maxseg]
    t0 = time.time()
    p = subprocess.run(cmd, capture_output=True)
    return p.stdout.decode("utf-8", "replace"), time.time() - t0


def para(wav, maxseg="10000"):
    cmd = [os.path.join(B, "llama-funasr-paraformer.exe"),
           "-m", os.path.join(M, "paraformer-q8.gguf"),
           "--vad", VAD, "-a", wav, "--srt", "--vad-maxseg", maxseg]
    t0 = time.time()
    p = subprocess.run(cmd, capture_output=True)
    return p.stdout.decode("utf-8", "replace"), time.time() - t0


for name, fn in (("NANO", nano), ("PARAFORMER", para)):
    out, secs = fn(SLICE)
    print("=" * 70)
    print(f"{name}  slice 15-45s  vad-maxseg=10000  {secs:.2f}s  "
          f"({out.count('-->')} segments)")
    print("=" * 70)
    print(out.strip())
    with open(rf"D:\Work\asr_mm\tools\phase0\slice_{name.lower()}.srt",
              "w", encoding="utf-8") as f:
        f.write(out)
    print()
