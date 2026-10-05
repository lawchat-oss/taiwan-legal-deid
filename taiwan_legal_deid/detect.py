"""推論：文件 → 要遮的人名位置。程式找候選（刻意多抓）→ 模型對每個候選給三個選項的機率 → 程式依門檻選出不重疊的切法。
判斷全部來自模型；這裡沒有任何「是不是人名」的規則，只有門檻與重疊時取機率高者。
"""
from __future__ import annotations

import json, os

import mlx.core as mx
import numpy as np
from transformers import BertTokenizerFast

from .decode import decode, extend_long
from .examples import collate, doc_windows
from .labels import PERSON_KINDS
from .model import KINDS, SpanModel


class Detector:
    def __init__(self, run_dir: str, tau: float = 0.5):
        cfg = json.load(open(os.path.join(run_dir, "config.json")))
        self.tok = BertTokenizerFast.from_pretrained(cfg["base_dir"], **({"do_lower_case": True} if cfg.get("lower") else {}))
        self.model = SpanModel(cfg)
        self.model.load_weights(os.path.join(run_dir, "model.safetensors"))
        self.model.eval()
        mx.eval(self.model.parameters())
        self.tau = tau
        self.pii = cfg.get("n_kinds", 6) > len(PERSON_KINDS)  # 舊模型只認得人名候選
        self.org = cfg.get("n_kinds", 6) > KINDS.index("org")  # v8 起才認得機構候選

    def scores(self, text: str):
        """回傳 [(start, end, kind, pMASK, pKEEP, pNOT)]"""
        ws = doc_windows({"id": "q", "text": text, "spans": [], "src": "infer"}, self.tok, None, train=False, pii=self.pii, org=self.org)
        out = []
        for i in range(0, len(ws), 32):
            b = ws[i:i + 32]
            ids, attn, cs, ce, ck, _ = collate(b)
            p = mx.softmax(self.model(mx.array(ids), mx.array(attn), mx.array(cs), mx.array(ce), mx.array(ck)), axis=-1)
            p = np.array(p)
            for bi, w in enumerate(b):
                for j, c in enumerate(w["cands"]):
                    out.append((c[4], c[5], KINDS[c[2]], *map(float, p[bi, j])))
        return out

    def detect(self, text: str):
        return extend_long(text, decode(self.scores(text), len(text), self.tau))
