"""Verify the frozen 1.4.0 build can write a real xlsx.

openpyxl is the most packaging-fragile dependency added so far: it ships XML
templates and a style table as data files and imports its writers lazily, so a
missing hook only shows up when the code actually runs inside the bundle.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

ROOT = Path(r"D:\Work\asr_mm")
DIST = ROOT / "dist" / "asr-mm"
EXE = DIST / "asr-mm.exe"
GUI = ROOT / "dist" / "asr-mm-gui" / "asr-mm-gui.exe"
LOG = ROOT / "tools" / "frozen_xlsx.txt"
VIDEO = ROOT / "samples/课堂录像示例.mp4"

lines: list[str] = []
fails: list[str] = []


def say(m=""):
    lines.append(m)
    LOG.write_text("\n".join(lines), encoding="utf-8")


def check(label, ok, detail=""):
    say(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f"  — {detail}" if detail else ""))
    if not ok:
        fails.append(label)


env = dict(os.environ)
env["ASR_MM_HOME"] = str(ROOT / ".asrhome")
env["PYTHONIOENCODING"] = "utf-8"
env["PYTHONUTF8"] = "1"

say("=" * 72)
say("FROZEN BUILD — Excel export")
say("=" * 72)

v = subprocess.run([str(EXE), "--version"], capture_output=True, env=env,
                   timeout=180).stdout.decode("utf-8", "replace")
check("version is 1.4.0", "1.4.0" in v, v.strip())

# --- openpyxl must be importable from inside the bundle ------------------
# Not checked by path: PyInstaller compiles pure-Python modules into the PYZ
# inside the exe, so there is no openpyxl/ directory in _internal/. The
# functional checks below are the real proof — if the module or its XML
# templates were missing, writing the workbook would fail outright.
internal = DIST / "_internal"
check("ffmpeg and engine are still staged in the bundle",
      (internal / "ffmpeg" / "ffmpeg.exe").exists()
      and (internal / "runtime").is_dir())

# --- the real thing: transcribe and write xlsx from the frozen build ------
tmp = Path(tempfile.mkdtemp(prefix="asr-mm-xlsx-"))
t0 = time.time()
r = subprocess.run(
    [str(EXE), "transcribe", str(VIDEO), "-s", "00:00:15", "-e", "00:00:45",
     "-f", "xlsx", "-o", str(tmp)],
    capture_output=True, env=env, timeout=900)
out = r.stdout.decode("utf-8", "replace")
err = r.stderr.decode("utf-8", "replace")
say("")
say("--- frozen CLI: -f xlsx ---")
say((out or err).strip()[:800])
say("")

check("frozen build writes xlsx", r.returncode == 0 and ".xlsx" in out,
      f"exit {r.returncode}")
books = list(tmp.glob("*.xlsx"))
check("workbook file exists", bool(books),
      books[0].name if books else "none")
if books:
    size = books[0].stat().st_size
    check("workbook is a real xlsx (zip container)", size > 4000, f"{size:,} bytes")
    with zipfile.ZipFile(books[0]) as zf:
        names = zf.namelist()
        check("contains a worksheet part",
              any(n.startswith("xl/worksheets/") for n in names))
        check("contains shared strings",
              "xl/sharedStrings.xml" in names or "inlineStr" in
              zf.read("xl/worksheets/sheet1.xml").decode("utf-8", "replace"))
    # read it back with the dev environment
    from openpyxl import load_workbook
    ws = load_workbook(books[0]).active
    headers = [c.value for c in ws[1]]
    check("headers are the documented ones",
          headers == ["序号", "开始", "结束", "开始(秒)", "时长(秒)", "内容"],
          str(headers))
    check("one row per segment", ws.max_row >= 2, f"{ws.max_row - 1} rows")
    say("")
    say(f"--- {books[0].name} ---")
    for row in ws.iter_rows(values_only=True):
        say("  " + " | ".join("" if v is None else str(v) for v in row))
    say("")
    check("timestamps are the video's own",
          str(ws.cell(row=2, column=2).value).startswith("00:00:1"),
          str(ws.cell(row=2, column=2).value))

# --- all four formats at once from the frozen build -----------------------
r = subprocess.run(
    [str(EXE), "transcribe", str(VIDEO), "-s", "00:00:15", "-e", "00:00:25",
     "-f", "txt,srt,json,xlsx", "-o", str(tmp / "all")],
    capture_output=True, env=env, timeout=900)
made = sorted(p.suffix for p in (tmp / "all").glob("*")) if (tmp / "all").exists() else []
check("all four formats from one run", made == [".json", ".srt", ".txt", ".xlsx"],
      str(made))

# --- the language warning must survive freezing ---------------------------
r = subprocess.run(
    [str(EXE), "--lang", "ja", "transcribe", str(VIDEO), "-m", "paraformer",
     "--content-lang", "ja", "-s", "00:00:15", "-e", "00:00:25",
     "--stdout", "--output-format", "srt", "--no-summary"],
    capture_output=True, env=env, timeout=900)
werr = r.stderr.decode("utf-8", "replace")
check("Japanese warning is localised in the frozen build",
      "日本語" in werr and "paraformer" in werr, werr.strip()[:90])

# --- the GUI must still start -------------------------------------------
p = subprocess.Popen([str(GUI), str(VIDEO)], env=env)
alive = 0
for _ in range(15):
    time.sleep(1)
    if p.poll() is not None:
        break
    alive += 1
check("GUI still launches with openpyxl bundled", p.poll() is None, f"{alive}s")
if p.poll() is None:
    p.terminate()
    try:
        p.wait(timeout=6)
    except subprocess.TimeoutExpired:
        p.kill()

import shutil  # noqa: E402
shutil.rmtree(tmp, ignore_errors=True)
say("")
say(f"RESULT: {len(fails)} failure(s)")
for f in fails:
    say(f"  FAILED: {f}")
print("WROTE", LOG)
