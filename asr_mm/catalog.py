"""Catalog of the FunASR llama.cpp runtime and GGUF ASR models.

Pinned to the v1.4.16 release of modelscope/FunASR. Checksums come from the
release's SHA256SUMS and were verified against locally downloaded archives.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .i18n import t

RUNTIME_VERSION = "v1.4.16"
RUNTIME_BASE = f"https://github.com/modelscope/FunASR/releases/download/{RUNTIME_VERSION}"

# The translation models are converted to CTranslate2 int8 by
# tools/prepare_mt_models.py and published as release assets rather than pulled
# from a third-party repository: there is no public zh->ja conversion to borrow,
# and hosting our own means one checksum we control instead of two we don't.
MT_VERSION = "v1.5.0"
MT_BASE = f"https://github.com/jiangyuyi/asr/releases/download/{MT_VERSION}"
MT_HF = "https://huggingface.co/Helsinki-NLP"

HF = "https://huggingface.co/FunAudioLLM"
# ModelScope mirrors the same GGUF repos and is reachable from mainland China
# without a VPN. Used as a fallback when HuggingFace is blocked, slow, or
# intercepted by a TLS-inspecting proxy.
MS = "https://modelscope.cn/models"


@dataclass(frozen=True)
class ModelFile:
    url: str
    filename: str
    size: int  # bytes
    mirror_url: str = ""   # same bytes, alternate host
    # Optional. The ASR weights were pinned by size only; translation weights
    # are 100-210 MB, where a truncated download that still passes the size
    # check is worth catching.
    sha256: str = ""

    def sources(self, mirror: str = "auto") -> list[str]:
        """URLs to try, in order, honouring the user's mirror preference."""
        if mirror == "huggingface":
            return [self.url]
        if mirror == "modelscope" and self.mirror_url:
            return [self.mirror_url]
        return [self.url, self.mirror_url] if self.mirror_url else [self.url]


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
    # Languages this model can actually transcribe, measured against SAPI
    # speech in zh/ja/en. Paraformer returns nothing for Japanese and drops all
    # spacing on English, so it is listed as Chinese-only.
    languages: tuple[str, ...] = ("zh",)
    # Languages it handles but with a visible quality cost.
    degraded: tuple[str, ...] = ()

    def supports(self, code: str) -> bool:
        if not code or code == "auto":
            return True
        return code in self.languages

    @staticmethod
    def lang_name(code: str) -> str:
        """Localised display name; falls back to the raw code."""
        return t("lang." + code) if code and code != "auto" else t("lang.auto")

    def warning_for(self, code: str) -> str:
        if not code or code == "auto" or self.supports(code):
            return ""
        return t("warn.model_no_lang", model=self.key, lang=self.lang_name(code))



VAD_FILE = ModelFile(f"{HF}/fsmn-vad-GGUF/resolve/main/fsmn-vad.gguf",
                     "fsmn-vad.gguf", 1_720_512,
                     mirror_url=f"{MS}/FunAudioLLM/fsmn-vad-GGUF/resolve/master/fsmn-vad.gguf")

NANO = ModelSpec(
    key="nano",
    label="Nano（质量档·推荐）",
    binary="llama-funasr-cli",
    encoder_file="funasr-encoder-f16.gguf",
    note="标点最完整；中/英/日均可，约 10× 实时。",
    aliases=("qwen3", "fun-asr-nano"),
    languages=("zh", "en", "ja"),
    files=(
        ModelFile(f"{HF}/Fun-ASR-Nano-GGUF/resolve/main/funasr-encoder-f16.gguf",
                  "funasr-encoder-f16.gguf", 469_331_008,
                  mirror_url=f"{MS}/FunAudioLLM/Fun-ASR-Nano-GGUF/resolve/master/funasr-encoder-f16.gguf"),
        ModelFile(f"{HF}/Fun-ASR-Nano-GGUF/resolve/main/qwen3-0.6b-q4km.gguf",
                  "qwen3-0.6b-q4km.gguf", 484_219_776,
                  mirror_url=f"{MS}/FunAudioLLM/Fun-ASR-Nano-GGUF/resolve/master/qwen3-0.6b-q4km.gguf"),
        VAD_FILE,
    ),
)

PARAFORMER = ModelSpec(
    key="paraformer",
    label="Paraformer（快速档·仅中文）",
    binary="llama-funasr-paraformer",
    note="约 27× 实时，体积最小；仅中文，且输出不带标点。仅 CPU。",
    aliases=("fast", "pf"),
    languages=("zh",),
    files=(
        ModelFile(f"{HF}/Paraformer-GGUF/resolve/main/paraformer-q8.gguf",
                  "paraformer-q8.gguf", 236_929_024,
                  mirror_url=f"{MS}/FunAudioLLM/Paraformer-GGUF/resolve/master/paraformer-q8.gguf"),
        VAD_FILE,
    ),
)

SENSEVOICE = ModelSpec(
    key="sensevoice",
    label="SenseVoice（均衡档）",
    binary="llama-funasr-sensevoice",
    note="唯一支持 CUDA/Vulkan 加速；中/英可用，日文分词间距有瑕疵。",
    aliases=("sv", "balanced"),
    languages=("zh", "en", "ja"),
    degraded=("ja",),
    files=(
        ModelFile(f"{HF}/SenseVoiceSmall-GGUF/resolve/main/sensevoice-small-q8.gguf",
                  "sensevoice-small-q8.gguf", 254_208_320,
                  mirror_url=f"{MS}/FunAudioLLM/SenseVoiceSmall-GGUF/resolve/master/sensevoice-small-q8.gguf"),
        VAD_FILE,
    ),
)

MODELS: dict[str, ModelSpec] = {m.key: m for m in (NANO, PARAFORMER, SENSEVOICE)}
DEFAULT_MODEL = "nano"

# ------------------------------------------------------------------ translation

@dataclass(frozen=True)
class MTModelSpec:
    """A CTranslate2 translation model, one per target language.

    Files live under ``<models>/<dir_name>/`` so the two languages never
    collide and a half-finished download of one cannot make the other look
    ready.
    """

    key: str                       # target language code
    target: str                    # native name, for the UI
    dir_name: str
    files: tuple[ModelFile, ...]
    note: str = ""
    # "marian" (OPUS-MT) or "m2m100". They differ in more than the file names:
    # Marian needs a trailing </s> on the source and has separate source and
    # target tokenizers, while M2M100 has one joint tokenizer and uses explicit
    # language codes. See asr_mm.translate.
    kind: str = "marian"
    spm_file: str = "source.spm"
    # M2M100 source language token; the target one lives in langs.json because
    # the exact string depends on the checkpoint's fairseq dictionary.
    src_lang: str = ""
    strip_spaces: bool = False

    def size(self) -> int:
        return sum(f.size for f in self.files)

    def sources(self, mirror: str = "auto") -> list[list[str]]:
        return [f.sources(mirror) for f in self.files]


def _mt_files(slug: str, entries: dict[str, tuple[int, str]]) -> tuple[ModelFile, ...]:
    """``{"model.bin": (size, sha256), ...}`` -> download descriptors.

    Release asset names cannot contain a slash, so the per-model directory
    (``mt-en/``) lives in the asset name rather than in the path; the app
    still lays the files out in that directory under the models root.
    """
    return tuple(
        ModelFile(f"{MT_BASE}/mt-{slug}-{name}", name, size, sha256=sha)
        for name, (size, sha) in entries.items()
    )


MT_EN_FILES = _mt_files("en", {
    "model.bin": (79_567_635,
                  "e4955858cae9542bef37424a9b79720e3db2f32501fe62264c0cd3eac6319777"),
    "config.json": (233,
                    "72901fbd8abd89fb5cf4a388f26fc681f5c4c58a1e1a88b30b879f107270e7ee"),
    "shared_vocabulary.json": (
        1_368_999,
        "55d071d6c63a2dab993f00e77077eca76573ac6964990e2e80de7462344401fb"),
    "source.spm": (804_677,
                   "e27a3a1b539f4959ec72ea60e453f49156289f95d4e6000b29332efc45616203"),
    "target.spm": (806_530,
                   "6a881f4717cd7265f53fea54fd3dc689c767c05338fac7a4590f3088cb2d7855"),
})

MT_JA_FILES = _mt_files("ja", {
    "model.bin": (490_667_752,
                  "590e9c7e229e84de8affe7b15487660a286d3d76e44a4ca10e33099b198d9a76"),
    "config.json": (233,
                    "72901fbd8abd89fb5cf4a388f26fc681f5c4c58a1e1a88b30b879f107270e7ee"),
    "shared_vocabulary.json": (
        2_924_590,
        "3463563ecd8b5083f48496c460aaaa8b0ecfb54c9e255f71d4504c8f11c43c06"),
    "sentencepiece.bpe.model": (
        2_423_393,
        "d8f7c76ed2a5e0822be39f0a4f95a55eb19c78f4593ce609e2edbc2aea4d380a"),
    "langs.json": (139,
                   "da08b5e251f17cca1bf6a807de80c3056ec0e3bc2bfd3708664ac23f2b6aef38"),
})

MT_MODELS: dict[str, MTModelSpec] = {
    "en": MTModelSpec(
        key="en", target="English", dir_name="mt-en", files=MT_EN_FILES,
        kind="marian", spm_file="source.spm",
        note="OPUS-MT 中译英。语料以通用书面语为主，课堂短句译得干净。"),
    # OPUS-MT 没有简中↔日的语言对：唯一的中日检查点 opus-mt-tc-big-zh-ja
    # 发布的词表里没有中文（用 HuggingFace 自己的 tokenizer，14 个 token 里 6 个
    # 变 <unk>）。zh->en->ja 中转也实测不可用——opus-mt-en-jap 是文学语料，
    # 「大家互相交流」会译成「弟子たちは互に語り合うべきである」。M2M100 直译。
    "ja": MTModelSpec(
        key="ja", target="日本語", dir_name="mt-ja", files=MT_JA_FILES,
        kind="m2m100", spm_file="sentencepiece.bpe.model",
        src_lang="__zh__", strip_spaces=True,
        note="M2M100-418M 中译日。质量弱于英文：能读懂但偶有实错"
             "（面積→表面公式、翻到→翻訳），建议人工复核。"),
}

MT_DEFAULT_TARGETS = ("en", "ja")



def mt_targets() -> tuple[str, ...]:
    return tuple(MT_MODELS)


def resolve_mt(code: str) -> MTModelSpec:
    try:
        return MT_MODELS[(code or "").strip().lower()]
    except KeyError:
        raise KeyError(code) from None


def mt_model_dir(code: str) -> "Path":
    from . import paths
    return paths.models_dir() / resolve_mt(code).dir_name


def mt_model_ready(code: str) -> bool:
    """True when every file of the model is present at a plausible size."""
    try:
        spec = resolve_mt(code)
    except KeyError:
        return False
    d = mt_model_dir(code)
    for f in spec.files:
        p = d / f.filename
        if not p.exists() or p.stat().st_size < f.size * 0.95:
            return False
    return True


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
