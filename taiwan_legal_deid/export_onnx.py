"""MLX 訓練好的權重 → PyTorch（只用來匯出）→ ONNX，給 CPU 推論（onnxruntime）；--int8 另出動態量化版。
用法：.venv-export/bin/python -m taiwan_legal_deid.export_onnx runs/v0 [--int8]
"""
from __future__ import annotations

import json, os, sys

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from safetensors.numpy import load_file
from transformers import BertConfig, BertModel


class TorchSpan(nn.Module):
    """與 taiwan_legal_deid.model.SpanModel 同一結構（權重名不同，load_mlx 對應）。"""

    def __init__(self, cfg):
        super().__init__()
        bc = BertConfig(**{k: cfg[k] for k in ("vocab_size", "hidden_size", "num_hidden_layers", "num_attention_heads",
                                               "intermediate_size", "max_position_embeddings", "type_vocab_size")},
                        layer_norm_eps=1e-12, hidden_act="gelu")
        self.bert = BertModel(bc, add_pooling_layer=False)
        d = cfg["hidden_size"]
        self.kind_emb, self.len_emb = nn.Embedding(cfg.get("n_kinds", 6), 32), nn.Embedding(12, 32)
        self.span_ln = nn.LayerNorm(3 * d + 64, eps=1e-12)
        self.fc1, self.fc2 = nn.Linear(3 * d + 64, d), nn.Linear(d, 3)

    def forward(self, ids, attn, cs, ce, ck):
        h = self.bert(input_ids=ids, attention_mask=attn).last_hidden_state
        B, L, D = h.shape
        cum = torch.cat([torch.zeros(B, 1, D, dtype=h.dtype), torch.cumsum(h, 1)], 1)
        cs, ce = cs.clamp(0, L - 1), ce.clamp(1, L)
        g = lambda t, idx: torch.gather(t, 1, idx.unsqueeze(-1).expand(-1, -1, t.shape[-1]))
        n = (ce - cs).clamp(min=1).unsqueeze(-1).to(h.dtype)
        rep = torch.cat([g(h, cs), g(h, ce - 1), (g(cum, ce) - g(cum, cs)) / n, self.kind_emb(ck),
                         self.len_emb((ce - cs).clamp(max=11))], -1)
        return self.fc2(F.gelu(self.fc1(self.span_ln(rep))))


def load_mlx(m: TorchSpan, path: str, n_layers: int):
    w = load_file(path)
    pairs = {"word.weight": "bert.embeddings.word_embeddings.weight", "position.weight": "bert.embeddings.position_embeddings.weight",
             "token_type.weight": "bert.embeddings.token_type_embeddings.weight",
             "emb_ln.weight": "bert.embeddings.LayerNorm.weight", "emb_ln.bias": "bert.embeddings.LayerNorm.bias"}
    for i in range(n_layers):
        for mine, theirs in (("query", "attention.self.query"), ("key", "attention.self.key"), ("value", "attention.self.value"),
                             ("attn_out", "attention.output.dense"), ("ln1", "attention.output.LayerNorm"),
                             ("up", "intermediate.dense"), ("down", "output.dense"), ("ln2", "output.LayerNorm")):
            for t in ("weight", "bias"):
                pairs[f"layers.{i}.{mine}.{t}"] = f"bert.encoder.layer.{i}.{theirs}.{t}"
    for k in ("kind_emb.weight", "len_emb.weight", "span_ln.weight", "span_ln.bias", "fc1.weight", "fc1.bias", "fc2.weight", "fc2.bias"):
        pairs[k] = k
    sd = {theirs: torch.from_numpy(np.ascontiguousarray(w[mine]).astype(np.float32)) for mine, theirs in pairs.items()}
    missing, unexpected = m.load_state_dict(sd, strict=False)
    missing = [k for k in missing if "position_ids" not in k]
    assert not missing and not unexpected, (missing[:5], unexpected[:5])
    return m


def main():
    run = sys.argv[1]
    cfg = json.load(open(os.path.join(run, "config.json")))
    m = load_mlx(TorchSpan(cfg), os.path.join(run, "model.safetensors"), cfg["num_hidden_layers"]).eval()
    B, L, K = 2, 64, 16
    ex = (torch.ones(B, L, dtype=torch.int64) * 100, torch.ones(B, L, dtype=torch.int64), torch.zeros(B, K, dtype=torch.int64),
          torch.ones(B, K, dtype=torch.int64), torch.zeros(B, K, dtype=torch.int64))
    out = os.path.join(run, "model.onnx")
    dyn = {"ids": {0: "B", 1: "L"}, "attn": {0: "B", 1: "L"}, "cs": {0: "B", 1: "K"}, "ce": {0: "B", 1: "K"}, "ck": {0: "B", 1: "K"},
           "logits": {0: "B", 1: "K"}}
    torch.onnx.export(m, ex, out, input_names=["ids", "attn", "cs", "ce", "ck"], output_names=["logits"], dynamic_axes=dyn,
                      opset_version=17, dynamo=False)
    print("ONNX →", out, f"{os.path.getsize(out) / 1e6:.0f} MB")
    if "--int8" in sys.argv:
        from onnxruntime.quantization import QuantType, quantize_dynamic
        q = os.path.join(run, "model.int8.onnx")
        quantize_dynamic(out, q, weight_type=QuantType.QInt8)
        print("int8 →", q, f"{os.path.getsize(q) / 1e6:.0f} MB")


if __name__ == "__main__":
    main()
