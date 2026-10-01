# 翻译功能：模型选型、踩坑与验证记录

## 结论

1.5.0 提供中文 → 英文、中文 → 日文，全部离线运行。

| 目标 | 模型 | 架构 | int8 体积 | 授权 | 速度 |
|---|---|---|---|---|---|
| 英文 | `Helsinki-NLP/opus-mt-zh-en` | Marian | 82.5 MB | CC-BY-4.0 | 41 ms/句 |
| 日文 | `facebook/m2m100_418M` | M2M100 | 496 MB | **CC-BY-NC-4.0** | 244 ms/句 |

运行时是 CTranslate2 4.8.2（MIT，macOS arm64 1.3 MB / Windows 19 MB），
不需要 PyTorch。

## 那个把人绕进去的 bug：源句末尾的 `</s>`

**症状**：译文首句正确，之后重启改写，然后复读到长度上限。`</s>` 从未出现。

这个症状和「int8 量化坏了」「转换器有 bug」几乎一模一样，我据此先后排除了
十来条假设，其中大部分是真的（也确实排除了），但**归因完全错了**。

真正的修复是一行：

```python
tokens = sp.encode(text, out_type=str) + ["</s>"]
```

HuggingFace 的 `MarianTokenizer` 和 M2M100 的 tokenizer 都会在源句末尾补一个
结束标记，而 CTranslate2 对这两种架构的 `add_source_eos` 都是 `false`，不会补。
少了它，解码器不知道源句在哪儿结束，于是把「该收尾了」理解成「继续说」。

补上之后：

| | 修复前 | 修复后 |
|---|---|---|
| `今天的会议改到明天下午三点钟，请通知一下所有参加的人。` | `Today's meeting has been rescheduled to 3 p.m. tomorrow…` | `The meeting has been moved to 3 p.m. tomorrow.` |
| 6 句耗时 | 1.86 s（跑满长度上限） | 0.14 s |

M2M100 同理，补 `</s>` 前输出是 `この一一一一一一一一…`，
补上后是 `この装置の保証期間は2年です。`

**教训**：这个 bug 的正确修法是去读参考实现的输入构造，而不是逐个排除
「转换器是不是坏了」。一开始就该把 transformers 的 tokenize 结果和自己的
逐位对比（`tools/` 里那段对照代码），那会直接指向少了一个 token。

## 曾经被误判的「CTranslate2 有缺陷」

我一度认定 CTranslate2 的 Marian 推理实现有 cross-attention 对齐缺陷，理由是
它输出退化。逐张量比对其实已经证明了转换无损：

`tools/mt_weight_diff.py` 把 CT2 spec 里的每个张量和 transformers 载入的权重
逐位对比，**全部 maxdiff = 0.000000**：词嵌入、输出投影、`final_logits_bias`、
编码器/解码器位置嵌入、QKV 三段融合顺序、`out_proj`。

也就是说转换是数值无损的，错的从来是我的输入。

## 为什么日文不用 OPUS-MT

1. OPUS-MT 官方没有简中↔日的语言对。
2. 唯一的中日检查点 `Helsinki-NLP/opus-mt-tc-big-zh-ja` 发布的词表里**没有中文**。
   用 HuggingFace 自己的 tokenizer 喂中文，14 个 token 里有 6 个变成 `<unk>`：

   ```
   输入: 今天的會議改到明天下午三點。
   token: ['▁','<unk>','<unk>',',','誰','能','<unk>','<unk>','<unk>','的','解','<unk>','?','</s>']
   缺失: 无
   ```
3. 中转 zh→en→ja 实测不可用。`opus-mt-en-jap` 是文学/论述语料：

   ```
   Please make three copies of this material.
     → 弟子たちは互に語り合うべきである.        ← 弟子＝门徒
   The meeting has been moved to 3 p.m. tomorrow.
     → わたしたちは,次の日に,休んでいることを学んでいる.
   ```

所以改用 M2M100-418M 直译。**代价是授权 CC-BY-NC，禁止商用**——给学校用没问题，
要放进任何商业产品前先确认。

## 质量实测（中→日）

```
这批设备的保修期是两年，过期之后需要重新购买。      → この装置の保証期間は2年です。
今天的会议改到明天下午三点钟，请通知一下所有参加的人。 → 今日の会議は明日の午後3時まで変更。
因为前面那条路正在维修，公交车今天临时改道绕行。 → 前面の道が修理されているため、バスは今日は一時的に周りを変えています。
你觉得这个价格合理吗？如果不合适可以再商量。            → この結論は正しいと思いますか?なぜ?
```

**能读懂，但弱于英文**：会出现实错（`面積`→`表面公式`、`翻到`→`翻訳`），
句式偏书面。界面和 README 都注明了「建议人工复核」。

英文方向质量好得多，6 句探针全对。

## M2M100 转换时踩到的第二个坑

CT2 报 `Source vocabulary 0 has size 128012 but the model expected a vocabulary of
size 128112`。原因：tokenizer 上有个过时的 `num_madeup_words = 8` 属性，
CT2 据此只补了 8 项，而缺的 100 项是语言码（id 128004..128103），这一版的
`get_vocab()` 里没有。

修法是按模型真实的 `vocab_size` 重建词表，保证每个下标和检查点的嵌入矩阵对齐
（`tools/prepare_mt_models.py::_patch_m2m100_vocabulary`）。语言码的具体字符串
在转换时解析好写进 `langs.json`，运行时就完全不需要 transformers。

## 质量闸门

`tools/prepare_mt_models.py` 转换完立刻用内置探针句跑一遍，检查复读率
（唯一词比例 < 0.55）和长度失控（译文 > 4× 原文），不通过就**拒绝打包**。
这个闸门在开发过程中真的拦下过一个退化模型——就是 `</s>` 那个 bug 存在时的
产物。如果当时没有它，那份「能下载、能加载、但输出是垃圾」的模型就发出去��。

## 复现

```bash
python tools/prepare_mt_models.py --quant int8 --force   # 下载 + 转换 + 质量闸门 + 打包
python tools/gui_translate_smoke.py                      # GUI 冒烟（无显示环境可跑）
python -m pytest -q                                      # 含译文对齐的回归测试
```

排查过程用的对照脚本（`mt_weight_diff.py` 等）保留在仓库里，作为
「转换无损」这个结论的证据。
