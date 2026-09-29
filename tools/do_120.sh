set -euo pipefail
cd /d/Work/asr_mm

git add -A
git commit -q -m "1.2.0: 加载视频不再卡死

版本号同步到 1.2.0。其余内容见上一条提交。

打包验证：dist/asr-mm/asr-mm.exe 报 1.2.0 且三语词条正常；
dist/asr-mm-gui/asr-mm-gui.exe 带视频参数启动后稳定运行 20 秒。"

git push -q origin main
echo "pushed main"

git tag -a v1.2.0 -m "asr-mm 1.2.0

修复打开视频时界面无响应的问题。

原先 ffprobe 与首帧解码都跑在 GUI 线程上，实测打开 AVI 期间 GUI 线程
停顿峰值 288ms；慢盘、网络盘或被杀毒扫描的大文件上更久，且期间窗口
完全没有响应。

现在读取与解码移到后台线程，期间弹窗显示进度并可随时取消：
- 探测阶段为不确定态动画（此时没有可信百分比）
- 解码阶段切换为 ffmpeg -progress 提供的真实百分比
- 快速加载不闪现弹窗，首帧画面先于播放器显示

顺带修复两个 Qt 行为问题：QProgressDialog.cancel() 不触发 canceled()
信号导致取消按钮失效；取消时过早释放 QThread 引用导致线程被回收。"

git push origin v1.2.0
echo
echo "=== runs ==="
sleep 6
gh run list --workflow release --limit 2
