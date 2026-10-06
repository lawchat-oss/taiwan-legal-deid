"""合成語料 → 全文＋spans（全標註）。
- data/synth/raw_NN.jsonl：只標人名（⟦P:…⟧ 要遮、⟦K:…⟧ 保留）→ synth_docs.jsonl（annot＝人名）
- data/synth/raw_pii_NN.jsonl：人名＋其他個資分類標記（見 PROMPT_PII.md）→ synth_pii_docs.jsonl（annot＝人名＋個資）
- data/synth/raw_org_NN.jsonl：再加機構標記（見 PROMPT_ORG.md）→ synth_org_docs.jsonl（annot＝人名＋個資＋機構）
私人全名換成隨機假名（同一份文件一致），同姓的部分稱呼跟著換姓、只用名字的稱呼跟著換名，增加名字多樣性；
電話、證號、帳號、密碼、車牌的數字換成同格式亂數（寫作 agent 愛用固定幾組號碼）。
用法：python -m taiwan_legal_deid.data_synth
"""
from __future__ import annotations

import glob, json, os, random, re

from .candidates import CJK, surname_len
from .fakes import fake_digits
from .labels import TAGS
from .names import TRAIN_WILD, sample_name

D = os.path.join(os.path.dirname(__file__), "..", "data")
MARK = re.compile(r"⟦([A-Z]+):([^⟦⟧]+)⟧")
KEEP_HEAD = {"TEL": 2, "ACCT": 3}  # 換數字時保留開頭幾碼（09／02、銀行代碼）


LOCAL_OFFICIAL = ("里長", "議員", "鄉長", "鎮長", "村長", "鄉民代表", "里幹事", "代表會主席")  # 地方民代與基層公職算私人（與 tw-PII-bench 口徑一致）


def parse(marked: str):
    text, spans, pos = [], [], 0
    for m in MARK.finditer(marked):
        text.append(marked[pos:m.start()]); cur = sum(map(len, text))
        lab, group = TAGS[m.group(1)]  # 不認得的標記 → KeyError，整行當壞行丟掉
        before, after = marked[max(0, m.start() - 6):m.start()], marked[m.end():m.end() + 5]
        if m.group(1) == "K" and (after.startswith(LOCAL_OFFICIAL) or before.endswith(LOCAL_OFFICIAL)):  # 寫作 agent 口徑不一（syn06 把虛構里長、議員標成保留）
            lab = "MASK"
        spans.append({"start": cur, "end": cur + len(m.group(2)), "label": lab, "group": group, "tag": m.group(1), "text": m.group(2)})
        text.append(m.group(2)); pos = m.end()
    text.append(marked[pos:])
    return "".join(text), spans


def randomize_values(text, spans, rng):
    """電話、證號、帳號、密碼、車牌：數字換成同格式亂數（只換數字，長度不變，spans 位置不用動）。"""
    chars = list(text)
    for s in spans:
        if s.get("tag") in ("TEL", "ID", "ACCT", "SEC", "CAR"):
            v = text[s["start"]:s["end"]]
            zeros = len(v) - len(v.lstrip("0"))  # 健保卡號 0000 開頭：開頭的 0 是格式的一部分，不換
            chars[s["start"]:s["end"]] = fake_digits(rng, v, keep_first=max(KEEP_HEAD.get(s["tag"], 0), zeros if zeros >= 2 else 0))
    return "".join(chars)


def resurrogate(text, spans, rng):
    """私人全名 → 假名；部分稱呼與只用名字的稱呼跟著換。回傳新全文與新 spans。"""
    person = lambda s: s.get("group", "person") == "person"
    fulls = {s["text"] for s in spans if person(s) and s["label"] == "MASK" and 2 <= len(s["text"]) <= 4 and surname_len(s["text"])
             and all(CJK.match(c) for c in s["text"])}
    taken = set(fulls) | {s["text"] for s in spans}
    sub = {}
    for n in sorted(fulls):
        sl = surname_len(n)
        sub[n] = sample_name(rng, length=len(n), compound=(sl == 2), avoid=taken, wild=TRAIN_WILD); taken.add(sub[n])
    by_sur = {}
    by_given = {}
    for n, new in sub.items():
        sl = surname_len(n)
        by_sur.setdefault(n[:sl], new[:sl])
        if len(n) - sl >= 2:
            by_given[n[sl:]] = new[sl:]
    out, new_spans, pos = [], [], 0
    for s in sorted(spans, key=lambda x: x["start"]):
        out.append(text[pos:s["start"]]); cur = sum(map(len, out))
        t = s["text"]
        if person(s) and s["label"] == "MASK":
            t = sub.get(t) or by_sur.get(t) or by_given.get(t) or t
        new_spans.append({k: v for k, v in dict(s, start=cur, end=cur + len(t)).items() if k != "text"})
        out.append(t); pos = s["end"]
    out.append(text[pos:])
    return "".join(out), new_spans


def resurrogate_orgs(text, spans, rng):
    """要換的機構（ORG）品牌換成隨機假品牌（同一份文件一致；法律形式、產業、類型照留）：寫作 agent 愛用固定幾個品牌字。
    只換一半文件（另一半留原本的品牌字，免得模型只認得假品牌字庫裡的字）。"""
    from .obfuscate import Obfuscator
    if not any(s.get("tag") == "ORG" for s in spans) or rng.random() < 0.5:  # 沒有機構的文件不動亂數：舊語料重建後跟 v7 訓練時一模一樣
        return text, spans
    ob = Obfuscator(seed=rng.random())
    out, new_spans, pos = [], [], 0
    for s in sorted(spans, key=lambda x: x["start"]):
        out.append(text[pos:s["start"]]); cur = sum(map(len, out))
        t = text[s["start"]:s["end"]]
        if s.get("tag") == "ORG":
            t = ob.fwd.get(t) or ob._add(t, ob._org(t, text), "ORG")
        new_spans.append(dict(s, start=cur, end=cur + len(t)))
        out.append(t); pos = s["end"]
    out.append(text[pos:])
    return "".join(out), new_spans


def build(pattern, out_name, src, annot, rng):
    n_bad = n = 0
    tags = {}
    with open(f"{D}/train/{out_name}", "w") as f:
        for path in sorted(glob.glob(f"{D}/synth/{pattern}")):
            for k, line in enumerate(open(path)):
                try:
                    r = json.loads(line)
                    marked = r["text"]
                    assert marked.count("⟦") == marked.count("⟧") == len(MARK.findall(marked))
                    text, spans = parse(marked)
                except Exception:
                    n_bad += 1; continue
                text, spans = resurrogate(text, spans, rng)
                text, spans = resurrogate_orgs(text, spans, rng)
                text = randomize_values(text, spans, rng)
                for s in spans:
                    tags[s["tag"]] = tags.get(s["tag"], 0) + 1
                f.write(json.dumps({"id": f"{os.path.basename(path)}#{k}", "genre": r.get("genre"), "text": text, "spans": spans,
                                    "src": src, "annot": annot}, ensure_ascii=False) + "\n")
                n += 1
    print(f"合成文件 {n} 份（壞行 {n_bad}）→ data/train/{out_name}；標記 {tags}")


def build_noisy(rng):
    """OCR 版副本（data/train/noisy_docs.jsonl）：合成文件一部分、判決一小部分，加上掃描件雜訊（形近字、斷行、字間空白、亂碼）。
    標準答案跟著搬，值中間的雜訊算在值裡面：模型要學會被 OCR 弄亂的名字、地址、日期一樣要遮（候選那邊有 OCR 容錯版）。
    要先跑 data_judgments（讀 judg_docs.jsonl）。"""
    from .ocr_noise import JUNK_OCR, noise
    share = {"synth_pii_docs.jsonl": 0.5, "synth_org_docs.jsonl": 0.5, "synth_docs.jsonl": 0.3, "judg_docs.jsonl": 0.15}
    n = 0
    with open(f"{D}/train/noisy_docs.jsonl", "w") as f:
        for name, frac in share.items():
            for line in open(f"{D}/train/{name}"):
                if rng.random() >= frac:
                    continue
                d = json.loads(line)
                p = rng.choice((0.02, 0.03, 0.05))
                text, spans = noise(d["text"], d["spans"], rng, p=p, junk=JUNK_OCR, garble=p / 4)
                spans = [{k: v for k, v in s.items() if k != "text"} for s in spans
                         if re.search(r"[0-9A-Za-z０-９一-鿿]", s["text"])]  # 整個值都被讀成亂碼（王→'~~）：已經不是那個值，不留標籤
                annot = d.get("annot", ["person"] if d.get("src") != "judgment" else [])  # 判決只標一部分：照原本的口徑
                f.write(json.dumps(dict(d, id=d["id"] + "#ocr", text=text, spans=spans, src="noisy", annot=annot), ensure_ascii=False) + "\n")
                n += 1
    print(f"OCR 版副本 {n} 份 → data/train/noisy_docs.jsonl")


def markdownify(text, spans, rng):
    """Markdown／表格寫法（LLM 產生的文字、Notion 匯出）：值用 `…`、**…**、*…* 包起來，「欄位：值」的行改成表格列，欄位名也加粗。
    包裝符號在值的外面；欄位名（不是個資）也會被包，免得模型把「被包起來」當成要不要遮的線索。只插入不刪字，spans 跟著搬。"""
    ins = []  # (位置, 插入字串, 0＝開頭（放在從這裡開始的值前面）／1＝結尾（放在到這裡結束的值後面）, 包值符號＝True)
    for s in spans:
        if rng.random() < 0.5:
            w = rng.choice(("`", "`", "**", "*"))
            ins += [(s["start"], w, 0, True), (s["end"], w, 1, True)]
    for m in re.finditer(r"(?m)^([^\n：:|`*]{1,12})([：:])[ \t]*(?=\S)", text):
        r = rng.random()
        if r < 0.25:  # 表格列：| 姓名： | 王小明 |
            e = text.find("\n", m.end())
            ins += [(m.start(), "| ", 0, False), (m.end(), " | ", 0, False), (len(text) if e < 0 else e, " |", 1, False)]
        elif r < 0.5:
            ins += [(m.start(1), "**", 0, False), (m.end(1), "**", 1, False)]
    # 同一位置：先放結尾、再放開頭；包值符號緊貼著值（結尾的先放、開頭的後放），表格線在外面
    ins.sort(key=lambda x: (x[0], x[2] == 0, (not x[3]) if x[2] == 1 else x[3]))
    out, pos = [], 0
    for p, w, _, _ in ins:
        out.append(text[pos:p] + w); pos = p
    out.append(text[pos:])
    shift = lambda p, start: sum(len(w) for q, w, side, _ in ins if q < p or (q == p and start))  # 同一位置插的符號（含前一個值的結尾）都在值的前面
    new = [dict(s, start=s["start"] + shift(s["start"], True), end=s["end"] + shift(s["end"], False)) for s in spans]
    return "".join(out), new


def build_markdown(rng):
    """Markdown 版副本（data/train/markdown_docs.jsonl）：合成文件三成。"""
    n = 0
    with open(f"{D}/train/markdown_docs.jsonl", "w") as f:
        for name in ("synth_pii_docs.jsonl", "synth_org_docs.jsonl", "synth_docs.jsonl"):
            for line in open(f"{D}/train/{name}"):
                if rng.random() >= 0.3:
                    continue
                d = json.loads(line)
                text, spans = markdownify(d["text"], d["spans"], rng)
                f.write(json.dumps(dict(d, id=d["id"] + "#md", text=text, spans=spans, src="markdown",
                                        annot=d.get("annot", ["person"])), ensure_ascii=False) + "\n")
                n += 1
    print(f"Markdown 版副本 {n} 份 → data/train/markdown_docs.jsonl")


def main():
    os.makedirs(f"{D}/train", exist_ok=True)
    build("raw_[0-9][0-9].jsonl", "synth_docs.jsonl", "synth", ["person"], random.Random(11))
    build("raw_pii_*.jsonl", "synth_pii_docs.jsonl", "synth_pii", ["person", "pii"], random.Random(12))
    build("raw_org_*.jsonl", "synth_org_docs.jsonl", "synth_org", ["person", "pii", "org"], random.Random(13))
    build_noisy(random.Random(14))
    build_markdown(random.Random(15))


if __name__ == "__main__":
    t8, sp8 = parse("⟦ORG:澄嶼公司⟧⟦P:王小明⟧到庭。")
    for seed in range(30):  # 兩個值緊鄰：後一個的起點要算進前一個的結尾符號
        t9, sp9 = markdownify(t8, sp8, random.Random(seed))
        assert [t9[s["start"]:s["end"]] for s in sp9] == ["澄嶼公司", "王小明"], (t9, sp9)
    t, sp = parse("請⟦P:王小明⟧先生與⟦P:王⟧太太、⟦K:賴清德⟧總統，王記牛肉麵。")
    assert t == "請王小明先生與王太太、賴清德總統，王記牛肉麵。" and [t[s["start"]:s["end"]] for s in sp] == ["王小明", "王", "賴清德"]
    t2, sp2 = resurrogate(t, [dict(s, text=t[s["start"]:s["end"]]) for s in sp], random.Random(0))
    names = [t2[s["start"]:s["end"]] for s in sp2]
    assert names[0][0] == names[1] and names[2] == "賴清德" and "王記牛肉麵" in t2, (t2, names)
    t3, sp3 = parse("⟦P:林怡君⟧手機⟦TEL:0912-118-406⟧，生日⟦BIRTH:78年5月12日⟧，⟦DATE:3/5⟧就診，客服 02-2345-6789。")
    t3, sp3 = resurrogate(t3, sp3, random.Random(0))
    t3 = randomize_values(t3, sp3, random.Random(0))
    got = [(t3[s["start"]:s["end"]], s["label"], s["group"]) for s in sp3]
    assert got[1][0].startswith("09") and len(got[1][0]) == 12 and got[1][0] != "0912-118-406", got
    assert got[2] == ("78年5月12日", "MASK", "pii") and got[3] == ("3/5", "KEEP", "pii") and "02-2345-6789" in t3, got
    t4, sp4 = parse("甲方⟦ORG:澄嶼顧問股份有限公司⟧（下稱⟦ORG:澄嶼公司⟧）款項匯入⟦ORGK:玉山銀行⟧，⟦P:陳志明⟧簽收。")
    for seed in range(6):  # 換到的那幾份：同品牌換成同一個假品牌、保留的機構與人名位置不受影響
        t5, sp5 = resurrogate_orgs(t4, [dict(s, text=t4[s["start"]:s["end"]]) for s in sp4], random.Random(seed))
        got = {s["tag"]: t5[s["start"]:s["end"]] for s in sp5 if s["tag"] != "ORG"}
        orgs = [t5[s["start"]:s["end"]] for s in sp5 if s["tag"] == "ORG"]
        assert got == {"ORGK": "玉山銀行", "P": "陳志明"} and orgs[0].endswith("顧問股份有限公司") and orgs[1].endswith("公司"), (t5, orgs)
        assert orgs[0][:2] == orgs[1][:2], orgs
    t6, sp6 = parse("員工姓名：⟦P:林建宇⟧\n出生年月日：⟦BIRTH:民國81年10月12日⟧\n公司統編 82937164，手機⟦TEL:0937-418-265⟧。")
    for seed in range(20):
        t7, sp7 = markdownify(t6, sp6, random.Random(seed))
        assert [t7[s["start"]:s["end"]] for s in sp7] == ["林建宇", "民國81年10月12日", "0937-418-265"], (t7, sp7)
        assert not re.search(r"[`*] \| |\| [`*]{1,2} ", t7), t7  # 包值符號緊貼著值，表格線在外面
    print("合成解析自檢 OK：", t2, "｜", t3, "｜", t5, "｜", t7.replace("\n", "⏎"))
    main()
