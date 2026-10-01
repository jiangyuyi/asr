"""逐张量对比 CTranslate2 spec 与 transformers 载入的权重。

转换器和模型加载都是确定的，所以差异一定出现在「权重搬到 spec」这一步。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import torch
from ctranslate2.converters import TransformersConverter
from ctranslate2.converters import transformers as ct2tf

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / ".mt-cache" / "opus-mt-zh-en"


def arr(x):
    if x is None:
        return None
    if hasattr(x, "detach"):
        x = x.detach().cpu().numpy()
    a = np.asarray(x, dtype=np.float32)
    return a.reshape(a.shape[-1]) if a.ndim == 2 and a.shape[0] == 1 else a


def cmp(label, spec_val, hf_val):
    a, b = arr(spec_val), arr(hf_val)
    if a is None or b is None:
        print(f"  {label:44s} spec={'None' if a is None else a.shape}  "
              f"hf={'None' if b is None else b.shape}")
        return
    # CT2 drops the trailing <pad> row, so a 65000-row spec tensor is expected
    # to match the first 65000 rows of the 65001-row checkpoint tensor.
    note = ""
    if a.shape != b.shape:
        if a.ndim == b.ndim:
            n = tuple(min(x, y) for x, y in zip(a.shape, b.shape))
            a = a[tuple(slice(0, y) for y in n)]
            b = b[tuple(slice(0, y) for y in n)]
            note = f" (按 {n} 对齐)"
        else:
            print(f"  {label:44s} !! 形状不同 spec={a.shape} hf={b.shape}")
            return
    d = np.abs(a - b)
    print(f"  {label:44s} {str(a.shape):18s} maxdiff={d.max():.6f}  "
          f"meandiff={d.mean():.6f}{note}")


def main() -> None:
    import transformers
    from transformers import AutoModelForSeq2SeqLM
    print("transformers", transformers.__version__)

    conv = TransformersConverter(str(SRC), copy_files=[])
    spec = conv._load()
    m = AutoModelForSeq2SeqLM.from_pretrained(str(SRC))
    m.eval()

    print("\n--- 词嵌入 / 输出投影 ---")
    cmp("encoder.embed_tokens", spec.encoder.embeddings[0].weight,
        m.model.encoder.embed_tokens.weight)
    cmp("decoder.embed_tokens", spec.decoder.embeddings.weight,
        m.model.decoder.embed_tokens.weight)
    cmp("decoder.projection (lm_head)", spec.decoder.projection.weight,
        m.lm_head.weight)
    cmp("decoder.projection.bias (logits_bias)",
        spec.decoder.projection.bias, m.final_logits_bias)

    print("\n--- 位置嵌入 ---")
    import numpy as _np
    for name, spec_pe, hf_mod in (
        ("encoder.embed_positions", spec.encoder.position_encodings,
         m.model.encoder.embed_positions),
        ("decoder.embed_positions", spec.decoder.position_encodings,
         m.model.decoder.embed_positions),
    ):
        hf_pe = getattr(hf_mod, "weight", None)
        if hf_pe is None and hasattr(hf_mod, "weights"):
            hf_pe = torch.tensor(_np.asarray(hf_mod.weights()))
        sp_pe = getattr(spec_pe, "weight", None)
        if sp_pe is None:
            for attr in ("encodings", "variables"):
                v = getattr(spec_pe, attr, None)
                if v is not None:
                    sp_pe = getattr(v, "weight", v)
                    break
        cmp(name, sp_pe, hf_pe)

    print("\n--- 第 0 层注意力 / FFN ---")
    el, dl = m.model.encoder.layers[0], m.model.decoder.layers[0]
    sa_e = spec.encoder.layer[0].self_attention
    sa_d = spec.decoder.layer[0].self_attention
    print("  MultiHeadAttentionSpec 属性:",
          [a for a in dir(sa_e) if not a.startswith("_")])
    print("  attention.linear.weight shape:", arr(sa_e.linear.weight).shape)
    print("  attention.queries_scale:", getattr(sa_e, "queries_scale", None))
    cmp("enc.self_attn.linear (vs q_proj)", sa_e.linear.weight, el.self_attn.q_proj.weight)
    cmp("dec.self_attn.linear (vs q_proj)", sa_d.linear.weight, dl.self_attn.q_proj.weight)
    cmp("enc.self_attn_layer_norm", sa_e.layer_norm.weight, el.self_attn_layer_norm.weight)
    cmp("dec.self_attn_layer_norm", sa_d.layer_norm.weight, dl.self_attn_layer_norm.weight)
    cmp("enc.fc1", spec.encoder.layer[0].ffn.linear_0.weight, el.fc1.weight)
    cmp("enc.fc2", spec.encoder.layer[0].ffn.linear_1.weight, el.fc2.weight)
    cmp("enc.ffn_layer_norm", spec.encoder.layer[0].ffn.layer_norm.weight, el.final_layer_norm.weight)
    cmp("dec.fc1", spec.decoder.layer[0].ffn.linear_0.weight, dl.fc1.weight)
    cmp("dec.fc2", spec.decoder.layer[0].ffn.linear_1.weight, dl.fc2.weight)
    cmp("dec.ffn_layer_norm", spec.decoder.layer[0].ffn.layer_norm.weight, dl.final_layer_norm.weight)

    print("\n--- 顶层 / 嵌入层归一化 ---")
    cmp("encoder.embed_scale", spec.encoder.embeddings[1] if len(spec.encoder.embeddings) > 1 else None, None)
    cmp("enc.final_layer_norm", spec.encoder.layer_norm.weight,
        getattr(m.model.encoder, "final_layer_norm", None))


if __name__ == "__main__":
    main()
