"""Download the GGUF models and the llama.cpp runtime on first use.

Resumable, checksummed, atomic. Files land in the user-writable home root so a
frozen macOS app bundle never has to hold a gigabyte of weights.

Transport lives in :mod:`asr_mm.net`: mirror fallback, a trust store that works
inside a frozen bundle, and an error taxonomy the UI can turn into advice.
"""
from __future__ import annotations

import hashlib
import shutil
import ssl
import tarfile
import zipfile
from pathlib import Path
from typing import Callable, Iterable

from . import catalog, net, paths, settings as settings_mod
from .i18n import t

Progress = Callable[[str, int, int], None]  # (filename, done_bytes, total_bytes)


def _sha256(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def net_config(overrides: dict | None = None) -> net.NetConfigLoaded:
    """Saved settings, optionally with per-call overrides."""
    s = settings_mod.Settings.load()
    data = s.to_dict()
    if overrides:
        data.update({k: v for k, v in overrides.items() if v not in (None, "")})
    return net.NetConfigLoaded.load(
        ca_bundle=data.get("ca_bundle", ""),
        insecure=bool(data.get("insecure")),
        mirror=data.get("mirror", "auto"),
    )


def ssl_context(cfg: net.NetConfigLoaded | None = None) -> ssl.SSLContext:
    return net.build_context(cfg or net_config())


def download(urls: list[str] | str, dst: Path, *, expect_size: int = 0,
             expect_sha256: str = "", progress: Progress | None = None,
             retries: int = 2, cfg: net.NetConfigLoaded | None = None) -> Path:
    """Fetch to ``dst``, trying each URL in turn and resuming where possible."""
    if isinstance(urls, str):
        urls = [urls]
    return net.fetch(urls, dst, ssl_context(cfg), expect_size=expect_size,
                     expect_sha256=expect_sha256, on_progress=progress,
                     retries=retries)


def explain(exc: Exception) -> str:
    """Turn a network failure into something the user can act on."""
    if isinstance(exc, net.NetConfigError):
        return str(exc)
    if isinstance(exc, net.DownloadError):
        lines = [t("dlg.dl_failed", name=exc.filename)]
        for host, why in exc.attempts:
            lines.append(f"  · {host}: {why}")
        if any("证书" in why for _, why in exc.attempts):
            lines.append("")
            lines.append(t("dlg.dl_ssl_help"))
        else:
            lines.append("")
            lines.append(t("dlg.dl_mirror_help"))
        return "\n".join(lines)
    return str(exc)


# --------------------------------------------------------------------------- models

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


def ensure_model(key: str, progress: Progress | None = None,
                 cfg: net.NetConfigLoaded | None = None) -> catalog.ModelSpec:
    """Download whatever parts of ``key`` are absent. Idempotent."""
    spec = catalog.resolve_model(key)
    cfg = cfg or net_config()
    for f in missing_files(spec):
        net.fetch(f.sources(cfg.mirror), model_path(f.filename),
                  net.build_context(cfg), expect_size=f.size,
                  on_progress=progress)
    return spec


# ------------------------------------------------------------------ translation

def mt_model_path(code: str, filename: str) -> Path:
    return paths.models_dir() / catalog.MT_MODELS[code].dir_name / filename


def mt_missing_files(spec: catalog.MTModelSpec) -> list[catalog.ModelFile]:
    out = []
    for f in spec.files:
        p = mt_model_path(spec.key, f.filename)
        if not p.exists() or not _size_ok(p.stat().st_size, f.size):
            out.append(f)
    return out


def ensure_mt_model(code: str, progress: Progress | None = None,
                    cfg: net.NetConfigLoaded | None = None) -> catalog.MTModelSpec:
    """Download the translation model for one target language. Idempotent."""
    spec = catalog.MT_MODELS[code]
    cfg = cfg or net_config()
    for f in mt_missing_files(spec):
        dest = mt_model_path(code, f.filename)
        net.fetch(f.sources(cfg.mirror), dest, net.build_context(cfg),
                  expect_size=f.size, expect_sha256=f.sha256,
                  on_progress=progress)
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
        t("err.unsupported_platform", platform=f"{system}/{machine}",
          dir=paths.runtime_dir()))


def runtime_status() -> dict:
    key = None
    try:
        key = detect_runtime_key()
    except RuntimeError:
        pass
    d = paths.runtime_dir()
    spec = catalog.RUNTIMES.get(key or "", None)
    present = bool(spec) and all((d / m).exists() for m in spec.members)
    return {"key": key, "dir": d, "ready": present,
            "label": spec.label if spec else t("runtime.unknown")}


def ensure_runtime(progress: Progress | None = None,
                   cfg: net.NetConfigLoaded | None = None) -> Path:
    key = detect_runtime_key()
    spec = catalog.RUNTIMES[key]
    dest = paths.runtime_dir()
    if all((dest / m).exists() for m in spec.members):
        return dest
    dest.mkdir(parents=True, exist_ok=True)
    archive = paths.cache_dir() / spec.archive
    # The runtime only ships on GitHub, but a corporate proxy may block it; the
    # user's mirror preference still applies if a mirror is known for it.
    net.fetch([spec.url], archive, net.build_context(cfg or net_config()),
              expect_sha256=spec.sha256, on_progress=progress)
    _extract(archive, dest)
    missing = [m for m in spec.members if not (dest / m).exists()]
    if missing:
        raise RuntimeError(t("err.runtime_incomplete", names=", ".join(missing)))
    return dest


def _extract(archive: Path, dest: Path) -> None:
    tmp = dest.parent / (dest.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True, exist_ok=True)
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as z:
            _safe_zip_extract(z, tmp)
    elif archive.name.endswith((".tar.gz", ".tgz")):
        with tarfile.open(archive, "r:gz") as t_:
            _safe_tar_extract(t_, tmp)
    else:
        raise RuntimeError(t("err.bad_archive", name=archive.name))
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
            raise RuntimeError(t("err.zip_escape", name=member.filename))
    z.extractall(dest)


def _safe_tar_extract(tf: tarfile.TarFile, dest: Path) -> None:
    root = dest.resolve()
    for member in tf.getmembers():
        target = (dest / member.name).resolve()
        if not str(target).startswith(str(root)):
            raise RuntimeError(t("err.zip_escape", name=member.name))
        if member.issym() or member.islnk():
            raise RuntimeError(t("err.tar_link", name=member.name))
    tf.extractall(dest, filter="data")


SIZE_TOLERANCE = 0.95


def _size_ok(actual: int, expect: int) -> bool:
    return not expect or actual >= expect * SIZE_TOLERANCE


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
    state = t("cli.status_ready") if rt["ready"] else t("cli.status_missing")
    yield f"  {t('cli.doctor.runtime')}: {rt['label']}  {state}  -> {rt['dir']}"
    for spec in catalog.MODELS.values():
        missing = missing_files(spec)
        if not missing:
            detail = t("cli.models.state_ready")
        else:
            detail = t("cli.doctor.model_incomplete_short", count=len(missing),
                       size=human(total_size(spec)))
        yield f"  {t('cli.doctor.models')} {spec.key:11s} {detail}"
