set -euo pipefail
cd /d/Work/asr_mm

git add -A
git commit -q -m "加载视频不再卡死：后台线程 + 进度弹窗

打开视频时 ffprobe 和首帧解码原本跑在 GUI 线程上。本机实测 AVI 打开期间
GUI 线程停顿峰值 288ms；慢盘、网络盘或被杀毒软件扫描的大文件上会更久，
而且期间界面完全没有响应，无法分辨是在读文件还是已经卡死。

改动：
- 新增 asr_mm/gui/loader.py，探测与海报解码移到后台线程
- 加载时弹 QProgressDialog：探测阶段为不确定态动画，解码阶段切换为
  ffmpeg -progress 提供的真实百分比，并做缓动避免跳变
- 快速加载不闪现弹窗（minimumDuration 350ms）
- 海报先于播放器显示，窗口不会是一块黑屏
- 取消按钮可用，且真的能中断 ffmpeg 子进程

两个实测到的坑：
1. Qt 6 / PySide6 的 QProgressDialog.cancel() 不触发 canceled() 信号，
   对话框只是隐藏。取消逻辑重写 cancel() 来拦截，否则按钮形同虚设。
2. 取消时立即丢弃 loader 引用会让仍在运行的 QThread 被回收
   （QThread: Destroyed while thread is still running）。改为在 finished
   信号里释放，并校验身份，避免旧 worker 清掉新 worker。

实测：AVI 打开的 GUI 线程停顿峰值从 288ms 降到 20-27ms；
模拟 3s 探测 + 4s 解码时，弹窗可见、进度单调递增、取消后正常收尾。"

git push -q origin main
echo "pushed"
git log --oneline -1
