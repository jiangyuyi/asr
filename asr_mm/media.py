"""Media probing and audio extraction via a bundled static ffmpeg.

ffmpeg ships inside the wheel via ``imageio-ffmpeg`` during development and is
copied into the bundle at build time, so end users never install it.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import paths

_DUR = re.compile(r"Duration:\s*(\d+):(\d{2}):(\d{2}(?:\.\d+)?)")
_STREAM = re.compile(r"^\s*Stream #\d+:\d+.*?:\s*(Audio|Video):\s*([A-Za-z0-9_]+)(.*)$")
_HZ = re.compile(r"(\d+)\s*Hz")
_CH = re.compile(r"\b(mono|stereo|\d+ channels?)\b", re.IGNORECASE)


class MediaError(RuntimeError):
    pass


@dataclass
class MediaInfo:
    path: Path
    duration: float
    has_audio: bool
    has_video: bool
    audio_codec: str = ""
    sample_rate: int = 0
    channels: int = 0

    @property
    def size_mb(self) -> float:
        return self.path.stat().st_size / 1_048_576


def ffmpeg_path() -> str:
    """Bundled ffmpeg if present, else whatever is on PATH."""
    bundled = paths.ffmpeg_exe()
    if bundled:
        return str(bundled)
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:  # dev fallback: the imageio-ffmpeg wheel ships a static build
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:  # pragma: no cover
        # imageio_ffmpeg is excluded from the frozen build on purpose (it would
        # duplicate the staged ffmpeg.exe), so reaching here means a broken
        # install rather than a missing dependency.
        raise MediaError(
            "找不到可用的 ffmpeg：程序内置的 ffmpeg/ffmpeg 缺失，PATH 中也没有。"
            "请重新安装本程序。") from exc


def _run(args: list[str], timeout: int = 3600) -> subprocess.CompletedProcess:
    cmd = [ffmpeg_path(), "-hide_banner", "-nostdin", *args]
    # Binary-safe: the child always writes UTF-8 regardless of the host locale.
    return subprocess.run(cmd, capture_output=True, timeout=timeout)


def probe(path: str | os.PathLike) -> MediaInfo:
    p = Path(path)
    if not p.exists():
        raise MediaError(f"文件不存在: {p}")
    if p.is_dir():
        raise MediaError(f"需要一个视频文件，不接受目录: {p}")
    r = _run(["-i", str(p)])
    err = r.stderr.decode("utf-8", "replace")
    m = _DUR.search(err)
    if not m:
        tail = "\n".join(err.strip().splitlines()[-6:])
        raise MediaError(f"无法解析媒体信息（可能不是 ffmpeg 支持的格式）:\n{tail}")
    duration = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    info = MediaInfo(path=p, duration=duration, has_audio=False, has_video=False)
    for line in err.splitlines():
        sm = _STREAM.match(line)
        if not sm:
            continue
        kind, codec, rest = sm.group(1), sm.group(2), sm.group(3)
        if kind == "Video":
            info.has_video = True
            continue
        if info.has_audio:
            continue
        info.has_audio = True
        info.audio_codec = codec
        hz = _HZ.search(rest)
        if hz:
            info.sample_rate = int(hz.group(1))
        ch = _CH.search(rest)
        if ch:
            token = ch.group(1).lower()
            info.channels = 1 if token == "mono" else 2 if token == "stereo" else int(token.split()[0])
    if not info.has_audio:
        raise MediaError("该文件没有音频轨道，无法转写。")
    return info


def extract_audio(src: str | os.PathLike, dst: str | os.PathLike,
                   start: float = 0.0, end: float | None = None,
                   loudnorm: bool = False) -> Path:
    """Decode ``[start, end)`` of ``src`` to 16 kHz mono PCM WAV.

    Uses input seeking plus ``-t`` (duration) rather than ``-to`` (absolute
    timestamp) because the two interact ambiguously once the input is seeked.
    """
    src, dst = Path(src), Path(dst)
    if end is None:
        end = probe(src).duration
    start = max(0.0, start)
    end = max(start, end)
    duration = end - start
    if duration <= 0:
        raise MediaError("时间区间为空。")

    args = ["-ss", f"{start:.3f}", "-i", str(src), "-t", f"{duration:.3f}"]
    if loudnorm:
        args += ["-af", "loudnorm=I=-16:TP=-1.5:LRA=11"]
    args += ["-vn", "-sn", "-dn", "-ac", "1", "-ar", "16000",
             "-c:a", "pcm_s16le", "-y", str(dst)]
    r = _run(args)
    if r.returncode != 0 or not dst.exists() or dst.stat().st_size <= 44:
        err = r.stderr.decode("utf-8", "replace")
        tail = "\n".join(err.strip().splitlines()[-8:])
        raise MediaError(f"音频抽取失败:\n{tail}")
    return dst


def clip(src: str | os.PathLike, dst: str | os.PathLike,
         start: float, end: float, reencode: bool = True) -> Path:
    """Cut a video/audio segment. Used by the export helpers, not by ASR."""
    src, dst = Path(src), Path(dst)
    args = ["-ss", f"{max(0.0, start):.3f}", "-i", str(src),
            "-t", f"{max(0.0, end - start):.3f}"]
    if reencode:
        args += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                 "-c:a", "aac", "-b:a", "160k"]
    else:
        args += ["-c", "copy"]
    args += ["-y", str(dst)]
    r = _run(args)
    if r.returncode != 0:
        err = r.stderr.decode("utf-8", "replace")
        tail = "\n".join(err.strip().splitlines()[-8:])
        raise MediaError(f"片段导出失败:\n{tail}")
    return dst


def thumbnail(src: str | os.PathLike, dst: str | os.PathLike,
               at: float = 1.0, width: int = 640) -> Path | None:
    """Grab a single frame as JPEG. Used as the poster when the video
    container/codec is not something the platform player can handle."""
    src, dst = Path(src), Path(dst)
    args = ["-ss", f"{max(0.0, at):.3f}", "-i", str(src), "-frames:v", "1",
            "-vf", f"scale={width}:-2", "-q:v", "3", "-y", str(dst)]
    r = _run(args, timeout=120)
    if r.returncode != 0 or not dst.exists() or dst.stat().st_size == 0:
        return None
    return dst


def probe_json(path: str | os.PathLike) -> dict:
    info = probe(path)
    return json.loads(json.dumps({
        "path": str(info.path), "duration": info.duration,
        "has_audio": info.has_audio, "has_video": info.has_video,
        "audio_codec": info.audio_codec, "sample_rate": info.sample_rate,
        "channels": info.channels, "size_mb": round(info.size_mb, 2),
    }, ensure_ascii=False))
