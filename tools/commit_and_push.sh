#!/usr/bin/env bash
# Create the public repo, commit, and push to main.
set -euo pipefail
cd /d/Work/asr_mm

git add -A
git rm -r --cached . -q 2>/dev/null || true
git add -A

echo "--- staged count ---"
git status --porcelain | wc -l
echo "--- staged total ---"
git ls-files -z | xargs -0 -I{} sh -c '[ -f "{}" ] && stat -c "%s" "{}"' 2>/dev/null \
  | awk '{s+=$1} END {printf "%.2f MB\n", s/1048576}'
echo "--- sanity: nothing huge or third-party ---"
git ls-files -z | xargs -0 -I{} sh -c '[ -f "{}" ] && stat -c "%s %n" "{}"' 2>/dev/null \
  | sort -rn | head -6

git -c user.name="$(git config user.name)" \
    -c user.email="$(git config user.email)" \
    commit -q -m "$(cat <<'EOF'
asr-mm: 视频指定时间段 → 中文语音转写

先用 ffmpeg 精确截取目标区间，再交给本地 ASR 引擎识别。
转写 30 秒音频约需 2.8 秒（11× 实时），全程离线。

实现要点：
- 识别交给 FunASR 官方预编译的 llama.cpp 二进制（Win 5MB / macOS 7MB），
  Python 侧只做编排，因此无需打包 Python ML 框架，安装包约 225MB 而非 2GB
- 三档模型按需下载并缓存，Nano（标点完整、默认）/ Paraformer（最快，无标点）/
  SenseVoice（唯一支持 CUDA/Vulkan）
- VAD 分段默认锁定 10 秒：LLM 解码模型在长噪声段上会退化成复读
- 疑似噪音幻听片段只标记不自动删除，交由使用者决定
- PySide6 界面 + 命令行双入口，ffmpeg 与引擎随包分发
EOF
)"

echo
echo "--- log ---"
git log --oneline -1
echo "--- files committed ---"
git ls-files | wc -l
