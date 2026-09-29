#!/usr/bin/env bash
# Sign the macOS bundles. Run AFTER PyInstaller, BEFORE make_archives.py.
#
# Notarisation is a separate step that has to run against the finished archive
# (see notarize_macos.sh): Apple issues the ticket for the exact bytes that
# were submitted, so zipping before signing and signing after would invalidate
# it.
#
# Requires repository secrets (see docs/NOTARIZATION.md).
set -euo pipefail

cd "$(dirname "$0")/.."

KEYCHAIN="asr-mm-signing-$(date +%s)"
CERT_TMP="$(mktemp -d)"
cleanup() {
  security delete-keychain "$KEYCHAIN" 2>/dev/null || true
  rm -rf "$CERT_TMP"
}
trap cleanup EXIT

echo "==> importing the Developer ID certificate"
echo "$MACOS_CERT_P12" | base64 --decode > "$CERT_TMP/cert.p12"
security create-keychain -p "$MACOS_KEYCHAIN_PASSWORD" "$KEYCHAIN"
security set-keychain-settings -lut 21600 "$KEYCHAIN"
security unlock-keychain -p "$MACOS_KEYCHAIN_PASSWORD" "$KEYCHAIN"
security import "$CERT_TMP/cert.p12" -k "$KEYCHAIN" \
  -P "$MACOS_CERT_PASSWORD" -T /usr/bin/codesign -T /usr/bin/security
security set-key-partition-list -S apple-tool:,apple: \
  -s -k "$MACOS_KEYCHAIN_PASSWORD" "$KEYCHAIN" >/dev/null
security list-keychain -d user -s "$KEYCHAIN"
security set-keychain-settings -lut 21600 "$KEYCHAIN"

IDENTITY="Developer ID Application"

echo "==> signing nested code, then the bundles"
for bundle in dist/asr-mm dist/asr-mm-gui; do
  [ -d "$bundle" ] || continue
  # Libraries first: a parent's signature is invalidated when a nested binary
  # changes, and there are hundreds of dylibs in a PyInstaller bundle.
  find "$bundle" -type f \( -name '*.dylib' -o -name '*.so' \) -print0 |
    while IFS= read -r -d '' lib; do
      codesign --force --timestamp --options runtime --sign "$IDENTITY" "$lib" \
        2>/dev/null || echo "    (skipped unsigned dylib: ${lib#$bundle/})"
    done
  codesign --force --timestamp --options runtime --deep --sign "$IDENTITY" "$bundle"
  codesign --verify --deep --strict --verbose=2 "$bundle"
  echo "    ${bundle}: $(codesign -dv "$bundle" 2>&1 | grep -i '^Authority' | head -1)"
done
