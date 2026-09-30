set -euo pipefail
cd /d/Work/asr_mm

for f in tools/mirror_probe.txt tools/net_e2e.txt tools/frozen_net.txt \
         tools/load_dialog_test.txt tools/archive_check.txt; do
  printf '%s\n' "$f" >> .gitignore.new
done
sort -u .gitignore .gitignore.new -o .gitignore
rm -f .gitignore.new

git add -A
git commit -q -m "1.3.0: 修复下载模型时的证书校验失败

macOS 用户下载模型报
  sslopen error [SSL: CERTIFICATE_VERIFY_FAILED]
  certificate verify failed: unable to get local issuer certificate

原因有两层，都属于打包/配置问题而非用户网络「不通」：

1. 打包后没有 CA 存储。macOS 的 Python 从框架目录读 cert.pem，PyInstaller
   不会把该文件带进包里，导致 ssl 的信任库为空 —— 此时任何 HTTPS 都会失败。
2. 企业 TLS 解密代理。代理用自���根证书重新签发，而那张根证书只存在于系统
   钥匙串 / 证书库里，Python 之前完全不读。浏览器能访问是因为系统信任它。

改动：
- 新增 asr_mm/net.py：始终加载 certifi 根证书；注入 truststore 以读取系统
  信任库；按「重试同一源 / 换下一个源」分别决策；把网络错误翻译成可执行建议
- 新增 asr_mm/settings.py：持久化语言、下载源、根证书
- catalog 加入 ModelScope 镜像（已逐文件核对体积一致），默认 HF 优先、失败
  自动切换；实测 huggingface.co → modelscope.cn 回退成功且内容一致
- 新增「工具 → 网络设置」：下载源、自定义根证书、跳过校验（带风险说明）
- 新增 asr-mm net-check：逐源测试并显示证书签发者，可据此判断是否被中间人解密
- 打包固定携带 certifi 与 truststore；已验证 137 张根证书进包，冻结产物可完成
  经校验的 HTTPS 请求
- 顺带修复：net.fetch 不再要求调用方预先创建目标目录

测试从 60 增至 92 项，覆盖镜像回退、断点续传、错误分类、CA 定制与三语词条。"

git push -q origin main
echo "pushed main"
git log --oneline -1

git tag -a v1.3.0 -m "asr-mm 1.3.0

修复下载模型时的证书校验失败，并加入网络诊断。

- 打包后始终携带 CA 根证书，并读取系统信任库（公司根证书所在处）
- 模型同时提供 ModelScope 镜像，默认优先 Hugging Face，失败自动切换
- 新增「工具 → 网络设置」与 asr-mm net-check，可直接看出证书是谁签发的
- 支持指定公司根证书；跳过校验需显式开启并提示风险"

git push origin v1.3.0
echo
sleep 6
gh run list --workflow release --limit 2
