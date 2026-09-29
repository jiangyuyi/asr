"""Command line interface."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__, catalog, downloader, engine, media, paths, transcribe
from .srt import render_srt, render_txt


def _fix_console() -> None:
    """The ASR binaries always emit UTF-8; make the terminal agree.

    Without this, Windows consoles using CP936 render every Chinese character as
    mojibake even though the underlying data is correct.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # py3.7+
        except Exception:
            pass


def _progress(label: str):
    return downloader.progress_printer(f"  {label}")


# --------------------------------------------------------------------- models

def cmd_models(args: argparse.Namespace) -> int:
    if args.action == "list":
        print(f"asr-mm {__version__} 可用模型：\n")
        for spec in catalog.MODELS.values():
            ready = downloader.is_model_ready(spec.key)
            size = downloader.human(sum(f.size for f in spec.files))
            mark = "✓ 已下载" if ready else "○ 未下载"
            print(f"  {spec.key:11s} {spec.label:24s} {size:>9s}  {mark}")
            print(f"  {'':11s} {spec.note}")
        print(f"\n默认模型: {catalog.DEFAULT_MODEL}")
        return 0

    if args.action == "status":
        for line in downloader.status_table():
            print("  " + line)
        return 0

    key = args.model or catalog.DEFAULT_MODEL
    try:
        spec = catalog.resolve_model(key)
    except KeyError:
        print(f"未知模型: {key}（可用: {', '.join(catalog.MODELS)}）", file=sys.stderr)
        return 2
    missing = downloader.missing_files(spec)
    if not missing:
        print(f"模型 {spec.key} 已就绪。")
        return 0
    total = sum(f.size for f in missing)
    print(f"下载模型 {spec.key} — {downloader.human(total)}")
    cb = _progress("下载")
    downloader.ensure_model(spec.key, progress=cb)
    downloader.clear_progress_line()
    print(f"完成 -> {paths.models_dir()}")
    return 0


def cmd_setup(args: argparse.Namespace) -> int:
    print(f"asr-mm {__version__} 环境准备")
    for k, v in paths.describe_layout().items():
        print(f"  {k:14s} {v}")
    print("\n[1/2] 识别运行时")
    try:
        dest = downloader.ensure_runtime(progress=_progress("下载"))
        print(f"  已就绪 -> {dest}")
    except Exception as exc:
        print(f"  失败: {exc}", file=sys.stderr)
        return 1
    print("\n[2/2] 模型")
    keys = [args.model] if args.model else list(catalog.MODELS)
    for k in keys:
        spec = catalog.resolve_model(k)
        missing = downloader.missing_files(spec)
        if not missing:
            print(f"  {spec.key:11s} 已就绪")
            continue
        size = downloader.human(sum(f.size for f in missing))
        print(f"  {spec.key:11s} 下载中 ({size})")
        downloader.ensure_model(k, progress=_progress(f"  {k:11s}"))
        downloader.clear_progress_line()
    print("\n准备完成。运行 `asr-mm doctor` 自检，或 `asr-mm transcribe 视频.mp4` 开始。")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    print(f"asr-mm {__version__} 自检\n")
    print("环境")
    for k, v in paths.describe_layout().items():
        print(f"  {k:14s} {v}")
    print("\n运行时")
    rt = downloader.runtime_status()
    print(f"  平台匹配       {'✓ ' + rt['label'] if rt['key'] else '✗ 不支持'}")
    print(f"  已安装         {'✓' if rt['ready'] else '✗'}")
    print("\n模型")
    for spec in catalog.MODELS.values():
        missing = downloader.missing_files(spec)
        print(f"  {spec.key:11s} {'✓ 已就绪' if not missing else '✗ 缺 ' + str(len(missing)) + ' 个文件'}")
    print("\nffmpeg")
    try:
        path = media.ffmpeg_path()
        print(f"  路径           {path}")
    except media.MediaError as exc:
        print(f"  ✗ {exc}")
        return 1
    if args.video:
        print("\n媒体探测")
        try:
            print("  " + json.dumps(media.probe_json(args.video), ensure_ascii=False))
        except media.MediaError as exc:
            print(f"  ✗ {exc}", file=sys.stderr)
            return 1
    return 0


# ----------------------------------------------------------------- transcribe

def _write_outputs(tr: transcribe.Transcript, out_dir: Path, stem: str,
                   formats: list[str], timestamps: bool) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    if "txt" in formats:
        p = out_dir / f"{stem}.txt"
        p.write_text(render_txt(tr.segments, timestamps), encoding="utf-8")
        written.append(p)
    if "srt" in formats:
        p = out_dir / f"{stem}.srt"
        p.write_text(render_srt(tr.segments), encoding="utf-8")
        written.append(p)
    if "json" in formats:
        p = out_dir / f"{stem}.json"
        p.write_text(json.dumps(tr.to_dict(), ensure_ascii=False, indent=2),
                     encoding="utf-8")
        written.append(p)
    return written


def cmd_transcribe(args: argparse.Namespace) -> int:
    try:
        tr = transcribe.transcribe(
            args.video, start=args.start, end=args.end, model=args.model,
            vad_maxseg_ms=args.maxseg, threads=args.threads,
            preroll=args.preroll, loudnorm=args.loudnorm,
            drop_short=args.drop_short, keep_audio=args.keep_audio)
    except (media.MediaError, engine.EngineError, ValueError, KeyError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1

    if args.stdout:
        if args.output_format == "json":
            print(json.dumps(tr.to_dict(), ensure_ascii=False, indent=2))
        elif args.output_format == "srt":
            sys.stdout.write(render_srt(tr.segments))
        else:
            print(render_txt(tr.segments, args.timestamps))
        if not args.no_summary:
            _summary(tr, to_stderr=True)
        return 0

    src = Path(tr.source)
    stem = args.name or f"{src.stem}_{_range_tag(tr)}"
    out_dir = Path(args.out_dir) if args.out_dir else src.parent / f"{src.stem}_transcript"
    written = _write_outputs(tr, out_dir, stem, args.format, args.timestamps)

    for p in written:
        print(f"已保存 {p}")
    _summary(tr)
    return 0


def _range_tag(tr: transcribe.Transcript) -> str:
    from .srt import format_ts
    if tr.range_start == 0 and abs(tr.range_end - tr.source_duration) < 0.1:
        return "full"

    def compact(sec: float) -> str:
        sec = int(round(sec))
        h, rem = divmod(sec, 3600)
        m, s = divmod(rem, 60)
        if h:
            return f"{h}h{m:02d}m"
        if m:
            return f"{m}m{s:02d}s"
        return f"{s}s"

    return f"{compact(tr.range_start)}-{compact(tr.range_end)}"


def _summary(tr: transcribe.Transcript, to_stderr: bool = False) -> None:
    out = sys.stderr if to_stderr else sys.stdout
    from .srt import format_ts
    lines = [
        "",
        f"区间  {format_ts(tr.range_start, comma=False)} – {format_ts(tr.range_end, comma=False)}"
        f"   (源时长 {format_ts(tr.source_duration, comma=False)})",
        f"模型  {tr.model_label}   片段 {len(tr.segments)} 条"
        f"   耗时 {tr.elapsed:.2f}s / 音频 {tr.audio_seconds:.1f}s"
        f"   ({1 / tr.rtf:.0f}× 实时)" if tr.audio_seconds else "",
    ]
    for ln in lines:
        if ln:
            print(ln, file=out)
    if tr.dropped:
        print(f"已过滤 {len(tr.dropped)} 个疑似噪音片段", file=out)
    if tr.warning:
        print(f"提示: {tr.warning}", file=out)
    print("", file=out)


# ---------------------------------------------------------------------- parse

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="asr-mm",
        description="视频指定时间段 → 中文语音转写",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例:
  asr-mm setup                              首次使用：装运行时 + 下载模型
  asr-mm transcribe v.mp4                   转写整段
  asr-mm transcribe v.mp4 -s 00:03:20 -e 00:05:10
  asr-mm transcribe v.mp4 -s 200 -e 310 --model paraformer --format srt
  asr-mm doctor v.mp4                      环境自检
""")
    p.add_argument("--version", action="version", version=f"asr-mm {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    t = sub.add_parser("transcribe", help="转写视频指定时间段")
    t.add_argument("video", help="视频文件路径")
    t.add_argument("-s", "--start", help="起始时间，如 00:03:20 / 3:20 / 200")
    t.add_argument("-e", "--end", help="结束时间")
    t.add_argument("-m", "--model", default=catalog.DEFAULT_MODEL,
                   choices=list(catalog.MODELS), help=f"默认 {catalog.DEFAULT_MODEL}")
    t.add_argument("-f", "--format", default="txt,srt",
                   help="导出格式，逗号分隔: txt,srt,json（默认 txt,srt）")
    t.add_argument("-o", "--out-dir", help="输出目录（默认 视频名_transcript/）")
    t.add_argument("--name", help="输出文件名主干")
    t.add_argument("--stdout", action="store_true", help="结果打到标准输出，不写文件")
    t.add_argument("--output-format", default="txt", choices=["txt", "srt", "json"],
                   help="配合 --stdout 使用的格式")
    t.add_argument("--timestamps", action="store_true", help="txt 中带时间戳")
    t.add_argument("--no-summary", action="store_true", help="不打印统计摘要")
    t.add_argument("--maxseg", type=int, default=engine.DEFAULT_MAXSEG_MS,
                   help=f"VAD 分段上限毫秒（默认 {engine.DEFAULT_MAXSEG_MS}）")
    t.add_argument("--preroll", type=float, default=0.0,
                   help="起点前多取几秒，避免切到半个字（默认 0）")
    t.add_argument("--loudnorm", action="store_true", help="先做响度归一化")
    t.add_argument("--drop-short", action="store_true",
                   help="丢弃极短且字数极少的疑似噪音片段")
    t.add_argument("--threads", type=int, help="CPU 线程数（默认自动）")
    t.add_argument("--keep-audio", action="store_true", help="保留抽取的中间 wav")
    t.set_defaults(func=cmd_transcribe)

    m = sub.add_parser("models", help="查看/下载模型")
    m.add_argument("action", nargs="?", default="list",
                   choices=["list", "status", "download"])
    m.add_argument("model", nargs="?", choices=list(catalog.MODELS))
    m.set_defaults(func=cmd_models)

    s = sub.add_parser("setup", help="安装运行时并下载模型")
    s.add_argument("-m", "--model", choices=list(catalog.MODELS),
                   help="只装指定模型（默认全部）")
    s.set_defaults(func=cmd_setup)

    d = sub.add_parser("doctor", help="环境自检")
    d.add_argument("video", nargs="?", help="顺便探测这个视频")
    d.set_defaults(func=cmd_doctor)
    return p


def main(argv: list[str] | None = None) -> int:
    _fix_console()
    args = build_parser().parse_args(argv)
    if getattr(args, "format", None):
        args.format = [x.strip() for x in str(args.format).split(",") if x.strip()]
        bad = set(args.format) - {"txt", "srt", "json"}
        if bad:
            print(f"未知输出格式: {', '.join(bad)}", file=sys.stderr)
            return 2
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\n已取消", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
