#!/usr/bin/env bash
# Commit the packaging fix, push, then tag v1.0.0 to trigger the release build.
set -euo pipefail
cd /d/Work/asr_mm

git add -A
git commit -q -m "打包改用 Python zipfile

Git Bash on Windows 不带 zip 可执行文件，流水线的 Windows job 会因此失败，
与构建本身无关。改由 packaging/make_archives.py 统一处理三个平台的归档。"

git push -q origin main
echo "pushed main"

echo
echo "=== tagging v1.0.0 ==="
git tag -a v1.0.0 -m "asr-mm 1.0.0

视频指定时间段 → 中文语音转写。
Windows x64 与 macOS arm64 构建产物由 CI 生成并附到 release。"
git push origin v1.0.0

echo
echo "=== tags on remote ==="
git ls-remote --tags origin
echo
echo "=== recent runs ==="
gh run list --limit 3
