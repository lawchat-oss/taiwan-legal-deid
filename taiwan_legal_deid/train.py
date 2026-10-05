"""訓練候選判斷模型（MLX）。資料：data/train/judg_docs.jsonl（名冊銀標）＋ synth_docs.jsonl（全標註合成）＋ aug_docs.jsonl（弱點擴增）。
dev 依文件切（10%），每個 epoch 印出來看；存最後一輪的權重（學習率排程最後一輪才降到 0。
挑 dev loss 最低會讓 12 層挑到第一輪：錯得較多、把「主治醫師：某某」當成判決書的書記官而判保留）。AdamW 開偏差校正（MLX 預設沒開，BERT 微調會卡）。
用法：python -m taiwan_legal_deid.train --base base/bert-base-chinese --out runs/v0 [--epochs 3]
"""
from __future__ import annotations

import argparse, json, os, random, time, zlib
from functools import partial

import mlx.core as mx
import mlx.nn as nn
import mlx.optimizers as optim
import numpy as np
from transformers import BertTokenizerFast

from .examples import collate, doc_windows, known_negatives
from .model import LABELS, SpanModel, base_config, load_base

ap = argparse.ArgumentParser()
ap.add_argument("--base", default="base/bert-base-chinese")
ap.add_argument("--out", default="runs/v0")
ap.add_argument("--epochs", type=int, default=3)
ap.add_argument("--bs", type=int, default=32)
ap.add_argument("--lr-enc", type=float, default=5e-5)
ap.add_argument("--lr-head", type=float, default=3e-4)
ap.add_argument("--neg-keep", type=float, default=0.3, help="沒有任何人名的視窗只保留這個比例")
ap.add_argument("--seed", type=int, default=1)
ap.add_argument("--judg-keep", type=float, default=0.5, help="判決視窗抽樣比例（判決視窗遠多於其他文類）")
ap.add_argument("--synth-rep", type=int, default=3, help="合成語料重複次數")
ap.add_argument("--data", default="data/train")
ap.add_argument("--layers", default=None, help="學生取哪幾層（例：0,1,2＝前三層）；不給＝全部")
ap.add_argument("--teacher", default=None, help="老師 run 目錄：學生從老師的這幾層起步，並學老師給每個候選的機率（蒸餾）")
ap.add_argument("--T", type=float, default=2.0, help="蒸餾溫度（老師很有把握，調高才看得到它猶豫在哪）")
ap.add_argument("--alpha", type=float, default=0.5, help="蒸餾 loss 的權重，其餘給有標籤的答案")
ap.add_argument("--hid", type=float, default=0.0, help="學生每層模仿老師對應層輸出（MSE）的權重；0＝只學答案")
a = ap.parse_args()
random.seed(a.seed); mx.random.seed(a.seed)
_f = getattr(mx, "set_cache_limit", None) or getattr(getattr(mx, "metal", None), "set_cache_limit", None)
if _f:
    _f(4 << 30)
os.makedirs(a.out, exist_ok=True)
log = open(f"{a.out}/train.log", "a")
say = lambda *x: (print(*x, flush=True), log.write(" ".join(map(str, x)) + "\n"), log.flush())

docs = []
for name in ("judg_docs.jsonl", "synth_docs.jsonl", "synth_pii_docs.jsonl", "synth_org_docs.jsonl", "aug_docs.jsonl", "noisy_docs.jsonl",
             "markdown_docs.jsonl"):
    p = f"{a.data}/{name}"
    if os.path.exists(p):
        docs += [json.loads(l) for l in open(p)]
is_dev = lambda d: zlib.crc32(d["id"].removesuffix("#ocr").removesuffix("#md").encode()) % 10 == 0  # 副本跟原文件同一邊，dev 才不會看過答案
train_docs, dev_docs = [d for d in docs if not is_dev(d)], [d for d in docs if is_dev(d)]
tok = BertTokenizerFast.from_pretrained(a.base, do_lower_case=True)  # 字表只有小寫英文；google bert-base-chinese 的設定沒開轉小寫，大寫英文字會全變 [UNK]
neg = known_negatives([d for d in train_docs if d.get("src") == "judgment"])
json.dump(sorted(neg), open(f"{a.out}/known_negatives.json", "w"), ensure_ascii=False)


def make(ds, keep_neg, train=True):
    out = []
    for d in ds:
        judg = d.get("src") == "judgment"
        rep = a.synth_rep if (train and d.get("src") in ("synth", "synth_pii", "synth_org")) else 1
        for w in doc_windows(d, tok, neg, train=not (a.teacher and train)):  # 蒸餾時沒標籤的視窗也有老師答案可學
            if train and judg and random.random() > a.judg_keep:
                continue
            if any(c[3] in (0, 1) for c in w["cands"]) or random.random() < keep_neg:
                out += [w] * rep
    return out


t0 = time.time()
train_w, dev_w = make(train_docs, a.neg_keep), make(dev_docs, 1.0, train=False)
say(f"文件 train {len(train_docs)}／dev {len(dev_docs)}；視窗 train {len(train_w)}／dev {len(dev_w)}；常用詞負例 {len(neg)}（{time.time() - t0:.0f}s）")
cnt = np.bincount([c[3] for w in train_w for c in w["cands"] if c[3] >= 0], minlength=3)
say("train 候選標籤：", dict(zip(LABELS, cnt.tolist())))

cfg = base_config(a.base)
cfg["base_dir"] = os.path.abspath(a.base)
from .labels import KINDS
cfg["n_kinds"] = len(KINDS)
cfg["lower"] = True  # 推論端照這個開轉小寫（舊 run 沒有這欄＝照底模原設定）
layers = [int(x) for x in a.layers.split(",")] if a.layers else list(range(cfg["num_hidden_layers"]))
cfg["num_hidden_layers"] = len(layers)
cfg["init"] = {"from": os.path.abspath(a.teacher or a.base), "layers": layers}  # 血統紀錄：權重從哪來
json.dump(cfg, open(f"{a.out}/config.json", "w"), ensure_ascii=False, indent=1)
model, teacher = SpanModel(cfg), None
if a.teacher:
    w = mx.load(f"{a.teacher}/model.safetensors")
    pick = {f"layers.{s}.": f"layers.{i}." for i, s in enumerate(layers)}
    pre = lambda k: ".".join(k.split(".")[:2]) + "."
    model.load_weights([(pick[pre(k)] + k[len(pre(k)):] if k.startswith("layers.") else k, v) for k, v in w.items()
                        if not k.startswith("layers.") or pre(k) in pick])  # strict：學生每個參數都要有來源
    tcfg = json.load(open(f"{a.teacher}/config.json"))
    assert tcfg.get("lower"), "老師要用同一種分詞（轉小寫）訓練，否則學生學到的是老師看不懂的輸入"
    teacher = SpanModel(tcfg)
    teacher.load_weights(f"{a.teacher}/model.safetensors")
    teacher.eval()
    N = len(teacher.layers)
    tmap = [round((j + 1) * N / len(layers)) - 1 for j in range(len(layers))]  # 學生第 j 層對老師第 tmap[j] 層（12→3：3、7、11）
    say(f"蒸餾：老師 {a.teacher}，學生取老師第 {layers} 層起步，T={a.T} alpha={a.alpha}" + (f"，各層模仿老師第 {tmap} 層 hid={a.hid}" if a.hid else ""))
else:
    load_base(model, a.base, layers)
mx.eval(model.parameters())


def batches(ws, shuffle=True):
    ws = sorted(ws, key=lambda w: len(w["ids"]))  # 長度相近的放一起，少補齊
    bs = [ws[i:i + a.bs] for i in range(0, len(ws), a.bs)]
    if shuffle:
        random.shuffle(bs)
    return bs


steps = a.epochs * len(batches(train_w))
warm = max(1, int(0.06 * steps))
sched = lambda peak: optim.join_schedules([optim.linear_schedule(0.0, peak, warm), optim.linear_schedule(peak, 0.0, max(1, steps - warm))], [warm])
is_enc = lambda path: path.startswith(("word", "position", "token_type", "emb_ln", "layers"))
opt = optim.MultiOptimizer([optim.AdamW(learning_rate=sched(a.lr_enc), weight_decay=0.01, bias_correction=True),
                            optim.AdamW(learning_rate=sched(a.lr_head), weight_decay=0.01, bias_correction=True)],
                           [lambda path, _: is_enc(path)])


def loss_fn(m, ids, attn, cs, ce, ck, lab, tl=None, *th):
    logits, sh = m(ids, attn, cs, ce, ck, hidden=True)
    valid = lab >= 0
    ce_ = nn.losses.cross_entropy(logits, mx.maximum(lab, 0), label_smoothing=0.05)
    hard = (ce_ * valid).sum() / mx.maximum(valid.sum(), 1)
    if tl is None:
        return hard
    # 蒸餾：每個真候選（含沒標籤的）都學老師的機率。補齊用的假候選 cs＝0；真候選至少從第 1 個 token 起（0 是 [CLS]）
    real = cs > 0
    ls = logits / a.T
    soft = -(mx.softmax(tl / a.T, axis=-1) * (ls - mx.logsumexp(ls, axis=-1, keepdims=True))).sum(-1) * a.T ** 2
    loss = a.alpha * (soft * real).sum() / mx.maximum(real.sum(), 1) + (1 - a.alpha) * hard
    if th:  # 每層輸出模仿老師對應層（只算真 token）
        tok = attn.astype(mx.float32)
        loss = loss + a.hid * sum((((s.astype(mx.float32) - t.astype(mx.float32)) ** 2).mean(-1) * tok).sum()
                                  for s, t in zip(sh, th)) / (len(th) * tok.sum())
    return loss


lg = nn.value_and_grad(model, loss_fn)
state = [model.state, opt.state, mx.random.state]


@partial(mx.compile, inputs=state, outputs=state)
def step(*arrs):
    loss, g = lg(model, *arrs)
    g, _ = optim.clip_grad_norm(g, 1.0)
    opt.update(model, g)
    return loss


def evaluate():
    model.eval()
    tot, n, conf = 0.0, 0, np.zeros((3, 3), int)
    for b in batches(dev_w, False):
        arrs = [mx.array(x) for x in collate(b)]
        logits = model(*arrs[:5]); lab = np.array(arrs[5])
        mx.eval(logits)
        lp = np.array(logits - mx.logsumexp(logits, axis=-1, keepdims=True))
        v = lab >= 0
        tot += -lp[v, lab[v]].sum(); n += v.sum()
        for t, p in zip(lab[v], lp[v].argmax(-1)):
            conf[t, p] += 1
    model.train()
    rec = {LABELS[i]: f"{conf[i, i]}/{conf[i].sum()}" for i in range(3)}
    return tot / max(n, 1), rec, conf


k = 0
model.train()
for ep in range(a.epochs):
    for b in batches(train_w):
        arrs = [mx.array(x) for x in collate(b)]
        if teacher is not None:
            tl, th = teacher(*arrs[:5], hidden=True)
            arrs += [mx.stop_gradient(tl)] + ([mx.stop_gradient(th[m]) for m in tmap] if a.hid else [])
        loss = step(*arrs)
        mx.eval(state)
        k += 1
        if k % 100 == 0:
            say(f"ep{ep} step{k}/{steps} loss={loss.item():.4f} {time.time() - t0:.0f}s")
    dl, rec, conf = evaluate()
    say(f"[dev ep{ep}] nll={dl:.4f} 各類答對（召回） {rec}｜混淆（列＝答案 MASK/KEEP/NOT）{conf.tolist()}")
    model.save_weights(f"{a.out}/model.safetensors")
say("done", f"{time.time() - t0:.0f}s")
