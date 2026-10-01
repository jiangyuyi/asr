set -euo pipefail
cd /d/Work/asr_mm

for f in tools/export_demo.txt tools/frozen_xlsx.txt tools/lang_probe.txt \
         tools/mirror_probe.txt tools/net_e2e.txt tools/final_130.txt; do
  printf '%s\n' "$f" >> .gitignore.new
done
sort -u .gitignore .gitignore.new -o .gitignore
rm -f .gitignore.new

git add -A
git commit -q -m "1.4.0: 新增 Excel 导出，并按实测修正语言支持说明

之前所有文案都把产品描述为「中文转写」，与实测不符。实测表明默认的 Nano
可以正确转写中/英/日，而 Paraformer 实质上是中文专用。

语言支持（用系统 TTS 分别生成中英日同一句话实测）
  Nano        中/英/日 均可，标点与大小写都正确
  SenseVoice  中/英 正常，日文词间多空格
  Paraformer  仅中文：日文输出为空，英文丢空格与大写

改动：
- catalog 为每个模型标注实测的 languages / degraded，并提供本地化警告
- 新增「内容语言」选择器（自动/中/英/日），选到模型不支持的语言时明确警告；
  命令行对应 --content-lang
- 修正三语文案：模型名与说明不再笼统写「中文」，Paraformer 标注「仅中文」
- 新增 asr_mm/export.py，统一 txt/srt/json/xlsx 导出（此前 CLI 与 GUI 各写一套，
  内容已经开始漂移：GUI 导界面上的编辑结果，CLI 导原始结果）
- Excel：每句一行，6 列（序号/开始/结束/开始(秒)/时长(秒)/内容），表头冻结、
  带筛选器、文本换行；时间戳为视频绝对时间，秒数为可排序数值列
- 界面「导出…」默认 .xlsx，过滤器含 Excel；导出的是界面当前内容（含手工编辑）
- openpyxl 为纯 Python 依赖，Windows/macOS 打包无需分别编译

测试从 92 增至 116 项。已验证冻结产物能写出结构正确、内容无误的 xlsx，
且 GUI 仍能正常启动。"

git push -q origin main
echo "pushed main"
git log --oneline -1

git tag -a v1.4.0 -m "asr-mm 1.4.0

新增 Excel 导出：每句一行，含序号、开始、结束、开始秒、时长与内容，
表头冻结并带筛选器，时间戳为视频绝对时间。列标题跟随界面语言。

同时按实测修正语言支持说明：默认的 Nano 支持中/英/日，Paraformer 仅中文。
新增「内容语言」选项，选到模型不支持的语言时会明确警告，而不是静默出错。"

git push origin v1.4.0
echo
sleep 6
gh run list --workflow release --limit 2
