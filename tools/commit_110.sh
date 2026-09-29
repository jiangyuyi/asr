set -euo pipefail
cd /d/Work/asr_mm

git add -A
git commit -q -m "1.1.0: 界面多语言（中/英/日）+ 日文/中文 Windows 路径修复

编码修复（实测发现的真实故障）:
llama.cpp 的 GGUF 加载器用窄字符 fopen 打开模型，路径中的非 ASCII 字符按
系统 ANSI 代码页解释。日文 Windows（CP932）上模型位于
C:\\Users\\日本語\\AppData\\Local\\asr-mm 时会加载失败：
  gguf_init_from_file: failed to open GGUF file '...\\日本語\\...' (No such file)
输入音频路径和可执行文件路径走的是另一条 UTF-8 通道，不受影响。

现在当用户目录含非 ASCII 字符时，模型会硬链接到同卷的纯 ASCII 目录
（优先 %PUBLIC% / %ProgramData% / 同盘盘根），不额外占用磁盘。
新增 tools/enc_stress.py 等脚本可复现全部编码场景。

多语言:
- asr_mm/i18n.py 提供 zh/en/ja 三份词条，CLI 与 GUI 共用
- GUI 右上角可切换，切换即时生效且不会丢失结果表里的手工编辑
- CLI 支持 --lang，默认跟随系统（Windows 读 UI 语言，POSIX 读 LC_ALL/LANG）
- 词条完整性由测试保证：三语键集合一致、占位符一致、无空串
- CJK 全角字符按显示宽度对齐命令行表格

已验证：60 项单元测试 + 11 项端到端全部通过；中文/日文/西里尔/emoji/
含空格文件名，日文目录下的音频与可执行文件路径，GUI 三语界面。"

git push -q origin main
echo "pushed main"
git log --oneline -1
echo
git ls-files | wc -l | xargs echo "tracked files:"
