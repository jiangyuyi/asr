"""Check that the generated .command launchers are syntactically valid bash."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packaging"))
import macos_extras  # noqa: E402

BASH = r"C:\Program Files\Git\bin\bash.exe"
if not Path(BASH).exists():
    print("  (bash unavailable, skipped)")
    raise SystemExit(0)

rc = 0
for bundle in ("asr-mm", "asr-mm-gui"):
    files = macos_extras.files_for(bundle)
    name = next(n for n in files if n.endswith(".command"))
    body = files[name]
    with tempfile.NamedTemporaryFile("w", suffix=".command", delete=False,
                                     encoding="utf-8", newline="\n") as f:
        f.write(body)
        path = f.name
    r = subprocess.run([BASH, "-n", path], capture_output=True)
    os.unlink(path)
    ok = r.returncode == 0
    print(f"  {name:<22} {'OK' if ok else r.stderr.decode('utf-8', 'replace')}")
    if not ok:
        rc = 1
raise SystemExit(rc)
