#!/usr/bin/env bash
# Verify the published release: assets present, sizes sane, links reachable.
set -uo pipefail
cd /d/Work/asr_mm

TAG="${1:-v1.0.0}"

echo "=== release $TAG ==="
gh release view "$TAG" --json tagName,name,isDraft,isPrerelease,url,publishedAt \
  --template 'tag:     {{.tagName}}
name:     {{.name}}
draft:    {{.isDraft}}
prerelease:{{.isPrerelease}}
url:      {{.url}}
published:{{.publishedAt}}
'

echo
echo "=== assets ==="
gh release view "$TAG" --json assets --jq '.assets[] | "  \(.name)  \(.size/1048576 | . | floor) MB  downloads=\(.downloadCount)"'

echo
echo "=== HTTP status of each download URL ==="
gh release view "$TAG" --json assets --jq '.assets[].url' | while read -r api_url; do
  name=$(basename "$api_url")
  code=$(curl -s -o /dev/null -w '%{http_code}' -L \
    -H 'Accept: application/octet-stream' "$api_url")
  echo "  $code  $name"
done

echo
echo "=== all releases ==="
gh release list
