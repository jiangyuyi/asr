#!/usr/bin/env bash
# Poll the release workflow until it finishes, then show the release state.
set -uo pipefail
cd /d/Work/asr_mm

RUN_ID="${1:-}"
if [ -z "$RUN_ID" ]; then
  RUN_ID=$(gh run list --workflow release --limit 1 --json databaseId --jq '.[0].databaseId')
fi
echo "watching run $RUN_ID"

for i in $(seq 1 60); do
  STATUS=$(gh run view "$RUN_ID" --json status,conclusion --jq '"\(.status)/\(.conclusion // "-")"')
  echo "[$i] $STATUS"
  case "$STATUS" in
    completed/*) break ;;
  esac
  sleep 20
done

echo
echo "=== jobs ==="
gh run view "$RUN_ID" --json jobs --jq '.jobs[] | "\(.name): \(.conclusion // .status)  (\(.startedAt))"'

echo
echo "=== failed steps, if any ==="
gh run view "$RUN_ID" --log-failed 2>/dev/null | tail -60 || echo "(no failed logs)"
