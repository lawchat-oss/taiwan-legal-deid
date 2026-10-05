"""tw-PII-bench 計分（去識別化角度）：每個標註 span 有沒有被「完整蓋住」（任何類型的預測都算），邊界是否完全一致，類型是否對；
另算誤遮：沒有碰到任何標註的預測，以及硬負例題（不該標任何東西）被標的比例。
用法：python eval/score_bench.py <bench.jsonl> <pred.jsonl> [系統名]
"""
import json, sys
from collections import defaultdict

# 標註類別 → 視為「類型正確」的系統類型（各系統共用；沒有對應的類別只算有沒有蓋住）
OK_TYPES = {
    "private_person": {"PERSON"}, "private_phone": {"TW_MOBILE", "TW_LANDLINE", "PHONE", "NUMBER"}, "private_email": {"EMAIL_ADDRESS", "EMAIL"},
    "private_address": {"TW_ADDRESS", "LOCATION", "ADDRESS"}, "private_date": {"TW_BIRTH_DATE", "DATE", "DATE_EVENT"},
    "account_number": {"TW_BANK_ACCOUNT", "CREDIT_CARD", "ACCOUNT", "NUMBER", "CODE"},
    "secret": {"TW_PASSWORD", "TW_VERIFICATION_CODE", "TW_CRYPTO_SEED", "TW_PRIVATE_KEY", "SECRET", "NUMBER", "CODE"},
    "tw_national_id": {"TW_NATIONAL_ID", "TW_ARC", "ID", "CODE"}, "tw_company_id": {"TW_BUSINESS_ID", "ID", "NUMBER"},
    "tw_license_plate": {"TW_LICENSE_PLATE", "ID", "CODE"}, "tw_passport": {"TW_PASSPORT", "ID", "NUMBER", "CODE"},
}


TITLE_TAIL = sorted(("先生", "小姐", "女士", "太太", "醫師", "護理師", "經理", "主任", "律師", "里長", "教授", "專員", "房東", "老師",
                     "爸爸", "媽媽", "業務經理", "採購專員", "店長", "組長", "課長", "院長", "教練", " 醫師", " 經理"), key=len, reverse=True)


def score(bench, preds):
    P = {p["id"]: p for p in preds}
    per = defaultdict(lambda: defaultdict(int))
    fp_spans = fp_chars = n_chars = neg_hit = n_neg = fp_repeat = 0
    fp_by_type = defaultdict(int)
    for r in bench:
        ps = P.get(r["id"], {"spans": []})["spans"]
        n_chars += len(r["text"])
        cov = [False] * len(r["text"])
        for p in ps:
            for i in range(max(0, p["start"]), min(len(cov), p["end"])):
                cov[i] = True
        for g in r["spans"]:
            d = per[g["label"]]
            d["n"] += 1
            full = all(cov[g["start"]:g["end"]]); part = any(cov[g["start"]:g["end"]])
            d["蓋滿"] += full; d["部分"] += part and not full
            ov = [p for p in ps if p["start"] < g["end"] and p["end"] > g["start"]]
            ok = OK_TYPES.get(g["label"])
            d["類型對"] += bool(ok and any(p["type"] in ok for p in ov))
            if g["label"] == "private_person":  # 名字核心：扣掉標註尾巴的稱謂（我們只遮名字、稱謂留原文；bench 有時把稱謂標進去）
                ce = g["end"] - next((len(x) for x in TITLE_TAIL if g["text"].rstrip().endswith(x) and len(g["text"].rstrip()) > len(x)), 0)
                ce -= len(g["text"]) - len(g["text"].rstrip())
                d["核心蓋滿"] += all(cov[g["start"]:max(g["start"] + 1, ce)])
            d["邊界全對"] += any(p["start"] == g["start"] and p["end"] == g["end"] for p in ov)
        names = [g["text"] for g in r["spans"] if g["label"] == "private_person"]
        for p in ps:
            if not any(p["start"] < g["end"] and p["end"] > g["start"] for g in r["spans"]):
                fp_spans += 1; fp_chars += p["end"] - p["start"]; fp_by_type[p["type"]] += 1
                s = r["text"][p["start"]:p["end"]].replace(" ", "")
                if p["type"] == "PERSON" and any(s in n.replace(" ", "") for n in names):
                    fp_repeat += 1  # 同文件已標人名的重複提及（含只有姓、只有名）
        if r["is_negative"]:
            n_neg += 1; neg_hit += bool(ps)
    return per, dict(fp_spans=fp_spans, fp_chars=fp_chars, n_chars=n_chars, neg_hit=neg_hit, n_neg=n_neg, fp_by_type=dict(fp_by_type), fp_repeat=fp_repeat)


def report(name, per, fp):
    tot = defaultdict(int)
    print(f"\n=== {name} ===")
    print(f"{'類別':20s} {'n':>5s} {'蓋滿':>7s} {'部分':>6s} {'漏掉':>6s} {'類型對':>7s} {'邊界全對':>8s}")
    for lab in sorted(per, key=lambda k: -per[k]["n"]):
        d = per[lab]; n = d["n"]
        miss = n - d["蓋滿"] - d["部分"]
        for k in ("n", "蓋滿", "部分", "類型對", "邊界全對"):
            tot[k] += d[k]
        tc = f"{d['類型對'] / n:7.1%}" if lab in OK_TYPES else "      —"
        core = f"  名字核心蓋滿 {d['核心蓋滿'] / n:.1%}" if lab == "private_person" else ""
        print(f"{lab:20s} {n:5d} {d['蓋滿'] / n:7.1%} {d['部分'] / n:6.1%} {miss / n:6.1%} {tc} {d['邊界全對'] / n:8.1%}{core}")
    n = tot["n"]
    print(f"{'全部':20s} {n:5d} {tot['蓋滿'] / n:7.1%} {tot['部分'] / n:6.1%} {(n - tot['蓋滿'] - tot['部分']) / n:6.1%}")
    print(f"誤遮：{fp['fp_spans']} 個預測沒碰到任何標註（{fp['fp_chars']} 字，每千字 {fp['fp_chars'] / fp['n_chars'] * 1000:.1f} 字）；"
          f"硬負例題被標 {fp['neg_hit']}/{fp['n_neg']}；誤遮類型 {fp['fp_by_type']}")
    print(f"  └ 其中 {fp['fp_repeat']} 個是同文件已標人名的重複提及（bench 沒標全）；扣掉後真正誤遮 {fp['fp_spans'] - fp['fp_repeat']} 個")


if __name__ == "__main__":
    import os, zlib
    bench = [json.loads(l) for l in open(sys.argv[1])]
    half = os.environ.get("HALF")  # dev＝開發半、test＝測試半（切分見 eval/reproduce.py）
    if half:
        bench = [r for r in bench if zlib.crc32(r["id"].encode()) % 2 == (0 if half == "dev" else 1)]
    preds = [json.loads(l) for l in open(sys.argv[2])]
    preds = [dict(p, spans=p["spans"] + p.get("pii", [])) for p in preds]  # 我們的輸出：人名以外的個資另放 pii（一般模式全遮，含個人行程日期）
    only = os.environ.get("ONLY_TYPES")  # 例：ONLY_TYPES=PERSON 只比人名
    if only:
        keep = set(only.split(","))
        preds = [dict(p, spans=[x for x in p["spans"] if x["type"] in keep]) for p in preds]
        bench = [dict(r, spans=[g for g in r["spans"] if g["label"] == "private_person"]) for r in bench]
    per, fp = score(bench, preds)
    report(sys.argv[3] if len(sys.argv) > 3 else sys.argv[2], per, fp)
    ms = [p.get("ms", 0) for p in preds]
    if any(ms):
        print(f"延遲：每筆中位 {sorted(ms)[len(ms) // 2]:.0f} ms、總 {sum(ms) / 1000:.1f} s")
