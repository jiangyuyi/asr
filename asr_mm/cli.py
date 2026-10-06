"""Command line interface."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__, catalog, downloader, engine, media, paths, transcribe
from .i18n import available_languages, display_width, get_language, pad, set_language, t
from .srt import format_ts, render_srt, render_txt

RUNTIME_KEYS = {
    "windows-x64-avx2": "runtime.windows_avx2",
    "windows-x64": "runtime.windows",
    "macos-arm64": "runtime.macos",
    "linux-x64": "runtime.linux",
}


def _fix_console() -> None:
    """The ASR binaries always emit UTF-8; make the terminal agree.

    Without this, Windows consoles using CP936/CP932 render every Chinese
    character as mojibake even though the underlying data is correct.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # py3.7+
        except Exception:
            pass


def _progress(label: str):
    return downloader.progress_printer(f"  {label}")


def _runtime_label(key: str | None) -> str:
    if not key:
        return t("runtime.unknown")
    return t(RUNTIME_KEYS.get(key, "runtime.unknown"))


def _model_label(spec: catalog.ModelSpec) -> str:
    key = {"nano": "model.nano", "paraformer": "model.paraformer",
           "sensevoice": "model.sensevoice"}.get(spec.key)
    return t(key) if key else spec.label


# --------------------------------------------------------------------- models

def cmd_models(args: argparse.Namespace) -> int:
    if args.action == "list":
        print(t("cli.models.title", version=__version__))
        rows = [(_model_label(s), s, downloader.is_model_ready(s.key),
                 downloader.human(sum(f.size for f in s.files)))
                for s in catalog.MODELS.values()]
        width = max((display_width(r[0]) for r in rows), default=10) + 2
        for label, spec, ready, size in rows:
            mark = (t("cli.models.state_ready") if ready
                    else t("cli.models.state_missing"))
            print(f"  {spec.key:11s} {pad(label, width)}"
                  f"{size:>9s}  {mark}")
            print(f"  {'':11s} {t('model.' + spec.key + '.note')}")
        print(f"\n{t('cli.models.default', key=catalog.DEFAULT_MODEL)}")
        return 0

    if args.action == "status":
        for line in downloader.status_table():
            print(line)
        return 0

    key = args.model or catalog.DEFAULT_MODEL
    try:
        spec = catalog.resolve_model(key)
    except KeyError:
        print(t("err.unknown_model", key=key, list=", ".join(catalog.MODELS)),
              file=sys.stderr)
        return 2
    missing = downloader.missing_files(spec)
    if not missing:
        print(t("cli.models.ready", key=spec.key))
        return 0
    total = sum(f.size for f in missing)
    print(t("cli.models.downloading", key=spec.key, size=downloader.human(total)))
    downloader.ensure_model(spec.key, progress=_progress(t("cli.models.default", key=spec.key)[:12]))
    downloader.clear_progress_line()
    print(t("cli.models.done", path=paths.models_dir()))
    return 0


def cmd_net(args: argparse.Namespace) -> int:
    """Test the download sources and report who issues their certificates."""
    from . import net
    cfg = downloader.net_config({
        "mirror": args.mirror,
        "ca_bundle": args.ca_bundle,
        "insecure": args.insecure,
    })
    if cfg.ca_error:
        print(cfg.ca_error, file=sys.stderr)
        return 1
    if cfg.insecure and not args.yes_insecure:
        print(t("net.insecure_warn"), file=sys.stderr)
        return 2

    print(t("cli.net.title", version=__version__))
    print(f"  {t('net.trust', source=net.inject_os_trust())}")
    if cfg.ca_bundle:
        print(f"  {t('net.ca_ok', path=cfg.ca_bundle)}")
    print()

    results = net.diagnose(cfg)
    if not results:
        print(t("net.diag_empty"))
        return 1
    failed = 0
    for r in results:
        mark = "OK  " if r.ok else "FAIL"
        print(f"[{mark}] {r.label}  ({r.host})")
        if not r.ok:
            failed += 1
            print(f"       {r.reason}")
        if r.issuer:
            print(f"       {t('net.issuer')}: {r.issuer}")
        if r.verdict:
            print(f"       {t('net.verdict')}: {r.verdict}")
        print()
    if failed:
        print(t("cli.net.some_fail", count=failed))
    else:
        print(t("cli.net.all_ok"))
    return 1 if failed else 0


def cmd_setup(args: argparse.Namespace) -> int:
    print(t("cli.setup.title", version=__version__))
    for k, v in paths.describe_layout().items():
        print(f"  {k:14s} {v}")
    print(f"\n{t('cli.setup.step_runtime')}")
    try:
        dest = downloader.ensure_runtime(progress=_progress("runtime"))
        print(t("cli.setup.runtime_ready", path=dest))
    except Exception as exc:
        print(f"  ✗ {exc}", file=sys.stderr)
        return 1
    print(f"\n{t('cli.setup.step_models')}")
    keys = [args.model] if args.model else list(catalog.MODELS)
    for k in keys:
        spec = catalog.resolve_model(k)
        missing = downloader.missing_files(spec)
        if not missing:
            print(t("cli.setup.model_ready", key=pad(spec.key, 11)))
            continue
        size = downloader.human(sum(f.size for f in missing))
        print(t("cli.setup.model_dl", key=pad(spec.key, 11), size=size))
        downloader.ensure_model(k, progress=_progress(f"  {k:11s}"))
        downloader.clear_progress_line()
    print(t("cli.setup.finished"))
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    print(t("cli.doctor.title", version=__version__))
    print(t("cli.doctor.env"))
    for k, v in paths.describe_layout().items():
        print(f"  {k:14s} {v}")
    print(f"\n{t('cli.doctor.runtime')}")
    rt = downloader.runtime_status()
    if rt["key"]:
        print(t("cli.doctor.platform_ok", label=_runtime_label(rt["key"])))
    else:
        print(f"  ✗ {t('runtime.unknown')}")
    print(t("cli.doctor.runtime_ok") if rt["ready"]
          else t("cli.doctor.runtime_no"))
    print(f"\n{t('cli.doctor.models')}")
    for spec in catalog.MODELS.values():
        missing = downloader.missing_files(spec)
        key = pad(spec.key, 11)
        if not missing:
            print(t("cli.doctor.model_ready", key=key))
        else:
            print(t("cli.doctor.model_missing", key=key, count=len(missing)))
    print(f"\n{t('cli.doctor.ffmpeg')}")
    try:
        path = media.ffmpeg_path()
        print(t("cli.doctor.ffmpeg_path", path=path))
    except media.MediaError as exc:
        print(f"  ✗ {exc}", file=sys.stderr)
        return 1
    if args.video:
        print(f"\n{t('cli.doctor.media')}")
        try:
            print("  " + json.dumps(media.probe_json(args.video), ensure_ascii=False))
        except media.MediaError as exc:
            print(f"  ✗ {exc}", file=sys.stderr)
            return 1
    return 0


# ----------------------------------------------------------------- transcribe

def _write_outputs(tr: transcribe.Transcript, out_dir: Path, stem: str,
                   formats: list[str], timestamps: bool,
                   translations: dict | None = None) -> list[Path]:
    from . import export
    return export.write_all(out_dir, stem, tr.segments, formats,
                            timestamps=timestamps, lang=get_language(),
                            json_payload=tr.to_dict(),
                            translations=translations)


def _model_lang_warning(model: str, content_lang: str) -> str:
    from . import catalog
    try:
        spec = catalog.resolve_model(model)
    except KeyError:
        return ""
    return spec.warning_for(content_lang)


def cmd_transcribe(args: argparse.Namespace) -> int:
    warning = _model_lang_warning(args.model, args.content_lang)
    try:
        tr = transcribe.transcribe(
            args.video, start=args.start, end=args.end, model=args.model,
            vad_maxseg_ms=args.maxseg, threads=args.threads,
            preroll=args.preroll, loudnorm=args.loudnorm,
            drop_short=args.drop_short, keep_audio=args.keep_audio)
    except (media.MediaError, engine.EngineError, ValueError, KeyError) as exc:
        print(exc, file=sys.stderr)
        return 1
    if warning:
        print(f"⚠ {warning}", file=sys.stderr)

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

    translations = _maybe_translate(args, tr)
    src = Path(tr.source)
    stem = args.name or f"{src.stem}_{_range_tag(tr)}"
    out_dir = Path(args.out_dir) if args.out_dir else src.parent / f"{src.stem}_transcript"
    for p in _write_outputs(tr, out_dir, stem, args.format, args.timestamps,
                            translations):
        print(t("cli.saved", path=p))
    _summary(tr)
    return 0


def _maybe_translate(args, tr: transcribe.Transcript) -> dict | None:
    """Translate the transcript in place. Returns {target: [per row]}."""
    from . import translate as mt
    targets = mt.normalize_targets(getattr(args, "translate", "") or "")
    if not targets:
        return None
    missing = [c for c in targets if not catalog.mt_model_ready(c)]
    if missing:
        print(t("err.mt_model_missing", target="、".join(
            catalog.MT_MODELS[c].target for c in missing)), file=sys.stderr)
        return None
    with mt.Translator(targets,
                       progress=_progress(t("cli.mt.progress"))) as tr_engine:
        result = tr_engine.translate([s.text for s in tr.segments])
    downloader.clear_progress_line()
    print(t("cli.translated",
            langs="、".join(t("mt." + c) for c in targets),
            count=result.total, elapsed=f"{result.elapsed:.1f}"),
          file=sys.stderr)
    return {c: v for c, v in result.texts.items()}


def cmd_mt(args: argparse.Namespace) -> int:
    """Inspect or download the translation models."""
    if args.action == "list" or args.action == "status":
        print(t("cli.mt.title", version=__version__))
        for spec in catalog.MT_MODELS.values():
            ready = catalog.mt_model_ready(spec.key)
            mark = (t("cli.models.state_ready") if ready
                    else t("cli.models.state_missing"))
            print(f"  {spec.key:4s} {pad(t('mt.' + spec.key), 18)}"
                  f"{downloader.human(spec.size()):>11s}  {mark}")
            print(f"       {t('mt.' + spec.key + '.note')}")
        return 0

    key = args.target or next(iter(catalog.MT_MODELS))
    try:
        spec = catalog.resolve_mt(key)
    except KeyError:
        print(t("err.unknown_model", key=key,
                list=", ".join(catalog.MT_MODELS)), file=sys.stderr)
        return 2
    if catalog.mt_model_ready(spec.key):
        print(t("cli.mt.ready", key=spec.key))
        return 0
    print(t("cli.mt.downloading", key=spec.key, size=downloader.human(spec.size())))
    downloader.ensure_mt_model(spec.key, progress=_progress(t("cli.mt.progress")))
    downloader.clear_progress_line()
    print(t("cli.mt.done", path=catalog.mt_model_dir(spec.key)))
    return 0


def _range_tag(tr: transcribe.Transcript) -> str:
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
    print("", file=out)
    print(t("cli.summary.range", start=format_ts(tr.range_start, comma=False),
            end=format_ts(tr.range_end, comma=False),
            duration=format_ts(tr.source_duration, comma=False)), file=out)
    if tr.audio_seconds:
        print(t("cli.summary.model", model=tr.model_label, count=len(tr.segments),
                elapsed=f"{tr.elapsed:.2f}", audio=f"{tr.audio_seconds:.1f}",
                speed=t("cli.speed", speed=f"{1 / tr.rtf:.0f}")), file=out)
    else:
        print(t("cli.summary.model_noaudio", model=tr.model_label,
                count=len(tr.segments), elapsed=f"{tr.elapsed:.2f}"), file=out)
    if tr.dropped:
        print(t("cli.summary.dropped", count=len(tr.dropped)), file=out)
    if tr.warning:
        print(t("cli.summary.note", text=tr.warning), file=out)
    print("", file=out)


# ---------------------------------------------------------------------- parse

def build_parser() -> argparse.ArgumentParser:
    # Language is already set by main() before we get here; the parser renders
    # its help text from the catalog, so resetting here would discard --lang.
    p = argparse.ArgumentParser(
        prog="asr-mm",
        description=t("cli.desc"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=t("cli.epilog"))
    p.add_argument("--version", action="version", version=f"asr-mm {__version__}")
    p.add_argument("--lang", choices=[c for c, _ in available_languages()],
                   metavar="{zh,en,ja}",
                   help=t("cli.lang.help"))
    sub = p.add_subparsers(dest="command", required=True)

    tsub = sub.add_parser("transcribe", help=t("cli.transcribe.help"))
    tsub.add_argument("video", help=t("cli.video.help"))
    tsub.add_argument("-s", "--start", help=t("cli.start.help"))
    tsub.add_argument("-e", "--end", help=t("cli.end.help"))
    tsub.add_argument("-m", "--model", default=catalog.DEFAULT_MODEL,
                      choices=list(catalog.MODELS), help=t("cli.model.help"))
    tsub.add_argument("-f", "--format", default="txt,srt", help=t("cli.format.help"))
    tsub.add_argument("--content-lang", default="auto",
                      choices=["auto", "zh", "en", "ja"],
                      help=t("cli.content_lang.help"))
    tsub.add_argument("-o", "--out-dir", help=t("cli.outdir.help"))
    tsub.add_argument("--name", help=t("cli.name.help"))
    tsub.add_argument("--stdout", action="store_true", help=t("cli.stdout.help"))
    tsub.add_argument("--output-format", default="txt",
                      choices=["txt", "srt", "json"], help=t("cli.output_format.help"))
    tsub.add_argument("--timestamps", action="store_true", help=t("cli.timestamps.help"))
    tsub.add_argument("--no-summary", action="store_true", help=t("cli.no_summary.help"))
    tsub.add_argument("--maxseg", type=int, default=engine.DEFAULT_MAXSEG_MS,
                      help=t("cli.maxseg.help", default=engine.DEFAULT_MAXSEG_MS))
    tsub.add_argument("--preroll", type=float, default=0.0, help=t("cli.preroll.help"))
    tsub.add_argument("--loudnorm", action="store_true", help=t("cli.loudnorm.help"))
    tsub.add_argument("--drop-short", action="store_true", help=t("cli.drop_short.help"))
    tsub.add_argument("--threads", type=int, help=t("cli.threads.help"))
    tsub.add_argument("--keep-audio", action="store_true", help=t("cli.keep_audio.help"))
    tsub.add_argument("--translate", default="", metavar="{en,ja}",
                      help=t("cli.translate.help"))
    tsub.set_defaults(func=cmd_transcribe)

    m = sub.add_parser("models", help=t("cli.models.help"))
    m.add_argument("action", nargs="?", default="list",
                   choices=["list", "status", "download"])
    m.add_argument("model", nargs="?", choices=list(catalog.MODELS))
    m.set_defaults(func=cmd_models)

    mt = sub.add_parser("mt", help=t("cli.mt.help"))
    mt.add_argument("action", nargs="?", default="list",
                    choices=["list", "status", "download"])
    mt.add_argument("target", nargs="?", choices=list(catalog.MT_MODELS))
    mt.set_defaults(func=cmd_mt)

    s = sub.add_parser("setup", help=t("cli.setup.help"))
    s.add_argument("-m", "--model", choices=list(catalog.MODELS),
                   help=t("cli.model.help"))
    s.set_defaults(func=cmd_setup)

    d = sub.add_parser("doctor", help=t("cli.doctor.help"))
    d.add_argument("video", nargs="?", help=t("cli.video.help"))
    d.set_defaults(func=cmd_doctor)

    n = sub.add_parser("net-check", help=t("cli.net.help"))
    n.add_argument("--mirror", choices=["auto", "huggingface", "modelscope", "hf-mirror"],
                   help=t("net.mirror"))
    n.add_argument("--ca-bundle", help=t("net.ca_bundle"))
    n.add_argument("--insecure", action="store_true", help=t("net.insecure"))
    n.add_argument("--yes-insecure", action="store_true",
                   help=argparse.SUPPRESS)
    n.set_defaults(func=cmd_net)
    return p


def main(argv: list[str] | None = None) -> int:
    _fix_console()
    argv = list(sys.argv[1:] if argv is None else argv)

    # --lang has to be honoured before the parser renders its help text, and
    # it may appear on either side of the subcommand.
    lang = None
    for i, a in enumerate(argv):
        if a == "--lang" and i + 1 < len(argv):
            lang = argv[i + 1]
            break
        if a.startswith("--lang="):
            lang = a.split("=", 1)[1]
            break
    set_language(lang)

    args = build_parser().parse_args(argv)
    if getattr(args, "format", None):
        from . import export
        args.format = [x.strip() for x in str(args.format).split(",") if x.strip()]
        bad = set(args.format) - set(export.FORMATS)
        if bad:
            print(t("cli.bad_format", names=", ".join(bad)), file=sys.stderr)
            return 2
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\n", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
