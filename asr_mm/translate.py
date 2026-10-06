"""中文 → 英文 / 日文 的本地机器翻译。

运行时是 CTranslate2（MIT），离线转成 int8，纯 CPU，不需要 PyTorch。

两种模型架构，差异都在 :class:`asr_mm.catalog.MTModelSpec` 里描述：

  英文  OPUS-MT（Marian），80 MB。源句必须以 ``</s>`` 结尾——HuggingFace 的
        MarianTokenizer 会补这个结束标记，而 CTranslate2 对该架构的
        ``add_source_eos`` 是 false 不会补。少了它解码器不知道源句在哪儿结束，
        会一路改写复读到长度上限。症状看着像量化坏了/转换坏了，极易误判，
        我就在这里绕了一大圈，排查记录见 docs/TRANSLATION.md。

  日文  M2M100-418M，一份联合分词器 + 显式语言码（源 ``>>cmn_Hans<<``、
        目标 ``>>jpn_Jpan<<`` 作 decoder 前缀）。选它是因为 OPUS-MT 没有
        简中↔日的语言对：唯一的中日检查点 opus-mt-tc-big-zh-ja 的词表其实
        有中文（实测零 ``<unk>``），zh→en→ja 中转又是文学语料（口语化的
        句子会被译成书面敬语）。

课堂讨论里「对」「是的」「嗯」这类短句会重复几十次，翻译前先去重：命中缓存
的句子不再进模型，一段 60 句的讨论通常能省掉三分之一算力。
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Callable, Sequence

from . import catalog
from .i18n import t

Progress = Callable[[str, int, int], None]  # (target, done, total)

# MarianTokenizer 补在源句末尾的结束标记，见模块 docstring
SOURCE_EOS = "</s>"

# int8 量化后偶尔会在长句上重复尾巴；这条兜底把明显的复读截掉。
_REPEAT = re.compile(r"(.{4,40}?)\1{2,}")

# M2M100 的联合词表用 U+2581 标词首，日文不用空格，渲染成空格就成了满屏裂缝
_ALL_SPACE = re.compile(r"[ \t　]+")


class TranslationError(RuntimeError):
    pass


@dataclass
class TranslationResult:
    """每个目标语种一份与输入等长的列表。"""

    texts: dict[str, list[str]] = field(default_factory=dict)
    elapsed: float = 0.0
    total: int = 0

    def is_empty(self) -> bool:
        return not any(self.texts.values())


class TranslationCancelled(TranslationError):
    pass


def _runtime_error(exc: Exception, target: str) -> TranslationError:
    name = type(exc).__name__
    if name in ("ImportError", "ModuleNotFoundError"):
        return TranslationError(t("err.mt_missing_runtime", name=str(exc)))
    if isinstance(exc, FileNotFoundError) or "model.bin" in str(exc):
        return TranslationError(t("err.mt_model_missing", target=target))
    return TranslationError(t("err.mt_failed", detail=f"{exc}"))


def normalize_targets(values: Sequence[str] | str | None) -> list[str]:
    """Accept 'en', 'en,ja', ['EN', 'ja'] in any order; drop what is unavailable."""
    if not values:
        return []
    if isinstance(values, str):
        values = values.split(",")
    available = catalog.mt_targets()
    out: list[str] = []
    for v in values:
        code = str(v).strip().lower()
        if code in available and code not in out:
            out.append(code)
    return out


def _dedupe_repeat(text: str) -> str:
    """剪掉量化模型偶发的复读尾巴；正常文本不会被正则改到。"""
    cleaned = _REPEAT.sub(r"\1", text)
    return cleaned.strip() or text


class _Engine:
    """One loaded model plus everything needed to feed it and read it back."""

    def __init__(self, spec: catalog.MTModelSpec, engine, src, tgt,
                 src_lang: str = "", tgt_prefix: list[str] | None = None):
        self.spec = spec
        self.engine = engine
        self.src = src
        self.tgt = tgt
        self.src_lang = src_lang
        self.tgt_prefix = tgt_prefix

    def encode(self, text: str) -> list[str]:
        toks = self.src.encode(text, out_type=str)
        if self.spec.kind == "m2m100":
            return [self.src_lang, *toks, SOURCE_EOS]
        return [*toks, SOURCE_EOS]

    def decode(self, pieces) -> str:
        if self.tgt_prefix and list(pieces[:len(self.tgt_prefix)]) == self.tgt_prefix:
            pieces = pieces[len(self.tgt_prefix):]   # 别把目标语言码留在译文里
        text = self.tgt.decode(list(pieces))
        return _ALL_SPACE.sub("", text) if self.spec.strip_spaces else text


class Translator:
    """Holds the loaded CTranslate2 translators for the requested targets.

    Instantiating is the expensive part (a few hundred milliseconds per model),
    so the GUI and CLI both keep one alive for the length of a job rather than
    reloading per segment.
    """

    def __init__(self, targets: Sequence[str] | None = None,
                 threads: int | None = None,
                 progress: Progress | None = None) -> None:
        wanted = normalize_targets(targets or catalog.MT_DEFAULT_TARGETS)
        if not wanted:
            raise TranslationError(t("err.mt_no_target"))
        self.targets = wanted
        self._progress = progress
        self._engines: dict[str, _Engine] = {}
        self._threads = threads

        missing = [c for c in wanted if not catalog.mt_model_ready(c)]
        if missing:
            names = "、".join(catalog.MT_MODELS[c].target for c in missing)
            raise TranslationError(t("err.mt_model_missing", target=names))

        for code in wanted:
            self._engines[code] = self._load(code)

    # ------------------------------------------------------------------ setup
    def _load(self, code: str) -> _Engine:
        try:
            import ctranslate2
            import sentencepiece as spm
        except Exception as exc:  # pragma: no cover - depends on the bundle
            raise _runtime_error(exc, code) from exc

        spec = catalog.MT_MODELS[code]
        model_dir = catalog.mt_model_dir(code)
        workers = max(1, int(self._threads or 0) or (os_cpu() // 2))
        try:
            engine = ctranslate2.Translator(
                str(model_dir), device="cpu",
                inter_threads=1, intra_threads=workers)
        except Exception as exc:
            raise _runtime_error(exc, code) from exc

        try:
            src = spm.SentencePieceProcessor()
            src.load(str(model_dir / spec.spm_file))
            if spec.kind == "m2m100":
                # 联合分词器，源和目标是同一份
                tgt, src_lang, prefix = src, spec.src_lang, None
                langs = model_dir / "langs.json"
                if langs.exists():
                    import json
                    data = json.loads(langs.read_text(encoding="utf-8"))
                    src_lang = data.get("src_token", src_lang)
                    tgt_token = data.get("tgt_token", "")
                    # 语言码是词表里的独立条目，不是 SPM 切出来的子词
                    prefix = [tgt_token] if tgt_token else None
            else:
                tgt = spm.SentencePieceProcessor()
                tgt.load(str(model_dir / "target.spm"))
                src_lang, prefix = "", None
        except Exception as exc:
            raise _runtime_error(exc, code) from exc
        return _Engine(spec, engine, src, tgt, src_lang, prefix)

    # ------------------------------------------------------------------- run
    def translate(self, texts: Sequence[str],
                  should_cancel: Callable[[], bool] | None = None
                  ) -> TranslationResult:
        items = [("" if t_ is None else str(t_)) for t_ in texts]
        out = TranslationResult(total=len(items))
        if not items:
            return out

        started = time.time()
        # 一个句子只翻一次：课堂讨论里的附和句重复率极高。
        unique: list[str] = []
        seen: dict[str, int] = {}
        for text in items:
            if text.strip() and text not in seen:
                seen[text] = len(unique)
                unique.append(text)

        for code in self.targets:
            bundle = self._engines[code]
            translated: dict[str, str] = {}
            pending = [t_ for t_ in unique if t_]
            batch = 32
            for i in range(0, len(pending), batch):
                if should_cancel and should_cancel():
                    raise TranslationCancelled(t("err.mt_cancelled"))
                chunk = pending[i:i + batch]
                tokens = [bundle.encode(t_) for t_ in chunk]
                kw = {}
                if bundle.tgt_prefix:
                    kw["target_prefix"] = [bundle.tgt_prefix] * len(chunk)
                try:
                    results = bundle.engine.translate_batch(
                        tokens, beam_size=4, max_decoding_length=512,
                        batch_type="tokens", max_batch_size=2048, **kw)
                except Exception as exc:
                    raise _runtime_error(exc, code) from exc
                for original, res in zip(chunk, results):
                    translated[original] = _dedupe_repeat(
                        bundle.decode(res.hypotheses[0]))
                if self._progress:
                    self._progress(code, min(i + batch, len(pending)),
                                   len(pending))
            out.texts[code] = [translated.get(t_, "") for t_ in items]

        out.elapsed = time.time() - started
        return out

    def close(self) -> None:
        self._engines.clear()

    def __enter__(self) -> "Translator":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def os_cpu() -> int:
    import os
    return max(1, os.cpu_count() or 1)


def translate_segments(segments, targets: Sequence[str] | str,
                       progress: Progress | None = None,
                       threads: int | None = None) -> dict[int, dict[str, str]]:
    """Translate a list of Segment-likes, keyed by index.

    Returns ``{row: {"en": ..., "ja": ...}}`` so callers can write straight into
    their own table without depending on Segment gaining new fields.
    """
    texts = [getattr(s, "text", "") or "" for s in segments]
    with Translator(targets, threads=threads, progress=progress) as tr:
        result = tr.translate(texts)
    return {i: {code: result.texts[code][i] for code in result.texts}
            for i in range(len(texts))}


def target_label(code: str) -> str:
    return catalog.MT_MODELS[code].label if code in catalog.MT_MODELS else code


def default_model_dir() -> str:
    return str(paths.models_dir())
