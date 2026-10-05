"""人名以外的個資候選：日期、號碼、英數代號、Email、網址、社群帳號、地址、字號。
跟人名候選一樣，程式只負責「找」而且刻意多抓（金額、案號、系統時間、機構電話全都會進來），要不要遮交給模型；
邊界不確定的地方（地址從哪裡開始、號碼要不要連分機）列出多種切法讓模型挑。
"""
from __future__ import annotations

import csv, functools, os, re

_D = "0-9０-９"
_CN = "〇○零一二三四五六七八九十"
_H = "一-鿿㐀-䶿"
_ASCII_END = ".,;:!?)]」』'\"`>"

EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+")
_URL_BODY = rf"[^\s，。、；！？「」『』（）()<>{_H}]+"
URL = re.compile(rf"(?:https?://|line://|www\.){_URL_BODY}|(?<![A-Za-z0-9@./])(?:[A-Za-z0-9\-]+\.)+(?:com|net|org|tw|cc|so|io|me|ly|gl|co|app)(?:\.[a-z]{{2}})?/{_URL_BODY}")
_PRE = r"(?:(?:中華民國|民國|西元)\s?)?"  # 空白只能跟在「民國」後面，不然候選會從前一個空白開始
DATES = [re.compile(p) for p in (
    rf"{_PRE}[{_D}]{{2,4}}\s?年\s?[{_D}]{{1,2}}\s?月\s?[{_D}]{{1,2}}\s?[日號]",
    rf"{_PRE}[{_D}]{{2,4}}\s?年\s?[{_D}]{{1,2}}\s?月",
    rf"(?<![{_D}年])[{_D}]{{1,2}}\s?月\s?[{_D}]{{1,2}}\s?[日號]",
    rf"(?<![{_D}./\-／])(?:[{_D}]{{4}}[-/.／][{_D}]{{1,2}}[-/.／][{_D}]{{1,2}}|[{_D}]{{2,3}}[/.／][{_D}]{{1,2}}[/.／][{_D}]{{1,2}}|[{_D}]{{1,2}}[/／][{_D}]{{1,2}})(?![{_D}])",
    rf"{_PRE}[{_CN}]{{2,4}}年[{_CN}]{{1,3}}月(?:[{_CN}]{{1,3}}[日號])?",
    r"(?<![A-Za-z])(?:\d{1,2} )?(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?(?: \d{1,2}(?:st|nd|rd|th)?(?!\d))?,?(?: \d{4})?(?![A-Za-z])",  # 12 March 1993、Oct 12、March 3, 1985
)]
ZI = re.compile(rf"字第\s?[{_D}A-Za-z\-]+\s?號")  # 從「字第」起算，前面的醫／藥師／物治／北市會證另外往前列
FW_ID = re.compile(rf"(?<![A-Za-zＡ-Ｚａ-ｚ])[Ａ-Ｚ][{_D}]{{7,10}}(?![{_D}])")  # 全形字母開頭的證號：Ｓ413894842
TOKEN = re.compile(r"(?<![A-Za-z0-9_@.\-])@?[A-Za-z0-9][A-Za-z0-9_.\-]*[A-Za-z0-9_](?![A-Za-z0-9_\-@])")
ASCII_RUN = re.compile(r"(?<![!-~])[!-~]{6,300}(?![!-~])")  # 含符號的密碼、金鑰（長串照掃，整串 64 字內才當候選）
_S = r" ?"  # 打字時常在數字前後留空白：中正路三段 266 號 5 樓之 2
_TAIL = re.compile(rf"{_S}(?:[{_CN}{_D}]+{_S}段{_S})?(?:[{_CN}{_D}]+{_S}巷{_S})?(?:[{_CN}{_D}]+{_S}弄{_S})?"
                   rf"(?P<hao>[{_CN}{_D}]+(?:-[{_D}]+)?(?:{_S}之{_S}[{_CN}{_D}]+)?{_S}號(?:{_S}之{_S}[{_D}]+)?)"
                   rf"(?P<lou>{_S}[{_CN}{_D}]+{_S}樓(?:{_S}之{_S}[{_CN}{_D}]+)?)?(?P<shi>{_S}[{_D}]+{_S}室)?")
CITIES = {c for x in ("臺北市 新北市 桃園市 臺中市 臺南市 高雄市 基隆市 新竹市 嘉義市 新竹縣 苗栗縣 彰化縣 南投縣 雲林縣 嘉義縣 "
                      "屏東縣 宜蘭縣 花蓮縣 臺東縣 澎湖縣 金門縣 連江縣").split() for c in (x, x.replace("臺", "台"))}
RURAL = re.compile(rf"[村里](?:{_S}[{_CN}{_D}]+{_S}鄰)?{_S}(?:[{_H}]{{1,4}}?)?[{_CN}{_D}]+(?:-[{_D}]+)?(?:之[{_D}]+)?{_S}號"
                   rf"(?:{_S}[{_CN}{_D}]+{_S}樓(?:之[{_CN}{_D}]+)?)?")  # 從「村／里」字起算，村名另外往前列
LOT = re.compile(rf"段{_S}(?:[{_H}]{{1,3}}小段{_S})?[{_D}]+(?:-[{_D}]+)?{_S}地號")  # 從「段」字起算，段名另外往前列
GENERIC_ROAD = re.compile(rf"(?:路|街|大道)(?=[{_CN}{_D}])")


@functools.lru_cache(None)
def _places():
    """內政部路名（taiwan_legal_deid/data/roads_a.csv）→ 路名、行政區、縣市；臺／台互通。"""
    roads, dists, cities = set(), set(), set()
    p = os.path.join(os.path.dirname(__file__), "data", "roads_a.csv")
    if os.path.exists(p):
        for row in csv.DictReader(open(p, encoding="utf-8-sig")):
            cities.add(row["city"]); dists.add(row["site_id"][len(row["city"]):]); roads.add(row["road"])
    alt = lambda s: s | {x.replace("臺", "台") for x in s} | {x.replace("台", "臺") for x in s}
    return alt(roads), alt(dists), alt(cities)


def _left_starts(text: str, s: int) -> set[int]:
    """路名（或村名）起點往左：可接 里／村＋鄰、行政區、縣市、郵遞區號；每一層都是一種切法。
    村名、區名不知道幾個字（中文字貪婪比對會吃到前一層），長度都試，交給模型挑。"""
    _, dists, _ = _places()
    starts, cur_set = {s}, {s}
    nxt = set()
    for cur in cur_set:  # 里／村（＋鄰），中間可能有空白：龍泉村 7 鄰
        m = re.search(rf"[里村]{_S}(?:[{_CN}{_D}]+{_S}鄰{_S})?$", text[max(0, cur - 10):cur])
        if m:
            base = cur - len(m.group(0))  # 「村／里」字的位置
            nxt |= {base - k for k in (1, 2, 3) if base - k >= 0 and re.fullmatch(f"[{_H}]+", text[base - k:base])}
    starts |= nxt; cur_set |= nxt
    nxt = set()
    for cur in cur_set:  # 行政區：表裡有的取表；沒有的用「1～3 字＋區鄉鎮市」各種長度
        known = {cur - k for k in (4, 3, 2) if cur - k >= 0 and text[cur - k:cur] in dists}  # 文字開頭就是區名時起點不能變負的
        nxt |= known or {cur - 1 - k for k in (1, 2, 3) if cur - 1 - k >= 0 and text[cur - 1] in "區鄉鎮市"
                         and re.fullmatch(f"[{_H}]+", text[cur - 1 - k:cur - 1])}
    starts |= nxt; cur_set |= nxt
    nxt = {cur - 3 for cur in cur_set if text[max(0, cur - 3):cur] in CITIES}  # 縣市
    starts |= nxt; cur_set |= nxt
    for cur in cur_set:  # 郵遞區號
        z = re.search(rf"[{_D}]{{3,6}}\s?$", text[max(0, cur - 7):cur])
        if z and (cur - len(z.group(0)) == 0 or not re.match(rf"[{_D}]", text[cur - len(z.group(0)) - 1])):
            starts.add(cur - len(z.group(0)))
    return starts


def _right_ends(m: re.Match) -> list[int]:
    """門牌往右：到「號」、到「樓（之幾）」、到「室」各算一種切法。"""
    return [m.end(g) for g in ("hao", "lou", "shi") if m.group(g)]


def _addresses(text: str) -> set[tuple[int, int]]:
    roads, _, _ = _places()
    out = set()
    n = len(text)
    road_spans = set()
    for e in range(2, n + 1):  # 路名表裡的路：取最長的
        for k in range(8, 1, -1):
            if e - k >= 0 and text[e - k:e] in roads:
                road_spans.add((e - k, e)); break
    for m in GENERIC_ROAD.finditer(text):  # 路名表沒有的路：往前 1～4 字都列為起點
        e = m.end()
        for k in range(1, 5):
            if e - len(m.group(0)) - k >= 0 and re.fullmatch(f"[{_H}]+", text[e - len(m.group(0)) - k:e - len(m.group(0))]):
                road_spans.add((e - len(m.group(0)) - k, e))
    for s, e in road_spans:
        tm = _TAIL.match(text, e)
        if not tm:
            continue
        for st in _left_starts(text, s):
            for en in _right_ends(tm):
                out.add((st, en))
    for rx in (RURAL, LOT):
        for m in rx.finditer(text):
            for k in range(1, 5):  # 村名、段名不知道幾個字：往前 1～4 字都列為起點（中文字貪婪比對會吃到前面的區名）
                s = m.start() - k
                if s < 0 or not re.fullmatch(f"[{_H}]+", text[s:m.start()]):
                    break
                for st in _left_starts(text, s):
                    out.add((st, m.end()))
    return out


def _numbers(text: str) -> set[tuple[int, int]]:
    """數字串：用 - 空白 括號 換行 串起來的一整串、以及其中每一段連續子串（電話、帳號、卡號、證號、驗證碼都在這）。
    千分位金額、小數不列；緊貼英文字母的數字照列（簡訊 OTP709484 的驗證碼），整串英數另外由英數代號抓。"""
    runs = []
    for m in re.finditer(f"[{_D}]+", text):
        s, e = m.span()
        prev, nxt = text[s - 1:s], text[e:e + 1]
        digit = lambda c: bool(re.match(f"[{_D}]", c or "x"))
        thousands = (prev == "," and digit(text[s - 2:s - 1]) and e - s == 3) or \
                    (nxt == "," and re.match(rf"[{_D}]{{3}}(?![{_D}])", text[e + 1:e + 5]))  # 只有「,」後正好三位數才是千分位（CSV 的逗號不是）
        decimal = (prev == "." and digit(text[s - 2:s - 1])) or (nxt == "." and digit(text[e + 1:e + 2]))
        if thousands or decimal:
            continue
        runs.append((s, e))
    out, i = set(), 0
    while i < len(runs):
        j = i
        while j + 1 < len(runs) and re.fullmatch(r"[-－ 、]|[)）] ?|[)）]-|-?\r?\n", text[runs[j][1]:runs[j + 1][0]]):  # 換行、頓號（9、8、0）也可能在號碼中間；全形括號的區碼（02）
            j += 1
        lead = re.search(r"(?:[A-Z] ){1,2}$", text[max(0, runs[i][0] - 4):runs[i][0]])  # 逐字唸的證號：G 1 3 7 9 …
        if lead and sum(r[1] - r[0] for r in runs[i:j + 1]) >= 6:
            out.add((runs[i][0] - len(lead.group(0)), runs[j][1]))
        for a in range(i, j + 1):
            for b in sorted(set(range(a, min(j, a + 5) + 1)) | {j}):  # 子串最多 6 段，另加「一路到底」（逐字唸、復原碼）
                s, e = runs[a][0], runs[b][1]
                if sum(r[1] - r[0] for r in runs[a:b + 1]) < 3:
                    continue
                ext = re.match(rf"\s?(?:#|轉|分機|ext\.?)\s?[{_D}]{{1,5}}", text[e:])
                for st in [s] + ([s - 1] if s > 0 and text[s - 1] in "+(（#" else []):  # 國碼的 +、區碼的括號、只寫分機的 #214
                    for en in [e] + ([e + len(ext.group(0))] if ext else []) + ([e + 1] if text[e:e + 1] == "#" else []):  # 分機、門鎖密碼 1805#
                        out.add((st, en))
        i = j + 1
    return out


_WS = " 　\n\r\t"
_ZERO, _ONE = set("OoＯ〇○"), set("lIｌＩ|")
_JUNK = set("^|_•⑴⑵⑶¦¬`")  # 掃描件夾在值中間的亂碼（永康區大； ^灣 里…：一個字被讀成「； ^」）
_JUNK_RUN = re.compile(r"[\s；;^|_•⑴⑵⑶¦¬`~'·]{1,6}")
_FW_D = {chr(0xFF10 + i): str(i) for i in range(10)}


def _normalize(text: str) -> tuple[str, list[int]]:
    """OCR／PDF 轉出來的雜訊容錯版：數字、日期、地址中間被插入的空白與換行拿掉；數字旁的 O、l、I 當成 0、1；
    全形數字轉半形；數字後的「曰」當成「日」。回傳 (乾淨版, 乾淨版每個字對回原文的位置)。"""
    isd = lambda c: c.isdigit() or c in _FW_D
    cjk = lambda c: bool(c) and "一" <= c <= "鿿"
    asc = lambda c: bool(c) and "!" <= c <= "~"
    word = lambda c: bool(c) and (isd(c) or cjk(c) or c in _ZERO | _ONE)
    out, idx = [], []
    n = len(text)
    drop = set()
    for m in _JUNK_RUN.finditer(text):  # 兩個字中間夾的一段亂碼（連同旁邊的空白、分號）整段拿掉；只有空白、分號的不算亂碼
        a, b = m.span()
        if any(ch in _JUNK for ch in m.group(0)) and a > 0 and b < n and word(text[a - 1]) and word(text[b]):
            drop.update(range(a, b))
    for i, c in enumerate(text):
        if i in drop:
            continue
        prev, nxt1 = (out[-1] if out else ""), (text[i + 1] if i + 1 < n else "")
        if c in _WS:  # 連續空白也算（「舒 ⏎妍麗」：行尾空白＋換行）：看前後第一個不是空白的字
            nw = next((x for x in text[i + 1:i + 6] if x not in _WS), "")
            if word(prev) and word(nw) and (isd(prev) or isd(nw) or (cjk(prev) and cjk(nw))):
                continue
        if c in "\n\r" and asc(prev) and asc(nxt1):  # Email、網址、帳號被斷行（yahoo.co⏎m.tw）
            continue
        if c in "~'·" and prev and nxt1 and (word(prev) or asc(prev)) and (word(nxt1) or asc(nxt1)) and not (c == "·" and cjk(prev) and cjk(nxt1)):
            continue  # 雜點（09'21、台北~市）；中文字之間的 · 是音譯名的間隔號，不拿掉
        prev = out[-1] if out else ""
        nxt = next((x for x in text[i + 1:i + 3] if x not in _WS), "")
        if c in _ZERO and (isd(prev) or isd(nxt)):
            c = "0"
        elif c in _ONE and (isd(prev) or isd(nxt)):
            c = "1"
        elif c == "曰" and isd(prev):
            c = "日"
        out.append(_FW_D.get(c, c)); idx.append(i)
    return "".join(out), idx


def pii_candidates(text: str) -> list[tuple[int, int, str]]:
    """原文找一次；OCR 容錯版再找一次、位置對回原文（多抓不少抓，判斷照樣交給模型）。"""
    out = set(_raw_candidates(text))
    norm, idx = _normalize(text)
    if norm != text:
        for s, e, k in _raw_candidates(norm):
            out.add((idx[s], idx[e - 1] + 1, k))
    return sorted(out)


def _raw_candidates(text: str) -> list[tuple[int, int, str]]:
    out: set[tuple[int, int, str]] = set()
    taken = []
    for m in EMAIL.finditer(text):
        out.add((m.start(), m.end(), "email")); taken.append(m.span())
    for m in URL.finditer(text):
        e = m.end()
        while e > m.start() and text[e - 1] in _ASCII_END:
            e -= 1
        out.add((m.start(), e, "url")); taken.append((m.start(), e))
    inside = lambda s, e: any(a <= s and e <= b for a, b in taken)
    for rx in DATES:
        for m in rx.finditer(text):
            s, e = m.span()
            out.add((s, e, "date"))
            pre = re.match(r"(?:中華民國|民國|西元)\s?", text[s:e])
            if pre:
                out.add((s + len(pre.group(0)), e, "date"))
    for s, e in _numbers(text):
        if not inside(s, e):
            out.add((s, e, "num"))
    for m in TOKEN.finditer(text):
        s, e = m.span()
        if inside(s, e) or len(m.group(0).lstrip("@")) < 3:
            continue
        t = m.group(0)
        kind = "alnum" if re.search("[0-9]", t) and re.search("[A-Za-z]", t) else ("handle" if re.search("[A-Za-z]", t) else None)
        if kind:
            out.add((s, e, kind))
            if t.startswith("@"):
                out.add((s + 1, e, kind))
    for m in ASCII_RUN.finditer(text):
        s, e = m.span()
        while s < e and text[s] in "`'\"(<[=:":  # 「=0x78…」「:abc」前面的符號不是值的一部分（不拿掉會跟「0x78…」變成兩個值）
            s += 1
        ends = {e}
        while e > s and text[e - 1] in _ASCII_END:  # 結尾的 ! . 可能是密碼的一部分，也可能是標點：兩種都列
            e -= 1; ends.add(e)
        for en in ends:
            t = text[s:en]
            if 6 <= len(t) <= 64 and not inside(s, en) and re.search("[0-9]", t) and re.search("[A-Za-z]", t):
                out.add((s, en, "alnum"))
        run = text[s:e]  # 藏在設定字串裡的值：DB_PASSWORD=…、密碼@主機、token=…（網址裡也算）
        for rx in (r"(?<=[=:])[^\s&=]{6,}", r"[^\s@/:=]{6,}(?=@)"):  # 分開比對：同一個正則會互相吃掉重疊的部分
            for v in re.finditer(rx, run):
                if re.search("[0-9]", v.group(0)) and re.search("[A-Za-z]", v.group(0)):
                    out.add((s + v.start(), s + v.end(), "alnum"))
    for m in FW_ID.finditer(text):
        out.add((m.start(), m.end(), "alnum"))
    for m in ZI.finditer(text):
        for k in range(1, 5):  # 醫字、藥師字、物治字、北市會證字：前面幾個字不一定
            if m.start() - k >= 0 and re.fullmatch(f"[{_H}]+", text[m.start() - k:m.start()]):
                out.add((m.start() - k, m.end(), "zi"))
    for s, e in _addresses(text):
        out.add((s, e, "addr"))
    return sorted(out)


if __name__ == "__main__":
    t = ("王先生 生日：民國78年5月12日，手機 0912-118-406、+886 935 221 087，市話 (02)2345-6789#205，"
         "Email chen.yuting@gmail.com，IG https://www.instagram.com/yuting_daily/。LINE ID：@metro_chen88，"
         "身分證 F128394015，帳號 013-123456789012，卡號 4311 9522 1087 3356，驗證碼 827103，密碼 Ab#29xQ!77，"
         "車牌 BKR-5821，住 114066 臺北市內湖區瑞光路999巷88號7樓，戶籍 南投縣信義鄉望美村3鄰12號，"
         "醫字第098765號，113年度訴字第123號，金額 3,500 元，2023/11/25 就診，10/27 出貨，一一二年五月十日。住家電話：（02）2736-5188。")
    got = {(t[s:e], k) for s, e, k in pii_candidates(t)}
    assert ("（02）2736-5188", "num") in got, "全形括號的區碼"
    for want in [("民國78年5月12日", "date"), ("78年5月12日", "date"), ("0912-118-406", "num"), ("+886 935 221 087", "num"),
                 ("(02)2345-6789#205", "num"), ("chen.yuting@gmail.com", "email"), ("https://www.instagram.com/yuting_daily/", "url"),
                 ("@metro_chen88", "alnum"), ("metro_chen88", "alnum"), ("F128394015", "alnum"), ("013-123456789012", "num"),
                 ("4311 9522 1087 3356", "num"), ("827103", "num"), ("Ab#29xQ!77", "alnum"), ("BKR-5821", "alnum"),
                 ("114066 臺北市內湖區瑞光路999巷88號7樓", "addr"), ("瑞光路999巷88號", "addr"), ("南投縣信義鄉望美村3鄰12號", "addr"),
                 ("醫字第098765號", "zi"), ("2023/11/25", "date"), ("10/27", "date"), ("一一二年五月十日", "date")]:
        assert want in got, want
    assert not any(x == "3,500" or x == "500" for x, _ in got), "千分位金額不該是候選"
    t2 = "居住所： 臺南市永康區大； ^灣 里 7鄰大勇路二段 2 5號4樓\n出生年月日 73/1 1/05"  # 掃描件：村里名一個字被讀成亂碼、號碼和日期中間斷開
    got2 = {t2[s:e] for s, e, k in pii_candidates(t2)}
    assert "臺南市永康區大； ^灣 里 7鄰大勇路二段 2 5號4樓" in got2 and "73/1 1/05" in got2, got2
    t4 = "我的生日是12 March 1993，March 3, 1985 另案。"  # 月份後面的「日」不能吃掉年份的前兩碼（12 March 19）
    got4 = {t4[s:e] for s, e, k in pii_candidates(t4) if k == "date"}
    assert {"12 March 1993", "March 3, 1985"} <= got4 and "12 March 19" not in got4, got4
    for t3 in ("安區瑞光路99號", "大安區瑞光路99號", "區瑞光路99號"):  # 區名在文字最開頭（視窗剛好從這裡切）：起點不能是負的
        assert all(0 <= s < e <= len(t3) for s, e, k in pii_candidates(t3)), [(s, e) for s, e, k in pii_candidates(t3)]
    print(f"個資候選自檢 OK：{len(got)} 個候選，{len(t)} 字")
