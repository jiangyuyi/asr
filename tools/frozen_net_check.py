"""Check the frozen 1.3.0 build actually carries a usable CA store.

This is the exact failure the user hit: a macOS build with no CA bundle rejects
every certificate. We cannot run macOS here, but we can prove the pieces that
make it work are in the bundle, and that the frozen interpreter can complete a
verified HTTPS request.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(r"D:\Work\asr_mm")
DIST = ROOT / "dist" / "asr-mm"
EXE = DIST / "asr-mm.exe"
LOG = ROOT / "tools" / "frozen_net.txt"

lines: list[str] = []
fails: list[str] = []


def say(m=""):
    lines.append(m)
    LOG.write_text("\n".join(lines), encoding="utf-8")


def check(label, ok, detail=""):
    say(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f"  — {detail}" if detail else ""))
    if not ok:
        fails.append(label)


internal = DIST / "_internal"
say("=" * 72)
say("FROZEN BUILD — CA store check")
say("=" * 72)
say(f"bundle: {DIST}")
say("")

# --- the CA bundle must physically exist in the bundle -------------------
cacerts = list(internal.rglob("cacert.pem"))
check("certifi cacert.pem is inside the bundle", bool(cacerts),
      str(cacerts[0].relative_to(DIST)) if cacerts else
      f"searched {internal}")
if cacerts:
    size = cacerts[0].stat().st_size
    check("cacert.pem has real content", size > 100_000, f"{size:,} bytes")
    # The file opens with issuer comments, so look for the marker anywhere.
    body = cacerts[0].read_text(encoding="utf-8", errors="replace")
    check("cacert.pem is a PEM bundle", "BEGIN CERTIFICATE" in body,
          f"{body.count('BEGIN CERTIFICATE')} certificates")

# Python modules are compiled into the PYZ archive, so truststore has no loose
# file in _internal/. Its presence is proven by the CA-source line below.

# --- and the frozen app must be able to complete a verified request ------
env = dict(os.environ)
env["ASR_MM_HOME"] = str(ROOT / ".asrhome")
env["PYTHONIOENCODING"] = "utf-8"
env["PYTHONUTF8"] = "1"

r = subprocess.run([str(EXE), "net-check"], capture_output=True, env=env,
                   timeout=300)
out = r.stdout.decode("utf-8", "replace")
err = r.stderr.decode("utf-8", "replace")
say("--- asr-mm net-check (frozen) ---")
say(out.strip() or err.strip()[-800:])
say("")

check("frozen build reports its version",
      "1.3.0" in subprocess.run([str(EXE), "--version"], capture_output=True,
                                env=env, timeout=120)
      .stdout.decode("utf-8", "replace"))
check("frozen build completes verified HTTPS", r.returncode == 0,
      f"exit {r.returncode}")
check("frozen build uses the OS trust store", "系统信任库" in out or "system" in out.lower(),
      "truststore is compiled into the PYZ, so this line is the proof it loaded")
check("frozen build reports certificate issuers",
      "签发者" in out or "Issuer" in out)
check("all three sources reachable from the bundle", out.count("[OK") == 3,
      f"{out.count('[OK')} ok")

# --- a settings file the user can hand-edit ------------------------------
import tempfile
tmp = Path(tempfile.mkdtemp(prefix="asr-mm-frozen-home-"))
env2 = dict(env)
env2["ASR_MM_HOME"] = str(tmp)
r = subprocess.run([str(EXE), "net-check", "--mirror", "modelscope"],
                   capture_output=True, env=env2, timeout=300)
check("--mirror override reaches the network layer", r.returncode == 0,
      f"exit {r.returncode}")
shutil.rmtree(tmp, ignore_errors=True)

say("")
say(f"RESULT: {len(fails)} failure(s)")
for f in fails:
    say(f"  FAILED: {f}")
print("WROTE", LOG)
