"""定位 zh-en 复读问题的对照实验：量化档位 vs 转换本身。"""
from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ctranslate2
import sentencepiece as spm
from ctranslate2.converters import TransformersConverter

SRC = Path(__file__).resolve().parent.parent / ".mt-cache" / "opus-mt-zh-en"
OUT = Path(__file__).resolve().parent.parent / "build_mt"

PROBES = [
    "今天的会议改到明天下午三点钟，请通知一下所有参加的人。",
    "你觉得这个价格合理吗？如果不合适可以再商量。",
    "因为前面那条路正在维修，公交车今天临时改道绕行。",
]


def trial(quant, beam):
    dst = OUT / f"trial-{quant}-b{beam}"
    if not (dst / "model.bin").exists():
        shutil.rmtree(dst, ignore_errors=True)
        conv = TransformersConverter(str(SRC), copy_files=[])
        conv.convert(str(dst), quantization=quant, force=True)
        for n in ("source.spm", "target.spm"):
            shutil.copy2(SRC / n, dst / n)
    size = (dst / "model.bin").stat().st_size / 1e6

    sp = spm.SentencePieceProcessor()
    sp.load(str(dst / "source.spm"))
    tp = spm.SentencePieceProcessor()
    tp.load(str(dst / "target.spm"))
    tr = ctranslate2.Translator(str(dst), device="cpu",
                                inter_threads=1, intra_threads=4)
    print(f"\n=== quant={quant} beam={beam}  model.bin={size:.0f} MB ===")
    for text in PROBES:
        toks = [sp.encode(text, out_type=str)]
        t0 = time.time()
        r = tr.translate_batch(toks, beam_size=beam, max_decoding_length=256)
        out = tp.decode(r[0].hypotheses[0])
        print(f"  ({time.time()-t0:.2f}s) {out}")


if __name__ == "__main__":
    for quant, beam in (("float32", 4), ("int8", 4), ("float32", 1),
                        ("int8", 1)):
        try:
            trial(quant, beam)
        except Exception as exc:
            print(f"!! quant={quant} beam={beam} 失败: {exc}")
