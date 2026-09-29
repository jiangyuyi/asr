"""Run the FunASR llama.cpp binaries and turn stdout into structured cues.

Command shapes verified in Phase 0 against the v1.4.16 binaries:

    llama-funasr-cli        --enc ENC -m LLM  --vad VAD -a audio.wav --srt
    llama-funasr-paraformer           -m PF   --vad VAD -a audio.wav --srt
    llama-funasr-sensevoice           -m SV   --vad VAD -a audio.wav --srt

All three accept ``--vad-maxseg <ms>``. That flag is not cosmetic: the LLM-decoder
model degenerates into repetition loops on long noisy segments ("大哥大哥。大哥。
大哥。…"), and capping segment length is what prevents that.
"""
from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import catalog, downloader, paths
from .srt import Cue, parse_srt

DEFAULT_MAXSEG_MS = 10_000


class EngineError(RuntimeError):
    pass


@dataclass
class EngineResult:
    cues: list[Cue]
    raw_srt: str
    seconds: float
    model: str
    model_label: str
    audio_seconds: float
    stderr: str = ""
    warning: str = ""
    meta: dict = field(default_factory=dict)

    @property
    def rtf(self) -> float:
        return self.seconds / self.audio_seconds if self.audio_seconds else 0.0


def executable_for(spec: catalog.ModelSpec) -> Path:
    suffix = paths.binary_suffix()
    return paths.runtime_dir() / (spec.binary + suffix)


def _model_arg_for(spec: catalog.ModelSpec, model_dir: Path) -> str:
    """Which GGUF is the main `-m` argument for this model."""
    if spec.key == "nano":
        return "qwen3-0.6b-q4km.gguf"
    return spec.files[0].filename


def build_command(spec: catalog.ModelSpec, wav: Path, *,
                  vad_maxseg_ms: int = DEFAULT_MAXSEG_MS,
                  threads: int | None = None) -> list[str]:
    exe = executable_for(spec)
    model_dir = paths.models_dir()
    cmd = [str(exe)]
    if spec.encoder_file:
        cmd += ["--enc", str(model_dir / spec.encoder_file)]
    cmd += ["-m", str(model_dir / _model_arg_for(spec, model_dir))]
    cmd += ["--vad", str(model_dir / "fsmn-vad.gguf"), "-a", str(wav), "--srt"]
    if vad_maxseg_ms and vad_maxseg_ms > 0:
        cmd += ["--vad-maxseg", str(int(vad_maxseg_ms))]
    if threads:
        cmd += ["-t", str(int(threads))]
    return cmd


def check_ready(key: str) -> catalog.ModelSpec:
    """Raise a clear, actionable error if the runtime or model is missing."""
    spec = catalog.resolve_model(key)
    rt = downloader.runtime_status()
    if not rt["ready"]:
        raise EngineError(
            f"未安装识别运行时（{rt['label']}）。请先运行： asr-mm setup"
            f"\n  目标目录: {rt['dir']}")
    exe = executable_for(spec)
    if not exe.exists():
        raise EngineError(f"缺少可执行文件: {exe}")
    missing = downloader.missing_files(spec)
    if missing:
        names = ", ".join(m.filename for m in missing)
        raise EngineError(
            f"模型 {spec.key} 尚未下载完整，缺少: {names}"
            f"\n请运行: asr-mm models download {spec.key}")
    return spec


def transcribe_wav(wav: str | Path, model: str = catalog.DEFAULT_MODEL, *,
                   vad_maxseg_ms: int = DEFAULT_MAXSEG_MS,
                   threads: int | None = None,
                   audio_seconds: float = 0.0) -> EngineResult:
    wav = Path(wav)
    if not wav.exists():
        raise EngineError(f"音频文件不存在: {wav}")
    spec = check_ready(model)
    cmd = build_command(spec, wav, vad_maxseg_ms=vad_maxseg_ms, threads=threads)

    t0 = time.time()
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=7200)
    except FileNotFoundError as exc:
        raise EngineError(f"无法启动识别引擎: {cmd[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise EngineError("识别超时（超过 2 小时）。") from exc
    elapsed = time.time() - t0

    out = p.stdout.decode("utf-8", "replace")
    err = p.stderr.decode("utf-8", "replace")

    if p.returncode != 0:
        tail = "\n".join(err.strip().splitlines()[-10:])
        raise EngineError(f"识别引擎返回 {p.returncode}:\n{tail}")
    if not out.strip():
        raise EngineError(
            "识别引擎没有输出任何内容。音频可能不含人声，或采样率/声道异常。")

    cues = parse_srt(out)
    warning = ""
    if not cues:
        warning = "VAD 未在该区间检测到有效语音（可能是纯静音或纯环境音）。"
    return EngineResult(
        cues=cues, raw_srt=out, seconds=elapsed, model=spec.key,
        model_label=spec.label, audio_seconds=audio_seconds, stderr=err,
        warning=warning,
        meta={"vad_maxseg_ms": vad_maxseg_ms, "executable": cmd[0]},
    )
