set -euo pipefail
cd /d/Work/asr_mm

git add -A
git commit -q -m "1.2.1: macOS 首次运行不再需要手动 xattr

从 GitHub 下载的压缩包带 quarantine 标记，未签名的程序在标记状态下不允许
dlopen 自己的动态库，PyInstaller 产物里全是 dylib，所以 macOS 上直接双击
必然失败：
  Failed to load Python shared library .../_internal/Python
  ... library load disallowed by system policy

改动：
- macOS 压缩包附带 Open asr-mm.command，双击即自动清除隔离标记再启动
- 同包附 README-macOS.txt，中英日三语说明
- 启动器按归档内容生成：命令行包指向 asr-mm/asr-mm，图形包指向
  asr-mm-gui/asr-mm-gui（此前两者共用一个指向 GUI 的路径，命令行包必然失败）
- 打包时显式保留 Unix 权限位，否则解压后启动器没有可执行权限
- 新增可选的签名与公证通路（packaging/sign_macos.sh、notarize_macos.sh），
  配置了 Apple secret 时自动启用，否则跳过
- docs/NOTARIZATION.md 说明如何配置

公证流程顺序为 签名 -> 打包 -> 公证：Apple 按提交的字节签发票据，
先打包后签名会让票据失效。由 tools/check_workflow_order.py 强制校验。"

git push -q origin main
echo "pushed main"

git tag -a v1.2.1 -m "asr-mm 1.2.1

修复 macOS 首次运行被 Gatekeeper 拦截的问题。

从 GitHub 下载的压缩包带 quarantine 标记，未签名的程序在标记状态下不允许
加载自己的动态库，表现为
「Failed to load Python shared library ... not valid for use in process:
library load disallowed by system policy」。

现在压缩包内附带 Open asr-mm.command，双击会自动清除标记后启动；
也可以手动执行一次 xattr -cr，或在 Finder 中右键 → 打开。

彻底免去该步骤需要 Apple Developer ID 签名与公证，配置见
docs/NOTARIZATION.md；流水线已支持，配置 secret 即自动启用。"

git push origin v1.2.1
echo
sleep 6
gh run list --workflow release --limit 2
