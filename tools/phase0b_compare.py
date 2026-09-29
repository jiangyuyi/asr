"""Phase 0b: VAD segment granularity + model head-to-head on the real video."""
import os
import subprocess
import time

B = r"D:\Work\asr_mm\vendor\avx2"
M = r"D:\Work\asr_mm\vendor\models"
W = r"D:\Work\asr_mm\tools\phase0\full.wav"
VAD = os.path.join(M, "fsmn-vad.gguf")


def run(binary, model, wav, maxseg=None, srt=True, extra=None):
    cmd = [os.path.join(B, binary), "-m", os.path.join(M, model),
           "--vad", VAD, "-a", wav]
    if maxseg:
        cmd += ["--vad-maxseg", str(maxseg)]
    if srt:
        cmd.append("--srt")
    if extra:
        cmd += extra
    t0 = time.time()
    p = subprocess.run(cmd, capture_output=True)
    return p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace"), time.time() - t0


print("=" * 70)
print("A. VAD segment granularity (Paraformer, full 66s video)")
print("=" * 70)
for ms in [None, 15000, 10000, 5000]:
    out, err, secs = run("llama-funasr-paraformer.exe", "paraformer-q8.gguf", W, maxseg=ms)
    n = out.count("-->")
    tag = f"vad-maxseg={ms}" if ms else "default"
    print(f"\n--- {tag}  ->  {n} segments, {secs:.2f}s ---")
    print(out.strip()[:700])

print("\n" + "=" * 70)
print("B. Paraformer vs SenseVoice, same 5s VAD segments")
print("=" * 70)
pf, _, t1 = run("llama-funasr-paraformer.exe", "paraformer-q8.gguf", W, maxseg=5000)
sv, _, t2 = run("llama-funasr-sensevoice.exe", "sensevoice-small-q8.gguf", W, maxseg=5000)
with open(r"D:\Work\asr_mm\tools\phase0\cmp_paraformer.srt", "w", encoding="utf-8") as f:
    f.write(pf)
with open(r"D:\Work\asr_mm\tools\phase0\cmp_sensevoice.srt", "w", encoding="utf-8") as f:
    f.write(sv)
print(f"Paraformer: {pf.count('-->')} seg, {t1:.2f}s")
print(f"SenseVoice: {sv.count('-->')} seg, {t2:.2f}s")
print("\n### PARAFORMER ###")
print(pf.strip())
print("\n### SENSEVOICE ###")
print(sv.strip())
