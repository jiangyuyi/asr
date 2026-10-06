"""量化没问题，但解码会复读。逐个试解码侧的对策。"""
from __future__ import annotations

from pathlib import Path

import ctranslate2
import sentencepiece as spm

ROOT = Path(__file__).resolve().parent.parent
D = ROOT / "build_mt" / "mt-zh-en-int8"

TESTS = [
    "今天的会议改到明天下午三点钟，请通知一下所有参加的人。",
    "请把这份材料复印三份，其中一份留给我自己用。",
    "因为前面那条路正在维修，公交车今天临时改道绕行。",
    "你觉得这个价格合理吗？如果不合适可以再商量。",
    "好的，我稍后把详细的情况整理好发给你。",
    "这批设备的保修期是两年，过期之后需要重新购买。",
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
