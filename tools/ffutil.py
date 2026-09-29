"""Shared ffmpeg helper for asr-mm development scripts."""
import os
import subprocess
import sys

import imageio_ffmpeg


def ffmpeg_exe() -> str:
    return imageio_ffmpeg.get_ffmpeg_exe()


def run(args, capture=True):
    cmd = [ffmpeg_exe(), "-hide_banner", *args]
    p = subprocess.run(cmd, capture_output=capture, text=True,
                       encoding="utf-8", errors="replace")
    return p


def probe(path: str) -> str:
    p = subprocess.run([ffmpeg_exe(), "-hide_banner", "-i", path],
                       capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return p.stderr


if __name__ == "__main__":
    print(probe(sys.argv[1]))
