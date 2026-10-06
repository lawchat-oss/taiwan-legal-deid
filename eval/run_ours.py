"""跑評測集，輸出預測 JSONL：spans＝要遮的人名、keep＝判成保留的人名與機構、pii＝其他要遮的值（含要換的機構）。
用法：python eval/run_ours.py <items.jsonl> <out.jsonl> [6l|3l|run目錄]
"""
import json, os, sys, time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from reproduce import predict
from taiwan_legal_deid import Detector

items, out = sys.argv[1:3]
det = Detector(sys.argv[3] if len(sys.argv) > 3 else "6l")
rows = [json.loads(l) for l in open(items, encoding="utf-8")]
t = time.time()
preds = predict([det.detect(r["text"]) for r in rows], rows)
with open(out, "w", encoding="utf-8") as f:
    for p in preds:
        f.write(json.dumps(p, ensure_ascii=False) + "\n")
chars = sum(len(r["text"]) for r in rows)
print(f"{len(rows)} 筆、{chars} 字；偵測共 {time.time() - t:.1f} 秒")
