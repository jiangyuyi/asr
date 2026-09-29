set -euo pipefail
cd /d/Work/asr_mm

# drop the throwaway fixture the error-path test created
mavis-trash tools/_fake_dist 2>/dev/null || rm -rf tools/_fake_dist

git add -A
git commit -q -m "避免误运行构建缓存里的 exe

PyInstaller 在 COLLECT 之前就会把 exe 写进 work 目录，但 _internal/
（python311.dll、ffmpeg、识别引擎）要到最后才组装进 dist/。直接双击
work 目录里的 exe 会报「Failed to load Python DLL」。

- README 补充构建章节，写明成品在 dist/ 以及这个报错的由来
- 构建与 CI 改用 --workpath .pyinstaller-cache，不再产生像产物的目录
- 新增 tools/run_gui.py：只从 dist/ 启动，产物不完整时给出可读提示"

git push -q origin main
echo "pushed"
git log --oneline -1
echo
echo "=== 工作区状态 ==="
git status --porcelain | head
echo "(空 = 干净)"
