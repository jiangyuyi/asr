"""Orchestration: video + time range -> transcript.

Pipeline:

    validate range -> ffmpeg extract (16 kHz mono) -> llama.cpp ASR
                   -> rebase timestamps to the source video -> flag low-quality cues
"""
from __future__ import annotations

import re
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import catalog, engine, media
from .srt import Cue, format_ts

# CJK and ASCII punctuation. Written with explicit escapes: embedding curly
# quotes in a raw double-quoted string silently terminates it, which turns the
# pattern into an implicit concatenation of several literals.
_PUNCT = re.compile(
    r"[\s"
    "，。、！？；："
    "“”‘’"
    "（）《》…—～"
    r",.!?;:\"'()\[\]-]"
)

# A cue this short with this little text is the shape ASR hallucination takes on
# room noise. We flag rather than delete — only the caller decides to drop.
SUSPICIOUS_MAX_SECONDS = 0.8
SUSPICIOUS_MAX_CHARS = 2


def visible_chars(text: str) -> int:
    return len(_PUNCT.sub("", text))


def parse_timecode(value: str | float | int | None) -> float | None:
    """Accept ``HH:MM:SS(.mmm)``, ``MM:SS``, bare seconds, or a number."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return max(0.0, float(value))
    s = str(value).strip()
    if not s:
        return None
    if re.fullmatch(r"\d+(\.\d+)?", s):
        return max(0.0, float(s))
    m = re.fullmatch(r"(?:(\d+):)?(\d{1,2}):(\d{1,2}(?:\.\d+)?)", s)
    if not m:
        raise ValueError(f"无法解析时间码: {value!r}（用 00:03:20 / 200 / 3:20 这样的格式）")
    h = int(m.group(1) or 0)
    return h * 3600 + int(m.group(2)) * 60 + float(m.group(3))


@dataclass
class Segment:
    start: float
    end: float
    text: str
    suspicious: bool = False

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["start_tc"] = format_ts(self.start, comma=False)
        d["end_tc"] = format_ts(self.end, comma=False)
        d["duration"] = round(self.end - self.start, 3)
        return d


@dataclass
class Transcript:
    source: str
    source_duration: float
    range_start: float
    range_end: float
    applied_start: float
    applied_end: float
    model: str
    model_label: str
    segments: list[Segment] = field(default_factory=list)
    dropped: list[Segment] = field(default_factory=list)
    elapsed: float = 0.0
    audio_seconds: float = 0.0
    warning: str = ""
    info: dict = field(default_factory=dict)

    @property
    def text(self) -> str:
        return "".join(s.text for s in self.segments)

    @property
    def rtf(self) -> float:
        return self.elapsed / self.audio_seconds if self.audio_seconds else 0.0

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "source_duration": round(self.source_duration, 3),
            "range": {"start": self.range_start, "end": self.range_end,
                      "start_tc": format_ts(self.range_start, comma=False),
                      "end_tc": format_ts(self.range_end, comma=False)},
            "applied_range": {"start": round(self.applied_start, 3),
                              "end": round(self.applied_end, 3)},
            "model": self.model,
            "model_label": self.model_label,
            "elapsed_seconds": round(self.elapsed, 2),
            "audio_seconds": round(self.audio_seconds, 2),
            "rtf": round(self.rtf, 4),
            "text": self.text,
            "segments": [s.to_dict() for s in self.segments],
            "dropped_segments": [s.to_dict() for s in self.dropped],
            "warning": self.warning,
            "info": self.info,
        }


def _flag(cue: Cue, offset: float) -> Segment:
    start, end = round(cue.start + offset, 3), round(cue.end + offset, 3)
    return Segment(start, end, cue.text,
                   suspicious=(cue.duration <= SUSPICIOUS_MAX_SECONDS
                               and visible_chars(cue.text) <= SUSPICIOUS_MAX_CHARS))


def transcribe(source: str | Path, *, start: str | float | None = None,
               end: str | float | None = None, model: str = catalog.DEFAULT_MODEL,
               vad_maxseg_ms: int = engine.DEFAULT_MAXSEG_MS,
               threads: int | None = None, preroll: float = 0.0,
               loudnorm: bool = False, drop_short: bool = False,
               keep_audio: bool = False, workdir: str | Path | None = None) -> Transcript:
    """Transcribe ``source`` between ``start`` and ``end``.

    ``preroll`` seconds are added before ``start`` so a word split by the cut is
    still captured; VAD then reports the true speech onset, so timestamps stay
    accurate.
    """
    info = media.probe(source)
    duration = info.duration

    req_start = parse_timecode(start) if start is not None else 0.0
    req_end = parse_timecode(end) if end is not None else duration
    raw_start, raw_end = req_start, req_end
    req_start = max(0.0, min(req_start, duration))
    req_end = max(req_start, min(req_end, duration))
    if req_end - req_start < 0.05:
        from .srt import format_ts
        if raw_start >= duration or raw_end >= duration:
            raise ValueError(
                f"指定的时间区间超出了视频时长。视频总长 "
                f"{format_ts(duration, comma=False)}，你给的是 "
                f"{format_ts(raw_start, comma=False)} – {format_ts(raw_end, comma=False)}。")
        raise ValueError(
            f"时间区间过短或顺序颠倒（{format_ts(req_start, comma=False)} – "
            f"{format_ts(req_end, comma=False)}）。请用 --start / --end 指定。")

    applied_start = max(0.0, req_start - max(0.0, preroll))
    applied_end = req_end

    spec = catalog.resolve_model(model)
    tmp_ctx = None
    if workdir:
        tmpdir = Path(workdir)
        tmpdir.mkdir(parents=True, exist_ok=True)
    else:
        tmp_ctx = tempfile.TemporaryDirectory(prefix="asr-mm-")
        tmpdir = Path(tmp_ctx.name)
    try:
        wav = media.extract_audio(info.path, tmpdir / "segment.wav",
                                  applied_start, applied_end, loudnorm=loudnorm)
        audio_seconds = applied_end - applied_start
        res = engine.transcribe_wav(
            wav, spec.key, vad_maxseg_ms=vad_maxseg_ms, threads=threads,
            audio_seconds=audio_seconds)
        if keep_audio:
            import shutil
            shutil.copy2(wav, str(Path(info.path).with_suffix("")) + f".{applied_start:.0f}s.wav")
    finally:
        if tmp_ctx is not None:
            tmp_ctx.cleanup()

    segments = [_flag(c, applied_start) for c in res.cues]
    kept = [s for s in segments if not (drop_short and s.suspicious)]
    dropped = [s for s in segments if s not in kept]

    warnings = [res.warning] if res.warning else []
    flagged = [s for s in kept if s.suspicious]
    if flagged and not drop_short:
        preview = "、".join(f"{format_ts(s.start, comma=False)} “{s.text}”"
                            for s in flagged[:3])
        warnings.append(
            f"{len(flagged)} 个片段很短且字数极少，可能是噪音误识别（{preview}"
            f"{' 等' if len(flagged) > 3 else ''}）。可用 --drop-short 过滤。")

    return Transcript(
        source=str(info.path), source_duration=duration,
        range_start=req_start, range_end=req_end,
        applied_start=applied_start, applied_end=applied_end,
        model=spec.key, model_label=spec.label, segments=kept, dropped=dropped,
        elapsed=res.seconds, audio_seconds=audio_seconds,
        warning=" ".join(w for w in warnings if w),
        info={"size_mb": round(info.size_mb, 2), "audio_codec": info.audio_codec,
              "sample_rate": info.sample_rate, "channels": info.channels,
              "has_video": info.has_video,
              "vad_maxseg_ms": vad_maxseg_ms},
    )
