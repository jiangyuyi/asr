#!/usr/bin/env bash
# Submit the finished macOS archives to Apple's notary service.
# Run AFTER sign_macos.sh and make_archives.py.
#
# Apple issues a ticket for the exact bytes submitted, so the archives that get
# notarised here are the same ones the release step uploads. Do not re-zip
# afterwards.
#
# A PyInstaller COLLECT build is a folder, not a .app, so it cannot be
# stapled. Gatekeeper still honours the server-side ticket, which turns the
# hard "cannot be opened" failure into a one-time "verified by Apple" prompt.
set -euo pipefail

cd "$(dirname "$0")/.."

VERSION="${GITHUB_REF_NAME#v}"
VERSION="${VERSION:-dev}"
ARCHIVES=(
  "release/asr-mm-${VERSION}-macos-arm64.zip"
  "release/asr-mm-gui-${VERSION}-macos-arm64.zip"
)

KEY_TMP="$(mktemp -d)"
trap 'rm -rf "$KEY_TMP"' EXIT
printf '%s' "$NOTARY_PRIVATE_KEY" > "$KEY_TMP/AuthKey_${NOTARY_KEY_ID}.p8"

for archive in "${ARCHIVES[@]}"; do
  [ -f "$archive" ] || { echo "missing $archive"; continue; }
  echo "==> notarising $(basename "$archive")"
  xcrun notarytool submit "$archive" \
    --key "$KEY_TMP/AuthKey_${NOTARY_KEY_ID}.p8" \
    --key-id "$NOTARY_KEY_ID" \
    --issuer "$NOTARY_ISSUER_ID" \
    --output-format json > "$KEY_TMP/result.json"

  status=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['status'])" \
    "$KEY_TMP/result.json")
  id=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('id',''))" \
    "$KEY_TMP/result.json")
  echo "    status: $status  id: $id"
  if [ "$status" != "Accepted" ]; then
    xcrun notarytool log "$id" --key "$KEY_TMP/AuthKey_${NOTARY_KEY_ID}.p8" \
      --issuer "$NOTARY_ISSUER_ID" 2>&1 | head -40 || true
    echo "::error::notarisation rejected for $archive"
    exit 1
  fi
done

echo "==> all archives accepted"
