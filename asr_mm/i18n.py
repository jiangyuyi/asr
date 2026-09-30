"""UI and CLI localisation (简体中文 / English / 日本語).

Kept as a plain Python module rather than Qt ``.ts``/``.qm`` resources: a frozen
one-file bundle has no compile step for translations, and shipping three small
dictionaries inline removes any chance of them going missing from the package.

The transcribed text is never translated — the engines produce Chinese speech
text regardless of which language the interface is set to.
"""
from __future__ import annotations

import os
import sys
from typing import Callable

# code -> (native name, English name, aliases we accept from the OS)
CATALOG_META: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "zh": ("简体中文", "Simplified Chinese",
           ("zh-cn", "zh_cn", "zh-hans", "zh_hans", "zh-sg", "zh_tw", "zh-hant",
            "zh-hk", "zh-mo", "chinese", "chs", "simplified chinese",
            "简体中文", "zh")),
    "en": ("English", "English",
           ("en-us", "en_us", "en-gb", "en_gb", "english", "eng", "en")),
    "ja": ("日本語", "Japanese",
           ("ja-jp", "ja_jp", "japanese", "jpn", "日本語", "ja", "jp")),
}

DEFAULT_LANG = "zh"

ZH: dict[str, str] = {
    # ---- window / toolbar
    "app.title": "asr-mm · 视频片段转写 {version}",
    "toolbar.open": "打开视频…",
    "toolbar.model": "模型",
    "toolbar.language": "语言",
    "drop.hint": "拖入视频文件\n或点击这里选择",
    # ---- range panel
    "section.range": "时间区间",
    "range.start": "开始",
    "range.end": "结束",
    "range.set_start": "起点 = 当前位置",
    "range.set_end": "终点 = 当前位置",
    "play": "▶ 播放",
    # ---- options
    "section.options": "识别选项",
    "opt.preroll": "预读",
    "opt.preroll_suffix": " 秒",
    "opt.preroll_tip": "起点前多取一点，避免切到半个字",
    "opt.drop_short": "过滤疑似噪音片段",
    "opt.drop_short_tip": "丢掉极短且字数极少的识别结果（常见于纯噪音）",
    "opt.loudnorm": "先做响度归一化",
    "opt.loudnorm_tip": "音量差异大时勾选",
    "model.ready": "✓ {key} 已就绪 · {size}",
    "model.missing": "⚠ 模型未下载，缺少 {count} 个文件（{names}…）\n点菜单「工具 → 下载缺失模型」",
    "run": "开始转写",
    # ---- results
    "section.results": "识别结果",
    "table.col_start": "开始",
    "table.col_dur": "时长",
    "table.col_text": "文字（可双击编辑）",
    "row.tip": "双击可编辑",
    "row.tip_suspect": "疑似噪音误识别（黄色底色），可双击编辑或删除整行",
    "action.copy": "复制全文",
    "action.export": "导出…",
    "action.export_clip": "导出该段视频",
    # ---- menu
    "menu.file": "文件(&F)",
    "menu.tools": "工具(&T)",
    "menu.help": "帮助(&H)",
    "menu.open": "打开视频…",
    "menu.quit": "退出",
    "menu.download_models": "下载缺失模型…",
    "menu.open_models": "打开模型目录",
    "menu.doctor": "自检",
    "menu.about": "关于",
    # ---- status bar
    "status.ready": "就绪。首次使用请先下载模型：asr-mm setup",
    "status.loaded": "已加载 {name}，时长 {duration}",
    "status.start_set": "起点 = {tc}",
    "status.end_set": "终点 = {tc}",
    "status.position": "播放位置 {tc}",
    "status.running": "正在识别…",
    "status.extract": "正在抽取音频…",
    "status.done": "完成：{count} 条片段，耗时 {elapsed}s / 音频 {audio}s（{speed}）",
    "status.done_note": "完成：{count} 条片段，耗时 {elapsed}s / 音频 {audio}s（{speed}）  |  {note}",
    "status.failed": "识别失败",
    "status.copied": "已复制全文到剪贴板",
    "status.exported": "已导出 {path}",
    "status.exported_clip": "已导出片段 {path}",
    "status.preview_failed": "该格式无法在系统播放器中预览（{error}）。不影响转写，可直接用时间输入框选择区间。",
    # ---- dialogs
    "dlg.cannot_open": "无法打开",
    "dlg.model_missing": "模型 {key} 尚未下载完成。\n请先执行「工具 → 下载缺失模型」。",
    "dlg.export_failed": "导出失败",
    "dlg.transcribe_failed": "识别失败",
    "dlg.about": (
        "<b>asr-mm {version}</b><br><br>"
        "视频指定时间段 → 中文语音转写<br>"
        "本地离线运行，模型来自 FunASR（MIT）。<br><br>"
        "<span style='color:#6b7280'>{hint}</span>"),
    "dlg.about_hint": "Ctrl+O 打开视频 · 双击结果行可编辑文字 · 点击结果行跳转播放位置",
    # ---- loading
    "load.window": "正在打开视频",
    "load.title": "正在读取视频，请稍候…",
    "load.cancel": "取消",
    "load.probing": "正在读取 {name} 的信息…",
    "load.decoding": "正在解码 {name} 的预览画面…",
    "load.done": "完成",
    "load.cancelled": "已取消打开 {name}",
    "load.failed": "无法打开 {name}",
    # ---- model download dialog
    "models.title": "下载识别模型",
    "models.intro": (
        "模型体积较大（Nano 约 911 MB，Paraformer 约 228 MB），只需下载一次，"
        "之后可离线使用。\n下载可随时中断，下次继续。"),
    "models.state_ready": "已就绪",
    "models.state_missing": "未下载",
    "models.all": "下载全部",
    "models.only_nano": "仅 Nano",
    "models.only_fast": "仅 Paraformer",
    "models.close": "关闭",
    "models.failed": "✗ {key} 下载失败：{error}",
    # ---- file dialogs
    "filedialog.video": "选择视频",
    "filedialog.export": "导出",
    "filedialog.clip": "导出片段视频",
    "filter.video": "视频文件 (*.mp4 *.mkv *.avi *.mov *.flv *.wmv *.m4v *.ts *.webm *.mpg *.mpeg *.rmvb *.3gp);;所有文件 (*.*)",
    "filter.text": "文本文件 (*.txt);;字幕文件 (*.srt);;JSON (*.json)",
    "filter.mp4": "MP4 (*.mp4);;所有文件 (*.*)",
    # ---- errors raised by the library
    "err.not_a_file": "文件不存在: {path}",
    "err.is_dir": "需要一个视频文件，不接受目录: {path}",
    "err.no_audio": "该文件没有音频轨道，无法转写。",
    "err.unreadable": "无法解析媒体信息（可能不是 ffmpeg 支持的格式）:\n{tail}",
    "err.extract_failed": "音频抽取失败:\n{tail}",
    "err.clip_failed": "片段导出失败:\n{tail}",
    "err.no_ffmpeg": "找不到可用的 ffmpeg：程序内置的 ffmpeg/ffmpeg 缺失，PATH 中也没有。请重新安装本程序。",
    "err.no_runtime": "未安装识别运行时（{platform}）。请先运行： asr-mm setup\n  目标目录: {dir}",
    "err.missing_exe": "缺少可执行文件: {path}",
    "err.model_incomplete": "模型 {key} 尚未下载完整，缺少: {names}\n请运行: asr-mm models download {key}",
    "err.engine_start": "无法启动识别引擎: {path}",
    "err.engine_timeout": "识别超时（超过 2 小时）。",
    "err.engine_returned": "识别引擎返回 {code}:\n{tail}",
    "err.engine_empty": "识别引擎没有输出任何内容。音频可能不含人声，或采样率/声道异常。",
    "err.wav_missing": "音频文件不存在: {path}",
    "err.range_short": "时间区间过短或顺序颠倒（{start} – {end}）。请用 --start / --end 指定。",
    "err.range_past_end": "指定的时间区间超出了视频时长。视频总长 {duration}，你给的是 {start} – {end}。",
    "err.empty_range": "时间区间为空。",
    "err.bad_timecode": "无法解析时间码: {value}（用 00:03:20 / 200 / 3:20 这样的格式）",
    "err.unknown_model": "未知模型: {key}（可用: {list}）",
    "err.unsupported_platform": "暂不支持的平台: {platform}。可手动放置 llama-funasr-* 可执行文件到 {dir}",
    "err.no_language": "GUI 依赖未安装。请运行: pip install PySide6",
    "err.bad_archive": "无法解压的归档格式: {name}",
    "err.zip_escape": "归档包含越界路径: {name}",
    "err.tar_link": "归档包含链接，已拒绝: {name}",
    "err.sha_mismatch": "校验失败 {name}\n  期望 sha256 {expected}\n  实际 {actual}",
    "err.runtime_incomplete": "运行时解压后仍缺少: {names}",
    "err.no_speech": "VAD 未在该区间检测到有效语音（可能是纯静音或纯环境音）。",
    "err.download_failed": "下载失败: {url}",
    "warn.noisy_segments": (
        "{count} 个片段很短且字数极少，可能是噪音误识别（{preview}{more}）。"
        "可用 --drop-short 过滤。"),
    # ---- shared nouns
    "model.nano": "Nano（质量档·推荐）",
    "model.paraformer": "Paraformer（快速档）",
    "model.sensevoice": "SenseVoice（均衡档）",
    "model.nano.note": "标点最完整、中文准确率最高；约 10× 实时。",
    "model.paraformer.note": "约 27× 实时，体积最小；输出不带标点。仅 CPU。",
    "model.sensevoice.note": "唯一支持 CUDA/Vulkan 加速；短片段（<1.5s）易输出空内容。",
    "runtime.windows_avx2": "Windows x64 (AVX2)",
    "runtime.windows": "Windows x64 (通用)",
    "runtime.macos": "macOS arm64",
    "runtime.linux": "Linux x64",
    "runtime.unknown": "未知平台",
    "layout.models_staged": "{path}  (ASCII 暂存)",
    "layout.ffmpeg_path": "(ffmpeg not found on PATH)",
    "units.mb": " MB",
    "units.mb_short": "MB",
    "units.sec": " 秒",
    # ---- CLI
    "cli.desc": "视频指定时间段 → 中文语音转写",
    "cli.epilog": """示例:
  asr-mm setup                              首次使用：装运行时 + 下载模型
  asr-mm transcribe v.mp4                   转写整段
  asr-mm transcribe v.mp4 -s 00:03:20 -e 00:05:10
  asr-mm transcribe v.mp4 -s 200 -e 310 --model paraformer --format srt
  asr-mm doctor v.mp4                      环境自检
""",
    "cli.transcribe.help": "转写视频指定时间段",
    "cli.video.help": "视频文件路径",
    "cli.start.help": "起始时间，如 00:03:20 / 3:20 / 200",
    "cli.end.help": "结束时间",
    "cli.model.help": "识别模型（默认 nano）",
    "cli.format.help": "导出格式，逗号分隔: txt,srt,json（默认 txt,srt）",
    "cli.outdir.help": "输出目录（默认 视频名_transcript/）",
    "cli.name.help": "输出文件名主干",
    "cli.stdout.help": "结果打到标准输出，不写文件",
    "cli.output_format.help": "配合 --stdout 使用的格式",
    "cli.timestamps.help": "txt 中带时间戳",
    "cli.no_summary.help": "不打印统计摘要",
    "cli.maxseg.help": "VAD 分段上限毫秒（默认 {default}）",
    "cli.preroll.help": "起点前多取几秒，避免切到半个字（默认 0）",
    "cli.loudnorm.help": "先做响度归一化",
    "cli.drop_short.help": "丢弃极短且字数极少的疑似噪音片段",
    "cli.threads.help": "CPU 线程数（默认自动）",
    "cli.keep_audio.help": "保留抽取的中间 wav",
    "cli.lang.help": "界面语言: zh / en / ja（默认跟随系统）",
    "cli.models.help": "查看/下载模型",
    "cli.setup.help": "安装运行时并下载模型",
    "cli.doctor.help": "环境自检",
    "cli.models.title": "asr-mm {version} 可用模型：\n",
    "cli.models.default": "默认模型: {key}",
    "cli.models.state_ready": "✓ 已下载",
    "cli.models.state_missing": "○ 未下载",
    "cli.models.ready": "模型 {key} 已就绪。",
    "cli.models.downloading": "下载模型 {key} — {size}",
    "cli.models.done": "完成 -> {path}",
    "cli.setup.title": "asr-mm {version} 环境准备",
    "cli.setup.step_runtime": "[1/2] 识别运行时",
    "cli.setup.step_models": "[2/2] 模型",
    "cli.setup.runtime_ready": "  已就绪 -> {path}",
    "cli.setup.model_ready": "  {key:11s} 已就绪",
    "cli.setup.model_dl": "  {key:11s} 下载中 ({size})",
    "cli.setup.finished": "\n准备完成。运行 `asr-mm doctor` 自检，或 `asr-mm transcribe 视频.mp4` 开始。",
    "cli.doctor.title": "asr-mm {version} 自检\n",
    "cli.doctor.env": "环境",
    "cli.doctor.runtime": "运行时",
    "cli.doctor.models": "模型",
    "cli.doctor.ffmpeg": "ffmpeg",
    "cli.doctor.media": "媒体探测",
    "cli.doctor.platform_ok": "  平台匹配       ✓ {label}",
    "cli.doctor.runtime_ok": "  已安装         ✓",
    "cli.doctor.runtime_no": "  已安装         ✗",
    "cli.doctor.ffmpeg_path": "  路径           {path}",
    "cli.doctor.model_ready": "  {key:11s} ✓ 已就绪",
    "cli.doctor.model_missing": "  {key:11s} ✗ 缺 {count} 个文件",
    "cli.doctor.model_incomplete_short": "缺 {count} 个文件 ({size})",
    "cli.status_missing": "未安装",
    "cli.summary.range": "区间  {start} – {end}   (源时长 {duration})",
    "cli.summary.model": "模型  {model}   片段 {count} 条   耗时 {elapsed}s / 音频 {audio}s   ({speed})",
    "cli.summary.model_noaudio": "模型  {model}   片段 {count} 条   耗时 {elapsed}s",
    "cli.summary.dropped": "已过滤 {count} 个疑似噪音片段",
    "cli.summary.note": "提示: {text}",
    "cli.saved": "已保存 {path}",
    "cli.speed": "{speed}× 实时",
    "cli.dash": "—",
    "cli.status_title": "就绪",
    "cli.status_ready": "已就绪",
    "cli.status_installed": "已安装",
    "cli.bad_format": "未知输出格式: {names}",
}

EN: dict[str, str] = {
    "app.title": "asr-mm · video segment transcription {version}",
    "toolbar.open": "Open video…",
    "toolbar.model": "Model",
    "toolbar.language": "Language",
    "drop.hint": "Drop a video file here\nor click to browse",
    "section.range": "Time range",
    "range.start": "Start",
    "range.end": "End",
    "range.set_start": "Start = playhead",
    "range.set_end": "End = playhead",
    "play": "▶ Play",
    "section.options": "Recognition options",
    "opt.preroll": "Preroll",
    "opt.preroll_suffix": " s",
    "opt.preroll_tip": "Read a little before the start so a word is not cut in half",
    "opt.drop_short": "Drop suspected noise segments",
    "opt.drop_short_tip": "Remove very short results with almost no text (usually room noise)",
    "opt.loudnorm": "Normalize loudness first",
    "opt.loudnorm_tip": "Enable when volumes differ a lot",
    "model.ready": "✓ {key} ready · {size}",
    "model.missing": "⚠ Model not downloaded, {count} file(s) missing ({names}…)\nUse menu “Tools → Download missing models”",
    "run": "Transcribe",
    "section.results": "Transcript",
    "table.col_start": "Start",
    "table.col_dur": "Duration",
    "table.col_text": "Text (double-click to edit)",
    "row.tip": "Double-click to edit",
    "row.tip_suspect": "Likely noise misheard (yellow); edit or delete the row",
    "action.copy": "Copy all",
    "action.export": "Export…",
    "action.export_clip": "Export video clip",
    "menu.file": "File(&F)",
    "menu.tools": "Tools(&T)",
    "menu.help": "Help(&H)",
    "menu.open": "Open video…",
    "menu.quit": "Quit",
    "menu.download_models": "Download missing models…",
    "menu.open_models": "Open model folder",
    "menu.doctor": "Diagnostics",
    "menu.about": "About",
    "status.ready": "Ready. First run? Download a model: asr-mm setup",
    "status.loaded": "Loaded {name}, duration {duration}",
    "status.start_set": "Start = {tc}",
    "status.end_set": "End = {tc}",
    "status.position": "Playhead {tc}",
    "status.running": "Transcribing…",
    "status.extract": "Extracting audio…",
    "status.done": "Done: {count} segments, {elapsed}s for {audio}s of audio ({speed})",
    "status.done_note": "Done: {count} segments, {elapsed}s for {audio}s of audio ({speed})  |  {note}",
    "status.failed": "Transcription failed",
    "status.copied": "Transcript copied to clipboard",
    "status.exported": "Exported {path}",
    "status.exported_clip": "Clip exported to {path}",
    "status.preview_failed": "The system player cannot preview this format ({error}). Transcription is unaffected; pick the range with the time fields.",
    "dlg.cannot_open": "Cannot open",
    "dlg.model_missing": "Model {key} is not fully downloaded.\nUse “Tools → Download missing models” first.",
    "dlg.export_failed": "Export failed",
    "dlg.transcribe_failed": "Transcription failed",
    "dlg.about": (
        "<b>asr-mm {version}</b><br><br>"
        "Transcribe a chosen time range of a video to Chinese text.<br>"
        "Runs fully offline; models come from FunASR (MIT).<br><br>"
        "<span style='color:#6b7280'>{hint}</span>"),
    "dlg.about_hint": "Ctrl+O open · double-click a row to edit · click a row to jump the playhead",
    "load.window": "Opening video",
    "load.title": "Reading the video, please wait…",
    "load.cancel": "Cancel",
    "load.probing": "Reading information from {name}…",
    "load.decoding": "Decoding a preview frame from {name}…",
    "load.done": "Done",
    "load.cancelled": "Opening {name} was cancelled",
    "load.failed": "Could not open {name}",
    "models.title": "Download recognition models",
    "models.intro": (
        "Models are large (Nano ≈ 911 MB, Paraformer ≈ 228 MB) and only need "
        "downloading once; afterwards everything runs offline.\n"
        "The download can be interrupted and will resume next time."),
    "models.state_ready": "ready",
    "models.state_missing": "not downloaded",
    "models.all": "Download all",
    "models.only_nano": "Nano only",
    "models.only_fast": "Paraformer only",
    "models.close": "Close",
    "models.failed": "✗ {key} download failed: {error}",
    "filedialog.video": "Select video",
    "filedialog.export": "Export",
    "filedialog.clip": "Export video clip",
    "filter.video": "Video files (*.mp4 *.mkv *.avi *.mov *.flv *.wmv *.m4v *.ts *.webm *.mpg *.mpeg *.rmvb *.3gp);;All files (*.*)",
    "filter.text": "Text files (*.txt);;Subtitles (*.srt);;JSON (*.json)",
    "filter.mp4": "MP4 (*.mp4);;All files (*.*)",
    "err.not_a_file": "File does not exist: {path}",
    "err.is_dir": "A video file is required, not a directory: {path}",
    "err.no_audio": "This file has no audio track, so it cannot be transcribed.",
    "err.unreadable": "Could not read media info (possibly not a format ffmpeg supports):\n{tail}",
    "err.extract_failed": "Audio extraction failed:\n{tail}",
    "err.clip_failed": "Clip export failed:\n{tail}",
    "err.no_ffmpeg": "No usable ffmpeg: the bundled ffmpeg/ffmpeg is missing and none is on PATH. Please reinstall.",
    "err.no_runtime": "Recognition runtime is not installed ({platform}). Run: asr-mm setup\n  target: {dir}",
    "err.missing_exe": "Missing executable: {path}",
    "err.model_incomplete": "Model {key} is incomplete, missing: {names}\nRun: asr-mm models download {key}",
    "err.engine_start": "Could not start the recognition engine: {path}",
    "err.engine_timeout": "Recognition timed out (over 2 hours).",
    "err.engine_returned": "Recognition engine returned {code}:\n{tail}",
    "err.engine_empty": "The engine produced no output. The audio may contain no speech, or have an unexpected sample rate or channel layout.",
    "err.wav_missing": "Audio file does not exist: {path}",
    "err.range_short": "The range is too short or reversed ({start} – {end}). Use --start / --end.",
    "err.range_past_end": "The range is past the end of the video. Duration is {duration}, you asked for {start} – {end}.",
    "err.empty_range": "The time range is empty.",
    "err.bad_timecode": "Could not parse the timecode: {value} (use 00:03:20 / 200 / 3:20)",
    "err.unknown_model": "Unknown model: {key} (available: {list})",
    "err.unsupported_platform": "Unsupported platform: {platform}. You can place the llama-funasr-* executables in {dir}",
    "err.no_language": "GUI dependencies are not installed. Run: pip install PySide6",
    "err.bad_archive": "Cannot extract this archive format: {name}",
    "err.zip_escape": "Archive contains an out-of-tree path: {name}",
    "err.tar_link": "Archive contains links, refused: {name}",
    "err.sha_mismatch": "Checksum mismatch for {name}\n  expected sha256 {expected}\n  actual   {actual}",
    "err.runtime_incomplete": "Runtime is still missing after extraction: {names}",
    "err.no_speech": "VAD found no speech in this range (it may be silence or ambient noise only).",
    "err.download_failed": "Download failed: {url}",
    "warn.noisy_segments": (
        "{count} segment(s) are very short with almost no text and may be "
        "noise misheard ({preview}{more}). Use --drop-short to remove them."),
    "model.nano": "Nano (quality, recommended)",
    "model.paraformer": "Paraformer (fast)",
    "model.sensevoice": "SenseVoice (balanced)",
    "model.nano.note": "Best punctuation and accuracy for Chinese; about 10× realtime.",
    "model.paraformer.note": "About 27× realtime and smallest; no punctuation. CPU only.",
    "model.sensevoice.note": "Only model with CUDA/Vulkan acceleration; weak on very short segments.",
    "runtime.windows_avx2": "Windows x64 (AVX2)",
    "runtime.windows": "Windows x64 (generic)",
    "runtime.macos": "macOS arm64",
    "runtime.linux": "Linux x64",
    "runtime.unknown": "unsupported platform",
    "layout.models_staged": "{path}  (ASCII staging)",
    "layout.ffmpeg_path": "(ffmpeg not found on PATH)",
    "units.mb": " MB",
    "units.mb_short": "MB",
    "units.sec": " s",
    "cli.desc": "Transcribe a chosen time range of a video to Chinese text",
    "cli.epilog": """Examples:
  asr-mm setup                              first run: install runtime + models
  asr-mm transcribe v.mp4                   transcribe the whole file
  asr-mm transcribe v.mp4 -s 00:03:20 -e 00:05:10
  asr-mm transcribe v.mp4 -s 200 -e 310 --model paraformer --format srt
  asr-mm doctor v.mp4                      environment check
""",
    "cli.transcribe.help": "Transcribe a time range of a video",
    "cli.video.help": "path to the video file",
    "cli.start.help": "start time, e.g. 00:03:20 / 3:20 / 200",
    "cli.end.help": "end time",
    "cli.model.help": "recognition model (default: nano)",
    "cli.format.help": "output formats, comma separated: txt,srt,json (default txt,srt)",
    "cli.outdir.help": "output directory (default: <video>_transcript/)",
    "cli.name.help": "base name for the output files",
    "cli.stdout.help": "write the result to stdout instead of files",
    "cli.output_format.help": "format used together with --stdout",
    "cli.timestamps.help": "include timestamps in the txt output",
    "cli.no_summary.help": "do not print the summary",
    "cli.maxseg.help": "VAD segment cap in milliseconds (default {default})",
    "cli.preroll.help": "read this many seconds before the start (default 0)",
    "cli.loudnorm.help": "normalize loudness before recognition",
    "cli.drop_short.help": "drop very short segments that look like noise misheard",
    "cli.threads.help": "CPU threads (default: automatic)",
    "cli.keep_audio.help": "keep the extracted intermediate wav",
    "cli.lang.help": "interface language: zh / en / ja (default: follow the system)",
    "cli.models.help": "inspect or download models",
    "cli.setup.help": "install the runtime and download models",
    "cli.doctor.help": "environment diagnostics",
    "cli.models.title": "asr-mm {version} available models:\n",
    "cli.models.default": "Default model: {key}",
    "cli.models.state_ready": "✓ downloaded",
    "cli.models.state_missing": "○ not downloaded",
    "cli.models.ready": "Model {key} is ready.",
    "cli.models.downloading": "Downloading model {key} — {size}",
    "cli.models.done": "Done -> {path}",
    "cli.setup.title": "asr-mm {version} setup",
    "cli.setup.step_runtime": "[1/2] Recognition runtime",
    "cli.setup.step_models": "[2/2] Models",
    "cli.setup.runtime_ready": "  ready -> {path}",
    "cli.setup.model_ready": "  {key:11s} ready",
    "cli.setup.model_dl": "  {key:11s} downloading ({size})",
    "cli.setup.finished": "\nSetup complete. Run `asr-mm doctor` to verify, or `asr-mm transcribe video.mp4` to start.",
    "cli.doctor.title": "asr-mm {version} diagnostics\n",
    "cli.doctor.env": "Environment",
    "cli.doctor.runtime": "Runtime",
    "cli.doctor.models": "Models",
    "cli.doctor.ffmpeg": "ffmpeg",
    "cli.doctor.media": "Media probe",
    "cli.doctor.platform_ok": "  platform        ✓ {label}",
    "cli.doctor.runtime_ok": "  installed        ✓",
    "cli.doctor.runtime_no": "  installed        ✗",
    "cli.doctor.ffmpeg_path": "  path             {path}",
    "cli.doctor.model_ready": "  {key:11s} ✓ ready",
    "cli.doctor.model_missing": "  {key:11s} ✗ {count} file(s) missing",
    "cli.doctor.model_incomplete_short": "{count} file(s) missing ({size})",
    "cli.status_missing": "not installed",
    "cli.summary.range": "Range {start} – {end}   (source {duration})",
    "cli.summary.model": "Model {model}   {count} segment(s)   {elapsed}s for {audio}s   ({speed})",
    "cli.summary.model_noaudio": "Model {model}   {count} segment(s)   {elapsed}s",
    "cli.summary.dropped": "Dropped {count} suspected noise segment(s)",
    "cli.summary.note": "Note: {text}",
    "cli.saved": "Saved {path}",
    "cli.speed": "{speed}× realtime",
    "cli.dash": "—",
    "cli.status_title": "Ready",
    "cli.status_ready": "ready",
    "cli.status_installed": "installed",
    "cli.bad_format": "Unknown output format: {names}",
}

JA: dict[str, str] = {
    "app.title": "asr-mm · 動画区間の文字起こし {version}",
    "toolbar.open": "動画を開く…",
    "toolbar.model": "モデル",
    "toolbar.language": "言語",
    "drop.hint": "動画ファイルをここにドロップ\nまたはクリックして選択",
    "section.range": "時間範囲",
    "range.start": "開始",
    "range.end": "終了",
    "range.set_start": "開始 = 再生位置",
    "range.set_end": "終了 = 再生位置",
    "play": "▶ 再生",
    "section.options": "認識オプション",
    "opt.preroll": "先読み",
    "opt.preroll_suffix": " 秒",
    "opt.preroll_tip": "先頭で語が分断されないよう、少し前から読み取ります",
    "opt.drop_short": "ノイズと判断した区間を除去",
    "opt.drop_short_tip": "極端に短く文字が少ない結果（多くは環境音）を削除します",
    "opt.loudnorm": "先に音量を正規化",
    "opt.loudnorm_tip": "音量差が大きい場合にオンにします",
    "model.ready": "✓ {key} 準備完了 · {size}",
    "model.missing": "⚠ モデル未ダウンロード（{count} ファイル不足: {names}…）\nメニュー「ツール → 不足モデルをダウンロード」",
    "run": "文字起こし開始",
    "section.results": "認識結果",
    "table.col_start": "開始",
    "table.col_dur": "長さ",
    "table.col_text": "テキスト（ダブルクリックで編集）",
    "row.tip": "ダブルクリックで編集",
    "row.tip_suspect": "ノイズの誤認識の可能性があります（黄色）。編集または行の削除で対処できます",
    "action.copy": "全文コピー",
    "action.export": "エクスポート…",
    "action.export_clip": "区間を動画書き出し",
    "menu.file": "ファイル(&F)",
    "menu.tools": "ツール(&T)",
    "menu.help": "ヘルプ(&H)",
    "menu.open": "動画を開く…",
    "menu.quit": "終了",
    "menu.download_models": "不足モデルをダウンロード…",
    "menu.open_models": "モデルフォルダを開く",
    "menu.doctor": "動作確認",
    "menu.about": "バージョン情報",
    "status.ready": "準備完了。初回はモデルのダウンロードが必要です: asr-mm setup",
    "status.loaded": "{name} を読み込みました（長さ {duration}）",
    "status.start_set": "開始 = {tc}",
    "status.end_set": "終了 = {tc}",
    "status.position": "再生位置 {tc}",
    "status.running": "認識しています…",
    "status.extract": "音声を取り出し中…",
    "status.done": "完了: {count} 区間、音声 {audio} 秒に {elapsed} 秒（{speed}）",
    "status.done_note": "完了: {count} 区間、音声 {audio} 秒に {elapsed} 秒（{speed}）  |  {note}",
    "status.failed": "認識に失敗しました",
    "status.copied": "全文をクリップボードにコピーしました",
    "status.exported": "{path} に書き出しました",
    "status.exported_clip": "区間動画を {path} に書き出しました",
    "status.preview_failed": "この形式はシステムプレーヤーで再生できません（{error}）。文字起こしには影響しません。時刻欄で範囲を指定してください。",
    "dlg.cannot_open": "開けません",
    "dlg.model_missing": "モデル {key} のダウンロードが完了していません。\n先に「ツール → 不足モデルをダウンロード」を実行してください。",
    "dlg.export_failed": "エクスポートに失敗しました",
    "dlg.transcribe_failed": "認識に失敗しました",
    "dlg.about": (
        "<b>asr-mm {version}</b><br><br>"
        "動画の任意の時間区間を中国語テキストに変換します。<br>"        "すべてローカルで動作します。モデルは FunASR（MIT）。<br><br>"
        "<span style='color:#6b7280'>{hint}</span>"),
    "dlg.about_hint": "Ctrl+O で開く · 行をダブルクリックで編集 · 行をクリックで再生位置へジャンプ",
    "load.window": "動画を開いています",
    "load.title": "動画を読み込んでいます。しばらくお待ちください…",
    "load.cancel": "キャンセル",
    "load.probing": "{name} の情報を読み込んでいます…",
    "load.decoding": "{name} のプレビューをデコードしています…",
    "load.done": "完了",
    "load.cancelled": "{name} を開く操作はキャンセルされました",
    "load.failed": "{name} を開けませんでした",
    "models.title": "認識モデルのダウンロード",
    "models.intro": (
        "モデルは大きく（Nano 約 911 MB、Paraformer 約 228 MB）、初回のみダウンロードが"
        "必要で、その後はオフラインで動作します。\nダウンロードは中断でき、次回再開します。"),
    "models.state_ready": "準備完了",
    "models.state_missing": "未ダウンロード",
    "models.all": "すべてダウンロード",
    "models.only_nano": "Nano のみ",
    "models.only_fast": "Paraformer のみ",
    "models.close": "閉じる",
    "models.failed": "✗ {key} のダウンロードに失敗: {error}",
    "filedialog.video": "動画を選択",
    "filedialog.export": "エクスポート",
    "filedialog.clip": "区間動画を書き出す",
    "filter.video": "動画ファイル (*.mp4 *.mkv *.avi *.mov *.flv *.wmv *.m4v *.ts *.webm *.mpg *.mpeg *.rmvb *.3gp);;すべてのファイル (*.*)",
    "filter.text": "テキスト (*.txt);;字幕 (*.srt);;JSON (*.json)",
    "filter.mp4": "MP4 (*.mp4);;すべてのファイル (*.*)",
    "err.not_a_file": "ファイルが見つかりません: {path}",
    "err.is_dir": "動画ファイルを指定してください（ディレクトリは不可）: {path}",
    "err.no_audio": "このファイルには音声トラックがありません。",
    "err.unreadable": "メディア情報を読み取れません（ffmpeg が対応していない形式の可能性）:\n{tail}",
    "err.extract_failed": "音声の抽出に失敗しました:\n{tail}",
    "err.clip_failed": "区間動画の書き出しに失敗しました:\n{tail}",
    "err.no_ffmpeg": "利用できる ffmpeg がありません。同梱の ffmpeg/ffmpeg が欠けており、PATH にもありません。再インストールしてください。",
    "err.no_runtime": "認識ランタイムがインストールされていません（{platform}）。実行してください: asr-mm setup\n  配置先: {dir}",
    "err.missing_exe": "実行ファイルがありません: {path}",
    "err.model_incomplete": "モデル {key} が不完全です。不足: {names}\nasr-mm models download {key} を実行してください",
    "err.engine_start": "認識エンジンを起動できません: {path}",
    "err.engine_timeout": "認識がタイムアウトしました（2 時間超）。",
    "err.engine_returned": "認識エンジンが {code} を返しました:\n{tail}",
    "err.engine_empty": "認識結果が出力されませんでした。音声に音声がない、またはサンプリングレート・チャンネル数が想定外です。",
    "err.wav_missing": "音声ファイルが見つかりません: {path}",
    "err.range_short": "時間範囲が短すぎるか逆順です（{start} – {end}）。--start / --end を指定してください。",
    "err.range_past_end": "指定した範囲が動画の長さを超えています。動画の長さは {duration}、指定は {start} – {end} です。",
    "err.empty_range": "時間範囲が空です。",
    "err.bad_timecode": "時刻を解釈できません: {value}（00:03:20 / 200 / 3:20 の形式で指定してください）",
    "err.unknown_model": "不明なモデルです: {key}（利用可能: {list}）",
    "err.unsupported_platform": "未対応のプラットフォームです: {platform}。llama-funasr-* を {dir} に手動で配置できます",
    "err.no_language": "GUI 依存パッケージが未インストールです。実行してください: pip install PySide6",
    "err.bad_archive": "展開できないアーカイブ形式です: {name}",
    "err.zip_escape": "アーカイブに範囲外のパスが含まれています: {name}",
    "err.tar_link": "アーカイブにリンクが含まれているため拒否しました: {name}",
    "err.sha_mismatch": "検証に失敗しました {name}\n  期待値 sha256 {expected}\n  実際   {actual}",
    "err.runtime_incomplete": "展開後もランタイムが不足しています: {names}",
    "err.no_speech": "この範囲では音声を検出できませんでした（無音または環境音のみの可能性）。",
    "err.download_failed": "ダウンロードに失敗しました: {url}",
    "warn.noisy_segments": (
        "{count} 件の区間が非常に短く文字も少ないため、ノイズの誤認識の可能性があります"
        "（{preview}{more}）。--drop-short で除去できます。"),
    "model.nano": "Nano（高品質・推奨）",
    "model.paraformer": "Paraformer（高速）",
    "model.sensevoice": "SenseVoice（バランス）",
    "model.nano.note": "中国語の句読点と精度が最も高い。約 10× リアルタイム。",
    "model.paraformer.note": "約 27× リアルタイムで最小。句読点なし。CPU のみ。",
    "model.sensevoice.note": "CUDA/Vulkan アクセラレーション対応。短い区間では弱ります。",
    "runtime.windows_avx2": "Windows x64 (AVX2)",
    "runtime.windows": "Windows x64（汎用）",
    "runtime.macos": "macOS arm64",
    "runtime.linux": "Linux x64",
    "runtime.unknown": "未対応のプラットフォーム",
    "layout.models_staged": "{path}  (ASCII ステージング)",
    "layout.ffmpeg_path": "(PATH に ffmpeg なし)",
    "units.mb": " MB",
    "units.mb_short": "MB",
    "units.sec": " 秒",
    "cli.desc": "動画の任意の区間を中国語テキストに変換",
    "cli.epilog": """例:
  asr-mm setup                              初回: ランタイムとモデルの準備
  asr-mm transcribe v.mp4                   全体を文字起こし
  asr-mm transcribe v.mp4 -s 00:03:20 -e 00:05:10
  asr-mm transcribe v.mp4 -s 200 -e 310 --model paraformer --format srt
  asr-mm doctor v.mp4                      動作確認
""",
    "cli.transcribe.help": "動画の指定区間を文字起こし",
    "cli.video.help": "動画ファイルのパス",
    "cli.start.help": "開始時刻（例: 00:03:20 / 3:20 / 200）",
    "cli.end.help": "終了時刻",
    "cli.model.help": "認識モデル（既定: nano）",
    "cli.format.help": "出力形式（カンマ区切り）: txt,srt,json（既定 txt,srt）",
    "cli.outdir.help": "出力先（既定: <動画名>_transcript/）",
    "cli.name.help": "出力ファイル名の前半",
    "cli.stdout.help": "ファイルではなく標準出力へ書き出す",
    "cli.output_format.help": "--stdout と併用する形式",
    "cli.timestamps.help": "txt に時刻を含める",
    "cli.no_summary.help": "要約を表示しない",
    "cli.maxseg.help": "VAD 区間の上限（ミリ秒。既定 {default}）",
    "cli.preroll.help": "開始位置より何秒だけ前まで読み取るか（既定 0）",
    "cli.loudnorm.help": "認識前に音量を正規化する",
    "cli.drop_short.help": "ノイズの誤認識と思われる短い区間を除去",
    "cli.threads.help": "CPU スレッド数（既定: 自動）",
    "cli.keep_audio.help": "抽出した中間 wav を残す",
    "cli.lang.help": "UI 言語: zh / en / ja（既定: システムに合わせる）",
    "cli.models.help": "モデルの確認とダウンロード",
    "cli.setup.help": "ランタイムのインストールとモデルのダウンロード",
    "cli.doctor.help": "動作確認",
    "cli.models.title": "asr-mm {version} で利用できるモデル:\n",
    "cli.models.default": "既定のモデル: {key}",
    "cli.models.state_ready": "✓ ダウンロード済み",
    "cli.models.state_missing": "○ 未ダウンロード",
    "cli.models.ready": "モデル {key} は準備完了です。",
    "cli.models.downloading": "モデル {key} をダウンロード中 — {size}",
    "cli.models.done": "完了 -> {path}",
    "cli.setup.title": "asr-mm {version} の準備",
    "cli.setup.step_runtime": "[1/2] 認識ランタイム",
    "cli.setup.step_models": "[2/2] モデル",
    "cli.setup.runtime_ready": "  準備完了 -> {path}",
    "cli.setup.model_ready": "  {key:11s} 準備完了",
    "cli.setup.model_dl": "  {key:11s} ダウンロード中 ({size})",
    "cli.setup.finished": "\n準備が完了しました。`asr-mm doctor` で確認、または `asr-mm transcribe 動画.mp4` を実行してください。",
    "cli.doctor.title": "asr-mm {version} 動作確認\n",
    "cli.doctor.env": "環境",
    "cli.doctor.runtime": "ランタイム",
    "cli.doctor.models": "モデル",
    "cli.doctor.ffmpeg": "ffmpeg",
    "cli.doctor.media": "メディア情報",
    "cli.doctor.platform_ok": "  プラットフォーム   ✓ {label}",
    "cli.doctor.runtime_ok": "  インストール済み   ✓",
    "cli.doctor.runtime_no": "  インストール済み   ✗",
    "cli.doctor.ffmpeg_path": "  パス              {path}",
    "cli.doctor.model_ready": "  {key:11s} ✓ 準備完了",
    "cli.doctor.model_missing": "  {key:11s} ✗ {count} ファイル不足",
    "cli.doctor.model_incomplete_short": "{count} ファイル不足 ({size})",
    "cli.status_missing": "未インストール",
    "cli.summary.range": "範囲  {start} – {end}   (元動画 {duration})",
    "cli.summary.model": "モデル {model}   {count} 区間   音声 {audio} 秒に {elapsed} 秒   ({speed})",
    "cli.summary.model_noaudio": "モデル {model}   {count} 区間   {elapsed} 秒",
    "cli.summary.dropped": "ノイズと判断した {count} 区間を除去しました",
    "cli.summary.note": "注意: {text}",
    "cli.saved": "{path} に保存しました",
    "cli.speed": "実時間 {speed} 倍",
    "cli.dash": "—",
    "cli.status_title": "準備完了",
    "cli.status_ready": "準備完了",
    "cli.status_installed": "インストール済み",
    "cli.bad_format": "不明な出力形式です: {names}",
}

CATALOGS: dict[str, dict[str, str]] = {"zh": ZH, "en": EN, "ja": JA}

# Network-settings vocabulary lives in its own module to keep this file
# navigable; merge it in before anything can look a key up.
from . import net_i18n as _net_i18n  # noqa: E402

for _code, _net in (("zh", _net_i18n.ZH), ("en", _net_i18n.EN),
                    ("ja", _net_i18n.JA)):
    CATALOGS[_code].update(_net)
del _code, _net

_ALIASES: dict[str, str] = {}
for _code, (_native, _english, _aliases) in CATALOG_META.items():
    _ALIASES[_code] = _code
    for _a in _aliases:
        _ALIASES[_a] = _code

_current: str = DEFAULT_LANG
_warned_missing: set[tuple[str, str]] = set()


def available_languages() -> list[tuple[str, str]]:
    """``[(code, native_name), ...]`` in menu order."""
    return [(code, CATALOG_META[code][0]) for code in CATALOG_META]


def resolve(code: str | None) -> str | None:
    """Map a locale string onto one of our language codes.

    Tolerates what the OS actually hands us: ``ja_JP.UTF-8``,
    ``zh-Hans-CN``, ``English``.
    """
    if not code:
        return None
    raw = str(code).strip()
    if not raw:
        return None
    candidates = [raw, raw.split(".")[0], raw.split("@")[0]]
    normalised = []
    for cand in candidates:
        low = cand.strip().lower()
        if not low:
            continue
        normalised.append(low)
        normalised.append(low.replace("-", "_"))
        normalised.append(low.replace("-", ""))
        normalised.append(low.replace("_", ""))
    for cand in normalised:
        hit = _ALIASES.get(cand)
        if hit:
            return hit
    return None


def detect_system_language() -> str:
    """Best guess at the user's language, defaulting to Simplified Chinese.

    ``LC_ALL``/``LANG`` win when set, because an explicit environment variable
    is a deliberate override and is what CI and Linux/macOS shells provide.
    Otherwise fall back to the OS UI language, which is the only signal Windows
    exposes.
    """
    import platform

    for var in ("LC_ALL", "LC_MESSAGES", "LANGUAGE", "LANG"):
        got = resolve(os.environ.get(var))
        if got:
            return got

    if platform.system() == "Windows":
        try:
            import ctypes
            lang = ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0xFFFF
            got = resolve({0x0804: "zh-cn", 0x0404: "zh-tw", 0x0409: "en-us",
                           0x0411: "ja-jp"}.get(lang, ""))
            if got:
                return got
        except Exception:
            pass
    elif platform.system() == "Darwin":
        try:
            import subprocess
            out = subprocess.run(
                ["defaults", "read", "-g", "AppleLocale"],
                capture_output=True, text=True, timeout=5).stdout.strip()
            got = resolve(out)
            if got:
                return got
        except Exception:
            pass
    return DEFAULT_LANG


def set_language(code: str | None) -> str:
    """Set the active language. Unknown or missing values fall back to default."""
    global _current
    _warned_missing.clear()
    resolved = resolve(code) or (detect_system_language() if code is None
                                 else DEFAULT_LANG)
    _current = resolved
    return _current


def get_language() -> str:
    return _current


def t(key: str, /, **kwargs) -> str:
    """Look up ``key`` in the active catalog.

    ``key`` is positional-only on purpose: many templates take a ``{key}``
    placeholder, and a normal parameter would collide with ``t("x", key=...)``.

    Falls back to Simplified Chinese and then to the key itself, so a missing
    translation degrades to readable text instead of crashing.
    """
    text = CATALOGS.get(_current, {}).get(key)
    if text is None:
        text = ZH.get(key)
        if text is None:
            if (_current, key) not in _warned_missing:
                _warned_missing.add((_current, key))
            return key
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            return text
    return text


def missing_keys(code: str) -> list[str]:
    """Keys present in the default catalog but absent from ``code``."""
    return sorted(set(ZH) - set(CATALOGS.get(code, {})))


def display_width(text: str) -> int:
    """Terminal cell count — CJK and full-width forms occupy two columns."""
    import unicodedata
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1
               for c in text)


def pad(text: str, width: int, align: str = "left") -> str:
    """Pad to ``width`` display columns rather than ``len()`` characters."""
    fill = max(0, width - display_width(text))
    if align == "right":
        return " " * fill + text
    return text + " " * fill
