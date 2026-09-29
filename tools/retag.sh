#!/usr/bin/env bash
# Move v1.0.0 to the fixed commit and re-trigger the release build.
set -euo pipefail
cd /d/Work/asr_mm

git add -A
git commit -q -m "修复 Windows 构建：打包步骤改用纯 Python 调用

GitHub 的 windows-latest 默认 shell 是 PowerShell，原步骤里的
set -euo pipefail 与 [ ... ] && 赋值语法会直接解析失败。
版本号改由 make_archives.py 从 GITHUB_REF_NAME 读取，步骤体内不再有 shell 专有语法。"

git push -q origin main
echo "pushed main"

echo
echo "=== moving tag v1.0.0 to the fixed commit ==="
git tag -d v1.0.0
git push origin :refs/tags/v1.0.0
git tag -a v1.0.0 -m "asr-mm 1.0.0

视频指定时间段 → 中文语音转写。
Windows x64 与 macOS arm64 构建产物由 CI 生成并附到 release。"
git push origin v1.0.0

echo
echo "=== runs ==="
gh run list --workflow release --limit 3
