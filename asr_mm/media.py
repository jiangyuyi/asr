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
from .i18n import t

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
        raise MediaError(t("err.no_ffmpeg")) from exc


def _run(args: list[str], timeout: int = 3600,
         proc_box: list | None = None) -> subprocess.CompletedProcess:
    cmd = [ffmpeg_path(), "-hide_banner", "-nostdin", *args]
    if proc_box is None:
        # Binary-safe: the child always writes UTF-8 regardless of the host locale.
        return subprocess.run(cmd, capture_output=True, timeout=timeout)
    # Caller wants to be able to kill this one mid-flight.
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    proc_box.append(proc)
    try:
        _out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        _out, err = proc.communicate()
        raise
    return subprocess.CompletedProcess(cmd, proc.returncode or 0, _out, err)


def _run_streaming(args: list[str], on_progress, timeout: int = 3600) -> str:
    """Run ffmpeg with ``-progress pipe:1`` and stream percentage updates.

    ``on_progress(fraction_0_to_1)`` is called as ffmpeg reports progress. This
    is what lets the GUI show a real moving bar instead of a guess.
    """
    cmd = [ffmpeg_path(), "-hide_banner", "-nostdin", "-progress", "pipe:1",
           "-nostats", *args]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert proc.stdout is not None
    for raw in proc.stdout:
        key, _, value = raw.decode("utf-8", "replace").strip().partition("=")
        if key != "out_time_us" and key != "out_time_ms":
            continue
        try:
            micros = int(value)
        except ValueError:
            continue
        on_progress(micros)
    proc.wait(timeout=timeout)
    return proc.stderr.read().decode("utf-8", "replace") if proc.stderr else ""


def probe(path: str | os.PathLike, proc_box: list | None = None) -> MediaInfo:
    """Inspect a media file.

    Pass ``proc_box`` (a list) to receive the ffmpeg Popen, so a caller that
    may be cancelled — such as the GUI's background loader — can kill a probe
    that is stuck on a slow or unreachable drive.
    """
    p = Path(path)
    if not p.exists():
        raise MediaError(t("err.not_a_file", path=p))
    if p.is_dir():
        raise MediaError(t("err.is_dir", path=p))
    r = _run(["-i", str(p)], proc_box=proc_box)
    err = r.stderr.decode("utf-8", "replace")
    m = _DUR.search(err)
    if not m:
        tail = "\n".join(err.strip().splitlines()[-6:])
        raise MediaError(t("err.unreadable", tail=tail))
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
        raise MediaError(t("err.no_audio"))
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
        raise MediaError(t("err.empty_range"))

    args = ["-ss", f"{start:.3f}", "-i", str(src), "-t", f"{duration:.3f}"]
    if loudnorm:
        args += ["-af", "loudnorm=I=-16:TP=-1.5:LRA=11"]
    args += ["-vn", "-sn", "-dn", "-ac", "1", "-ar", "16000",
             "-c:a", "pcm_s16le", "-y", str(dst)]
    r = _run(args)
    if r.returncode != 0 or not dst.exists() or dst.stat().st_size <= 44:
        err = r.stderr.decode("utf-8", "replace")
        tail = "\n".join(err.strip().splitlines()[-8:])
        raise MediaError(t("err.extract_failed", tail=tail))
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
        raise MediaError(t("err.clip_failed", tail=tail))
    return dst


def thumbnail(src: str | os.PathLike, dst: str | os.PathLike,
               at: float = 1.0, width: int = 640,
               on_progress=None, proc: subprocess.Popen | None = None) -> Path | None:
    """Grab a single frame as JPEG.

    Used as the poster shown while the platform player is still opening the
    file, and as the preview fallback when the container or codec is one the
    system player cannot handle.

    With ``on_progress`` the work runs through ``-progress pipe:1`` and reports
    0.0–1.0 as ffmpeg decodes; pass ``proc`` to let a caller cancel it.
    """
    src, dst = Path(src), Path(dst)
    args = ["-ss", f"{max(0.0, at):.3f}", "-i", str(src), "-frames:v", "1",
            "-vf", f"scale={width}:-2", "-q:v", "3", "-y", str(dst)]
    if on_progress is None:
        r = _run(args, timeout=300)
        err = r.stderr.decode("utf-8", "replace")
    else:
        err = _run_streaming(args, on_progress, timeout=300)
    if not dst.exists() or dst.stat().st_size == 0:
        return None
    if proc is not None and proc.poll() is not None:
        return None
    return dst


def duration_of(src: str | os.PathLike) -> float:
    return probe(src).duration


def probe_json(path: str | os.PathLike) -> dict:
    info = probe(path)
    return json.loads(json.dumps({
        "path": str(info.path), "duration": info.duration,
        "has_audio": info.has_audio, "has_video": info.has_video,
        "audio_codec": info.audio_codec, "sample_rate": info.sample_rate,
        "channels": info.channels, "size_mb": round(info.size_mb, 2),
    }, ensure_ascii=False))
