set -euo pipefail
cd /d/Work/asr_mm

# pull the PyInstaller cache back out of git; it is a build artefact
git rm -r -q --cached .pyinstaller-cache 2>/dev/null || true
git rm -q --cached tools/frozen_gui_120.txt 2>/dev/null || true

git add -A
git commit -q -m "修正 .gitignore，忽略 .pyinstaller-cache

上一条提交误把 PyInstaller 的构建缓存当源码提交了（19 个 .toc/.pyz 文件）。
缓存是本地产物，不应进仓库。"

git push -q origin main
echo "pushed main"
echo
echo "--- 确认已从索引移除 ---"
git ls-files | grep -c 'pyinstaller-cache' || echo "0 (clean)"
echo
echo "--- 仓库文件数 ---"
git ls-files | wc -l
echo
git log --oneline -3
