"""量化没问题，但解码会复读。逐个试解码侧的对策。"""
from __future__ import annotations

from pathlib import Path

import ctranslate2
import sentencepiece as spm

ROOT = Path(__file__).resolve().parent.parent
D = ROOT / "build_mt" / "mt-zh-en-int8"

TESTS = [
    "同学们，谁能告诉我这个方程的解是什么？",
    "你觉得这个结论对吗？为什么？",
    "因为水的密度比空气大，所以物体会上浮或者下沉。",
    "今天我们来学习三角形的面积公式。",
    "大家互相交流啊。",
    "小土丘，呃，孩子们，张老师先解释一下啊，看一下你们拿到的讨论单。",
]

SETTINGS = [
    ("baseline beam=4", dict(beam_size=4)),
    ("beam=2", dict(beam_size=2)),
    ("no_repeat_ngram=3", dict(beam_size=4, no_repeat_ngram_size=3)),
    ("repetition_penalty=1.3", dict(beam_size=4, repetition_penalty=1.3)),
    ("coverage_penalty=1.0", dict(beam_size=4, coverage_penalty=1.0)),
    ("no_repeat+reppen", dict(beam_size=4, no_repeat_ngram_size=3,
                              repetition_penalty=1.2)),
    ("patience=1 lenpen=0.6", dict(beam_size=4, patience=1.0,
                                   length_penalty=0.6)),
]


def main() -> None:
    sp = spm.SentencePieceProcessor()
    sp.load(str(D / "source.spm"))
    tp = spm.SentencePieceProcessor()
    tp.load(str(D / "target.spm"))
    tr = ctranslate2.Translator(str(D), device="cpu", compute_type="int8",
                                inter_threads=1, intra_threads=4)
    batch = [sp.encode(t, out_type=str) for t in TESTS]
    for label, kw in SETTINGS:
        r = tr.translate_batch(batch, max_decoding_length=256, **kw)
        print(f"\n### {label}")
        for t, res in zip(TESTS, r):
            out = tp.decode(res.hypotheses[0])
            print(f"  {out}")


if __name__ == "__main__":
    main()
