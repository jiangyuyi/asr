"""最小验证：ONNX Runtime 能否复现 transformers 的翻译质量。

只做一件事：把 opus-mt-zh-en 导出成 encoder / decoder 两个 ONNX 图，动态 int8
量化，然后在 onnxruntime 里手写贪心解码，和 transformers 的输出逐句对比。
跑通了方向就成立；跑不通就立刻停，不往下做。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import torch

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / ".mt-cache" / "opus-mt-zh-en"
OUT = ROOT / "build_onnx"

TESTS = [
    "今天的会议改到明天下午三点钟，请通知一下所有参加的人。",
    "你觉得这个价格合理吗？如果不合适可以再商量。",
    "因为前面那条路正在维修，公交车今天临时改道绕行。",
    "这批设备的保修期是两年，过期之后需要重新购买。",
    "大家一起讨论啊。",
]

EOS_ID = 0          # </s>，本检查点里 id 0
START_ID = 65000    # Marian 从 pad 起手；它的嵌入恰好是零向量，不能用 </s> 代替
NEG = np.float32(-1e9)


class DecoderForOnnx(torch.nn.Module):
    """decoder + lm_head + final_logits_bias 合成一个图。

    bias 必须进图：它把非 EOS token 的 logit 压到 -4.3 附近而给 </s> 加 +6.4，
    丢了这个模型永远不会停下来。
    """

    def __init__(self, model):
        super().__init__()
        self.decoder = model.model.decoder
        self.lm_head = model.lm_head
        self.register_buffer("bias", model.final_logits_bias.reshape(-1))

    def forward(self, input_ids, encoder_hidden_states, encoder_attention_mask,
                self_attn_mask):
        out = self.decoder(
            input_ids=input_ids,
            encoder_hidden_states=encoder_hidden_states,
            encoder_attention_mask=encoder_attention_mask,
            attention_mask=self_attn_mask,
            use_cache=False,
        )
        return self.lm_head(out.last_hidden_state) + self.bias


def build(int8: bool = True) -> tuple[Path, Path]:
    from onnxruntime.quantization import QuantType, quantize_dynamic
    from transformers import AutoModelForSeq2SeqLM

    OUT.mkdir(parents=True, exist_ok=True)
    model = AutoModelForSeq2SeqLM.from_pretrained(str(SRC))
    model.eval()
    d_model = model.config.d_model

    enc_path, dec_path = OUT / "encoder.onnx", OUT / "decoder.onnx"
    enc_q, dec_q = OUT / "encoder.int8.onnx", OUT / "decoder.int8.onnx"

    ids = torch.tensor([[7, 100, 200, 300, 400]], dtype=torch.long)
    mask = torch.ones_like(ids)
    enc_dyn = {"input_ids": {0: "batch", 1: "src"},
               "attention_mask": {0: "batch", 1: "src"},
               "hidden_states": {0: "batch", 1: "src"}}
    with torch.no_grad():
        torch.onnx.export(
            model.model.encoder, (ids, mask), str(enc_path),
            input_names=["input_ids", "attention_mask"],
            output_names=["hidden_states"], opset_version=17, dynamo=False,
            dynamic_axes=enc_dyn)

        dec = DecoderForOnnx(model)
        dec_dyn = {
            "input_ids": {0: "batch", 1: "tgt"},
            "encoder_hidden_states": {0: "batch", 1: "src"},
            "encoder_attention_mask": {0: "batch", 1: "src"},
            "self_attn_mask": {0: "batch", 2: "tgt", 3: "tgt"},
            "logits": {0: "batch", 1: "tgt"},
        }
        torch.onnx.export(
            dec,
            (torch.tensor([[0, 50, 60]], dtype=torch.long),
             torch.randn(1, 4, d_model),
             torch.ones(1, 4, dtype=torch.long),
             torch.zeros(1, 1, 3, 3)),
            str(dec_path),
            input_names=["input_ids", "encoder_hidden_states",
                         "encoder_attention_mask", "self_attn_mask"],
            output_names=["logits"], opset_version=17, dynamo=False,
            dynamic_axes=dec_dyn)

    if not int8:
        return enc_path, dec_path
    for src, dst in ((enc_path, enc_q), (dec_path, dec_q)):
        quantize_dynamic(str(src), str(dst), weight_type=QuantType.QInt8)
    return enc_q, dec_q


def vocab() -> list[str]:
    """vocab.json is a token -> id dict; the model is indexed by id."""
    mapping: dict[str, int] = json.loads(
        (SRC / "vocab.json").read_text(encoding="utf-8"))
    tokens = [""] * (max(mapping.values()) + 1)
    for tok, i in mapping.items():
        tokens[i] = tok
    return tokens


def run_ort(enc_path: Path, dec_path: Path, texts: list[str]) -> list[str]:
    import onnxruntime as ort
    import sentencepiece as spm

    tokens = vocab()
    sp = spm.SentencePieceProcessor()
    sp.load(str(SRC / "source.spm"))
    # 译文的 ▁ 是英文分词器的词边界标记，必须用 target.spm 还原成空格
    tp = spm.SentencePieceProcessor()
    tp.load(str(SRC / "target.spm"))

    so = ort.SessionOptions()
    so.intra_op_num_threads = 4
    so.inter_op_num_threads = 1
    enc = ort.InferenceSession(str(enc_path), so,
                               providers=["CPUExecutionProvider"])
    dec = ort.InferenceSession(str(dec_path), so,
                               providers=["CPUExecutionProvider"])

    results, t0 = [], time.time()
    for text in texts:
        ids = [tokens.index(p) for p in sp.encode(text, out_type=str)]
        x = np.array([ids], dtype=np.int64)
        h = enc.run(["hidden_states"],
                    {"input_ids": x, "attention_mask": np.ones_like(x)})[0]
        ecm = np.ones((1, x.shape[1]), dtype=np.int64)
        seq = [START_ID]
        for _ in range(200):
            L = len(seq)
            causal = np.triu(np.full((L, L), NEG, np.float32), 1)[None, None]
            logits = dec.run(["logits"], {
                "input_ids": np.array([seq], np.int64),
                "encoder_hidden_states": h.astype(np.float32),
                "encoder_attention_mask": ecm,
                "self_attn_mask": causal,
            })[0]
            nxt = int(np.argmax(logits[0, -1]))
            if nxt == EOS_ID or nxt == START_ID:
                break
            seq.append(nxt)
        results.append(tp.decode([tokens[i] for i in seq[1:]]))
    print(f"  {time.time()-t0:.2f}s / {len(texts)} 句 "
          f"= {(time.time()-t0)/len(texts)*1000:.0f} ms/句")
    return results


def run_hf(texts: list[str]) -> list[str]:
    from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
    tk = AutoTokenizer.from_pretrained(str(SRC))
    m = AutoModelForSeq2SeqLM.from_pretrained(str(SRC))
    m.eval()
    enc = tk(texts, return_tensors="pt", padding=True)
    with torch.no_grad():
        out = m.generate(**enc, num_beams=4, max_length=96)
    return [tk.decode(o, skip_special_tokens=True) for o in out]


def run_hf_manual(texts: list[str]) -> list[str]:
    """Same greedy loop, but in torch. If torch and ORT disagree, the export
    is wrong. If they agree and both are bad, the input setup is wrong."""
    from transformers import AutoModelForSeq2SeqLM
    m = AutoModelForSeq2SeqLM.from_pretrained(str(SRC))
    m.eval()
    import sentencepiece as spm
    tokens = vocab()
    sp = spm.SentencePieceProcessor()
    sp.load(str(SRC / "source.spm"))
    tp = spm.SentencePieceProcessor()
    tp.load(str(SRC / "target.spm"))
    out = []
    with torch.no_grad():
        for text in texts:
            ids = [tokens.index(p) for p in sp.encode(text, out_type=str)]
            x = torch.tensor([ids], dtype=torch.long)
            h = m.model.encoder(input_ids=x, attention_mask=torch.ones_like(x)).last_hidden_state
            seq = [START_ID]
            for _ in range(200):
                L = len(seq)
                ids_t = torch.tensor([seq], dtype=torch.long)
                mask = torch.full((1, 1, L, L), -1e9)
                mask = torch.triu(mask, 1)
                lg = m.model.decoder(
                    input_ids=ids_t,
                    encoder_hidden_states=h,
                    encoder_attention_mask=torch.ones(1, x.shape[1], dtype=torch.long),
                    attention_mask=mask,
                    use_cache=False,
                ).last_hidden_state
                logits = m.lm_head(lg[0, -1]) + m.final_logits_bias.reshape(-1)
                logits[START_ID] = -1e9
                nxt = int(logits.argmax())
                if nxt == EOS_ID:
                    break
                seq.append(nxt)
            out.append(tp.decode([tokens[i] for i in seq[1:]]))
    return out


if __name__ == "__main__":
    int8 = "--fp32" not in sys.argv
    print(f"=== 导出（{'int8' if int8 else 'fp32'}）===")
    t0 = time.time()
    enc_p, dec_p = build(int8=int8)
    print(f"   encoder {(enc_p.stat().st_size)/1e6:.1f} MB  "
          f"decoder {(dec_p.stat().st_size)/1e6:.1f} MB  "
          f"（{time.time()-t0:.1f}s）")

    print("\n=== transformers 基准 ===")
    for a in run_hf(TESTS):
        print("  ", a)

    print("\n=== onnxruntime int8 贪心 ===")
    got = run_ort(enc_p, dec_p, TESTS)
    for a in got:
        print("  ", a)

    print("\n=== torch 手写贪心（同样的输入 / 掩码 / 起始 token）===")
    for a in run_hf_manual(TESTS):
        print("  ", a)
