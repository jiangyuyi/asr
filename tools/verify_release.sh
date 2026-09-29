#!/usr/bin/env bash
# Verify the published release: assets present, sizes sane, links reachable.
set -uo pipefail
cd /d/Work/asr_mm

echo "=== release ==="
gh release view v1.0.0 --json tagName,name,isDraft,isPrerelease,url,publishedAt,body \
  --template 'tag:     {{.tagName}}
name:     {{.name}}
draft:    {{.isDraft}}
prerelease:{{.isPrerelease}}
url:      {{.url}}
published:{{.publishedAt}}
'

echo
echo "=== assets ==="
gh release view v1.0.0 --json assets --jq '.assets[] | "  \(.name)  \(.size/1048576 | . | floor) MB  downloads=\(.downloadCount)"'

echo
echo "=== HTTP status of each download URL ==="
gh release view v1.0.0 --json assets --jq '.assets[].url' | while read -r api_url; do
  name=$(basename "$api_url")
  # the API URL needs Accept:application/octet-stream to serve the file;
  # we only want to confirm the asset is published and resolvable.
  code=$(curl -s -o /dev/null -w '%{http_code}' -L \
    -H 'Accept: application/octet-stream' "$api_url")
  echo "  $code  $name"
done

echo
echo "=== repo summary ==="
gh repo view jiangyuyi/asr --json visibility,stargazerCount,forkCount,diskUsage \
  --template 'visibility: {{.visibility}}
stars:     {{.stargazerCount}}
forks:     {{.forkCount}}
disk:      {{.diskUsage}} KB
'
