"""End-to-end: download a real model through the mirror-aware downloader.

Uses fsmn-vad.gguf (1.7 MB) so the test is quick, and drives it with the
HuggingFace source forced to fail so the ModelScope fallback is exercised for
real rather than in a unit test.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import urllib.error
from pathlib import Path

os.environ["ASR_MM_HOME"] = r"D:\Work\asr_mm\tools\_netcheck_home"
sys.path.insert(0, r"D:\Work\asr_mm")

from asr_mm import catalog, downloader, net  # noqa: E402

WORK = Path(r"D:\Work\asr_mm\tools\_netcheck")
LOG = Path(r"D:\Work\asr_mm\tools\net_e2e.txt")
lines: list[str] = []
fails: list[str] = []


def say(m=""):
    lines.append(m)
    LOG.write_text("\n".join(lines), encoding="utf-8")


def check(label, ok, detail=""):
    say(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f"  — {detail}" if detail else ""))
    if not ok:
        fails.append(label)


shutil.rmtree(WORK, ignore_errors=True)
WORK.mkdir(parents=True)
shutil.rmtree(Path(os.environ["ASR_MM_HOME"]), ignore_errors=True)

vad = next(f for f in catalog.resolve_model("paraformer").files
           if f.filename == "fsmn-vad.gguf")
cfg = downloader.net_config({"mirror": "auto"})
say("=" * 72)
say("NETWORK LAYER — end-to-end download")
say("=" * 72)
say(f"CA source : {net.inject_os_trust()}")
say(f"sources   : {vad.sources(cfg.mirror)}")
say(f"expected  : {vad.size:,} bytes")
say()

# --- 1. the normal path, Hugging Face first -------------------------------
say("--- 1. 直连 Hugging Face ---")
t0 = time.time()
out = net.fetch(vad.sources("auto"), WORK / vad.filename,
                net.build_context(cfg), expect_size=vad.size)
size = out.stat().st_size
check("download completed", size == vad.size,
      f"{size:,} bytes in {time.time() - t0:.1f}s")

# --- 2. force the first mirror to fail, prove the fallback works ----------
say()
say("--- 2. 强制首选源失败，验证自动切换 ---")
real_once = net._download_once
calls: list[str] = []


def sabotage(url, part, ctx, offset, expect_size, on_progress, timeout):
    calls.append(net.host_of(url))
    if net.host_of(url) == "huggingface.co":
        raise urllib.error.URLError("CERTIFICATE_VERIFY_FAILED")
    return real_once(url, part, ctx, offset, expect_size, on_progress, timeout)


net._download_once = sabotage
try:
    t0 = time.time()
    out2 = net.fetch(vad.sources("auto"), WORK / "fallback" / vad.filename,
                     net.build_context(cfg), expect_size=vad.size)
    check("fell back to ModelScope", out2.exists() and
          out2.stat().st_size == vad.size,
          f"{' -> '.join(calls)}")
    check("fallback content matches", out2.read_bytes() == out.read_bytes())
finally:
    net._download_once = real_once

# --- 3. pinned to a single source ----------------------------------------
say()
say("--- 3. 锁定单一下载源 ---")
check("pinned to modelscope only", vad.sources("modelscope") == [vad.mirror_url])
r = subprocess.run(
    [sys.executable, "-m", "asr_mm", "net-check", "--mirror", "modelscope"],
    cwd=r"D:\Work\asr_mm", capture_output=True,
    env={**os.environ, "PYTHONIOENCODING": "utf-8"}, timeout=180)
text = r.stdout.decode("utf-8", "replace")
check("net-check --mirror works", r.returncode == 0 and "ModelScope" in text)

# --- 4. a real model install still works ----------------------------------
say()
say("--- 4. ensure_model 真实安装 ---")
t0 = time.time()
try:
    spec = downloader.ensure_model("paraformer", cfg=cfg)
    check("paraformer installed", not downloader.missing_files(spec),
          f"{time.time() - t0:.1f}s")
except Exception as exc:  # noqa: BLE001
    check("paraformer installed", False, downloader.explain(exc))

shutil.rmtree(WORK, ignore_errors=True)
shutil.rmtree(Path(os.environ["ASR_MM_HOME"]), ignore_errors=True)
say()
say(f"RESULT: {len(fails)} failure(s)")
for f in fails:
    say(f"  FAILED: {f}")
print("WROTE", LOG)
