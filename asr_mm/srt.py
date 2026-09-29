"""SRT parsing and rendering.

The llama-funasr binaries write SRT to stdout (diagnostics go to stderr), so
this is the primary structured output channel. Text can be multi-line, so the
parser keys on the numeric index line rather than on blank-line splitting.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_TS = re.compile(
    r"(\d{2,}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*(\d{2,}):(\d{2}):(\d{2})[,.](\d{1,3})"
)


def _ms_to_s(h: str, m: str, s: str, ms: str) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000.0


def format_ts(seconds: float, comma: bool = True) -> str:
    if seconds < 0:
        seconds = 0.0
    total_ms = int(round(seconds * 1000))
    h, rem = divmod(total_ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    sep = "," if comma else "."
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def parse_ts(text: str) -> float:
    m = re.fullmatch(r"(?:(\d{2,}):)?(\d{1,2}):(\d{2})[,.](\d{1,3})", text.strip())
    if not m:
        raise ValueError(f"bad timecode: {text!r}")
    h = m.group(1) or "0"
    return _ms_to_s(h, m.group(2), m.group(3), m.group(4))


@dataclass
class Cue:
    start: float
    end: float
    text: str

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    def shifted(self, offset: float) -> "Cue":
        return Cue(self.start + offset, self.end + offset, self.text)


def parse_srt(text: str) -> list[Cue]:
    """Parse SRT into cues. Unparseable noise is skipped, not fatal."""
    cues: list[Cue] = []
    for block in re.split(r"\r?\n\s*\r?\n", text.replace("﻿", "").strip()):
        lines = [ln for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue
        idx = 0
        if lines[0].strip().isdigit():
            idx = 1
        if idx >= len(lines):
            continue
        ts = _TS.search(lines[idx])
        if not ts:
            continue
        start = _ms_to_s(ts.group(1), ts.group(2), ts.group(3), ts.group(4))
        end = _ms_to_s(ts.group(5), ts.group(6), ts.group(7), ts.group(8))
        body = " ".join(ln.strip() for ln in lines[idx + 1:]).strip()
        if body:
            cues.append(Cue(start, end, body))
    return cues


def render_srt(cues: list[Cue]) -> str:
    out: list[str] = []
    for i, c in enumerate(cues, 1):
        out.append(f"{i}")
        out.append(f"{format_ts(c.start)} --> {format_ts(c.end)}")
        out.append(c.text)
        out.append("")
    return "\n".join(out)


def render_txt(cues: list[Cue], with_timestamps: bool = False) -> str:
    if not with_timestamps:
        return "".join(c.text if c.text.endswith(("。", "！", "？", "，", "、", "…"))
                       else c.text + "。" for c in cues)
    lines = []
    for c in cues:
        lines.append(f"[{format_ts(c.start, comma=False)}] {c.text}")
    return "\n".join(lines)
