"""Download the GGUF models and the llama.cpp runtime on first use.

Resumable, checksummed, atomic. Files land in the user-writable home root so a
frozen macOS app bundle never has to hold a gigabyte of weights.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import tarfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from . import catalog, paths

Progress = Callable[[str, int, int], None]  # (filename, done_bytes, total_bytes)

_UA = "asr-mm/0.1 (+https://github.com/)"


def _sha256(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def _open(url: str, offset: int = 0, timeout: int = 60):
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    if offset:
        req.add_header("Range", f"bytes={offset}-")
    return urllib.request.urlopen(req, timeout=timeout)


def download(url: str, dst: Path, *, expect_size: int = 0,
             expect_sha256: str = "", progress: Progress | None = None,
             retries: int = 3) -> Path:
    """Fetch ``url`` to ``dst``, resuming a partial ``.part`` file if present."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        if expect_sha256 and _sha256(dst) != expect_sha256:
            dst.unlink()
        elif _size_ok(dst.stat().st_size, expect_size):
            return dst

    part = dst.with_suffix(dst.suffix + ".part")
    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        offset = part.stat().st_size if part.exists() else 0
        try:
            with _open(url, offset) as r:
                total = expect_size or int(r.headers.get("Content-Length") or 0)
                if offset and total:
                    total += offset
                if offset and r.status == 200:
                    # Server ignored our Range header — restart from scratch.
                    part.unlink(missing_ok=True)
                    offset = 0
                    total = int(r.headers.get("Content-Length") or 0)
                mode = "ab" if offset else "wb"
                done = offset
                if progress:
                    progress(dst.name, done, total)
                with part.open(mode) as f:
                    while True:
                        block = r.read(1 << 20)
                        if not block:
                            break
                        f.write(block)
                        done += len(block)
                        if progress:
                            progress(dst.name, done, total)
            break
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            last_err = exc
            if attempt == retries:
                raise
    else:  # pragma: no cover
        raise RuntimeError(f"下载失败: {url}") from last_err

    if expect_sha256:
        got = _sha256(part)
        if got != expect_sha256.lower():
            part.unlink(missing_ok=True)
            raise RuntimeError(
                f"校验失败 {dst.name}\n  期望 sha256 {expect_sha256}\n  实际 {got}")
    part.replace(dst)
    return dst


# --------------------------------------------------------------------------- models

# Pinned sizes are exact today; the tolerance keeps a future re-upload of the
# same file from looking "missing" and triggering an endless re-download loop.
SIZE_TOLERANCE = 0.95


def _size_ok(actual: int, expect: int) -> bool:
    return not expect or actual >= expect * SIZE_TOLERANCE


def model_path(filename: str) -> Path:
    return paths.models_dir() / filename


def missing_files(spec: catalog.ModelSpec) -> list[catalog.ModelFile]:
    out = []
    for f in spec.files:
        p = model_path(f.filename)
        if not p.exists() or not _size_ok(p.stat().st_size, f.size):
            out.append(f)
    return out


def is_model_ready(key: str) -> bool:
    try:
        return not missing_files(catalog.resolve_model(key))
    except KeyError:
        return False


def total_size(spec: catalog.ModelSpec) -> int:
    return sum(f.size for f in spec.files)


def ensure_model(key: str, progress: Progress | None = None) -> catalog.ModelSpec:
    """Download whatever parts of ``key`` are absent. Idempotent."""
    spec = catalog.resolve_model(key)
    for f in missing_files(spec):
        download(f.url, model_path(f.filename), expect_size=f.size,
                 progress=progress)
    return spec


# ------------------------------------------------------------------------ runtime

def detect_runtime_key() -> str:
    import platform
    system, machine = platform.system(), platform.machine().lower()
    if system == "Windows" and machine in ("amd64", "x86_64"):
        return "windows-x64-avx2"
    if system == "Windows":
        return "windows-x64"
    if system == "Darwin" and machine in ("arm64", "aarch64"):
        return "macos-arm64"
    if system == "Linux" and machine in ("x86_64", "amd64"):
        return "linux-x64"
    raise RuntimeError(
        f"暂不支持的平台: {system}/{machine}。"
        "可手动放置 llama-funasr-* 可执行文件到 " + str(paths.runtime_dir()))


def runtime_status() -> dict:
    key = None
    try:
        key = detect_runtime_key()
    except RuntimeError:
        pass
    d = paths.runtime_dir()
    spec = catalog.RUNTIMES.get(key or "", None)
    present = bool(spec) and all(
        (d / m).exists() for m in spec.members)
    return {"key": key, "dir": d, "ready": present,
            "label": spec.label if spec else "未知平台"}


def ensure_runtime(progress: Progress | None = None) -> Path:
    key = detect_runtime_key()
    spec = catalog.RUNTIMES[key]
    dest = paths.runtime_dir()
    if all((dest / m).exists() for m in spec.members):
        return dest
    dest.mkdir(parents=True, exist_ok=True)
    archive = paths.cache_dir() / spec.archive
    download(spec.url, archive, expect_sha256=spec.sha256, progress=progress)
    _extract(archive, dest)
    missing = [m for m in spec.members if not (dest / m).exists()]
    if missing:
        raise RuntimeError(f"运行时解压后仍缺少: {', '.join(missing)}")
    return dest


def _extract(archive: Path, dest: Path) -> None:
    tmp = dest.parent / (dest.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True, exist_ok=True)
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as z:
            _safe_zip_extract(z, tmp)
    elif archive.name.endswith((".tar.gz", ".tgz")):
        with tarfile.open(archive, "r:gz") as t:
            _safe_tar_extract(t, tmp)
    else:
        raise RuntimeError(f"无法解压的归档格式: {archive.name}")
    # Archives may or may not have a top-level directory.
    inner = [p for p in tmp.iterdir() if p.is_dir()]
    if len(inner) == 1 and not any(tmp.glob("llama-funasr-*")):
        for item in inner[0].iterdir():
            shutil.move(str(item), str(dest / item.name))
        shutil.rmtree(tmp, ignore_errors=True)
    else:
        for item in tmp.iterdir():
            shutil.move(str(item), str(dest / item.name))
        shutil.rmtree(tmp, ignore_errors=True)


def _safe_zip_extract(z: zipfile.ZipFile, dest: Path) -> None:
    root = dest.resolve()
    for member in z.infolist():
        target = (dest / member.filename).resolve()
        if not str(target).startswith(str(root)):
            raise RuntimeError(f"归档包含越界路径: {member.filename}")
    z.extractall(dest)


def _safe_tar_extract(t: tarfile.TarFile, dest: Path) -> None:
    root = dest.resolve()
    for member in t.getmembers():
        target = (dest / member.name).resolve()
        if not str(target).startswith(str(root)):
            raise RuntimeError(f"归档包含越界路径: {member.name}")
        if member.issym() or member.islnk():
            raise RuntimeError(f"归档包含链接，已拒绝: {member.name}")
    t.extractall(dest, filter="data")


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def progress_printer(prefix: str = "", stream=None, min_interval: float = 0.15):
    """A throttled single-line progress callback for terminals."""
    import sys
    import time

    out = stream or sys.stderr
    state = {"t": 0.0, "name": ""}

    def cb(name: str, done: int, total: int) -> None:
        now = time.time()
        if done < total and now - state["t"] < min_interval:
            return
        state["t"] = now
        if name != state["name"]:
            state["name"] = name
            out.write("\r" + " " * 78 + "\r")
        pct = f"{done / total * 100:5.1f}%" if total else "  ? %"
        out.write(f"\r{prefix}{name}  {pct}  "
                  f"{human(done)}/{human(total)}   ")
        out.flush()
        if done >= total:
            out.write("\n")
            out.flush()

    return cb


def clear_progress_line(stream=None) -> None:
    import sys
    (stream or sys.stderr).write("\r" + " " * 78 + "\r")
    (stream or sys.stderr).flush()


def status_table() -> Iterable[str]:
    rt = runtime_status()
    yield f"运行时: {rt['label']}  {'已就绪' if rt['ready'] else '未安装'}  -> {rt['dir']}"
    for spec in catalog.MODELS.values():
        missing = missing_files(spec)
        state = "已就绪" if not missing else \
            f"缺 {len(missing)} 个文件 ({human(total_size(spec))})"
        yield f"模型 {spec.key:11s} {state}"
