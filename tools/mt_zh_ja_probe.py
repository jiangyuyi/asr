"""复核 opus-mt-tc-big-zh-ja 到底能不能当中译日用。

为什么有这个东西：早期 docs/TRANSLATION.md 写「这个模型词表里没有中文，
14 个 token 里有 6 个变 `<unk>`」，据此排除了它。那条记录是错的——实测
零 `<unk>`。这个脚本把该做的实测补上：词表覆盖 + 实际输出。

结论（2026-10 实测）：词表覆盖没问题，但社区唯一的 CT2 转换版是 float16，
在 CPU 上输出几乎全是 `⁇`，没法评估质量。要认真比较得自己从原版转 int8。

    python tools/mt_zh_ja_probe.py            # 只测 tokenizer（不下载权重）
    python tools/mt_zh_ja_probe.py --weights  # 顺带下载 420MB 权重并实测输出

权重落到 .mt-cache/opus-mt-tc-big-zh-ja-ct2/。
"""
from __future__ import annotations

import argparse
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

CACHE = ROOT / ".mt-cache" / "opus-mt-tc-big-zh-ja-ct2"
REPO = "ooeoeo/opus-mt-tc-big-zh-ja-ct2-float16"
MIRRORS = ["https://hf-mirror.com", "https://huggingface.co"]
# 420MB 那份就是 git-lfs 里记录的 sha256
FILES = {
    "config.json": None,
    "model.bin": 420423239,
    "shared_vocabulary.json": None,
    "source.spm": 719585,
    "target.spm": 802604,
    "tokenizer_config.json": None,
    "vocab.json": None,
}

SAMPLES = [
    "今天的会议改到明天下午三点钟，请通知一下所有参加的人。",
    "请把这份材料复印三份，其中一份留给我自己用。",
    "你觉得这个价格合理吗？如果不合适可以再商量。",
]


def check_tokenizer() -> None:
    """词表到底覆不覆盖中文——这是当年被记错的那一条。"""
    from transformers import MarianTokenizer

    tok = MarianTokenizer.from_pretrained("Helsinki-NLP/opus-mt-tc-big-zh-ja")
    print(f"vocab={tok.vocab_size} unk_id={tok.unk_token_id} "
          f"eos_id={tok.eos_token_id}")
    total = unks = 0
    for text in SAMPLES:
        toks = tok.tokenize(text)
        n = sum(1 for t in toks if t == tok.unk_token)
        total += len(toks)
        unks += n
        print(f"  {text}\n    {toks}\n    <unk> {n}/{len(toks)}")
    print(f"\n合计 {total} 个 token，<unk> {unks} 个")


def fetch(name: str, size: int | None) -> bool:
    out = CACHE / name
    if out.exists() and (size is None or out.stat().st_size == size):
        return True
    for base in MIRRORS:
        try:
            req = urllib.request.Request(
                f"{base}/{REPO}/resolve/main/{name}",
                headers={"User-Agent": "asr-mm-probe"})
            with urllib.request.urlopen(req, timeout=300) as r, \
                    out.open("wb") as f:
                while chunk := r.read(1 << 20):
                    f.write(chunk)
            if size is not None and out.stat().st_size != size:
                print(f"  {name} 截断了 {out.stat().st_size} != {size}，换源重下")
                out.unlink()
                continue
            return True
        except Exception as exc:  # noqa: BLE001
            print(f"  {name} 从 {base} 失败: {exc}")
    return False


def check_output() -> None:
    """实际翻译——float16 版在 CPU 上是废的，别拿它评估质量。"""
    import ctranslate2
    import sentencepiece as spm

    src = spm.SentencePieceProcessor()
    src.load(str(CACHE / "source.spm"))
    tgt = spm.SentencePieceProcessor()
    tgt.load(str(CACHE / "target.spm"))
    tr = ctranslate2.Translator(str(CACHE), device="cpu",
                                compute_type="float32",
                                inter_threads=1, intra_threads=4)
    batch = [src.encode(t, out_type=str) for t in SAMPLES]
    for r in tr.translate_batch(batch, beam_size=4, max_decoding_length=128):
        print(f"  → {tgt.decode(r.hypotheses[0])}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", action="store_true",
                    help="下载 420MB 权重并实测输出")
    args = ap.parse_args()

    print("=== 1. tokenizer 词表覆盖 ===")
    check_tokenizer()

    if not args.weights:
        print("\n加 --weights 可继续下载权重并实测输出（420MB）。")
        return

    print("\n=== 2. 实际输出 ===")
    CACHE.mkdir(parents=True, exist_ok=True)
    for name, size in FILES.items():
        print(f"  {name} {'已有' if fetch(name, size) else '拿不到'}")
    if (CACHE / "model.bin").exists():
        check_output()
    print("\n提示：输出大量 ⁇ 说明 float16 权重在 CPU 上不可用，"
          "不是模型本身不能翻。")


if __name__ == "__main__":
    main()