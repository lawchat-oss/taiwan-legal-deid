"""解碼（MLX 與 CPU 推論共用）：重疊的候選取「是」（要遮＋保留）機率高者，低於門檻不選；判斷全來自模型。
類型：人名看標籤（PERSON／PERSON_KEEP）；其他個資看候選來源（PII_TYPE），日期判成「個人行程日期」的是 DATE_EVENT
（一般模式照遮、法律模式保留：遮不遮是產品設定，不在這裡決定）。"""
import numpy as np

from .labels import GROUP, PII_TYPE


def extend_long(text, spans):
    """比一個視窗還長的網址、Email（超過 WIN 字）：模型只看得到其中一段，判定要換的那段延伸成全文找到的完整值，尾巴才不會留著。
    只調整範圍，不改判斷（沒被判定要換的不會變成要換）。"""
    from .examples import WIN
    from .pii_candidates import EMAIL, URL
    for typ, rx in (("URL", URL), ("EMAIL", EMAIL)):
        for m in rx.finditer(text):
            s0, e0 = m.span()
            hit = [x for x in spans if x["start"] < e0 and x["end"] > s0 and x["type"] not in ("PERSON_KEEP", "ORG_KEEP", "DATE_EVENT")]
            if e0 - s0 > WIN and hit:
                best = max(hit, key=lambda x: x["score"])
                spans = [x for x in spans if x not in hit] + [dict(best, start=s0, end=e0, type=typ, kind=typ.lower())]
    return sorted(spans, key=lambda x: x["start"])


def decode(scores, n_chars, tau):
    chosen, taken = [], np.zeros(n_chars + 1, bool)
    for s, e, kind, pm, pk, pn in sorted(scores, key=lambda x: -(x[3] + x[4])):
        if pm + pk < tau or taken[s:e].any():
            continue
        taken[s:e] = True
        g = GROUP.get(kind, "person")
        if g == "person":
            typ = "PERSON" if pm >= pk else "PERSON_KEEP"
        elif g == "org":
            typ = "ORG" if pm >= pk else "ORG_KEEP"
        else:
            typ = "DATE_EVENT" if kind == "date" and pk > pm else PII_TYPE[kind]
        chosen.append({"start": s, "end": e, "type": typ, "score": round(pm + pk, 3), "p_mask": round(pm, 3), "kind": kind})
    return sorted(chosen, key=lambda x: x["start"])
