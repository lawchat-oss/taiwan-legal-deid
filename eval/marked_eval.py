"""標記式測試集計分，依難點類型分開看。
人名：⟦P:…⟧ 要遮、⟦K:…⟧ 保留。其他個資：⟦ID⟧ ⟦TEL⟧ ⟦MAIL⟧ ⟦URL⟧ ⟦ACCT⟧ ⟦SEC⟧ ⟦CAR⟧ ⟦HDL⟧ ⟦ADDR⟧ ⟦BIRTH⟧ 要遮；
⟦DATE⟧（個人行程日期）一般模式要遮、法律模式保留。
用法：python eval/marked_eval.py make <marked.jsonl> <items.jsonl>     → 給各系統跑的 {id, text}
      python eval/marked_eval.py score <marked.jsonl> <pred.jsonl> [系統名]
pred 的 spans＝要遮的人名（其他系統：全部要遮的值）；人名以外的個資放 pii（type＝DATE_EVENT 的是個人行程日期）；keep＝判成保留的人名。
"""
import json, os, re, sys
from collections import defaultdict

MARK = re.compile(r"⟦([A-Z]+):([^⟦⟧]+)⟧")


def parse(marked):
    text, spans, pos = [], [], 0
    for m in MARK.finditer(marked):
        text.append(marked[pos:m.start()]); cur = sum(map(len, text))
        spans.append((cur, cur + len(m.group(2)), m.group(1))); text.append(m.group(2)); pos = m.end()
    text.append(marked[pos:])
    return "".join(text), spans


def score(items, preds, name):
    P = {p["id"]: p for p in preds}
    full = any(tag not in ("P", "K") for it in items for _, _, tag in parse(it["text"])[1])
    tot = defaultdict(lambda: defaultdict(int))
    for it in items:
        text, gold = parse(it["text"])
        pr = P.get(it["id"], {"spans": [], "keep": []})
        masked = [(p["start"], p["end"]) for p in pr["spans"] + (pr.get("pii", []) if full else [])]
        legal = [(p["start"], p["end"]) for p in pr["spans"] + pr.get("pii", []) if p.get("type") != "DATE_EVENT"]
        persons = masked + [(p["start"], p["end"]) for p in pr.get("keep", [])]
        cov = lambda s, e, ms=masked: all(any(a <= c < b for a, b in ms) for c in range(s, e))
        touch = lambda s, e, ms=masked: any(a < e and b > s for a, b in ms)
        for key in ["全部"] + [f"類型{x}" for x in it.get("phenomena", [])]:
            d = tot[key]
            for s, e, tag in gold:
                if tag == "P":
                    d["P"] += 1; d["P蓋滿"] += cov(s, e); d["P切法全對"] += (s, e) in persons
                elif tag == "K":
                    d["K"] += 1; d["K沒被遮"] += not touch(s, e)
                else:
                    d[tag] += 1; d[tag + "蓋滿"] += cov(s, e); d[tag + "切法"] += (s, e) in masked
                    d["個資"] += 1; d["個資蓋滿"] += cov(s, e)
                    if tag == "DATE":
                        d["DATE法律模式保留"] += not touch(s, e, legal)
                    elif tag == "BIRTH":
                        d["BIRTH法律模式蓋滿"] += cov(s, e, legal)
            gold_iv = [(s, e) for s, e, tag in gold if tag != "K"]
            d["誤遮"] += sum(1 for a, b in masked if not any(s < b and e > a for s, e in gold_iv))
            d["題數"] += 1
    f = lambda d, a, b: f"{d[a] / d[b]:.1%}（{d[a]}/{d[b]}）" if d[b] else "—"
    print(f"\n=== {name} ===")
    print(f"{'':10s} {'人名要遮蓋滿':>14s} {'人名切法全對':>14s} {'保留沒被遮':>12s}" + (f" {'個資蓋滿':>14s}" if full else "") + f" {'誤遮（個）':>8s}")
    for key in ["全部"] + sorted([k for k in tot if k != "全部"], key=lambda k: int(k[2:])):
        d = tot[key]
        print(f"{key:10s} {f(d, 'P蓋滿', 'P'):>14s} {f(d, 'P切法全對', 'P'):>14s} {f(d, 'K沒被遮', 'K'):>12s}"
              + (f" {f(d, '個資蓋滿', '個資'):>14s}" if full else "") + f" {d['誤遮']:8d}")
    if full:
        d = tot["全部"]
        print("各類個資（一般模式）：" + "｜".join(f"{t} 蓋滿 {f(d, t + '蓋滿', t)} 切法 {d[t + '切法']}/{d[t]}"
                                          for t in ("ID", "TEL", "MAIL", "URL", "ACCT", "SEC", "CAR", "HDL", "ADDR", "BIRTH", "DATE") if d[t]))
        print(f"法律模式：生日蓋滿 {f(d, 'BIRTH法律模式蓋滿', 'BIRTH')}｜個人行程日期保留 {f(d, 'DATE法律模式保留', 'DATE')}")


if __name__ == "__main__":
    items = [json.loads(l) for l in open(sys.argv[2])]
    if sys.argv[1] == "make":
        with open(sys.argv[3], "w") as fo:
            for it in items:
                fo.write(json.dumps({"id": it["id"], "text": parse(it["text"])[0]}, ensure_ascii=False) + "\n")
        print(len(items), "題 →", sys.argv[3])
    else:
        half = os.environ.get("HALF")  # odd＝開發用（看過錯題）、even＝最終驗收（只看分數）
        if half:
            items = [it for it in items if int(it["id"].split("-")[1]) % 2 == (1 if half == "odd" else 0)]
        score(items, [json.loads(l) for l in open(sys.argv[3])], (sys.argv[4] if len(sys.argv) > 4 else sys.argv[3]) + (f"［{half}］" if half else ""))
