#!/usr/bin/env bash
# Sanity-check the release archive: extract to a clean dir and run it.
set -euo pipefail
cd /d/Work/asr_mm

TMP="/tmp/asr-release-check"
rm -rf "$TMP"
mkdir -p "$TMP"

echo "=== extracting asr-mm-1.0.0-windows-x64.zip ==="
unzip -q "release/asr-mm-1.0.0-windows-x64.zip" -d "$TMP"

echo "--- payload present? ---"
ls -lh "$TMP/asr-mm/_internal/ffmpeg/ffmpeg.exe"
ls -lh "$TMP/asr-mm/_internal/runtime/" | head -4

echo
echo "=== run from the extracted copy ==="
EXE="$TMP/asr-mm/asr-mm.exe"
"$EXE" --version

# Point the model cache at the already-downloaded set so we exercise the real
# path without a 900 MB download.
ASR_MM_HOME=/d/Work/asr_mm/.asrhome "$EXE" doctor \
  "/d/Work/asr_mm/课堂录像示例.mp4" 2>&1 | tail -12

echo
echo "=== transcribe from the extracted copy ==="
ASR_MM_HOME=/d/Work/asr_mm/.asrhome "$EXE" transcribe \
  "/d/Work/asr_mm/课堂录像示例.mp4" \
  -s 00:00:15 -e 00:00:30 --stdout --output-format srt --no-summary

rm -rf "$TMP"
echo
echo "ARCHIVE OK"
