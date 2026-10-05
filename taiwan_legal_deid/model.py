"""MLX 判斷模型：BERT 編碼器（依底模 config 建構）＋候選判斷頭。
一個視窗只跑一次編碼器，視窗裡所有候選同時判斷（同一份編碼、多題一次回答）。
每個候選的表示＝[起點, 終點, 整段平均, 來源類型, 長度] → 三個選項的機率：要遮（私人）／保留（執行職務、公眾人物）／不是人名。
混合精度：權重 fp32、運算 bf16（實測 BERT 微調同速度、更新不會被 bf16 吃掉）。
"""
from __future__ import annotations

import json, math, os

import mlx.core as mx
import mlx.nn as nn
from safetensors import safe_open

COMPUTE = mx.bfloat16
from .labels import KINDS, LABELS  # noqa: F401


class Linear(nn.Linear):
    def __call__(self, x):
        return x.astype(COMPUTE) @ self.weight.astype(COMPUTE).T + self.bias.astype(COMPUTE)


class LayerNorm(nn.Module):
    def __init__(self, d, eps=1e-12):
        super().__init__()
        self.weight, self.bias, self.eps = mx.ones((d,)), mx.zeros((d,)), eps

    def __call__(self, x):
        return mx.fast.layer_norm(x.astype(mx.float32), self.weight, self.bias, self.eps).astype(COMPUTE)


class Block(nn.Module):
    def __init__(self, d, h, ff, p):
        super().__init__()
        self.h = h
        self.query, self.key, self.value, self.attn_out = Linear(d, d), Linear(d, d), Linear(d, d), Linear(d, d)
        self.ln1, self.up, self.down, self.ln2 = LayerNorm(d), Linear(d, ff), Linear(ff, d), LayerNorm(d)
        self.drop = nn.Dropout(p)

    def __call__(self, x, mask):
        B, L, D = x.shape
        split = lambda t: t.reshape(B, L, self.h, -1).transpose(0, 2, 1, 3)
        a = mx.fast.scaled_dot_product_attention(split(self.query(x)), split(self.key(x)), split(self.value(x)),
                                                 scale=1 / math.sqrt(D // self.h), mask=mask)
        x = self.ln1(x + self.drop(self.attn_out(a.transpose(0, 2, 1, 3).reshape(B, L, D))))
        return self.ln2(x + self.drop(self.down(nn.gelu(self.up(x)))))


class SpanModel(nn.Module):
    def __init__(self, cfg: dict, p: float = 0.1):
        super().__init__()
        d = cfg["hidden_size"]
        self.cfg = cfg
        self.word, self.position = nn.Embedding(cfg["vocab_size"], d), nn.Embedding(cfg["max_position_embeddings"], d)
        self.token_type = nn.Embedding(cfg.get("type_vocab_size", 2), d)
        self.emb_ln, self.drop = LayerNorm(d), nn.Dropout(p)
        self.layers = [Block(d, cfg["num_attention_heads"], cfg["intermediate_size"], p) for _ in range(cfg["num_hidden_layers"])]
        self.kind_emb, self.len_emb = nn.Embedding(cfg.get("n_kinds", 6), 32), nn.Embedding(12, 32)  # 舊 run 沒有 n_kinds＝6 種
        self.span_ln = LayerNorm(3 * d + 64)
        self.fc1, self.fc2 = Linear(3 * d + 64, d), Linear(d, len(LABELS))

    def encode(self, ids, attn):
        """回傳每一層的輸出（最後一個＝給判斷頭用的）。"""
        B, L = ids.shape
        x = self.word(ids) + self.position(mx.arange(L))[None] + self.token_type.weight[0]
        x = self.drop(self.emb_ln(x))
        mask = ((1 - attn[:, None, None, :]).astype(COMPUTE) * -1e4)
        hs = []
        for blk in self.layers:
            x = blk(x, mask)
            hs.append(x)
        return hs

    def __call__(self, ids, attn, cs, ce, ck, hidden=False):
        """cs／ce：候選的 token 起訖（ce 不含），(B, K)；ck：來源類型。回傳 (B, K, 3) logits（float32）；hidden＝另回各層輸出（蒸餾用）。"""
        hs = self.encode(ids, attn)
        h = hs[-1].astype(mx.float32)
        B, L, D = h.shape
        cum = mx.concatenate([mx.zeros((B, 1, D)), mx.cumsum(h, axis=1)], axis=1)  # 前綴和算整段平均
        g = lambda t, idx: mx.take_along_axis(t, mx.broadcast_to(idx[:, :, None], (*idx.shape, t.shape[-1])), axis=1)
        cs, ce = mx.clip(cs, 0, L - 1), mx.clip(ce, 1, L)
        n = mx.maximum(ce - cs, 1)[:, :, None].astype(mx.float32)
        rep = mx.concatenate([g(h, cs), g(h, ce - 1), (g(cum, ce) - g(cum, cs)) / n,
                              self.kind_emb(ck), self.len_emb(mx.minimum(ce - cs, 11))], axis=-1)
        logits = self.fc2(nn.gelu(self.fc1(self.span_ln(rep)))).astype(mx.float32)
        return (logits, hs) if hidden else logits


def load_base(model: SpanModel, base_dir: str, src_layers: list[int] | None = None) -> SpanModel:
    """載入 HF BERT 權重（bert.* 前綴、LayerNorm 的 gamma/beta 或 weight/bias 都可）；判斷頭隨機初始化。
    src_layers：第 i 層取底模的第 src_layers[i] 層（切小模型用）；不給＝依序。"""
    f = safe_open(os.path.join(base_dir, "model.safetensors"), "np")
    keys = set(f.keys())

    def g(k):
        for cand in (k, "bert." + k, k.replace(".weight", ".gamma").replace(".bias", ".beta"),
                     "bert." + k.replace(".weight", ".gamma").replace(".bias", ".beta")):
            if cand in keys:
                return mx.array(f.get_tensor(cand))
        raise KeyError(k)

    w = [("word.weight", g("embeddings.word_embeddings.weight")), ("position.weight", g("embeddings.position_embeddings.weight")),
         ("token_type.weight", g("embeddings.token_type_embeddings.weight")),
         ("emb_ln.weight", g("embeddings.LayerNorm.weight")), ("emb_ln.bias", g("embeddings.LayerNorm.bias"))]
    for i in range(len(model.layers)):
        hf = f"encoder.layer.{src_layers[i] if src_layers else i}."
        for mine, theirs in (("query", "attention.self.query"), ("key", "attention.self.key"), ("value", "attention.self.value"),
                             ("attn_out", "attention.output.dense"), ("ln1", "attention.output.LayerNorm"),
                             ("up", "intermediate.dense"), ("down", "output.dense"), ("ln2", "output.LayerNorm")):
            for t in ("weight", "bias"):
                w.append((f"layers.{i}.{mine}.{t}", g(f"{hf}{theirs}.{t}")))
    model.load_weights(w, strict=False)
    return model


def base_config(base_dir: str) -> dict:
    return json.load(open(os.path.join(base_dir, "config.json")))
