"""重跑 README 的數字。
    pip install -e . pyarrow
    python eval/reproduce.py [--model 6l|3l]      （不給＝兩個都跑）
1. tw-PII-bench（Liang Hsun Huang，Apache-2.0）測試半 453 份：固定版本、驗 sha256；切分 crc32(id) % 2 == 1。
   README 只引用人名以外的類別：人名類別在切分之前整份看過，不算乾淨。
2. 合成法律文件測試集（eval/data/synthetic_legal_test.jsonl，75 份，虛構內容）。
"""
import json, os, sys, zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
from taiwan_legal_deid import Detector, weights
from marked_eval import score as marked_score
from score_bench import report, score as bench_score

BENCH = "https://huggingface.co/datasets/lianghsun/tw-PII-bench/resolve/62bdad506803b15e1a4193f4493200ad431b1af7/data"
BENCH_SHA = {"short": "03e4850a0a97a2b5cb046c1dcd3996b42c5eea3766ae2618d4bbf64391e73693",
             "mid": "5d05e1c7fc6adaf7c66591de0d76e5ac5d175fb182f67a19da6d23896b3b02e0",
             "long": "b30ca2a1012254f164893d1aad491a778d2fe49cfef71239f8c934e0544883e2"}


def load_bench():
    """tw-PII-bench 全部 910 份（下載一次，存在模型同一個資料夾）。"""
    import pyarrow.parquet as pq
    rows = []
    for split, sha in BENCH_SHA.items():
        p = os.path.join(weights.home(), "tw-PII-bench-62bdad5", f"{split}.parquet")
        if not os.path.exists(p):
            weights._download(f"{BENCH}/{split}.parquet", p, sha)
        rows += [dict(r, split=split) for r in pq.read_table(p).to_pylist()]
    return rows


def predict(det, items):
    """偵測結果分三組：spans＝要遮的人名、keep＝判成保留的人名與機構、pii＝其他（含要換的機構）。"""
    out = []
    for r in items:
        s = det.detect(r["text"])
        out.append({"id": r["id"], "spans": [x for x in s if x["type"] == "PERSON"],
                    "keep": [x for x in s if x["type"] in ("PERSON_KEEP", "ORG_KEEP")],
                    "pii": [x for x in s if not x["type"].startswith("PERSON") and x["type"] != "ORG_KEEP"]})
    return out


def main():
    models = [sys.argv[sys.argv.index("--model") + 1]] if "--model" in sys.argv else ["6l", "3l"]
    bench = [r for r in load_bench() if zlib.crc32(r["id"].encode()) % 2 == 1]
    synth = [json.loads(l) for l in open(os.path.join(HERE, "data", "synthetic_legal_test.jsonl"), encoding="utf-8")]
    from marked_eval import parse
    synth_items = [{"id": it["id"], "text": parse(it["text"])[0]} for it in synth]
    for m in models:
        det = Detector(m)
        preds = [dict(p, spans=p["spans"] + p["pii"]) for p in predict(det, bench)]  # 一般模式：人名以外的個資全算要遮
        per, fp = bench_score(bench, preds)
        report(f"{m}｜tw-PII-bench 測試半（人名類別不乾淨，只供參考）", per, fp)
        n = sum(d["n"] for k, d in per.items() if k != "private_person")
        c = sum(d["蓋滿"] for k, d in per.items() if k != "private_person")
        print(f"→ {m}｜tw-PII-bench 測試半，人名以外的個資完整蓋住：{c / n:.1%}（{c}/{n}）")
        marked_score(synth, predict(det, synth_items), f"{m}｜合成法律文件測試集")


if __name__ == "__main__":
    main()
