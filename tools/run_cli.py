"""Run asr-mm in a subprocess, capture UTF-8, and write a log we can read back.

The Windows console is often CP936, so printing captured UTF-8 back to stdout
mangles it. Writing to a file sidesteps the console codepage entirely.
"""
import os
import subprocess
import sys
from pathlib import Path

PY = sys.executable
ROOT = r"D:\Work\asr_mm"
LOG = Path(ROOT) / "tools" / "cli.log"
ENV = dict(os.environ)
ENV["ASR_MM_HOME"] = os.path.join(ROOT, ".asrhome")
ENV["PYTHONIOENCODING"] = "utf-8"
ENV["PYTHONUTF8"] = "1"

_buf: list[str] = []


def run(*args, label: str | None = None):
    r = subprocess.run([PY, "-m", "asr_mm", *args], cwd=ROOT, env=ENV,
                       capture_output=True, timeout=3600)
    out = r.stdout.decode("utf-8", "replace").strip()
    err = r.stderr.decode("utf-8", "replace").strip()
    head = f"$ asr-mm {' '.join(args)}" + (f"   [{label}]" if label else "")
    body = head + "\n" + "=" * len(head) + "\n"
    if out:
        body += out + "\n"
    if err:
        body += "--- stderr ---\n" + err + "\n"
    body += f"[exit {r.returncode}]\n\n"
    _buf.append(body)
    LOG.write_text("".join(_buf), encoding="utf-8")
    return r


if __name__ == "__main__":
    run(*sys.argv[1:])
    print(str(LOG))
