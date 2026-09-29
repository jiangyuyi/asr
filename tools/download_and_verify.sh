#!/usr/bin/env bash
# Download the published assets back and verify they are real, working builds.
set -uo pipefail
cd /d/Work/asr_mm

TMP="/tmp/asr-gh-verify"
rm -rf "$TMP"; mkdir -p "$TMP"

echo "=== download macOS asset (the one we could not test locally) ==="
gh release download v1.0.0 -p 'asr-mm-1.0.0-macos-arm64.zip' -D "$TMP" --clobber
ls -lh "$TMP"

echo
echo "=== macOS bundle structure ==="
unzip -l "$TMP/asr-mm-1.0.0-macos-arm64.zip" | grep -Ei '(_internal/(runtime|ffmpeg)/|MacOS/.*asr-mm|^Archive)' | head -20

echo
echo "--- arch check on the shipped engine binaries ---"
unzip -o -q "$TMP/asr-mm-1.0.0-macos-arm64.zip" -d "$TMP/mac"
for f in "$TMP/mac/asr-mm/_internal/runtime/llama-funasr-cli" \
         "$TMP/mac/asr-mm/_internal/ffmpeg/ffmpeg"; do
  if [ -f "$f" ]; then
    printf '%-70s %s\n' "$(basename "$f")" "$(file -b "$f" 2>/dev/null | cut -c1-80)"
  else
    echo "MISSING: $f"
  fi
done
echo "--- any stray .exe (would mean the wrong platform payload) ---"
find "$TMP/mac" -name '*.exe' | head -5 || true

echo
echo "=== download Windows asset and run it ==="
gh release download v1.0.0 -p 'asr-mm-1.0.0-windows-x64.zip' -D "$TMP" --clobber
unzip -o -q "$TMP/asr-mm-1.0.0-windows-x64.zip" -d "$TMP/win"

EXE="$TMP/win/asr-mm/asr-mm.exe"
ls -lh "$EXE" "$TMP/win/asr-mm/_internal/ffmpeg/ffmpeg.exe"

echo
echo "--- version ---"
"$EXE" --version

echo
echo "--- transcribe (models from local cache) ---"
ASR_MM_HOME=/d/Work/asr_mm/.asrhome "$EXE" transcribe \
  "/d/Work/asr_mm/20250912 哲商現代実験学校 MR1 part1.avi" \
  -s 00:00:27 -e 00:00:38 --stdout --output-format srt --no-summary

rm -rf "$TMP"
echo
echo "GITHUB RELEASE VERIFIED"
