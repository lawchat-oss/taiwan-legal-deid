"""重跑 README 的數字。
    pip install -e . pyarrow
    python eval/reproduce.py [--model 6l|3l]      （不給＝兩個都跑）
1. tw-PII-bench（Liang Hsun Huang，Apache-2.0）測試半 453 份：固定版本、驗 sha256；切分 crc32(id) % 2 == 1。
   README 只引用人名以外的類別：人名類別在切分之前整份看過，不算乾淨。
2. 合成法律文件測試集（eval/data/synthetic_legal_test.jsonl，75 份，虛構內容）。
3. 匿名化（Anonymizer 預設）：直接識別資料有沒有整個換掉、間接識別資料（生日、地址、日期）有沒有粗化。偵測跟假名化同一份。
"""
import json, os, re, sys, zlib
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
from taiwan_legal_deid import Detector, weights
from taiwan_legal_deid.obfuscate import _FW2HW, _has_day, _parse_date
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


def predict(raws, items):
    """偵測結果分三組：spans＝要遮的人名、keep＝判成保留的人名與機構、pii＝其他（含要換的機構）。"""
    return [{"id": r["id"], "spans": [x for x in s if x["type"] == "PERSON"],
             "keep": [x for x in s if x["type"] in ("PERSON_KEEP", "ORG_KEEP")],
             "pii": [x for x in s if not x["type"].startswith("PERSON") and x["type"] != "ORG_KEEP"]} for r, s in zip(items, raws)]


def _leak(orig, out):
    """輸出還留著原值的一段：英數字連續 4 碼（密碼 19860217 被當成日期換成「1986年」也算），或整個原值。"""
    out = re.sub(r"〔[^〕]*〕|Company [A-Z]\d*", "", out)  # 代號本身（〔Email1〕、Company A）的字不算：gmail 的 mail 不是從〔Email1〕洩漏出去的
    a, o = (re.sub(r"[^0-9A-Za-z]", "", x.translate(_FW2HW)) for x in (orig, out))
    return orig in out or any(a[i:i + 4] in o for i in range(len(a) - 3))


def anon(name, texts, raws, golds, direct, quasi, keep=()):
    """匿名化（Anonymizer 預設：生日留年、地址留縣市、個人行程日期留年月）。golds：每份 [(起, 訖, 類別)]。看實際輸出：
    direct 的類別要整個換掉、輸出不留原值；quasi（類別 → 名稱）要粗化：生日只剩年（或整個遮掉）、日期不留日、地址扣掉照留的縣市後整個換掉；
    keep 的類別不能被動到。"""
    from taiwan_legal_deid.codes import CodeObfuscator
    from taiwan_legal_deid.pii_candidates import CITIES
    tot = defaultdict(lambda: [0, 0])
    for t, raw, gold in zip(texts, raws, golds):
        eng = CodeObfuscator(event_dates="month")
        fake, _ = eng.apply(t, raw)
        reps = [(x["orig_start"], x["orig_end"], fake[x["start"]:x["end"]]) for x in eng.spans]
        for s, e, cat in gold:
            if quasi.get(cat) == "地址":
                s += next((len(c) for c in CITIES if t.startswith(c, s)), 0)
            group = "直接識別資料" if cat in direct else quasi.get(cat) or ("保留" if cat in keep else None)
            if not group:
                continue
            over = [r for r in reps if r[0] < e and r[1] > s]
            out = "".join(f for _, _, f in over)
            covered = all(any(a <= i < b for a, b, _ in over) for i in range(s, e))
            ok = (not over if group == "保留" else covered and not _leak(t[s:e], out) if group == "直接識別資料"
                  else covered and (_parse_date(out) is None) if group == "生日"
                  else covered and not _has_day(out) if group in ("個人行程日期", "日期") else covered)
            tot[group][0] += ok
            tot[group][1] += 1
    f = lambda g: f"{tot[g][0] / tot[g][1]:.1%}（{tot[g][0]}/{tot[g][1]}）" if tot[g][1] else "—"
    print(f"→ {name}：直接識別資料完整遮蔽 {f('直接識別資料')}；粗化 " + "、".join(f"{q} {f(q)}" for q in dict.fromkeys(quasi.values()))
          + (f"；執行職務的人名照留 {f('保留')}" if keep else ""))


def main():
    models = [sys.argv[sys.argv.index("--model") + 1]] if "--model" in sys.argv else ["6l", "3l"]
    bench = [r for r in load_bench() if zlib.crc32(r["id"].encode()) % 2 == 1]
    synth = [json.loads(l) for l in open(os.path.join(HERE, "data", "synthetic_legal_test.jsonl"), encoding="utf-8")]
    from marked_eval import parse
    synth_items = [{"id": it["id"], "text": parse(it["text"])[0]} for it in synth]
    for m in models:
        det = Detector(m)
        raw_bench, raw_synth = [det.detect(r["text"]) for r in bench], [det.detect(r["text"]) for r in synth_items]
        preds = [dict(p, spans=p["spans"] + p["pii"]) for p in predict(raw_bench, bench)]  # 一般模式：人名以外的個資全算要遮
        per, fp = bench_score(bench, preds)
        report(f"{m}｜tw-PII-bench 測試半（人名類別不乾淨，只供參考）", per, fp)
        n = sum(d["n"] for k, d in per.items() if k != "private_person")
        c = sum(d["蓋滿"] for k, d in per.items() if k != "private_person")
        print(f"→ {m}｜tw-PII-bench 測試半，人名以外的個資完整蓋住：{c / n:.1%}（{c}/{n}）")
        marked_score(synth, predict(raw_synth, synth_items), f"{m}｜合成法律文件測試集")
        quasi = {"BIRTH": "生日", "ADDR": "地址", "DATE": "個人行程日期"}
        anon(f"{m}｜匿名化・合成法律文件", [r["text"] for r in synth_items], raw_synth, [parse(it["text"])[1] for it in synth],
             {"P", "ID", "TEL", "MAIL", "URL", "ACCT", "SEC", "CAR", "HDL"}, quasi, keep={"K"})
        anon(f"{m}｜匿名化・tw-PII-bench 測試半（人名以外）", [r["text"] for r in bench], raw_bench,
             [[(g["start"], g["end"], g["label"]) for g in r["spans"]] for r in bench],
             {g["label"] for r in bench for g in r["spans"]} - {"private_person", "private_address", "private_date"},
             {"private_address": "地址", "private_date": "日期"})


if __name__ == "__main__":
    main()
