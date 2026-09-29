"""Catalog of the FunASR llama.cpp runtime and GGUF ASR models.

Pinned to the v1.4.16 release of modelscope/FunASR. Checksums come from the
release's SHA256SUMS and were verified against locally downloaded archives.
"""
from __future__ import annotations

from dataclasses import dataclass, field

RUNTIME_VERSION = "v1.4.16"
RUNTIME_BASE = f"https://github.com/modelscope/FunASR/releases/download/{RUNTIME_VERSION}"

HF = "https://huggingface.co/FunAudioLLM"


@dataclass(frozen=True)
class ModelFile:
    url: str
    filename: str
    size: int  # bytes


@dataclass(frozen=True)
class ModelSpec:
    key: str
    label: str
    binary: str
    files: tuple[ModelFile, ...]
    note: str = ""
    # Nano needs an explicit --enc pointing at the audio encoder
    encoder_file: str | None = None
    aliases: tuple[str, ...] = field(default_factory=tuple)


VAD_FILE = ModelFile(f"{HF}/fsmn-vad-GGUF/resolve/main/fsmn-vad.gguf",
                     "fsmn-vad.gguf", 1_720_512)

NANO = ModelSpec(
    key="nano",
    label="Nano（质量档·推荐）",
    binary="llama-funasr-cli",
    encoder_file="funasr-encoder-f16.gguf",
    note="标点最完整、中文准确率最高；约 10× 实时。",
    aliases=("qwen3", "fun-asr-nano"),
    files=(
        ModelFile(f"{HF}/Fun-ASR-Nano-GGUF/resolve/main/funasr-encoder-f16.gguf",
                  "funasr-encoder-f16.gguf", 469_331_008),
        ModelFile(f"{HF}/Fun-ASR-Nano-GGUF/resolve/main/qwen3-0.6b-q4km.gguf",
                  "qwen3-0.6b-q4km.gguf", 484_219_776),
        VAD_FILE,
    ),
)

PARAFORMER = ModelSpec(
    key="paraformer",
    label="Paraformer（快速档）",
    binary="llama-funasr-paraformer",
    note="约 27× 实时，体积最小；输出不带标点。仅 CPU。",
    aliases=("fast", "pf"),
    files=(
        ModelFile(f"{HF}/Paraformer-GGUF/resolve/main/paraformer-q8.gguf",
                  "paraformer-q8.gguf", 236_929_024),
        VAD_FILE,
    ),
)

SENSEVOICE = ModelSpec(
    key="sensevoice",
    label="SenseVoice（均衡档）",
    binary="llama-funasr-sensevoice",
    note="唯一支持 CUDA/Vulkan 加速；短片段（<1.5s）易输出空内容。",
    aliases=("sv", "balanced"),
    files=(
        ModelFile(f"{HF}/SenseVoiceSmall-GGUF/resolve/main/sensevoice-small-q8.gguf",
                  "sensevoice-small-q8.gguf", 254_208_320),
        VAD_FILE,
    ),
)

MODELS: dict[str, ModelSpec] = {m.key: m for m in (NANO, PARAFORMER, SENSEVOICE)}
DEFAULT_MODEL = "nano"

_ALIASES: dict[str, str] = {}
for _m in MODELS.values():
    _ALIASES[_m.key] = _m.key
    for _a in _m.aliases:
        _ALIASES[_a] = _m.key


def resolve_model(name: str) -> ModelSpec:
    key = _ALIASES.get((name or "").strip().lower())
    if key is None:
        raise KeyError(name)
    return MODELS[key]


@dataclass(frozen=True)
class RuntimeSpec:
    key: str
    label: str
    url: str
    sha256: str
    archive: str
    members: tuple[str, ...]  # executables that must be present after extract
    prefer_avx2: bool = False


RUNTIMES: dict[str, RuntimeSpec] = {
    "windows-x64-avx2": RuntimeSpec(
        key="windows-x64-avx2",
        label="Windows x64 (AVX2)",
        url=f"{RUNTIME_BASE}/funasr-llamacpp-windows-x64-avx2.zip",
        sha256="062cda8fefadd31c3e811227116daccf448a8520f4b0bb168d225c896e65ebbd",
        archive="funasr-llamacpp-windows-x64-avx2.zip",
        members=("llama-funasr-cli.exe", "llama-funasr-paraformer.exe",
                 "llama-funasr-sensevoice.exe", "llama-funasr-vad.exe"),
        prefer_avx2=True,
    ),
    "windows-x64": RuntimeSpec(
        key="windows-x64",
        label="Windows x64 (通用)",
        url=f"{RUNTIME_BASE}/funasr-llamacpp-windows-x64.zip",
        sha256="f6a73a548413ba9fbaf2145263ea66ec53cbdad1fb11790dbeeee493e339492e",
        archive="funasr-llamacpp-windows-x64.zip",
        members=("llama-funasr-cli.exe", "llama-funasr-paraformer.exe",
                 "llama-funasr-sensevoice.exe", "llama-funasr-vad.exe"),
    ),
    "macos-arm64": RuntimeSpec(
        key="macos-arm64",
        label="macOS arm64",
        url=f"{RUNTIME_BASE}/funasr-llamacpp-macos-arm64.tar.gz",
        sha256="bda59474202b887190f59d25b7b42c714469efae71276072c12fa0a38de68792",
        archive="funasr-llamacpp-macos-arm64.tar.gz",
        members=("llama-funasr-cli", "llama-funasr-paraformer",
                 "llama-funasr-sensevoice", "llama-funasr-vad"),
    ),
    "linux-x64": RuntimeSpec(
        key="linux-x64",
        label="Linux x64",
        url=f"{RUNTIME_BASE}/funasr-llamacpp-linux-x64.tar.gz",
        sha256="779967de1c528c2be966bcc47f246e7d3e6fcdb748d9491263062f4120f35e52",
        archive="funasr-llamacpp-linux-x64.tar.gz",
        members=("llama-funasr-cli", "llama-funasr-paraformer",
                 "llama-funasr-sensevoice", "llama-funasr-vad"),
    ),
}
