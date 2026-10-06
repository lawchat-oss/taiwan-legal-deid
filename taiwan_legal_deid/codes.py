"""代號版：人名換成甲、乙…，機構換成 A公司…，號碼換成〔號碼1〕…，生日只留年、地址只留縣市。
- CodeObfuscator：留對照表＝假名化的代號版（Obfuscator(style="code") 用它），可以把 AI 回覆換回原文。
- Anonymizer：不留對照表＝匿名化，無法還原；同一個物件連續處理的文件代號一致（代號表只在這個物件裡）。
偵測跟擬真版共用，差別只在換成什麼：
- 人名：同一個人整份一致，稱謂照留（甲小姐）。只寫姓（陳小姐）、只寫名字（美玲）、綽號（阿玲、玲姐）能唯一對到這份文件裡的全名，
  就用那個人的代號；對到好幾個（同姓多人）寫「〇」——寧可前後不一致，也不把兩個人併成同一個代號；一個都對不到就自己給一個代號。
- 機構：A公司（類型字尾照留：A商行、A診所；英文名 Company A）。下稱別名、上市櫃簡稱、單獨出現的品牌換成同一個字母（A）。
- 號碼、Email、網址、社群帳號：〔身分證1〕〔電話1〕〔Email1〕〔網址1〕〔帳號1〕〔號碼1〕，同一個值同一個編號；地號、建號〔地號1〕。
- 生日只留年；地址只留縣市（addr="district" 留到鄉鎮市區），其餘〔地址1〕。
- 個人行程日期 event_dates、其他日期（判決日、起訴日）other_dates：keep 照留／month 只留年月／year 只留年。
- 代號避開原文已經用過的（甲方、A 棟、〔號碼1〕）；anonymize_many() 一次處理多份時先掃過全部原文。
"""
from __future__ import annotations

import functools, itertools, re, warnings

from .candidates import surname_len
from .obfuscate import (_BDAY_RX, _FW2HW, _JUNK, _MONTHS, _ORG_TOKENS, PERSON_CODES, PROP_TITLES, RESTORE_TITLES, Obfuscator,
                        _canon, _common, _gnorm, _guard, _parse_date, _places_set)
from .org_candidates import SUFFIXES
from .pii_candidates import CITIES, DATES, _places

_LEVELS = ("keep", "month", "year")
_TITLES = sorted(RESTORE_TITLES, key=len, reverse=True)
_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_COMPANY = {"股份有限公司", "有限公司", "無限公司", "兩合公司", "公司", "股份有限公", "有限公"}
_ORG_FORMS = sorted(set(SUFFIXES) | {"管理委員會", "委員會", "協會", "學會", "基金會", "工會", "診所", "醫院", "學校", "補習班", "幼兒園",
                                     "中心", "工作室", "事務所", "合作社", "教會"}, key=len, reverse=True)
_TOKEN_RX = re.compile(r"[〔\[【]([^〔〕\[\]【】]{1,16})[〕\]】]")
_LETTER_RX = re.compile(r"(?<![A-Za-z])([A-Z])(?![A-Za-z])")
_FULL = ("full", "latin", "translit")


@functools.lru_cache(None)
def _cities_dists():
    return sorted(CITIES, key=len, reverse=True), sorted(_places()[1], key=len, reverse=True)


def _has(c, text):
    """原文裡有沒有這個代號：結尾是數字的（人物1、甲2）不比對到更長的編號（人物12）。"""
    return re.search(r"\s*".join(map(re.escape, c)) + (r"(?!\d)" if c[-1].isdigit() else ""), text) is not None  # 中間夾空白也算（還原時不管空白）


def _scan(text):
    """原文已經用過的代號（已經去識別化過的文件：甲、乙、A 公司、〔號碼1〕）：天干字、單獨的英文大寫字母、括號裡的編號。"""
    hw = text.translate(_FW2HW)  # 還原時不管空白（〔電話 1〕＝〔電話1〕），預留時也一樣；備用代號（人物1、機構1）也算
    tokens = {re.sub(r"\s", "", x) for x in _TOKEN_RX.findall(hw)} | {re.sub(r"\s", "", x) for x in re.findall(r"(?:人\s*物|機\s*構)\s*\d+", hw)}
    return {c for c in PERSON_CODES if c in text}, set(_LETTER_RX.findall(hw)), tokens


def _label(v, typ):
    hw = re.sub(r"\s", "", v.translate(_FW2HW))
    if typ == "EMAIL":
        return "Email"
    if typ == "URL":
        return "網址"
    if typ == "HANDLE" or (typ == "CODE" and re.fullmatch(r"@?[a-z][a-z0-9_.]{2,}", hw) and re.search("[a-z]{3}", hw)):
        return "帳號"
    if re.fullmatch(r"[A-Z][12]\d{8}", hw):
        return "身分證"
    d = re.sub(r"\D", "", hw)
    if re.fullmatch(r"(?:886|0)9\d{8}", d) or (re.fullmatch(r"0[2-8]\d{7,8}", d) and re.search(r"[-()（）]", hw)):
        return "電話"
    return "號碼"


def _coarse(s, level):
    """日期粗化：year 只留年、month 只留年月（沒寫年就只留月）。解析不出來回 None（呼叫端整個遮掉）。"""
    p = _parse_date(s)
    if not p or not 1 <= p[1] <= 12 or (level == "year" and p[0] is None):
        return None
    y, mo, _ = p
    if re.search(r"[A-Za-z]", s):
        return str(y) if level == "year" else f"{_MONTHS[mo - 1]} {y}" if y is not None else _MONTHS[mo - 1]
    head = ("民國" if "民國" in s else "") + (f"{y}年" if y is not None else "")
    return head if level == "year" else head + f"{mo}月"


def _org_form(name, default="公司"):
    """代號後面接的類型：公司（各種公司字尾都寫成公司）、商行、診所…；沒有類型字尾回 default；英文名回 None（寫成 Company A）。"""
    core = re.sub(r"\s", "", name)
    if not re.search("[一-鿿]", core):
        return None
    suf = next((x for x in _ORG_FORMS if core.endswith(x) and len(x) < len(core)), None)
    return default if suf is None else "公司" if suf in _COMPANY else suf


def _brands(name):
    """名稱拿掉法律形式、產業詞、縣市後剩下的品牌（岱昀顧問股份有限公司 → 岱昀）：單獨出現（岱昀表示…）也換。"""
    core = re.sub(r"\s", "", name)
    for w in _ORG_TOKENS:
        core = core.replace(w, " ")
    return [b for b in core.split() if len(b) >= 2 and re.search("[一-鿿]", b)]


class CodeObfuscator:
    """代號版的替換（見檔頭）。mapping：同一案件前面文件的對照表（代號版），沿用同一套代號。"""

    def __init__(self, detector=None, mapping=None, event_dates="keep", addr="city", other_dates="keep"):
        if event_dates not in _LEVELS or other_dates not in _LEVELS or addr not in ("city", "district"):
            raise ValueError(f"event_dates／other_dates 只能是 {_LEVELS}，addr 只能是 city 或 district")
        self.det, self.event_dates, self.other_dates, self.addr = detector, event_dates, other_dates, addr
        self.entries = [dict(e) for e in mapping or []]  # 複製：標 ambiguous 不會動到呼叫端手上的對照表
        live = [e for e in self.entries if e.get("key") and not e.get("ambiguous")]
        self.codes = {e["key"]: e["c"] for e in live if not e.get("alias")}  # 對象 → 代號（p 人、s 只寫姓、g 只寫名字、n 綽號、o 機構、t 號碼）
        self.fakes = {e["key"]: e["fake"] for e in live if not e.get("alias")}  # 對象 → 文件裡寫成的樣子（甲、A公司、〔號碼1〕）
        self.origs = {e["key"]: e["original"] for e in live if not e.get("alias")}
        self.types = {e["key"]: e["type"] for e in live if not e.get("alias")}
        self.aliases = {e["key"]: e["c"] for e in live if e.get("alias")}  # 別名、品牌 → 機構的 key（跟著機構的字母走）
        self.alias_tpl = {e["key"]: e.get("tpl", "{c}") for e in live if e.get("alias")}  # 別名寫成的樣子：品牌字換成字母（麒碩科技 → {c}科技）
        self.reserved = (set(), set(), set())
        self.events = set()  # 粗化過的個人行程日期（年月日）：同一天別處沒被抓到的寫法也粗化（只在記憶體，不進對照表）
        self.spans = []

    def reserve(self, texts):
        """先掃過這一批的原文：原文已經用的代號（甲方、A 棟、〔號碼1〕）一開始就不編。"""
        for t in texts:
            for have, new in zip(self.reserved, _scan(t)):
                have |= new
        self._fix("", self.reserved)  # 先前編好的代號撞到這批原文：整批開始前就換，同一批才一致

    def pseudonymize(self, text):
        return self.apply(text, self.det.detect(text))

    # ── 代號 ──────────────────────────────────────────────
    def _new(self, key, text, scan):
        used = set(self.codes.values()) | {e["c"] for e in self.entries if "c" in e}  # 停用過的代號也不再分給別人（同一案件的甲只代表一個人）
        chars, letters, tokens = (a | b for a, b in zip(self.reserved, scan))
        if key[0] == "t":
            return next(c for c in (f"{key.split(':')[1]}{n}" for n in itertools.count(1)) if c not in used and c not in tokens)
        pool, fallback = ([c for c in _LETTERS if c not in letters], "機構") if key[0] == "o" else ([c for c in PERSON_CODES if c not in chars], "人物")
        gen = itertools.chain(pool, (f"{c}{n}" for n in itertools.count(2) for c in pool)) if pool else (f"{fallback}{n}" for n in itertools.count(1))
        return next(c for c in gen if c not in used and not _has(c, text) and c not in tokens)

    def _code(self, key, text, scan):
        if key not in self.codes:
            self.codes[key] = self._new(key, text, scan)
        return self.codes[key]

    def _fix(self, text, scan):
        """前面文件編好的代號，在這份原文裡已經有別的意思（原文本來就有「乙」）：這份起改用新代號，兩個意思才不會混在一起。"""
        chars, letters, tokens = scan
        for key, c in list(self.codes.items()):
            hit = c in tokens if key[0] == "t" else c[0] in letters if key[0] == "o" and c[0] in _LETTERS else c[0] in chars if c[0] in PERSON_CODES else c in tokens or _has(c, text)
            if hit:
                new = self._new(key, text, scan)
                warnings.warn(f"代號「{c}」在這份原文裡已經有別的意思，從這份起改用「{new}」；同一批文件請用 anonymize_many() 一次處理", stacklevel=4)
                self.codes[key] = new
                for e in self.entries:  # 舊代號的對照（含「甲小姐」「A科技」這類衍生寫法）停用：舊代號在這份已經有別的意思，還原時不能再指這個人
                    if not e.get("alias") and (e.get("key") == key or e.get("of") == key):
                        e["ambiguous"] = True
                old = self.fakes.get(key)
                if old is not None:  # 立刻登錄新寫法：模型這份漏抓同一個名字時，後面的同值補換照樣換成新代號
                    fake = f"〔{new}〕" if key[0] == "t" else ("Company " + new if old.startswith("Company ") else new + old[len(c):]) if key[0] == "o" else new
                    self._entry(key, fake, self.origs[key], self.types.get(key, "PERSON"))

    def _alias_fake(self, akey, orig):
        """別名換成機構的字母：品牌字換掉、其餘照留（下稱麒碩科技 → A科技、岱昀公司 → A公司）；不是單獨字母、也不等於全名代號的寫法另記一筆，
        AI 回覆照抄「A科技」才換得回來（單獨的字母不還原）。"""
        o = self.aliases[akey]
        fake = self.alias_tpl.get(akey, "{c}").replace("{c}", self.codes[o])
        part = {"fake": fake, "original": orig, "type": "ORG_ALIAS", "code": True, "of": o}
        if fake not in (self.codes[o], self.fakes.get(o)) and part not in self.entries:
            self.entries.append(part)
        return fake

    def _entry(self, key, fake, orig, typ, **extra):
        """登錄一筆對照（同一個對象、同一個寫法只記一次）。"""
        if self.fakes.get(key) != fake or key not in self.origs:
            self.fakes[key] = fake
            self.origs.setdefault(key, orig)
            self.types.setdefault(key, typ)
            self.entries.append({"fake": fake, "original": orig, "type": typ, "code": True, "key": key, "c": self.codes[key], **extra})

    # ── 主流程 ──────────────────────────────────────────────
    def apply(self, text, spans):
        """spans：偵測結果（start、end、type、kind）。回傳 (代號版文字, 對照表)。"""
        scan = _scan(text)
        self._fix(text, scan)
        spans = Obfuscator._reconcile(text, spans)
        done = {k.split(":", 2)[-1] for k in self.codes if k[0] in "pot"} | {k[2:] for k in self.aliases}  # 同一案件前面已經判定要換的值（含別名），這份也照換
        aliases = {a for s in spans if s["type"] == "ORG" for a in Obfuscator._alias_names(text[s["start"]:s["end"]], text, s["end"])
                   if a not in _places_set() and a not in _common(300)}
        keep_events = self.event_dates == "keep"
        kept = lambda s: (s["type"] in ("PERSON_KEEP", "ORG_KEEP") or (keep_events and s["type"] == "DATE_EVENT")) and not (
            s["type"] == "ORG_KEEP" and any(a in _canon(text[s["start"]:s["end"]]) for a in aliases)) and _canon(text[s["start"]:s["end"]]) not in done
        masked = {_canon(text[s["start"]:s["end"]]) for s in spans if not kept(s)}
        keep = [(s["start"], s["end"]) for s in spans if kept(s) and _canon(text[s["start"]:s["end"]]) not in masked]
        is_full = lambda s: s["type"].startswith("PERSON") and (s.get("kind", "full") in _FULL or re.search(r"[A-Za-z·‧・．]", text[s["start"]:s["end"]]))
        todo = sorted((s for s in spans if (s["start"], s["end"]) not in keep), key=lambda s: (not is_full(s), s["start"]))  # 全名先編，代號照出現順序
        fulls = {}  # 這份文件裡要換的全名（去空白）→ (姓, 名字)；外文名、找不到姓的不拿來對
        for s in todo:
            if is_full(s):
                core = re.sub(r"[ 　\n]", "", text[s["start"]:s["end"]])
                sl = 0 if re.search(r"[A-Za-z·‧・．]", core) else surname_len(core)
                fulls.setdefault(core, (core[:sl], core[sl:]) if sl and len(core) > sl else ("", ""))
        for k in self.codes:  # 前面文件登錄過、這份也出現但模型沒抓到的全名：一樣拿來對只寫姓、名字的稱呼（後面的同值補換也會換掉它）
            core = k[2:]
            if k[0] == "p" and core not in fulls and re.search((_JUNK + "{0,3}").join(map(re.escape, core)), text):
                sl = 0 if re.search(r"[A-Za-z·‧・．]", core) else surname_len(core)
                fulls[core] = (core[:sl], core[sl:]) if sl and len(core) > sl else ("", "")
        bdays = {p for p in (_parse_date(text[s["start"]:s["end"]]) for s in todo if s["type"] == "DATE") if p and p[0] is not None}
        is_bday = lambda v: bool(bdays) and re.fullmatch(r"[0-9]{6,8}", re.sub(r"\s", "", v)) is not None and _parse_date(re.sub(r"\s", "", v)) in bdays
        repl = {}  # (起, 訖) → (換成, 還原成哪些也算對)

        def pick(hits, key, orig, typ, title=""):
            """只寫姓、名字、綽號：唯一對到一個全名就用那個人的代號；對到好幾個寫〇；都對不到就自己給一個。"""
            if len(hits) == 1:
                k = "p:" + _canon(next(iter(hits)))
                part = {"fake": self.codes[k] + title, "original": orig + title, "type": "PERSON_PART", "code": True, "of": k}
                if title and part not in self.entries:  # 「甲小姐」換回「陳小姐」（不是全名＋小姐）
                    self.entries.append(part)
                return self.codes[k], {_gnorm(self.origs[k])}
            if hits:
                return "〇", set()
            self._code(key, text, scan)
            self._entry(key, self.codes[key], orig, typ)
            return self.codes[key], set()

        def person(s):
            orig = text[s["start"]:s["end"]]
            core = re.sub(r"[ 　\n]", "", orig)
            kind = s.get("kind", "full")
            if is_full(s):
                k = "p:" + _canon(core)
                if k not in self.codes:  # 同一個字串前面被標成名字、綽號（文昌）：沿用那個代號，不拆成兩個人
                    alt = next((self.codes[a + core] for a in ("g:", "n:") if a + core in self.codes), None)
                    if alt:
                        self.codes[k] = alt
                self._code(k, text, scan)
                self._entry(k, self.codes[k], orig, "PERSON")
                return self.codes[k], set()
            if "p:" + _canon(core) in self.codes:  # 這個字串已經是某個人的全名（同一個名字別處被標成全名）
                k = "p:" + _canon(core)
                return self.codes[k], {_gnorm(self.origs[k])} if k in self.origs else set()
            sl = surname_len(core)
            if kind == "partial" or (sl and len(core) == sl):
                title = next((t for t in _TITLES if text.startswith(t, s["end"])), "")
                return pick({f for f, (su, _) in fulls.items() if su == core}, f"s:{core}|{title}", core, "SURNAME", title)
            if kind == "nick":
                head = core[0] if core[0] in "老小阿" and len(core) > 1 else ""
                body = core[len(head):]
                if head in ("老", "小") and surname_len(body) == len(body):
                    return pick({f for f, (su, _) in fulls.items() if su == body}, f"n:{core}", core, "PERSON")
                return pick({f for f, (_, g) in fulls.items() if body and body in g}, f"n:{core}", core, "PERSON")
            return pick({f for f, (_, g) in fulls.items() if g and g.endswith(core)}, f"g:{core}", core, "GIVEN")

        def token(v, typ, label=None):
            k = f"t:{label or _label(v, typ)}:{_canon(v)}"
            self._code(k, text, scan)
            self._entry(k, f"〔{self.codes[k]}〕", v, typ)
            return self.fakes[k]

        def org(s):
            orig = text[s["start"]:s["end"]]
            known = self.aliases.get("a:" + _canon(orig))
            if known in self.codes:  # 模型把別名（岱昀公司）也判成一家機構：跟著全名用同一個字母（A公司），還原時換回全名也算對
                return self._alias_fake("a:" + _canon(orig), orig), {_gnorm(self.origs[known])}
            k = "o:" + _canon(orig)
            c = self._code(k, text, scan)
            form = _org_form(orig)
            self._entry(k, f"Company {c}" if form is None else c + form, orig, "ORG")
            # 明講的別名（下稱台積電）只擋很常用的詞（統一、中華）；沒明講、只是名稱裡的品牌，詞典裡的詞都不換（信義、玉山）
            brands = sorted(_brands(orig), key=len, reverse=True)
            names = [(a, 300) for a in Obfuscator._alias_names(orig, text, s["end"])] + [(b, 1) for b in brands]
            for a, common in names:
                ak = "a:" + _canon(a)
                if a not in _places_set() and a not in _common(common) and ak not in self.aliases:
                    tpl = a
                    for b in brands:
                        tpl = tpl.replace(b, "{c}")
                    if "{c}" not in tpl:  # 別名裡沒有全名的品牌（台積電）：只寫字母，有類型字尾的照留
                        tpl = "{c}" + (_org_form(a, "") or "")
                    self.aliases[ak], self.alias_tpl[ak] = k, tpl
                    self.entries.append({"fake": c, "original": a, "type": "ORG_ALIAS", "code": True, "alias": True, "key": ak, "c": k, "tpl": tpl})
            return self.fakes[k], set()

        def date(v, level):
            return _coarse(v, level) or token(v, "DATE", "日期")

        def address(s):
            a, b = s["start"], s["end"]
            v = text[a:b]
            if re.search(r"\d\s?[地建]號", v):  # 地號、建號：段名留著，號碼換成〔地號1〕
                for m in re.finditer(r"(\d+(?:-\d+)?)\s?([地建])號", v):
                    repl[(a + m.start(), a + m.end())] = (token(m.group(0), "ADDRESS", m.group(2) + "號"), set())
                return
            cities, dists = _cities_dists()
            city = next((c for c in cities if v.startswith(c)), "")
            head = city
            if self.addr == "district":
                d = next((d for d in dists if v.startswith(d, len(city))), "")
                head = city + d if city or d else ""
            if len(head) < len(v):
                repl[(a + len(head), b)] = (token(v[len(head):], "ADDRESS", "地址"), set())

        for s in todo:
            iv, orig, typ = (s["start"], s["end"]), text[s["start"]:s["end"]], s["type"]
            if typ in ("NUMBER", "CODE") and is_bday(orig) or typ == "DATE_EVENT" and _parse_date(orig) in bdays:
                typ = "DATE"  # 同一天在別處被判成生日：照生日處理
            if typ.startswith("PERSON"):
                repl[iv] = person(s)
            elif typ.startswith("ORG"):
                repl[iv] = org(s)
            elif typ == "DATE":
                repl[iv] = (date(orig, "year"), set())
            elif typ == "DATE_EVENT":
                if self.event_dates != "keep":
                    repl[iv] = (date(orig, self.event_dates), set())
                    if _parse_date(orig):
                        self.events.add(_parse_date(orig))
            elif typ == "ADDRESS":
                address(s)
            else:
                repl[iv] = (token(orig, typ), set())
        free = lambda iv: not any(a < iv[1] and b > iv[0] for a, b in list(repl) + keep)
        # 同一個值在文件別處也換（模型漏抓的重複提及）：人名三個字以上、其他五個字以上才換，避免誤傷；別名、品牌兩個字以上
        values = [(k.split(":", 2)[-1], self.fakes[k], k[0] == "p", 3 if k[0] == "p" else 5, None) for k in self.fakes if k[0] in "pot"]
        # 別名、品牌換成機構的字母（見 _alias_fake）；長的先換，下稱麒碩科技才不會被品牌麒碩先換掉一半
        values += [(k[2:], None, False, 2, k) for k, o in self.aliases.items() if o in self.codes]
        accept = {self.fakes[o]: {_gnorm(self.origs[o])} for o in self.aliases.values() if o in self.fakes}
        for c, fake, is_person, shortest, akey in sorted(values, key=lambda v: -len(v[0])):
            if len(c) < shortest:
                continue
            sep = _JUNK + "{0,3}" if is_person else r"\s?"
            word = c.isascii() and c.isalpha()
            rx = re.compile(("(?<![0-9０-９])" if c[0].isdigit() else r"(?<![A-Za-z])" if word else "")
                            + sep.join(f"[{ch}{chr(ord(ch) + 0xFEE0)}]" if ch.isdigit() else re.escape(ch) for ch in c)
                            + ("(?![0-9０-９])" if c[-1].isdigit() else r"(?![A-Za-z])" if word else ""))
            for m in rx.finditer(text):
                if free(m.span()):
                    f = self._alias_fake(akey, m.group(0)) if akey else fake
                    repl[m.span()] = (f, accept.get(f, set()))
        for m in re.finditer(r"(?<![0-9])\d+(?:-\d+)?\s?[地建]號", text):  # 同一筆地號別處也換（短的「12地號」不夠五個字，上面的補換沒算到）
            k = f"t:{m.group(0)[-2:]}:{_canon(m.group(0))}"
            if k in self.fakes and free(m.span()):
                repl[m.span()] = (self.fakes[k], set())
        for rx in _BDAY_RX if bdays or self.events else ():  # 生日、行程日期的其他寫法（075/02/17、0750217）：同一天也照樣粗化
            for m in rx.finditer(text):
                p = _parse_date(m.group(0))
                if p in bdays and free(m.span()):
                    repl[m.span()] = (date(m.group(0), "year"), set())
                elif p in self.events and p not in bdays and free(m.span()):
                    repl[m.span()] = (date(m.group(0), self.event_dates), set())
        surs = {su for su, _ in fulls.values() if su} | {k[2:].split("|")[0] for k in self.codes if k[0] == "s"}
        if surs:  # 姓＋稱謂：別處的「陳阿姨」「陳老太太」也換，不洩漏真姓
            rx = re.compile("(" + "|".join(map(re.escape, sorted(surs, key=len, reverse=True))) + ")(" + "|".join(PROP_TITLES) + ")")
            for m in rx.finditer(text):
                iv = (m.start(1), m.end(1))
                if free(iv):
                    repl[iv] = pick({f for f, (su, _) in fulls.items() if su == m.group(1)}, f"s:{m.group(1)}|{m.group(2)}", m.group(1), "SURNAME", m.group(2))
        if self.other_dates != "keep":  # 其他日期（判決日、起訴日）也粗化
            for rx in DATES:
                for m in rx.finditer(text):
                    if free(m.span()):
                        repl[m.span()] = (date(m.group(0), self.other_dates), set())
        out, pos, self.spans = [], 0, []
        for (a, b), (fake, accept) in sorted(repl.items()):
            if a < pos:
                continue
            out.append(text[pos:a]); cur = sum(map(len, out))
            self.spans.append({"start": cur, "end": cur + len(fake), "original": text[a:b], "orig_start": a, "orig_end": b, "accept": accept})
            out.append(fake); pos = b
        out.append(text[pos:])
        fake = "".join(out)
        _guard(text, fake, self.spans, self.entries)
        return fake, [dict(e) for e in self.entries]


class Anonymizer:
    """匿名化：換成代號、不留對照表，無法還原。同一個 Anonymizer 連續處理的文件代號一致（代號表只在這個物件裡，不回傳、不寫出）。
    event_dates：個人行程日期 month（預設，只留年月）／year／keep；other_dates：判決日、起訴日等其他日期 keep（預設）／month／year；
    addr：city（預設，地址只留縣市）／district（留到鄉鎮市區）。"""

    def __init__(self, detector=None, event_dates="month", addr="city", other_dates="keep"):
        self._engine = CodeObfuscator(detector, event_dates=event_dates, addr=addr, other_dates=other_dates)

    def anonymize(self, text):
        return self._engine.pseudonymize(text)[0]

    def apply(self, text, spans):
        """自己的偵測結果（start、end、type、kind）→ 匿名化文字。"""
        return self._engine.apply(text, spans)[0]

    def anonymize_many(self, texts):
        """同一批文件：先掃過全部原文，避開原文已經用的代號，再逐份處理（代號整批一致）。"""
        texts = list(texts)
        self._engine.reserve(texts)
        return [self.anonymize(t) for t in texts]


def _demo():
    from .obfuscate import restore, restore_exact
    import random

    def spans_of(t, items):  # 每個值取第一個還沒被前面的標註佔掉的位置
        out = []
        for x, typ, kind in items:
            i = next(i for i in (m.start() for m in re.finditer(re.escape(x), t)) if not any(s["start"] < i + len(x) and s["end"] > i for s in out))
            out.append({"start": i, "end": i + len(x), "type": typ, **({"kind": kind} if kind else {})})
        return out
    t = ("原告陳美玲（身分證F223456781，民國71年3月8日生，住臺中市西屯區文心路三段100號7樓，手機0912-345-678）與被告岱昀顧問股份有限公司（下稱岱昀公司）"
         "間確認僱傭關係存在事件。原告自113年5月2日起任職於岱昀公司，陳小姐主張岱昀違法解僱，美玲並提出證人林志強之證詞。被告訴訟代理人王大同律師。法官李佳穎。")
    sp = spans_of(t, [("陳美玲", "PERSON", "full"), ("F223456781", "CODE", None), ("民國71年3月8日", "DATE", None), ("臺中市西屯區文心路三段100號7樓", "ADDRESS", None),
                      ("0912-345-678", "NUMBER", None), ("岱昀顧問股份有限公司", "ORG", None), ("113年5月2日", "DATE_EVENT", None), ("陳", "PERSON", "partial"),
                      ("美玲", "PERSON", "given"), ("林志強", "PERSON", "full"), ("王大同", "PERSON_KEEP", "full"), ("李佳穎", "PERSON_KEEP", "full")])
    ob = CodeObfuscator()
    fake, mp = ob.apply(t, sp)
    print(fake)
    for orig in ("陳美玲", "F223456781", "3月8日", "文心路", "0912-345-678", "岱昀", "林志強", "陳小姐", "美玲"):
        assert orig not in fake, orig
    assert fake.startswith("原告甲（身分證〔身分證1〕，民國71年生，住臺中市〔地址1〕，手機〔電話1〕）與被告A公司（下稱A公司）"), fake
    assert "甲小姐主張A違法" in fake and "甲並提出證人乙" in fake and "王大同律師" in fake and "法官李佳穎" in fake and "113年5月2日" in fake
    assert restore_exact(fake, ob.spans) == t and not any(e.get("ambiguous") for e in mp)
    ai = "甲小姐可主張A公司違法解僱；甲方與乙方之約定、甲說見解、指甲、甲級均不影響，乙之證詞亦有利於甲。請撥〔電話1〕或[電話1]。"
    assert restore(ai, mp) == ("陳小姐可主張岱昀顧問股份有限公司違法解僱；甲方與乙方之約定、甲說見解、指甲、甲級均不影響，林志強之證詞亦有利於陳美玲。"
                               "請撥0912-345-678或0912-345-678。"), restore(ai, mp)
    anon = Anonymizer().apply(t, sp)
    assert "113年5月起" in anon and "113年5月2日" not in anon and "民國71年生" in anon, anon
    # 同姓多人：只寫姓的對不上就寫〇，不指錯人；原文已經用的代號（甲方、乙方）不編
    t2 = "原告陳美玲、陳志明與被告王小明間事件。陳小姐主張王先生違約，甲方乙方另有約定。"
    sp2 = spans_of(t2, [("陳美玲", "PERSON", "full"), ("陳志明", "PERSON", "full"), ("王小明", "PERSON", "full"), ("陳", "PERSON", "partial"), ("王", "PERSON", "partial")])
    f2, m2 = CodeObfuscator().apply(t2, sp2)
    assert f2 == "原告丙、丁與被告戊間事件。〇小姐主張戊先生違約，甲方乙方另有約定。", f2
    # 只寫姓、文件裡沒有全名：自己給一個代號，稱謂不同的分開（不把陳先生、陳小姐併成同一個人）
    t3 = "陳先生與陳小姐當天都在場，陳先生先離開。"
    f3, m3 = CodeObfuscator().apply(t3, spans_of(t3, [("陳", "PERSON", "partial"), ("陳", "PERSON", "partial")]))
    assert f3 == "甲先生與乙小姐當天都在場，甲先生先離開。", f3
    assert restore("甲先生說乙小姐也在", m3) == "陳先生說陳小姐也在"
    # 同一個 Anonymizer：代號整批一致；逐份處理撞到原文既有的代號（這份本來就有「乙」）→ 換新代號、發警告；anonymize_many 先掃過就不撞
    d1, d2 = "證人林志強到庭。", "證人林志強與乙公司人員到庭。"
    s1, s2 = spans_of(d1, [("林志強", "PERSON", "full")]), spans_of(d2, [("林志強", "PERSON", "full")])
    an = Anonymizer()
    assert an.apply(d1, s1) == "證人甲到庭。"
    an2 = Anonymizer()
    an2.apply("被告王小明到庭。", spans_of("被告王小明到庭。", [("王小明", "PERSON", "full")]))
    assert an2.apply(d1, s1) == "證人乙到庭。"
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        out = an2.apply(d2, s2)
    assert out == "證人丙與乙公司人員到庭。" and w and "已經有別的意思" in str(w[0].message), (out, w)

    class FakeDet:
        def __init__(self, table):
            self.table = table

        def detect(self, text):
            return self.table[text]
    an3 = Anonymizer(FakeDet({"被告王小明到庭。": spans_of("被告王小明到庭。", [("王小明", "PERSON", "full")]), d1: s1, d2: s2}))
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert an3.anonymize_many(["被告王小明到庭。", d1, d2]) == ["被告甲到庭。", "證人丙到庭。", "證人丙與乙公司人員到庭。"]
    # 前一份登錄的別名，這份被判成保留也照換；代號撞到原文改名時，模型漏抓的同一個名字照樣換成新代號、還原得回來
    eng = CodeObfuscator()
    e1 = "被告岱昀顧問有限公司（下稱岱昀公司）與證人林志強。"
    eng.apply(e1, spans_of(e1, [("岱昀顧問有限公司", "ORG", None), ("林志強", "PERSON", "full")]))
    e2 = "岱昀公司表示，甲方約定林志強負責。"
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        f, m = eng.apply(e2, spans_of(e2, [("岱昀公司", "ORG_KEEP", None)]))
    assert "岱昀" not in f and "林志強" not in f and "甲方" in f, f
    assert restore(f.replace("甲方", ""), m) == e2.replace("甲方", "").replace("岱昀公司", "岱昀顧問有限公司"), (f, restore(f, m))
    # 同一天的行程日期只抓到一處：別處也粗化；地號、建號：還原不掉字尾、不碰同數字的金額、地號建號分開
    e3 = "原告113年5月2日到職，113年5月2日當天簽約。西屯段12345地號、12345建號，價金12345元，同段12345地號另案。"
    a3 = Anonymizer().apply(e3, spans_of(e3, [("113年5月2日", "DATE_EVENT", None), ("西屯段12345地號", "ADDRESS", None), ("12345建號", "ADDRESS", None)]))
    assert a3 == "原告113年5月到職，113年5月當天簽約。西屯段〔地號1〕、〔建號1〕，價金12345元，同段〔地號1〕另案。", a3
    f4, m4 = CodeObfuscator().apply(e3, spans_of(e3, [("西屯段12345地號", "ADDRESS", None)]))
    assert restore("〔地號1〕與[地號1]", m4) == "12345地號與12345地號"
    # 前一份登錄的全名、這份模型只抓到姓：「林先生」對到同一個代號，不拆成兩個人
    eng = CodeObfuscator()
    eng.apply("證人林志強到庭。", spans_of("證人林志強到庭。", [("林志強", "PERSON", "full")]))
    e5 = "林志強主張林先生無責。"
    i5 = e5.index("林先生")
    assert eng.apply(e5, [{"start": i5, "end": i5 + 1, "type": "PERSON", "kind": "partial"}])[0] == "甲主張甲先生無責。"
    # 原文有「〔電話 1〕」（中間有空白，還原時算同一個）：新的電話從 2 編；天干全被原文用掉時的備用代號也整批避開
    e6 = "前案代號〔電話 1〕。原告手機0912-345-678。"
    f6, m6 = CodeObfuscator().apply(e6, spans_of(e6, [("0912-345-678", "NUMBER", None)]))
    assert "〔電話2〕" in f6 and restore("〔電話2〕", m6) == "0912-345-678", f6
    full8 = "甲乙丙丁戊庚壬癸都是代號。"
    d7, d8 = "證人林志強到庭。" + full8, "人物1另案。證人林志強到庭。"
    an = Anonymizer(FakeDet({d7: spans_of(d7, [("林志強", "PERSON", "full")]), d8: spans_of(d8, [("林志強", "PERSON", "full")])}))
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert an.anonymize_many([d7, d8]) == ["證人人物2到庭。" + full8, "人物1另案。證人人物2到庭。"]
    # 還原時一般詞不換（甲板、布丁、丁字路口），但「甲未到庭」「甲乙二人」照換
    assert restore("甲在甲板上，甲未到庭，甲乙二人均吃布丁，經丁字路口。", mp) == "陳美玲在甲板上，陳美玲未到庭，陳美玲林志強二人均吃布丁，經丁字路口。"
    # 原文有「人物 1」（中間有空白）：備用代號從人物2編
    d10 = "人物 1另案。證人林志強到庭。"
    an = Anonymizer(FakeDet({d7: spans_of(d7, [("林志強", "PERSON", "full")]), d10: spans_of(d10, [("林志強", "PERSON", "full")])}))
    assert an.anonymize_many([d7, d10]) == ["證人人物2到庭。" + full8, "人物 1另案。證人人物2到庭。"]
    # 代號撞到原文改名：舊代號的對照停用（AI 回覆的「甲委託乙」不能兩個都還原成林志強）
    eng = CodeObfuscator()
    eng.apply("證人林志強到庭。", spans_of("證人林志強到庭。", [("林志強", "PERSON", "full")]))
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        f12, m12 = eng.apply("甲方委託林志強到庭。", spans_of("甲方委託林志強到庭。", [("林志強", "PERSON", "full")]))
    assert f12 == "甲方委託乙到庭。" and restore("甲委託乙到庭。", m12) == "甲委託林志強到庭。", (f12, restore("甲委託乙到庭。", m12))
    # 停用過的代號不再分給別人：林志強先是甲，撞到甲方改成乙；後來新的人不能再拿到甲
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        f13, _ = eng.apply("證人陳美玲到庭。", spans_of("證人陳美玲到庭。", [("陳美玲", "PERSON", "full")]))
    assert f13 == "證人丙到庭。", f13
    # 英文機構代號：Company A 不比對到 Company A2
    e14 = "Nimbus LLC signed."
    _, m14 = CodeObfuscator().apply(e14, [{"start": 0, "end": 10, "type": "ORG"}])
    assert restore("Company A and Company A2", m14) == "Nimbus LLC and Company A2", restore("Company A and Company A2", m14)
    # 備用代號字間有空白（人 物 1）也預留
    d15 = "人 物 1另案。證人林志強到庭。"
    an = Anonymizer(FakeDet({d7: spans_of(d7, [("林志強", "PERSON", "full")]), d15: spans_of(d15, [("林志強", "PERSON", "full")])}))
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert an.anonymize_many([d7, d15]) == ["證人人物2到庭。" + full8, "人 物 1另案。證人人物2到庭。"]
    # 別名的字尾跟全名不同（下稱麒碩科技）：寫成 A科技，而且換得回來；單獨的品牌寫成字母
    e11 = "被告麒碩科技股份有限公司（下稱麒碩科技）。麒碩科技應給付，麒碩表示異議。"
    f11, m11 = CodeObfuscator().apply(e11, spans_of(e11, [("麒碩科技股份有限公司", "ORG", None)]))
    assert f11 == "被告A公司（下稱A科技）。A科技應給付，A表示異議。", f11
    assert restore("A科技應給付，A公司不爭執。", m11) == "麒碩科技應給付，麒碩科技股份有限公司不爭執。"
    # 同一個名字一處標成全名、一處標成名字：同一個代號
    e9 = "文昌到庭。文昌說明。"
    f9, _ = CodeObfuscator().apply(e9, [{"start": 0, "end": 2, "type": "PERSON", "kind": "full"}, {"start": 5, "end": 7, "type": "PERSON", "kind": "given"}])
    assert f9 == "甲到庭。甲說明。", f9
    # 機構代號還原：NBA公司 不是 A公司
    assert restore("NBA公司與A公司均有責任。", mp) == "NBA公司與岱昀顧問股份有限公司均有責任。"
    # 同一個物件先處理過文件，再整批處理：舊代號撞到這批原文的，整批開始前就換掉
    pre = Anonymizer(FakeDet({"林志強到庭。": spans_of("林志強到庭。", [("林志強", "PERSON", "full")]),
                              "甲方委託林志強到庭。": spans_of("甲方委託林志強到庭。", [("林志強", "PERSON", "full")])}))
    assert pre.anonymize("林志強到庭。") == "甲到庭。"
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        assert pre.anonymize_many(["林志強到庭。", "甲方委託林志強到庭。"]) == ["乙到庭。", "甲方委託乙到庭。"]
    # 備用代號比對整個編號：原文有「人物12」不算用掉「人物1」
    d9 = "人物12另案。證人林志強到庭。"
    an = Anonymizer(FakeDet({d7: spans_of(d7, [("林志強", "PERSON", "full")]), d9: spans_of(d9, [("林志強", "PERSON", "full")])}))
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert an.anonymize_many([d7, d9]) == ["證人人物1到庭。" + full8, "人物12另案。證人人物1到庭。"]
    # 性質測試：隨機文件（同姓多人、只寫姓、號碼、地址、機構＋別名、原文已經有代號）
    rng = random.Random(7)
    surs, gives = "陳林黃張李王吳劉", "美玲志明家豪雅婷宗翰怡君俊傑淑芬"
    for _ in range(300):
        parts, items, names = [], [], []
        for _ in range(rng.randint(1, 4)):
            n = rng.choice(surs) + "".join(rng.sample(gives, 2))
            names.append(n)
            parts.append(f"證人{n}到庭，"); items.append((n, "PERSON", "full"))
        sur = rng.choice(names)[0]
        parts.append(f"{sur}小姐說明。"); items.append((sur, "PERSON", "partial"))
        tel = f"09{rng.randint(10, 99)}-{rng.randint(100, 999)}-{rng.randint(100, 999)}"
        parts.append(f"電話{tel}。"); items.append((tel, "NUMBER", None))
        org = rng.choice(("岱昀", "鼎昕", "麒碩")) + "顧問有限公司"
        parts.append(f"任職於{org}（下稱{org[:2]}公司）。"); items.append((org, "ORG", None))
        if rng.random() < 0.5:
            parts.append(rng.choice(("甲方、乙方另有約定。", "A棟住戶在場。", "詳〔號碼1〕。")))
        doc = "".join(parts)
        try:
            sp = spans_of(doc, items)
        except ValueError:  # 隨機出來的名字剛好重疊，跳過
            continue
        o = CodeObfuscator()
        f, m = o.apply(doc, sp)
        assert restore_exact(f, o.spans) == doc
        assert not any(e.get("ambiguous") for e in m), (doc, f)
        for n in names + [tel, org]:
            assert n not in f, (n, f)
        codes = {e["fake"]: e["original"] for e in m if e["type"] == "PERSON"}
        assert len(set(codes.values())) == len(codes) == len(set(names)), (codes, names)  # 不同的人不同代號
        assert not any(c[0] in doc for c in codes), (codes, doc)  # 代號不用原文已經出現的字
    print("代號版自檢 OK：代號一致、同姓寫〇、避開原文既有代號、整批一致、還原不換一般詞、逐字還原")


if __name__ == "__main__":
    _demo()
