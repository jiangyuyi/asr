"""End-to-end exercise of the asr-mm CLI against the real classroom video."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_cli import LOG, run  # noqa: E402

VIDEO = r"D:\Work\asr_mm\samples/课堂录像示例.mp4"
OUT = r"D:\Work\asr_mm\tools\e2e"
os.makedirs(OUT, exist_ok=True)

t0 = time.time()

run("doctor", VIDEO, label="environment + media probe")
run("models", "list", label="model catalog")

# core use case: a 30 s window out of the middle
run("transcribe", VIDEO, "-s", "00:00:15", "-e", "00:00:45",
    "-o", os.path.join(OUT, "slice"), "--format", "txt,srt,json",
    label="core: 15s-45s, txt+srt+json")

# numeric timecodes + preroll, inside the video
run("transcribe", VIDEO, "-s", "10", "-e", "40", "--preroll", "0.5",
    "-o", os.path.join(OUT, "preroll"), "--format", "srt",
    label="numeric timecode + preroll")

# fast model over the whole file, noise segments dropped
run("transcribe", VIDEO, "-m", "paraformer", "--drop-short",
    "-o", os.path.join(OUT, "fast"), "--format", "txt,srt",
    label="whole file, paraformer, --drop-short")

# tail window, stdout only
run("transcribe", VIDEO, "--stdout", "--output-format", "srt",
    "-s", "00:01:00", "-e", "00:01:06",
    label="stdout mode, 6 s tail")

# coarser VAD segmentation
run("transcribe", VIDEO, "-s", "00:00:20", "-e", "00:00:45", "--maxseg", "15000",
    "--stdout", "--output-format", "srt", "--no-summary",
    label="coarser VAD (--maxseg 15000)")

# error paths
run("transcribe", VIDEO, "-s", "00:00:05", "-e", "00:00:02",
    label="error: inverted range")
run("transcribe", VIDEO, "-s", "00:05:00", "-e", "00:06:00",
    label="error: range past end of file")
run("transcribe", os.path.join(OUT, "nope.mp4"), label="error: missing file")
run("transcribe", VIDEO, "-m", "paraformer", "-s", "0", "-e", "20",
    "--stdout", "--output-format", "txt", "--no-summary", "--timestamps",
    label="txt with timestamps")

print(f"total {time.time() - t0:.1f}s -> {LOG}")
