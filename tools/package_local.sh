#!/usr/bin/env bash
# Build local release archives for Windows. Kept as a fallback if CI cannot run.
set -euo pipefail
cd /d/Work/asr_mm

VERSION="${1:-1.0.0}"
OUT="release"
rm -rf "$OUT"
mkdir -p "$OUT"

for name in asr-mm asr-mm-gui; do
  [ -d "dist/$name" ] || { echo "missing dist/$name — run the build first"; exit 1; }
  echo "packing $name ..."
  ( cd dist && zip -rq "../$OUT/${name}-${VERSION}-windows-x64.zip" "$name" )
done

echo
echo "--- archives ---"
ls -lh "$OUT"
echo
echo "--- total ---"
du -sh "$OUT"
