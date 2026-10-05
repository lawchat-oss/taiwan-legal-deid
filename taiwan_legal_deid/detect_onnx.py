"""CPU 推論（onnxruntime，不需要 MLX 或 PyTorch）。介面與 taiwan_legal_deid.detect.Detector 相同。
用法：Detector().detect(text)（預設 6 層，第一次用時下載）；Detector("3l") 較快；Detector("runs/xxx") 用自己訓練的 run 目錄。
"""
from __future__ import annotations

import json, os

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer
from tokenizers.normalizers import BertNormalizer

from . import weights
from .decode import decode, extend_long
from .examples import MAX_TOK, collate, doc_windows
from .labels import KINDS, PERSON_KINDS

TOKENIZER = os.path.join(os.path.dirname(__file__), "data", "tokenizer.json")  # bert-base-chinese 字表＋轉小寫（跟訓練時逐字一致）


class _Tok:
    """tokenizers 版，呼叫方式跟訓練用的 BertTokenizerFast 一樣（examples.doc_windows 共用）。"""

    def __init__(self, lower: bool):
        self.t = Tokenizer.from_file(TOKENIZER)
        if not lower:  # 舊 run 沒開轉小寫
            self.t.normalizer = BertNormalizer(lowercase=False)
        self.t.enable_truncation(MAX_TOK)

    def __call__(self, text, **_):
        e = self.t.encode(text)
        return {"input_ids": e.ids, "offset_mapping": e.offsets}


class Detector:
    def __init__(self, model: str = "6l", tau: float = 0.5, threads: int = 0, int8: bool = False):
        """model："6l"（預設，較準）、"3l"（較快），或含 config.json 與 model.onnx 的 run 目錄。"""
        if model in weights.MODELS:
            cfg, path = {"n_kinds": weights.N_KINDS, "lower": True}, weights.path(model)
        else:
            cfg = json.load(open(os.path.join(model, "config.json")))
            path = os.path.join(model, "model.int8.onnx" if int8 else "model.onnx")
        self.tok = _Tok(cfg.get("lower", False))
        so = ort.SessionOptions()
        if threads:
            so.intra_op_num_threads = threads
        self.sess = ort.InferenceSession(path, so, providers=["CPUExecutionProvider"])
        self.tau = tau
        self.n_kinds = cfg.get("n_kinds", 6)
        self.pii = self.n_kinds > len(PERSON_KINDS)  # 舊模型只認得人名候選
        self.org = self.n_kinds > KINDS.index("org")  # v8 起才認得機構候選

    def scores(self, text: str):
        ws = doc_windows({"id": "q", "text": text, "spans": [], "src": "infer"}, self.tok, None, train=False, pii=self.pii, org=self.org)
        ws = [w for w in (dict(w, cands=[c for c in w["cands"] if c[2] < self.n_kinds]) for w in ws) if w["cands"]]  # 模型沒學過的候選種類（後來才加的）不送
        out = []
        for i in range(0, len(ws), 16):
            b = ws[i:i + 16]
            ids, attn, cs, ce, ck, _ = collate(b, L=max(len(w["ids"]) for w in b), K=max(len(w["cands"]) for w in b))
            lg = self.sess.run(None, {"ids": ids.astype(np.int64), "attn": attn.astype(np.int64), "cs": cs.astype(np.int64),
                                      "ce": ce.astype(np.int64), "ck": ck.astype(np.int64)})[0]
            p = np.exp(lg - lg.max(-1, keepdims=True)); p /= p.sum(-1, keepdims=True)
            for bi, w in enumerate(b):
                for j, c in enumerate(w["cands"]):
                    out.append((c[4], c[5], KINDS[c[2]], *map(float, p[bi, j])))
        return out

    def detect(self, text: str):
        return extend_long(text, decode(self.scores(text), len(text), self.tau))
