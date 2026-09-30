"""Verify ModelScope mirrors exist and are reachable, and compare with HuggingFace.

ModelScope is a domestic CDN, so it solves two problems at once: reachability
from mainland China and HuggingFace-specific TLS interception.
"""
from __future__ import annotations

import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(r"D:\Work\asr_mm")
sys.path.insert(0, str(ROOT))
from asr_mm import catalog  # noqa: E402

OUT = ROOT / "tools" / "mirror_probe.txt"
lines: list[str] = []


def say(m=""):
    lines.append(m)
    OUT.write_text("\n".join(lines), encoding="utf-8")


def head(url: str, ctx=None, timeout: int = 25):
    req = urllib.request.Request(url, method="HEAD",
                                 headers={"User-Agent": "asr-mm/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            return r.status, int(r.headers.get("Content-Length") or 0)
    except urllib.error.HTTPError as e:
        return e.code, 0
    except Exception as e:  # noqa: BLE001
        return type(e).__name__, 0


MS = "https://modelscope.cn/models/{repo}/resolve/master/{name}"
HF = "https://huggingface.co/{repo}/resolve/main/{name}"

REPO_FOR = {
    "fsmn-vad.gguf": "FunAudioLLM/fsmn-vad-GGUF",
    "paraformer-q8.gguf": "FunAudioLLM/Paraformer-GGUF",
    "sensevoice-small-q8.gguf": "FunAudioLLM/SenseVoiceSmall-GGUF",
    "funasr-encoder-f16.gguf": "FunAudioLLM/Fun-ASR-Nano-GGUF",
    "qwen3-0.6b-q4km.gguf": "FunAudioLLM/Fun-ASR-Nano-GGUF",
}

say("=" * 72)
say("MODELSCOPE MIRROR PROBE")
say("=" * 72)
say(f"{'file':<28}{'modelscope':>14}{'size':>12}   {'huggingface':>12}")
say("-" * 72)

ctx = ssl.create_default_context()
results = {}
for name, repo in REPO_FOR.items():
    ms_url = MS.format(repo=repo, name=name)
    hf_url = HF.format(repo=repo, name=name)
    ms_status, ms_size = head(ms_url, ctx)
    hf_status, hf_size = head(hf_url, ctx)
    results[name] = (ms_status, ms_size)
    say(f"{name:<28}{str(ms_status):>14}{ms_size / 1_048_576:>10.1f}MB"
        f"   {str(hf_status):>12}")
say("")

ok = [n for n, (s, _) in results.items() if s == 200]
bad = {n: s for n, (s, _) in results.items() if s != 200}
say(f"ModelScope 可用: {len(ok)}/{len(REPO_FOR)}")
if bad:
    say(f"不可用: {bad}")
say("")

# size cross-check against the catalog so a mirror cannot silently ship a
# different file
say("--- 与 catalog 中的体积交叉核对 ---")
for spec in catalog.MODELS.values():
    for f in spec.files:
        repo = REPO_FOR.get(f.filename)
        if not repo:
            continue
        _, ms_size = results[f.filename]
        if ms_size and f.size:
            delta = abs(ms_size - f.size) / f.size
            flag = "OK" if delta < 0.02 else f"差异 {delta:.1%}"
            say(f"  {f.filename:<28} catalog={f.size / 1_048_576:>7.1f}MB  "
                f"mirror={ms_size / 1_048_576:>7.1f}MB  {flag}")

print("WROTE", OUT)
