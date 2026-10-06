"""文件 → 訓練／推論用的視窗：每個視窗一份 token 序列＋視窗內所有候選（token 起訖、來源類型、標籤）。
標籤：0 要遮、1 保留（日期＝個人行程日期）、2 不是、-1 不知道（不計 loss）。候選分兩組：人名、其他個資。
- 候選和同一組的標註逐字相同 → 該標籤；碰到任何標註但切法或組別不同 → 不是（錯的切法、Email 裡的英文名）。
- 文件的 annot 列出完整標註了哪幾組：那幾組其餘候選 → 不是；沒標的組 → 不知道。
  舊合成語料與擴增只標人名（裡面的電話、地址沒標，不能當「不是」）；判決兩組都只標一部分（名冊、法院已遮的個資），
  人名另外用跨判決高頻常用詞當確定的「不是」。
"""
from __future__ import annotations

import collections

import numpy as np

from .candidates import candidates
from .labels import GROUP, KINDS, LABELS
from .org_candidates import org_candidates
from .pii_candidates import pii_candidates

WIN, OVERLAP = 220, 60  # 字元；中文約一字一 token，留空間給英數字的 wordpiece
MAX_TOK = 256
LID = {l: i for i, l in enumerate(LABELS)}


def windows(text: str, keep=()):
    """切成重疊視窗；每個視窗有一段「核心區」，候選中心落在核心區才算這個視窗的（避免重複）。
    keep：不能從中間切開的長值（網址、Email）。它在重疊區之前就開始、又跨過視窗結尾時，沒有一個視窗裝得下整個值，
    只會剩前後兩段各自被判（換完還留著一截原文）：改在它開頭往後 OVERLAP 字切，下一個視窗就從它開頭開始，最長 WIN 字都裝得下。"""
    if len(text) <= WIN:
        return [(0, len(text), 0, len(text))]
    out, s = [], 0
    while True:
        e = min(len(text), s + WIN)
        if e < len(text):
            e = min([S + OVERLAP for S, E in keep if s < S and S + OVERLAP < e < E and E - S <= WIN] + [e])
        core_s = s if s == 0 else s + OVERLAP // 2
        core_e = e if e == len(text) else e - OVERLAP // 2
        out.append((s, e, core_s, core_e))
        if e == len(text):
            return out
        s = e - OVERLAP


def common_words(min_freq=30) -> set[str]:
    """jieba 詞典（MIT）裡「兩三字、姓氏字開頭、詞性不是人名」的常用詞（高中、高度、周圍、林口）→ 確定不是人名。"""
    import os
    from .candidates import CJK, surname_len
    p = os.path.join(os.path.dirname(__file__), "data", "jieba_dict_big.txt")
    out = set()
    if os.path.exists(p):
        with open(p, encoding="utf-8") as fh:
            for line in fh:
                w, f, pos = (line.split() + ["", "", ""])[:3]
                if 2 <= len(w) <= 3 and all(CJK.match(c) for c in w) and surname_len(w) and not pos.startswith("nr") and int(f or 0) >= min_freq:
                    out.add(w)
    return out


def known_negatives(docs, min_df=20) -> set[str]:
    """跨判決反覆出現、又從不是標註人名的「姓氏字開頭」二三字詞 → 確定不是人名（高度、周圍、曾經…）。"""
    df, named = collections.Counter(), set()
    for d in docs:
        t = d["text"]
        named.update(t[s["start"]:s["end"]] for s in d["spans"])
        df.update({t[s:e] for s, e, k in candidates(t) if k == "full" and e - s <= 3})
    freq = {w for w, c in df.items() if c >= min_df}
    return {w for w in freq | common_words() if w not in named and not any(w in n or n in w for n in named if len(n) >= 2)}


def doc_windows(doc: dict, tok, neg: set[str] | None = None, train: bool = True, pii: bool = True, org: bool = True):
    """pii／org＝False：不列那組候選（舊模型的來源類型沒有那幾種）。機構候選要看全文（字根），整份算一次再分給視窗。"""
    text, spans = doc["text"], doc.get("spans", [])
    annot = set(doc.get("annot", ["person"] if doc.get("src") != "judgment" else []))
    exact = {(s["start"], s["end"], s.get("group", "person")): LID[s["label"]] for s in spans}
    ivs = [(s["start"], s["end"]) for s in spans]
    oc = org_candidates(text) if org else []
    pc = pii_candidates(text) if pii else []  # 全文算一次，只用來決定視窗從哪裡切（長值不切開）；候選照舊逐視窗列
    out = []
    for ws, we, cs_, ce_ in windows(text, [(S, E) for S, E, _ in pc + oc if E - S > OVERLAP]):
        wt = text[ws:we]
        enc = tok(wt, add_special_tokens=True, return_offsets_mapping=True, truncation=True, max_length=MAX_TOK)
        offs = enc["offset_mapping"]
        char2tok = {}
        for ti, (a, b) in enumerate(offs):
            for c in range(a, b):
                char2tok.setdefault(c, ti)
        cands = []
        for s, e, kind in candidates(wt) + (pii_candidates(wt) if pii else []) + [(S - ws, E - ws, k) for S, E, k in oc if ws <= S and E <= we]:
            mid = ws + (s + e) / 2
            if e <= s or not (cs_ <= mid < ce_) or s not in char2tok or (e - 1) not in char2tok:  # 空的、顛倒的候選（MLX 不會報錯，ONNX 會）
                continue
            S, E, g = ws + s, ws + e, GROUP[kind]
            if (S, E, g) in exact:
                lab = exact[(S, E, g)]
            elif g == "org" and g not in annot:  # 沒標機構的文件：碰到人名、地址標註也不代表它不是機構名（王大明律師事務所）
                lab = -1
            elif any(a < E and b > S for a, b in ivs):
                lab = LID["NOT"]
            elif g in annot or (g == "person" and neg and text[S:E] in neg):
                lab = LID["NOT"]
            else:
                lab = -1
            cands.append((char2tok[s], char2tok[e - 1] + 1, KINDS.index(kind), lab, S, E))
        if cands and (not train or any(c[3] >= 0 for c in cands)):
            out.append({"ids": enc["input_ids"], "cands": cands, "doc": doc.get("id"), "ws": ws})
    return out


def collate(batch, L=None, K=None):
    """視窗 → 固定形狀陣列（L 取 128／256 兩級，K 取 16 的倍數），讓 mx.compile 只需少數幾張圖。"""
    L = L or (128 if max(len(b["ids"]) for b in batch) <= 128 else MAX_TOK)
    K = K or max(16, -(-max(len(b["cands"]) for b in batch) // 16) * 16)
    B = len(batch)
    ids, attn = np.zeros((B, L), np.int32), np.zeros((B, L), np.int32)
    cs, ce, ck, lab = (np.zeros((B, K), np.int32) for _ in range(4))
    lab[:] = -1
    for i, b in enumerate(batch):
        ids[i, :len(b["ids"])] = b["ids"]; attn[i, :len(b["ids"])] = 1
        for j, c in enumerate(b["cands"][:K]):
            cs[i, j], ce[i, j], ck[i, j], lab[i, j] = c[0], c[1], c[2], c[3]
        for j in range(len(b["cands"]), K):
            cs[i, j], ce[i, j] = 0, 1
    return ids, attn, cs, ce, ck, lab


if __name__ == "__main__":
    tok = lambda t, **_: {"input_ids": [0] * (len(t) + 2), "offset_mapping": [(0, 0)] + [(i, i + 1) for i in range(len(t))] + [(0, 0)]}  # 一字一 token
    mail = "chen.yuting.lawfirm.contact." + "x" * 30 + "@example-law-office.com.tw"  # 84 字的 Email 剛好跨過第一個視窗的結尾
    text = "甲" * 150 + mail + "。" + "乙" * 200
    S, E = 150, 150 + len(mail)
    ws = windows(text, [(S, E)])
    assert any(a <= S and E <= b for a, b, _, _ in ws), ws
    got = {(c[4], c[5]) for w in doc_windows({"id": "t", "text": text}, tok, train=False) for c in w["cands"]}
    assert (S, E) in got, sorted(got)  # 整個 Email 是一個候選，不是被切開的兩段
    assert windows("丙" * 600) == windows("丙" * 600, [(10, 20)])  # 沒有跨邊界的長值：切法不變
    import random
    rng = random.Random(0)
    for _ in range(300):  # 任意位置、61～220 字的網址：要有一個視窗整個裝得下、中心落在核心區（候選才算這個視窗的）
        L, S = rng.randint(61, WIN), rng.randint(0, 500)
        url = ("https://example-law-office.com.tw/" + "a" * WIN)[:L]
        t = "丁" * S + url + "戊" * 300
        ws = windows(t, [(S, S + L)])
        assert any(a <= S and S + L <= b and cs <= S + L / 2 < ce for a, b, cs, ce in ws), (S, L, ws)
        assert all(b - a <= WIN for a, b, _, _ in ws), ws
    print("視窗自檢 OK：", [(a, b) for a, b, _, _ in ws])
