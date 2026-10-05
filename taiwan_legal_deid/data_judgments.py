"""公開判決（著作權法§9 I① 不受著作權保護）→ 段落級訓練文件：名冊上的人名先一致地換成假名（模型不看真名），記下位置與標籤。
標籤：MASK（當事人、證人等私人；法院已遮的「王○明」補成假名）、KEEP（尾部執行職務的法官／書記官，以律師身分出現的代理人／辯護人）。
名冊以外、內文裡的其他名字沒有標籤（訓練時不計 loss，見 examples.py），不會被當成「不是人名」。
用法：python -m taiwan_legal_deid.data_judgments <裁判書快取.db> → data/train/judg_docs.jsonl（SQLite，judgment_cache 表：cache_key、data_json）
"""
from __future__ import annotations

import collections, json, os, random, re, sqlite3, sys

from .candidates import CJK, surname_len
from .names import TRAIN_WILD, sample_name, sample_surname
from .surnames import COMMON_CHAR

DB = sys.argv[1] if len(sys.argv) > 1 else None
OUT = os.path.join(os.path.dirname(__file__), "..", "data", "train", "judg_docs.jsonl")
WS = re.compile(r"[ \t　]+")
PRIVATE_ROLES = ["附帶民事訴訟原告", "附帶民事訴訟被告", "再審原告", "再審被告", "再抗告人", "被上訴人", "法定代理人", "抗告人", "上訴人", "告訴人",
                 "自訴人", "聲請人", "相對人", "受刑人", "債權人", "債務人", "被害人", "參加人", "異議人", "受處分人", "代表人", "被告", "原告"]
COUNSEL_ROLES = ["選任辯護人", "指定辯護人", "訴訟代理人", "複代理人", "辯護人", "代理人"]
OFFICIAL_ROLES = ["審判長法官", "受命法官", "陪席法官", "司法事務官", "法官助理", "書記官", "檢察官", "法官", "通譯"]
ORG_SUFFIX = ("公司", "銀行", "檢察署", "法院", "政府", "局", "處", "署", "會", "部", "所", "廠", "社", "行", "店", "中心", "醫院", "學校",
              "大學", "協會", "基金會", "機關", "分局", "隊", "廟", "宮", "寺", "堂", "司令部")
STOP = ("以上", "中華", "本件", "如不", "附錄", "附表", "得上", "不得", "上列", "附件", "正本", "到庭", "提起", "偵查", "聲請", "起訴", "追加",
        "移送", "執行", "律師", "於本", "等人", "選任", "指定", "訴訟", "代理", "法定", "被告", "被上", "上訴", "原告", "輔佐", "共同", "民國",
        "之", "等", "及", "與", "為", "係", "均", "亦", "即", "兼", "所", "因", "男", "女", "對", "向", "在", "於", "則", "將", "就", "已",
        "並", "而", "稱", "供", "證", "表", "主", "上", "下", "（", "(", "\n")
MASKED = re.compile(r"(歐陽|張簡|范姜|司馬|[一-鿿])([○Ｏ〇◯OＯ][○Ｏ〇◯OＯ一-鿿])")
STEMS = set("甲乙丙丁戊己庚辛壬癸")  # 天干代號（丁○○）不是人名
TITLE_AFTER = ("男", "女", "姓", "某")


def spaced(word):
    return r"[ \t　]*".join(map(re.escape, word))


def role_re(roles):
    return re.compile("|".join(spaced(r) for r in sorted(roles, key=len, reverse=True)))


R_PRIV, R_COUN, R_OFF = role_re(PRIVATE_ROLES), role_re(COUNSEL_ROLES), role_re(OFFICIAL_ROLES)


def take_name(s, i):
    """從 s[i] 起讀一個人名；邊界不明確就放棄（寧缺勿濫，標籤要乾淨）。"""
    i0 = i
    while i < len(s) and s[i] in " \t　\n":
        i += 1
    run = ""
    while i + len(run) < len(s) and len(run) < 6 and CJK.match(s[i + len(run)]):
        run += s[i + len(run)]
    sl = surname_len(run)
    if not sl or (i == i0 and run[:sl] in COMMON_CHAR):  # 常用字姓緊接在職稱後面多半不是名字（辯護人應選任律師、大法官解釋）
        return None
    for n in (sl + 2, sl + 1):
        if n <= len(run) and (n == len(run) or s[i + n:i + n + 2].startswith(STOP) or s[i + n] in STOP):
            return run[:n]
    return None


def roster(t):
    """{姓名: 'MASK'|'KEEP'}；同一個名字兩種角色就丟掉。"""
    got = collections.defaultdict(set)
    m = re.search(r"上\s*列|主\s*文", t[:5000])
    head = t[:m.start() if m else 1500]
    for m in R_PRIV.finditer(head):
        ent = WS.sub(" ", head[m.end():m.end() + 30]).strip().split(" ")[0]
        if len(ent) >= 4 and any(ent.endswith(h) or (h + "兼") in ent for h in ORG_SUFFIX):
            continue
        n = take_name(head, m.end())
        if n:
            got[n].add("MASK")
    for m in R_COUN.finditer(t):
        n = take_name(t, m.end())
        if n and WS.sub("", t[m.end():m.end() + 16]).replace("\n", "").startswith(n + "律師"):
            got[n].add("KEEP")
    for m in R_OFF.finditer(t, max(0, len(t) - 2500)):
        n = take_name(t, m.end())
        if n:
            got[n].add("KEEP")
    return {n: next(iter(v)) for n, v in got.items() if len(v) == 1}


def build_doc(t, rng):
    """回傳 (換名後全文, spans)。spans：[{start, end, label}]"""
    t = WS.sub(" ", t)
    rost = roster(t)
    names = dict(rost)
    for m in MASKED.finditer(t):  # 法院已遮的名字：一律 MASK，補成假名
        if m.group(1) not in STEMS and surname_len(m.group(1)):
            names.setdefault(m.group(0), "MASK")
    if not names:
        return None, []
    taken = set(names)
    sub = {}
    for n in names:  # 假名長度不必跟原名一樣：順便擴增兩字名、複姓（原始判決 98% 是三字名）
        r = rng.random()
        if r < 0.12:
            sub[n] = sample_name(rng, length=2, compound=False, avoid=taken, wild=TRAIN_WILD)
        elif r < 0.20:
            sub[n] = sample_name(rng, length=rng.choice((3, 4, 4)), compound=True, avoid=taken, wild=TRAIN_WILD)
        elif r < 0.24:  # 冠夫姓（林徐阿嬌）
            sub[n] = sample_name(rng, length=4, compound=False, avoid=taken, wild=TRAIN_WILD)
        else:
            sub[n] = sample_name(rng, length=3, compound=False, avoid=taken, wild=TRAIN_WILD)
        taken.add(sub[n])
    # 部分稱呼（王男、王姓）：只有一個名冊人物是這個姓時才跟著換
    by_sur = collections.defaultdict(list)
    for n in names:
        by_sur[n[:surname_len(n) or 1]].append(n)
    partial = {s + suf: (ns[0], s) for s, ns in by_sur.items() if len(ns) == 1 for suf in TITLE_AFTER}
    keys = sorted(list(names) + list(partial), key=len, reverse=True)
    rx = re.compile("|".join(map(re.escape, keys)))
    out, spans, pos = [], [], 0
    for m in rx.finditer(t):
        out.append(t[pos:m.start()]); cur = sum(map(len, out))
        k = m.group(0)
        if k in names:
            new = sub[k]; spans.append({"start": cur, "end": cur + len(new), "label": names[k]})
        else:
            n, s = partial[k]
            new_sur = sub[n][:len(s)]
            new = new_sur + k[len(s):]; spans.append({"start": cur, "end": cur + len(new_sur), "label": names[n]})
        out.append(new); pos = m.end()
    out.append(t[pos:])
    return "".join(out), spans


_O = "○Ｏ〇"
ACCT0 = re.compile(r"(?<![0-9A-Za-z])0{2,4}-0{6,16}(?![0-9])|(?<![0-9A-Za-z\-])0{10,16}(?![0-9\-])")
ID0 = re.compile(r"(?<![A-Za-z0-9])[A-Z]0{9,10}(?![0-9])")
BIRTH0 = re.compile(r"(?:民國)?0{2,3}年0{1,2}月0{1,2}日(?=生)")
ADDR0 = re.compile(rf"[{_O}]{{1,3}}[市縣]?[{_O}]{{1,3}}[區鄉鎮市][{_O}0一-鿿]{{0,20}}?號(?:之[0{_O}]+)?(?:[0{_O}]+樓(?:之[0{_O}]+)?)?")


def fill_masked_pii(text, spans, rng):
    """法院已遮的個資（帳號 000-000000000000、證號 Z000000000、生日 00年0月00日生、地址 ○○市○○區○○路000號）→ 擬真假值，
    標成要遮的個資（group＝pii）。其餘號碼、日期沒有標籤（訓練時不計 loss）。"""
    from .fakes import fake_address, fake_birth, fake_digits, fake_id
    from .pii_candidates import CITIES
    gens = ((ACCT0, "ACCT", lambda m, c: fake_digits(rng, m.group(0))),
            (ID0, "ID", lambda m, c: fake_id(rng) if len(m.group(0)) == 10 else m.group(0)[0] + fake_digits(rng, m.group(0)[1:])),
            (BIRTH0, "BIRTH", lambda m, c: ("民國" if m.group(0).startswith("民國") else "") + fake_birth(rng)),
            (ADDR0, "ADDR", lambda m, c: fake_address(rng, city=c)))
    repls = []
    for rx, tag, gen in gens:
        for m in rx.finditer(text):
            s, e = m.span()
            city = None
            if tag == "ADDR":  # 判決常只遮區以下（臺中市○○區…）：前面真的縣市併進地址，假地址從同一縣市挑
                pre = re.search(r"(\S{3}) ?$", text[max(0, s - 4):s])
                if pre and pre.group(1) in CITIES:
                    city, s = pre.group(1), s - len(pre.group(0))
            if any(a < e and b > s for a, b, *_ in repls) or any(x["start"] < e and x["end"] > s for x in spans):
                continue
            if tag == "ADDR" and re.search(r"(設|營業所|事務所|所在地)[：:]?\s*$", text[max(0, s - 6):s]):
                tag = None  # 法院連公司登記地址也遮，但我們的口徑是公司地址不遮：照樣補值、不給標籤
            repls.append((s, e, gen(m, city), tag))
    if not repls:
        return text, spans
    repls.sort()
    out, new_spans, marks, pos = [], [], [], 0
    for s, e, new, tag in repls:
        out.append(text[pos:s]); cur = sum(map(len, out))
        if tag:
            new_spans.append({"start": cur, "end": cur + len(new), "label": "MASK", "group": "pii", "tag": tag})
        out.append(new); pos = e; marks.append((e, len(new) - (e - s)))
    out.append(text[pos:])
    mv = lambda p: p + sum(d for e, d in marks if e <= p)
    new_spans += [dict(x, start=mv(x["start"]), end=mv(x["end"])) for x in spans]
    return "".join(out), sorted(new_spans, key=lambda x: x["start"])


def main():
    if not DB:
        sys.exit(__doc__)
    rng = random.Random(7)
    rows = sqlite3.connect(DB).execute("select cache_key, data_json from judgment_cache").fetchall()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    n_doc = 0; lab = collections.Counter()
    with open(OUT, "w") as f:
        for key, dj in sorted(rows):
            d = json.loads(dj)
            t = (d.get("full_text") or "") if isinstance(d, dict) else ""
            if len(t) < 800:
                continue
            text, spans = build_doc(t, rng)
            if not spans:
                continue
            text, spans = fill_masked_pii(text, spans, random.Random(key))  # 每份自己的亂數：不影響上面假名的抽樣順序
            n_doc += 1; lab.update(s.get("tag", s["label"]) for s in spans)
            f.write(json.dumps({"id": key, "text": text, "spans": spans, "src": "judgment"}, ensure_ascii=False) + "\n")
    print(f"判決 {n_doc} 份 → {OUT}；標籤 {dict(lab)}")


if __name__ == "__main__":
    main()
