#!/usr/bin/env bash
# Commit the licence change, create the public repo, and push main.
set -euo pipefail
cd /d/Work/asr_mm

git add -A
git commit -q -m "添加 MIT LICENSE，并在 README 列出第三方组件许可"

echo "=== creating repo ==="
if gh repo view jiangyuyi/asr >/dev/null 2>&1; then
  echo "repo already exists"
else
  gh repo create jiangyuyi/asr \
    --public \
    --description "视频指定时间段 → 中文语音转写。本地离线，ffmpeg 精确截取 + FunASR 引擎" \
    --homepage "https://github.com/jiangyuyi/asr" \
    --source . --remote origin
fi

echo
echo "=== remote ==="
git remote -v

echo
echo "=== pushing ==="
git push -u origin main 2>&1 | tail -5

echo
echo "=== repo state ==="
gh repo view jiangyuyi/asr --json name,visibility,url,defaultBranchRef,description \
  --jq '"name=\(.name)  visibility=\(.visibility)  branch=\(.defaultBranchRef.name)\nurl=\(.url)\ndesc=\(.description)"'
