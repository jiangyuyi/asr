set -euo pipefail
cd /d/Work/asr_mm

rm -f tools/republish_121.sh

git add -A
git commit -q -m "修复打包压缩失效

zipfile 的 writestr() 从 ZipInfo 上读 compress_type，而 ZipInfo 默认是
ZIP_STORED，不继承 ZipFile 的设置。为了保留 Unix 权限位把 z.write() 换成
writestr() 时，压缩就此静默失效：

  macOS    115 MB -> 308 MB
  Windows   89 MB -> 244 MB

现在显式设置 compress_type，并加一道打包后的体积断言：压缩率高于 75%
直接报错退出，避免同类回归再次悄悄发版。"

git push -q origin main
echo "pushed main"
git log --oneline -1

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
