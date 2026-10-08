"""重跑 README 的數字。
    pip install -e . pyarrow
    python eval/reproduce.py [--model 6l|3l|<模型資料夾>]      （不給＝6l、3l 都跑）
1. tw-PII-bench（Liang Hsun Huang，Apache-2.0）測試半 453 份：固定版本、驗 sha256；切分 crc32(id) % 2 == 1。
   README 的總分不含人名、電話：人名類別在切分之前整份看過；電話在 0.3.0 開發時看過錯題（另列只供參考）。
2. 合成法律文件測試集（eval/data/synthetic_legal_test.jsonl，75 份，虛構內容）。
3. 匿名化（Anonymizer 預設）與代號假名化（style="code"）：直接識別資料有沒有整個換掉、間接識別資料（生日、地址、日期）有沒有粗化。偵測跟假名化同一份。
4. 各類別的召回與精確率（README 的分類表，印成 Markdown）。
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


# 開發時看過錯題的類別，不算進總分（另列只供參考）：bench 的人名在切分之前整份看過；
# 電話在 0.3.0 開發時為了找漏網原因，看過 bench 和合成法律文件的錯題（合成法律文件的直接識別資料也因此不含電話）
SEEN_BENCH = {"private_person", "private_phone"}


# README 分類表：召回看標註類別（標註的值整個被換掉才算，任何類型的預測都算）；精確率看輸出類型（換掉的值碰到任何標註就算對）。
# 機構不算精確率（兩份考題都沒標機構）；bench 的人名兩邊都不算（切分前看過）
GOLD_CAT = {"P": "人名", **dict.fromkeys(("ID", "tw_national_id", "tw_passport"), "身分證、居留證、護照"),
            **dict.fromkeys(("tw_nhi_card", "tw_driver_license", "tw_household_no", "tw_medical_license", "tw_military_id"), "健保卡、駕照、戶號等證號"),
            **dict.fromkeys(("ACCT", "account_number"), "帳號、卡號"), "tw_company_id": "統一編號", **dict.fromkeys(("SEC", "secret"), "密碼、驗證碼"),
            **dict.fromkeys(("CAR", "tw_license_plate"), "車牌"), **dict.fromkeys(("MAIL", "private_email"), "Email"),
            **dict.fromkeys(("URL", "private_url"), "網址"), **dict.fromkeys(("HDL", "tw_line_id", "tw_ptt_id"), "社群帳號"),
            **dict.fromkeys(("ADDR", "private_address"), "地址"), "BIRTH": "生日", "DATE": "個人行程日期", "private_date": "日期（不分生日、行程）",
            **dict.fromkeys(("TEL", "private_phone"), "電話（只供參考）")}
OUT_CAT = {"PERSON": "人名", "CODE": "英數代碼（身分證、護照、車牌等）", "NUMBER": "數字號碼（帳號、統編等）", "EMAIL": "Email",
           "URL": "網址", "HANDLE": "社群帳號", "ADDRESS": "地址", "DATE": "生日等身分日期", "DATE_EVENT": "個人行程日期"}


def by_category(golds, masks, skip=(), seen=()):
    """golds：每份 [(起, 訖, 標註類別)]（不含保留的人名）；masks：每份 [(起, 訖, 輸出類型)]（一般模式要換的全部）；
    skip：不算精確率的輸出類型；seen：開發時看過錯題的標註類別（電話），碰到它的預測不算精確率（只拿掉換對的，偏保守）。
    回傳 (召回, 精確率)，都是 {類別: [對, 共]}。"""
    rec, pre = defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0])
    for gold, ms in zip(golds, masks):
        for s, e, lab in gold:
            if lab in GOLD_CAT:
                r = rec[GOLD_CAT[lab]]
                r[0] += all(any(a <= i < b for a, b, _ in ms) for i in range(s, e)); r[1] += 1
        for a, b, t in ms:
            if t in OUT_CAT and t not in skip and not any(s < b and e > a for s, e, lab in gold if lab in seen):
                p = pre[OUT_CAT[t]]
                p[0] += any(s < b and e > a for s, e, _ in gold); p[1] += 1
    return rec, pre


def category_tables(name, cols):
    """cols：[(欄名, (召回, 精確率))]，印成 README 的 Markdown 表格。"""
    pct = lambda d, k: f"{d[k][0] / d[k][1]:.1%}（{d[k][0]}/{d[k][1]}）" if d.get(k, [0, 0])[1] else "—"
    for title, i, cats in (("召回（該換的值整個換掉）", 0, dict.fromkeys(GOLD_CAT.values())), ("精確率（換掉的值確實是個資）", 1, OUT_CAT.values())):
        print(f"\n{name}｜{title}\n| 類別 | " + " | ".join(c for c, _ in cols) + " |\n|---|" + "---|" * len(cols))
        for k in cats:
            if any(x[i].get(k, [0, 0])[1] for _, x in cols):
                print(f"| {k} | " + " | ".join(pct(x[i], k) for _, x in cols) + " |")
    for c, (_, pre) in cols:
        ok, n = sum(v[0] for v in pre.values()), sum(v[1] for v in pre.values())
        print(f"→ {name}｜{c}：精確率 " + (f"{ok / n:.1%}（{ok}/{n}）" if n else "—"))  # 只認人名的舊模型在 bench 沒有可計分的預測


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


def anon(name, texts, raws, golds, direct, quasi, keep=(), event_dates="month"):
    """匿名化（Anonymizer 預設：生日留年、地址留縣市、個人行程日期留年月）。golds：每份 [(起, 訖, 類別)]。看實際輸出：
    direct 的類別要整個換掉、輸出不留原值；quasi（類別 → 名稱）要粗化：生日只剩年（或整個遮掉）、日期不留日、地址扣掉照留的縣市後整個換掉；
    keep 的類別、以及名稱結尾是「照留」的 quasi（代號假名化的個人行程日期）不能被動到。event_dates＝keep 量代號假名化。"""
    from taiwan_legal_deid.codes import CodeObfuscator
    from taiwan_legal_deid.pii_candidates import CITIES
    tot = defaultdict(lambda: [0, 0])
    for t, raw, gold in zip(texts, raws, golds):
        eng = CodeObfuscator(event_dates=event_dates)
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
            ok = (not over if group == "保留" or group.endswith("照留") else covered and not _leak(t[s:e], out) if group == "直接識別資料"
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
        report(f"{m}｜tw-PII-bench 測試半（人名、電話類別不乾淨，只供參考）", per, fp)
        n = sum(d["n"] for k, d in per.items() if k not in SEEN_BENCH)
        c = sum(d["蓋滿"] for k, d in per.items() if k not in SEEN_BENCH)
        print(f"→ {m}｜tw-PII-bench 測試半，人名、電話以外的個資完整蓋住：{c / n:.1%}（{c}/{n}）")
        d = per["private_phone"]
        print(f"→ {m}｜tw-PII-bench 測試半，電話完整蓋住（開發時看過錯題，只供參考）：{d['蓋滿'] / d['n']:.1%}（{d['蓋滿']}/{d['n']}）")
        ps = predict(raw_synth, synth_items)
        marked_score(synth, ps, f"{m}｜合成法律文件測試集")
        tot = {True: [0, 0], False: [0, 0]}  # 電話／電話以外的其他個資（一般模式：人名以外全算要遮）
        for it, p in zip(synth, ps):
            ms = [(x["start"], x["end"]) for x in p["spans"] + p["pii"]]
            for s0, e0, tag in parse(it["text"])[1]:
                if tag not in ("P", "K"):
                    tot[tag == "TEL"][0] += all(any(a <= i < b for a, b in ms) for i in range(s0, e0)); tot[tag == "TEL"][1] += 1
        print(f"→ {m}｜合成法律文件，電話以外的其他個資完整蓋住：{tot[False][0] / tot[False][1]:.1%}（{tot[False][0]}/{tot[False][1]}）")
        print(f"→ {m}｜合成法律文件，電話完整蓋住（開發時看過錯題，只供參考）：{tot[True][0] / tot[True][1]:.1%}（{tot[True][0]}/{tot[True][1]}）")
        span3 = lambda xs: [(x["start"], x["end"], x["type"]) for x in xs]
        category_tables(m, [
            ("合成法律文件", by_category([[g for g in parse(it["text"])[1] if g[2] != "K"] for it in synth], [span3(p["spans"] + p["pii"]) for p in ps], seen={"TEL"})),
            ("tw-PII-bench 測試半", by_category([[(g["start"], g["end"], g["label"]) for g in r["spans"]] for r in bench],
                                               [span3(p["spans"]) for p in preds], skip={"PERSON"}, seen=SEEN_BENCH))])
        quasi = {"BIRTH": "生日", "ADDR": "地址", "DATE": "個人行程日期"}
        anon(f"{m}｜匿名化・合成法律文件", [r["text"] for r in synth_items], raw_synth, [parse(it["text"])[1] for it in synth],
             {"P", "ID", "MAIL", "URL", "ACCT", "SEC", "CAR", "HDL"}, quasi, keep={"K"})
        anon(f"{m}｜匿名化・tw-PII-bench 測試半（人名以外）", [r["text"] for r in bench], raw_bench,
             [[(g["start"], g["end"], g["label"]) for g in r["spans"]] for r in bench],
             {g["label"] for r in bench for g in r["spans"]} - SEEN_BENCH - {"private_address", "private_date"},
             {"private_address": "地址", "private_date": "日期"})
        anon(f"{m}｜代號假名化・合成法律文件", [r["text"] for r in synth_items], raw_synth, [parse(it["text"])[1] for it in synth],
             {"P", "ID", "MAIL", "URL", "ACCT", "SEC", "CAR", "HDL"}, dict(quasi, DATE="個人行程日期照留"), keep={"K"}, event_dates="keep")


if __name__ == "__main__":
    main()
