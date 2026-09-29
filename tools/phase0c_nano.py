"""Phase 0c: Fun-ASR-Nano — does it solve the punctuation gap?"""
import os
import subprocess
import time

B = r"D:\Work\asr_mm\vendor\avx2"
M = r"D:\Work\asr_mm\vendor\models"
W = r"D:\Work\asr_mm\tools\phase0\full.wav"
VAD = os.path.join(M, "fsmn-vad.gguf")
ENC = os.path.join(M, "funasr-encoder-f16.gguf")
LLM = os.path.join(M, "qwen3-0.6b-q4km.gguf")


def help_():
    p = subprocess.run([os.path.join(B, "llama-funasr-cli.exe"), "--help"],
                       capture_output=True)
    print("USAGE:", p.stderr.decode("utf-8", "replace") + p.stdout.decode("utf-8", "replace"))


def run(extra):
    cmd = [os.path.join(B, "llama-funasr-cli.exe"), "--enc", ENC, "-m", LLM,
           "--vad", VAD, "-a", W, "--srt", *extra]
    t0 = time.time()
    p = subprocess.run(cmd, capture_output=True)
    return (p.stdout.decode("utf-8", "replace"),
            p.stderr.decode("utf-8", "replace"), time.time() - t0, p.returncode)


help_()

for extra, label in [([], "default vad"), (["--vad-maxseg", "10000"], "vad-maxseg=10000")]:
    out, err, secs, rc = run(extra)
    print("\n" + "=" * 70)
    print(f"FUN-ASR-NANO  [{label}]  rc={rc}  {secs:.2f}s  "
          f"({out.count('-->')} segments)")
    print("=" * 70)
    print(out.strip()[:2600])
    if err.strip():
        print("--- stderr tail ---")
        print(err.strip()[-500:])
    fn = label.replace(" ", "_").replace("=", "")
    with open(rf"D:\Work\asr_mm\tools\phase0\nano_{fn}.srt", "w", encoding="utf-8") as f:
        f.write(out)
