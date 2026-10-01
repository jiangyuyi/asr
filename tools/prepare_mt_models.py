"""一次性离线转换：OPUS-MT / M2M100 → CTranslate2 int8，产出发布资产 zip。

这台开发机上跑一次就够了，产物（zip + sha256）随后作为 GitHub Release 资产
上传，终端用户不需要 torch/transformers，直接下载解压即用。

两种架构的差别不小，所以这里显式区分而不是假装它们一样：

  marian   OPUS-MT（Marian）。源句必须以 </s> 结尾——HuggingFace 的
           MarianTokenizer 会补这个结束标记，而 CTranslate2 对该架构的
           add_source_eos 是 false，不会补。少了它解码器不知道源句在哪儿
           结束，会一路改写复读到长度上限。症状看着像量化坏了，极易误判。

  m2m100   M2M100（多语言）。源句前加源语言码 >>cmn_Hans<<，目标语言码
           >>jpn_Jpan<< 作为 decoder 前缀；分词器只有一份
           sentencepiece.bpe.model，源和目标共用。

用法：
    python tools/prepare_mt_models.py
    python tools/prepare_mt_models.py --only ja --force
"""
from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "build_mt"
CACHE = ROOT / ".mt-cache"

MARIAN_FILES = ["config.json", "generation_config.json", "pytorch_model.bin",
                "source.spm", "target.spm", "vocab.json", "tokenizer_config.json"]
M2M100_FILES = ["config.json", "generation_config.json", "pytorch_model.bin",
                "sentencepiece.bpe.model", "vocab.json", "tokenizer_config.json"]


class Target:
    def __init__(self, key, repo, files, kind, direction,
                 src_lang="", tgt_lang="", note="", strip_spaces=False):
        self.key = key
        self.repo = repo
        self.files = files
        self.kind = kind            # "marian" | "m2m100"
        self.direction = direction
        self.src_lang = src_lang
        self.tgt_lang = tgt_lang
        self.note = note
        self.strip_spaces = strip_spaces

    @property
    def spm(self) -> str:
        return "sentencepiece.bpe.model" if self.kind == "m2m100" else "source.spm"

    def payload(self) -> list[str]:
        """The files the app actually needs at runtime.

        shared_vocabulary.json is not optional: CTranslate2 takes token
        *strings* and resolves them through it, so without it the Translator
        will not even load.
        """
        common = ["config.json", "model.bin", "shared_vocabulary.json"]
        if self.kind == "m2m100":
            return common + ["sentencepiece.bpe.model", "langs.json"]
        return common + ["source.spm", "target.spm"]


TARGETS = {
    "en": Target(
        "en", "Helsinki-NLP/opus-mt-zh-en", MARIAN_FILES, "marian", "zh->en",
        note="OPUS-MT 中译英。"),
    # OPUS-MT 没有简中↔日的语言对：唯一的中日检查点 opus-mt-tc-big-zh-ja
    # 发布的词表里没有中文（HuggingFace 自己的 tokenizer 也会把 6/14 个中文
    # token 转成 <unk>）。中转 zh->en->ja 也实测不可用——opus-mt-en-jap 是
    # 文学/论述语料，「大家一起讨论」会译成「弟子たちは互に語り合うべきである」。
    # M2M100 一次到位，代价是 CC-BY-NC 禁止商用。
    "ja": Target(
        "ja", "facebook/m2m100_418M", M2M100_FILES, "m2m100", "zh->ja",
        src_lang="zh", tgt_lang="ja",
        note="M2M100-418M 中译日，直译无需中转。", strip_spaces=True),
}

# M2M100 的联合词表用 U+2581 标词首，日文不用空格，渲染成空格就成了满屏裂缝
_ALL_SPACE = re.compile(r"[ \t　]+")

PROBES = {
    "en": [
        "这批设备的保修期是两年，过期之后需要重新购买。",
        "今天的会议改到明天下午三点钟，请通知一下所有参加的人。",
        "请把这份材料复印三份，其中一部分留给我自己用。",
        "因为前面那条路正在维修，公交车今天临时改道绕行。",
        "你觉得这个价格合理吗？如果不合适可以再商量。",
        "大家一起讨论啊。",
    ],
    "ja": [
        "这批设备的保修期是两年，过期之后需要重新购买。",
        "今天的会议改到明天下午三点钟，请通知一下所有参加的人。",
        "请把这份材料复印三份，其中一部分留给我自己用。",
        "因为前面那条路正在维修，公交车今天临时改道绕行。",
        "你觉得这个价格合理吗？如果不合适可以再商量。",
        "大家一起讨论啊。",
    ],
}


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _bases(repo: str) -> list[str]:
    """ModelScope first, HuggingFace second.

    ModelScope rejects a Range request on LFS files with 403 and full GETs are
    ~9 MB/s from here, against 0.07 MB/s straight from huggingface.co. Same
    order the app itself uses for the ASR weights.
    """
    return [f"https://modelscope.cn/models/{repo}/resolve/master",
            f"https://huggingface.co/{repo}/resolve/main"]


def _remote_size(url: str, ctx) -> int:
    try:
        req = urllib.request.Request(url, method="HEAD",
                                     headers={"User-Agent": "asr-mm/1.5"})
        with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
            return int(r.headers.get("Content-Length") or 0)
    except Exception:
        return 0


def fetch(repo: str, files: list[str]) -> Path:
    import ssl
    import urllib.request
    ctx = ssl.create_default_context()
    try:
        import certifi
        ctx.load_verify_locations(certifi.where())
    except Exception:
        pass

    dst = CACHE / repo.split("/")[-1]
    dst.mkdir(parents=True, exist_ok=True)
    for name in files:
        target = dst / name
        for base in _bases(repo):
            want = _remote_size(f"{base}/{name}", ctx)
            if want and target.exists() and target.stat().st_size == want:
                log(f"  已缓存 {name}  ({want/1e6:.1f} MB)")
                break
            target.unlink(missing_ok=True)
            try:
                log(f"  下载 {name}  <- {base.split('/')[2]}")
                req = urllib.request.Request(f"{base}/{name}",
                                             headers={"User-Agent": "asr-mm/1.5"})
                with urllib.request.urlopen(req, timeout=180,
                                            context=ctx) as r, \
                        open(target, "wb") as f:
                    while True:
                        chunk = r.read(1 << 20)
                        if not chunk:
                            break
                        f.write(chunk)
                got = target.stat().st_size
                if want and got != want:
                    raise OSError(f"大小不符 期望 {want} 实际 {got}")
                break
            except Exception as exc:
                target.unlink(missing_ok=True)
                log(f"    失败: {exc}")
        else:
            raise RuntimeError(f"下载 {name} 失败：两个源都不可用")
    return dst


def _patch_m2m100_vocabulary() -> None:
    """Make CTranslate2 build a 128112-entry vocabulary for M2M100.

    The tokenizer exposes ``num_madeup_words = 8`` — a leftover from the
    original fairseq dictionary — so CTranslate2 pads 128004 entries up to
    128012 and the conversion dies with "Source vocabulary 0 has size 128012
    but the model expected 128112". The 100 missing slots are the language
    codes (ids 128004..128103), which this transformers version keeps out of
    ``get_vocab()``.

    Rebuilding the list straight from ``convert_ids_to_tokens`` over the real
    ``vocab_size`` keeps every index aligned with the checkpoint's embedding
    matrix, which is all the runtime needs: ids are what get looked up, and
    the trailing ``<unk>`` placeholders are never produced by a real
    translation.
    """
    from ctranslate2.converters import transformers as ct2tf

    def get_vocabulary(self, model, tokenizer):
        n = model.config.vocab_size
        toks = [tokenizer.convert_ids_to_tokens(i) for i in range(n)]
        seen: dict[str, int] = {}
        for i, t in enumerate(toks):
            if t in seen:
                seen[t] += 1
                toks[i] = f"{t}#{seen[t]}"
            else:
                seen[t] = 0
        return toks

    ct2tf.M2M100Loader.get_vocabulary = get_vocabulary


def _write_langs(tgt: Target, src: Path, dst: Path) -> None:
    """Resolve the language-code token strings once, at build time.

    The app should not need transformers just to learn that Chinese is
    ``>>cmn_Hans<<``, so the strings are baked into the model directory.
    """
    import json

    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(str(src))
    out = {"src_lang": tgt.src_lang, "tgt_lang": tgt.tgt_lang}
    for field, code in (("src", tgt.src_lang), ("tgt", tgt.tgt_lang)):
        short = code.strip("<>").split("_")[0]
        lang_id = tok.lang_code_to_id.get(short)
        if lang_id is None:
            raise RuntimeError(f"模型不认识语言码 {code}")
        out[f"{field}_token"] = tok.convert_ids_to_tokens(lang_id)
        out[f"{field}_id"] = int(lang_id)
    (dst / "langs.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"{tgt.key}: 语言标记 {out['src_token']!r} / {out['tgt_token']!r}")


def convert(tgt: Target, quant: str, force: bool) -> Path:
    from ctranslate2.converters import TransformersConverter

    dst = OUT / f"mt-{tgt.key}-{quant}"
    if dst.exists() and force:
        shutil.rmtree(dst)
    if (dst / "model.bin").exists() and not force:
        log(f"{tgt.key}: 已存在，跳过转换")
        return dst

    src = fetch(tgt.repo, tgt.files)
    total = sum(f.stat().st_size for f in src.rglob("*") if f.is_file())
    log(f"{tgt.key}: 载入权重（{total/1e6:.0f} MB, {tgt.kind}）")
    dst.mkdir(parents=True, exist_ok=True)
    if tgt.kind == "m2m100":
        _patch_m2m100_vocabulary()
    # CT2 4.8 takes the model path on the constructor and only the destination
    # on convert(); quantization rides along there too.
    TransformersConverter(str(src), copy_files=[]).convert(
        str(dst), quantization=quant, force=True)

    # 分词器必须跟着走：CT2 只收 token，句子怎么切由 sentencepiece 负责
    if tgt.kind == "m2m100":
        shutil.copy2(src / "sentencepiece.bpe.model",
                     dst / "sentencepiece.bpe.model")
        _write_langs(tgt, src, dst)
    else:
        for name in ("source.spm", "target.spm"):
            shutil.copy2(src / name, dst / name)
    (dst / "KIND").write_text(tgt.kind + "\n", encoding="utf-8")
    (dst / "DIRECTION").write_text(tgt.direction + "\n", encoding="utf-8")
    return dst


def _load_spms(tgt: Target, model_dir: Path):
    import sentencepiece as spm
    sp = spm.SentencePieceProcessor()
    sp.load(str(model_dir / tgt.spm))
    if tgt.kind == "m2m100":
        return sp, sp
    tp = spm.SentencePieceProcessor()
    tp.load(str(model_dir / "target.spm"))
    return sp, tp


def lang_tokens(tgt: Target, model_dir: Path) -> tuple[str, str]:
    """Language-code token strings, read from the baked-in langs.json."""
    import json
    data = json.loads((model_dir / "langs.json").read_text(encoding="utf-8"))
    return data["src_token"], data["tgt_token"]


def encode(tgt: Target, sp, text: str, src_lang: str = "") -> list[str]:
    """Source token list for one sentence.

    Both architectures need a trailing ``</s>``. MarianTokenizer and
    M2M100Tokenizer's fairseq counterpart both emit one, and CTranslate2's
    ``add_source_eos`` is false for both, so without it the decoder has no
    "the source stops here" signal and runs away repeating itself instead of
    stopping. This one token is the difference between usable and garbage.
    """
    toks = sp.encode(text, out_type=str)
    if tgt.kind == "m2m100":
        return [src_lang, *toks, "</s>"]
    return [*toks, "</s>"]


def strip_japanese(text: str) -> str:
    """M2M100's joint vocabulary marks word starts with U+2581; Japanese does
    not use spaces, so sentencepiece's '▁ -> space' turns them into gaps."""
    return _ALL_SPACE.sub("", text)


def verify(tgt: Target, model_dir: Path) -> list[tuple[str, str]]:
    """A gate, not a report: degenerate decoding must not produce a release
    asset. See the module docstring for the failure this exists to catch."""
    import ctranslate2

    sp, tp = _load_spms(tgt, model_dir)
    engine = ctranslate2.Translator(str(model_dir), device="cpu",
                                    inter_threads=2, intra_threads=4)
    samples = PROBES[tgt.key]
    src_lang = tgt_lang = ""
    prefix = None
    if tgt.kind == "m2m100":
        src_lang, tgt_lang = lang_tokens(tgt, model_dir)
        # 语言码是词表里的独立条目（id 128004..128103），不是 SPM 切出来的子词，
        # 所以必须整块传，不能拿 sp.encode 去切。
        prefix = [tgt_lang]

    out, t0 = [], time.time()
    for text in samples:
        kw = {"target_prefix": [prefix]} if prefix else {}
        res = engine.translate_batch([encode(tgt, sp, text, src_lang)],
                                     beam_size=4, max_decoding_length=256, **kw)
        pieces = list(res[0].hypotheses[0])
        if prefix and pieces[:len(prefix)] == prefix:
            pieces = pieces[len(prefix):]      # 别把目标语言码留在译文里
        hyp = tp.decode(pieces)
        out.append((text, strip_japanese(hyp) if tgt.strip_spaces else hyp))
    elapsed = time.time() - t0
    log(f"{tgt.key}: {len(samples)} 句耗时 {elapsed:.2f}s"
        f"（{elapsed/len(samples)*1000:.0f} ms/句）")
    for src, hyp in out:
        print(f"    {src}\n  → {hyp}")

    problems = quality_problems(out)
    if problems:
        raise SystemExit(
            f"\n拒绝打包 {tgt.key}：质量检查未通过\n  - "
            + "\n  - ".join(problems)
            + "\n\n详见 docs/TRANSLATION.md")
    return out


def quality_problems(pairs) -> list[str]:
    """Cheap, deterministic checks that catch degenerate decoding."""
    problems: list[str] = []
    for src, hyp in pairs:
        if not hyp.strip():
            problems.append(f"空译文: {src}")
            continue
        words = re.findall(r"[\w一-鿿぀-ヿ]+", hyp, re.UNICODE)
        if len(words) >= 8:
            uniq = len(set(words))
            if uniq / len(words) < 0.55:
                problems.append(f"复读率过高 ({uniq}/{len(words)} 唯一): {hyp[:60]}…")
        if len(hyp) > 4 * max(len(src), 8):
            problems.append(f"译文长度失控 ({len(hyp)} vs {len(src)}): {hyp[:60]}…")
    return problems


def pack(tgt: Target, model_dir: Path) -> Path:
    keep = set(tgt.payload())
    zip_path = OUT / f"mt-{tgt.key}-{tgt.kind}.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED,
                         compresslevel=9) as z:
        for f in sorted(model_dir.rglob("*")):
            if f.is_file() and f.name in keep:
                z.write(f, f.relative_to(model_dir).as_posix())
    digest = sha256(zip_path)
    (OUT / f"mt-{tgt.key}.zip.sha256").write_text(
        f"{digest}  {zip_path.name}\n", encoding="ascii")
    log(f"{tgt.key}: {zip_path.name}  {zip_path.stat().st_size/1e6:.1f} MB  "
        f"sha256={digest}")
    return zip_path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quant", default="int8",
                    choices=["int8", "int8_float16", "float16"])
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--only", default="", help="只处理某个 key（en / ja）")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    for key, tgt in TARGETS.items():
        if args.only and key != args.only:
            continue
        model_dir = convert(tgt, args.quant, args.force)
        verify(tgt, model_dir)
        pack(tgt, model_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
