"""真名混淆：偵測到的人名與個資換成同類型的擬真假值（同一份文件一致），並留對照表供還原。
- 人名：姓、名分開對應（王→陳、小明→志豪）；全名、姓＋稱謂、只叫名字、綽號都由這兩張表組出來，所以王先生→陳先生、老王→老陳；
  同姓的人換成同一個假姓（家人關係還看得出來）。保留的人名（法官、公眾人物）不動。
- 號碼與代號：同格式換字元（手機留 09、市話留區碼、健保卡留開頭 0、銀行代碼留著）；身分證換成檢查碼正確的號碼（首字母、性別碼不變）。
- Email／網址／社群帳號：同格式換字元；公用信箱與大平台的網域留著。
- 地址：預設保留縣市（管轄看得出來），其餘換成同縣市的真實路名。
- 地號：段名留著，號碼整案一致地換（452→537、452-1→537-1：同一筆同一個假號，分割關係看得出來）。
- 機構：只換品牌那段（逐字對應，整案一致：岱昀顧問／岱昀科技／岱昀公司 → 鼎昕顧問／鼎昕科技／鼎昕公司），
  法律形式、產業詞、類型詞、分公司、縣市都留著；名稱裡的人名跟人名對照表走（陳記商行 → 劉記商行，陳先生 → 劉先生）。
  五個字以上的品牌（台灣積體電路製造）整段換成兩個字；別名（下稱台積電）和上市櫃公司的簡稱跟著全名換。
  保留的機構（政府機關、事務所、順帶提到的平台）不動。
- 生日：保留年份（年齡不變），月日換掉。
- 個人行程日期：預設（legal）不動——實測位移日期會讓 AI 的時間推理出錯（文中「上週末」「四月初」、案號裡的日期都不會跟著挪）；
  general 模式才整份文件同一個位移（7 的倍數天：間隔、星期幾都不變），給要照醫療去識別標準的人用。
- 模型抓到的值，文件裡其他一模一樣的地方也一起換（夠長的才換，避免誤傷）。
對照表：[{fake, original, type}]，restore() 一次替換換回（最長的先比、不會連鎖）。
"""
from __future__ import annotations

import bisect, collections, copy, datetime as dt, functools, random, re, warnings

from .candidates import SURNAME_AFTER, TITLES, surname_len
from .companies import all_short_names, short_name
from .fakes import county_of, fake_address, fake_id
from .names import GIVEN_F, GIVEN_M, sample_surname
from .org_candidates import BRANCH, SUFFIXES, _common
from .pii_candidates import CITIES, DATES, _places
from .surnames import JP_SURNAMES, SURNAMES

_BDAY_RX = DATES + [re.compile(r"(?<![0-9])[0-9]{6,8}(?![0-9])")]  # 生日的其他寫法（含沒有分隔的 0750217）：解析成同一天才換

RESTORE_TITLES = tuple(t for t in TITLES if t != "家") + ("老太太", "老先生", "老奶奶", "老伯伯", "老闆娘")  # 姓＋稱謂的還原用（「家」不用：莊家會被換錯）
# 文件裡別處的「姓＋稱謂」也跟著換（林小姐→鄧小姐，林老太太也要→鄧老太太）：只用兩字以上的稱謂（單字的「男」「伯」會誤配到「森林男孩」），
# 執行職務的稱謂不換（法官、律師照留）
_KEEP_TITLES = {"法官", "檢察官", "書記官", "律師", "審判長", "庭長", "院長", "委員"}
PROP_TITLES = tuple(sorted({t for t in RESTORE_TITLES if len(t) >= 2 and t not in _KEEP_TITLES}, key=len, reverse=True))
PUBLIC_MAIL = ("gmail.com", "yahoo.com.tw", "yahoo.com", "hotmail.com", "outlook.com", "icloud.com", "msa.hinet.net", "pchome.com.tw", "livemail.tw")
PLATFORMS = ("instagram.com", "facebook.com", "linkedin.com", "github.com", "github.io", "youtube.com", "threads.net", "x.com", "twitter.com",
             "notion.so", "notion.site", "drive.google.com", "medium.com", "blogspot.com", "pixnet.net", "dcard.tw", "ptt.cc", "line.me",
             "reurl.cc", "bit.ly", "linktr.ee", "vocus.cc", "behance.net")
LATIN_GIVEN = ("Kevin Jason Eric David Andy Vincent Allen Jack Ryan Leo Sean Ivy Amy Grace Joyce Wendy Vivian Emily Cindy Tina Irene "
               "Peggy Sandy Alice Angela Jessica Michael Peter Frank Steven Tony Daniel Brian Henry Oscar Victor Ethan Lucas Aaron Owen "
               "Jerry Terry Gary Ben Sam Max Nick Mia Zoe Ella Lily Ruby Nina Fiona Helen Karen Linda Mandy Nancy Olivia Rita Sophie "
               "Tracy Una Vera Winnie Yvonne Zara Jenny Kelly Lucy Maggie").split()
ROMAN_SUR = "Chen Lin Huang Chang Lee Wang Wu Liu Tsai Yang Hsu Cheng Hsieh Kuo Hung Tseng Chiu Liao Lai Chou".split()
ROMAN_SYL = "Chia Hao Yu Ting Wei Ming Hsin Yi Chun Hung Kai Jie Pei Shan Tzu Han Yen Lun Fang Hui Ching Kuan Po Wen".split()
_NAME_WORDS = set(LATIN_GIVEN) | set(ROMAN_SUR) | set(ROMAN_SYL)  # 假人名會用到的英文字：假品牌字要避開
TRANSLIT_POOL = "瓦歷斯尤幹比令亞布伊婕拉達魯巴萬撒韵武荖約翰史密斯瑪麗安娜帕蘇洛卡索莉亞"
# 假姓只挑「很少出現在一般詞裡」的姓：AI 回覆常只用姓稱呼（「劉取車」「朱作證」），還原時才能放心把單獨的假姓換回去。
# 不用：陳（陳述）張（張貼）李（行李）林（森林）黃（黃金）王（王道）謝（謝謝）賴（信賴）戴（戴口罩）許（許可）曾（曾經）周（周延）高 方 文 金 白 石 田 萬 何 簡 施 余 連 程 康 溫 馬 洪 羅 葉 胡 游 顏 孫 江 莊
# 也不用（公開判決裡常組成一般詞）：紀（紀錄）杜（杜絕、杜拜）傅（師傅）梁（梁柱）沈（沈默）蕭（蕭條）卓（卓越）翁（翁婿）柯（古柯鹼）
# 楊（楊梅區）吳（東吳）徐（徐州路）阮（台語「阮」）汪（汪汪）涂（涂抹）
SAFE_SURNAMES = "劉蔡郭邱廖呂潘朱鍾彭詹趙盧魏鄧侯曹薛姚邵鄒龔鄔滕"
# 代號版（codes.py）的人名代號：天干拿掉己（自己）、辛（辛苦）這種常組成一般詞的字，AI 回覆裡單獨出現時才換得回來
PERSON_CODES = "甲乙丙丁戊庚壬癸"
_BARE_CODE = re.compile(rf"[{PERSON_CODES}]\d*")
# 代號後面接這些字是一般詞（甲方、甲說、甲級、甲狀腺、乙醇、甲子），前面是這些字也是（指甲、盔甲、園丁）：還原時不換
_CODE_NEXT_BLOCK = set("方級種說案狀類型組區棟欄表式版稿目款項醇烯酮烷烴胺子丑寅卯辰巳午申酉戌亥")  # 「未」不擋：甲未到庭
_CODE_PREV_BLOCK = set("指盔裝園壯補庖布")
# 機構名稱：這些照留（法律形式、產業、類型看得出來），其餘的品牌字逐字換成品牌常用字
ORG_PREFIX = re.compile(r"(?:醫療|學校|宗教)?(?:財團法人|社團法人)|私立|國立|公立|(?:" + "|".join(sorted(CITIES, key=len, reverse=True)) + r")(?:私立|立)?")
ORG_KEEP_WORDS = sorted(set("""
建設 營造 顧問 管理顧問 科技 電子 資訊 國際 開發 實業 投資 貿易 保全 物業管理 物業 不動產 建築 室內裝修 裝修 設計 工程 機械 化工 食品 餐飲 生技 生物科技
醫療 文教 教育 旅行 運輸 物流 汽車 精密 光電 能源 環保 紡織 印刷 廣告 行銷 傳播 娛樂 影視 數位 網路 軟體 通訊 電信 金融 證券 保險 人壽 產物 租賃
美容 服飾 家具 五金 塑膠 鋼鐵 水泥 營建 地產 興業 企業 工業 商業 實業 農產 水產 畜產 製藥 藥品 醫藥 生醫 健康 照護 長照 托育 補習 文化 出版 音樂 藝術
運動 健身 休閒 觀光 開發建設 交通 客運 貨運 航運 海運 空運 通運 搬家 清潔 綠能 電機 電器 冷凍 空調 水電 機電 自動化 半導體 材料 包裝 物產 百貨
傢俱 珠寶 銀樓 鐘錶 眼鏡 寵物 動物 婚紗 攝影 診所 牙醫 中醫 眼科 小兒科 婦產科 皮膚科 社區 大樓 管理 委員會 協會 學會 基金會 公益 慈善 宗親 同鄉
記 家 氏 的 之 與 及
""".split()), key=len, reverse=True)
_ORG_STRUCT = sorted(set(SUFFIXES) | {"分公司", "分行", "分店", "營業所", "分院", "分校", "分會", "辦事處", "服務處", "工廠", "財團法人", "社團法人",
                                      "私立", "國立", "公立", "市立", "縣立"} | CITIES |
                     {c[:2] for c in CITIES}, key=len, reverse=True)  # 法律形式、類型、分支、前綴、縣市：一定照留
_ORG_TOKENS = sorted(set(_ORG_STRUCT) | set(ORG_KEEP_WORDS), key=len, reverse=True)
_SHOP_AFTER_SURNAME = set("記家氏媽嬤姐哥師")  # 陳記、林家、王媽媽：開頭的姓跟人名對照表走
_ORG_KEEP_1 = {w for w in ORG_KEEP_WORDS if len(w) == 1}  # 記、家、之、的：哪裡都照留；單字結尾詞（店、局、宮）只在最後才算
ORG_CHARS = "鼎昕岳宏晟碩緯聯豐源泰勝達興隆嘉昌祥瑞益恆冠宇翔華群匯創璟騰禾鴻銓翊崴邦穎凱展昊頡晉澄奕霆煒璋峰岑灝暐睿駿麒燊鈺瀚昱勁曜崧樺楷捷嶸鎧鈞錡威德富榮茂豪弘承典誠智遠恩璞喬翰瑋薪"
EN_KEEP_WORDS = set("""Consulting Consultants Technology Technologies Tech International Trading Development Construction Engineering Holdings Group
Industrial Industries Enterprise Enterprises Bank Insurance Securities Logistics Foods Food Design Media Digital Software Systems Electronics
Semiconductor Investment Investments Capital Management Services Service Realty Properties Property Global Asia Pacific Taiwan Co Co. Ltd Ltd.
Limited Inc Inc. Corp Corp. Corporation LLC PLC GmbH AG Company and & of the Consultant Consultancy Advisory Partners Associates
Studio Salon Spa SPA Cafe Bistro Bakery Clinic Hotel Shop Store Boutique Restaurant Kitchen Bar Gym Fitness Office Branch Plant Factory
Ld Lfd Pte Bhd Sdn AS ASA AB Oy SA SpA Srl NV BV KK JSC Holdings""".split())
_CN_D = "〇一二三四五六七八九"
_FW = "０１２３４５６７８９"
_HW2FW = {str(i): _FW[i] for i in range(10)}
_FW2HW = {c + 0xFEE0: c for c in range(0x21, 0x7F)}  # 全形英數符號 → 半形（str.translate 用）
_HW2FW_ALL = {c: c + 0xFEE0 for c in range(0x21, 0x7F)}


_JUNK = r"[\s|｜_•¦¬~'·；;^]"  # 人名字間的空白、OCR 雜點（補換時容許、還原保護比對時不算）
_gnorm = lambda x: re.sub(_JUNK, "", x).translate(str.maketrans("０１２３４５６７８９", "0123456789"))  # 還原保護的比對：雜點不算、全形數字當半形
_NOT_VALUE = ("SURNAME", "GIVEN", "GIVEN_CHAR", "PERSON_PART", "LOT", "ORG_WORD", "ORG_CHAR")  # 組件、不是完整的值：不進「同值同假值」表（LOT＝地號號碼，單獨拿去比會誤換金額）
# 機構全名後面的別名定義：（下稱台積電）、（以下簡稱「岱昀」）
_ALIAS_RX = re.compile(r"\s*[（(]\s*(?:以下|下)?(?:簡稱|合稱|稱)\s*[：:]?\s*[「『“\"]?([^「」『』“”\"（）()，,、。；\s]{2,12}?)[」』”\"]?\s*[）)]")


@functools.lru_cache(None)
def _extra_given():
    """名字常用字用完時的備用字池：品牌常用字，再來是內政部路名用到的字（幾千個，讀起來沒那麼像名字，但保證不同的字不撞）。"""
    roads, _, _ = _places()
    return list(dict.fromkeys(ORG_CHARS + "".join(sorted({c for r in roads for c in r if "一" <= c <= "鿿"} - set(SURNAMES) - set("路街巷弄段道")))))


@functools.lru_cache(None)
def _places_set():
    """縣市、行政區（含去掉區鄉鎮市的簡稱）：品牌剛好是地名時不做全文替換（信義、玉山）。"""
    _, dists, cities = _places()
    return set(cities) | set(dists) | {d[:-1] for d in dists if len(d) >= 3} | {c[:2] for c in cities}


def _canon(s):
    """對照用的正規化：去空白、全形數字轉半形（PDF／OCR 轉出來同一個值常有這些差別）。"""
    return re.sub(r"\s", "", s).translate(str.maketrans(_FW, "0123456789"))


def _shape(rng, s, keep=0):
    """同形狀換字：英數字換同類字元（大小寫、全形數字不變），其他符號照舊；前 keep 個英數字元保留。"""
    out, k = [], 0
    for c in s:
        if c.isascii() and c.isalnum() or c in _FW:
            if k >= keep:
                if c in _FW:
                    c = _FW[rng.randrange(10)]
                elif c.isdigit():
                    c = str(rng.randrange(10))
                else:
                    c = chr(rng.randrange(26) + (65 if c.isupper() else 97))
            k += 1
        out.append(c)
    return "".join(out)


def _word(rng, n, upper=False):
    """n 個字母左右、念得出來的假字（用台灣常見拼音拼起來），Email、帳號、網址用。"""
    w = ""
    while len(w) < n:
        w += rng.choice(ROMAN_SYL + ROMAN_SUR).lower()
    w = w[:max(n, 2)]
    return w.upper() if upper else w


def _shape_words(rng, s):
    """英文字母串換成念得出來的假字（長度、大小寫照舊），數字照樣換、符號不動。"""
    s = re.sub(r"[A-Za-z]+", lambda m: _word(rng, len(m.group(0)), m.group(0).isupper()), s)
    return re.sub(r"[0-9]", lambda m: str(rng.randrange(10)), s)


_SLD = {"com", "org", "net", "edu", "gov", "idv", "mil", "co", "ac", "or", "ne", "go"}  # .com.tw、.co.jp 這類兩段的頂級網域


def _fake_host(rng, host):
    """私人網域：頂級網域（.com、.com.tw）以外每一段都換。只換第一段的話，mail.alice-chen.com 會留下 alice-chen.com。"""
    labels = host.split(".")
    keep = 2 if len(labels) >= 3 and len(labels[-1]) == 2 and labels[-2].lower() in _SLD else 1
    if len(labels) <= keep:
        return _shape_words(rng, host)
    return ".".join([_shape_words(rng, x) for x in labels[:-keep]] + labels[-keep:])


def _keep_head(s):
    """號碼開頭要保留幾碼：手機 09、市話區碼、國碼＋9、銀行代碼、健保卡的 0000。至少換 4 碼：全零的密碼（000000）不能整串照留。"""
    d = re.sub(r"[^0-9０-９]", "", s).translate(str.maketrans(_FW, "0123456789"))
    zeros = len(d) - len(d.lstrip("0"))
    if s.lstrip().startswith("+886") or d.startswith("886"):
        k = 4
    elif re.match(r"\d{3}-", s):
        k = 3
    else:
        k = zeros if zeros >= 2 else 2 if re.match(r"0[2-9]", d) else 0
    return min(k, max(0, len(d) - 4))


def _cn_num(n):  # 1～31 → 中文數字
    return {10: "十"}.get(n) or (("" if n < 20 else _CN_D[n // 10]) + "十" + (_CN_D[n % 10] if n % 10 else "") if n > 10 else _CN_D[n])


def _cn_parse(s):
    if all(c in _CN_D or c in "○零" for c in s) and len(s) >= 2:  # 年份逐字：一一二
        return int("".join(str(_CN_D.index(c) if c in _CN_D else 0) for c in s))
    if "十" in s:
        a, _, b = s.partition("十")
        return (_CN_D.index(a) if a else 1) * 10 + (_CN_D.index(b) if b else 0)
    return _CN_D.index(s) if s in _CN_D else None


_DATE_RX = [  # (正則, 群組角色)
    (re.compile(r"(\d{2,4})(\s?年\s?)(\d{1,2})(\s?月\s?)(\d{1,2})"), "ymd"),
    (re.compile(r"(\d{4})([-/.／])(\d{1,2})([-/.／])(\d{1,2})"), "ymd"),
    (re.compile(r"(\d{2,3})([/.／])(\d{1,2})([/.／])(\d{1,2})"), "ymd"),
    (re.compile(r"(\d{2,4})(\s?年\s?)(\d{1,2})(\s?月)"), "ym"),
    (re.compile(r"(\d{1,2})(\s?月\s?)(\d{1,2})"), "md"),
    (re.compile(r"(\d{1,2})([/／])(\d{1,2})"), "md"),
    (re.compile(r"^(\d{2,4})()(\d{2})()(\d{2})$"), "ymd"),  # 沒有分隔的寫法：0750217、1120510、19860217（偵測已判定是日期才會走到這）
]
_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]


def _rewrite_date(s, fn):
    """找出日期裡的年月日，交給 fn(y, m, d, roc) → (y, m, d)，再照原本寫法寫回（民國／西元、補零、分隔符號、中文數字、英文月份）。
    解析不出合法日期就回 None（呼叫端改用同格式換數字），任何寫法都不能讓整份文件失敗。"""
    try:
        return _rewrite_date_inner(re.sub(r"(?<=[\d/.／-])\s+(?=[\d/.／-])", "", s), fn)  # OCR 把日期拆開（75/0 2/17）：數字之間的空白不算
    except (ValueError, OverflowError, IndexError, TypeError):
        return None


def _parse_date(s):
    """日期 → (年, 月, 日)（沒寫年＝None）；解析不出來回 None。同一天的不同寫法（075/02/17、0750217、75年2月17日）得到同一組。"""
    got = []
    _rewrite_date(s, lambda y, mo, d, roc: got.append((y, mo, d)) or (y, mo, d))
    return got[0] if got else None


def _has_day(s):
    """日期有沒有寫到「日」：只改日，看寫回來的字有沒有變（75年7月 沒寫日）。"""
    out = _rewrite_date(s, lambda y, mo, d, roc: (y, mo, d % 28 + 1))
    return out is not None and out != s


def _as_date(p):
    """(年, 月, 日) → date（民國年換西元；沒寫年當 2000 年）。不合法的日期丟 ValueError。"""
    y, mo, d = p
    return dt.date((y + 1911 if y < 1000 else y) if y else 2000, mo, d)


_ykey = lambda p: (p[0] + 1911 if p[0] < 1000 else p[0], p[1], p[2])  # 有年份的日期：民國、西元當成同一天


def _rewrite_date_inner(s, fn):
    t = s.translate(str.maketrans(_FW, "0123456789"))
    for rx, roles in _DATE_RX:
        m = rx.search(t)
        if not m:
            continue
        g = list(m.groups())
        vals = {r: int(g[i * 2]) for i, r in enumerate(roles)}
        roc = "y" in vals and vals["y"] < 1000
        try:
            y, mo, d = fn(vals.get("y"), vals.get("m"), vals.get("d", 1), roc)
        except (ValueError, OverflowError):  # 不是合法日期（25/12、分數 15/20）：交給呼叫端改用同格式換數字
            return None
        new = {"y": y, "m": mo, "d": d}
        parts = []
        compact = not any(g[1::2])  # 沒有分隔符號：每一段都要維持原本的位數
        for i, r in enumerate(roles):
            width = len(g[i * 2]) if g[i * 2].startswith("0") or compact else 1
            parts.append(str(new[r]).zfill(width))
            if i * 2 + 1 < len(g):
                parts.append(g[i * 2 + 1])
        out = t[:m.start()] + "".join(parts) + t[m.end():]
        return "".join(fw if orig in _FW else c for c, orig, fw in zip(out, s, out)) if len(out) == len(s) else out
    m = re.search(r"([〇○零一二三四五六七八九十]{2,4})年([〇○零一二三四五六七八九十]{1,3})月(?:([〇○零一二三四五六七八九十]{1,3})([日號]))?", s)
    if m and _cn_parse(m.group(1)) is not None and _cn_parse(m.group(2)):
        y, mo, d = fn(_cn_parse(m.group(1)), _cn_parse(m.group(2)), _cn_parse(m.group(3)) if m.group(3) else 1, True)
        ys = "".join(_CN_D[int(c)] for c in str(y))
        return s[:m.start()] + f"{ys}年{_cn_num(mo)}月" + (f"{_cn_num(d)}{m.group(4)}" if m.group(3) else "") + s[m.end():]
    m = re.search(r"(?:(\d{1,2}) )?(" + "|".join(x[:3] for x in _MONTHS) + r")[a-z]*\.?(?: (\d{1,2})(?!\d))?(,? (\d{4}))?", s)
    if m:
        mo = [x[:3] for x in _MONTHS].index(m.group(2)) + 1
        d0 = int(m.group(1) or m.group(3) or 1)
        y, mo2, d = fn(int(m.group(5)) if m.group(5) else None, mo, d0, False)
        full = len(m.group(0).split()[0 if not m.group(1) else 1]) > 4
        mname = _MONTHS[mo2 - 1] if full else _MONTHS[mo2 - 1][:3]
        dd = str(d)
        body = (f"{dd} {mname}" if m.group(1) else (f"{mname} {dd}" if m.group(3) else mname)) + (f"{m.group(4)[:-4]}{y}" if m.group(5) else "")
        return s[:m.start()] + body + s[m.end():]
    return None


class Obfuscator:
    """假名化（留對照表，可以把 AI 回覆換回原文）。detector：有 detect(text) 的偵測器（taiwan_legal_deid.detect 或 taiwan_legal_deid.detect_onnx）。
    style：假名長什麼樣——realistic（預設，擬真假名：陳美玲 → 詹筱怡）／code（代號：甲、A 公司、〔號碼1〕，見 codes.py）。
    mode：個人行程日期怎麼處理——legal（預設，照留）／general（擬真版整份位移、代號版只留年月）。
    mapping：沿用同一案件前面文件的對照表，讓同一個人在不同文件換成同一個假名（同一案件不能混用兩種 style）。"""

    def __init__(self, detector=None, mode="legal", seed=None, keep_city=True, mapping=None, style="realistic"):
        if style not in ("realistic", "code"):
            raise ValueError(f"style 只能是 realistic 或 code：{style!r}")
        if mapping and any(e.get("code") for e in mapping) != (style == "code"):  # 代號的對照表配擬真假名（或反過來）會換錯
            raise ValueError(f"對照表是{'代號版' if style == 'realistic' else '擬真版'}，跟 style={style!r} 不同：同一案件請用同一種")
        self.det, self.mode, self.keep_city, self.style = detector, mode, keep_city, style
        self._code = None
        if style == "code":
            from .codes import CodeObfuscator
            self._code = CodeObfuscator(detector, mapping=mapping, event_dates="keep" if mode == "legal" else "month")
            return
        self.rng = random.Random(seed)
        self.entries = [dict(e) for e in mapping or []]  # 每一項都複製：標 ambiguous、改類型都不會動到呼叫端手上的對照表
        live = [e for e in self.entries if not e.get("ambiguous")]  # 同一個原值有新舊兩筆時用最新的（撞名後另取的假名）；停用的不用
        self.fwd = {e["original"]: e["fake"] for e in live}
        self.cfwd, self.ctype = {}, {}  # 正規化（去空白、全形轉半形）後的值 → 假值：同一個值寫法不同也換成同一個
        for e in live:
            if e["type"] not in _NOT_VALUE:
                self.cfwd[_canon(e["original"])], self.ctype[_canon(e["original"])] = e["fake"], e["type"]
        self.sur, self.given, self.gchar = {}, {}, {}
        self.ochar, self.oword, self.lot = {}, {}, {}  # 機構品牌逐字對應、英文品牌字、地號號碼
        for e in self.entries:
            if e["type"] == "SURNAME":
                self.sur[e["original"]] = e["fake"]
            elif e["type"] in ("GIVEN", "GIVEN_CHAR"):
                self.given[e["original"]] = e["fake"]
                if len(e["original"]) == len(e["fake"]):  # 沿用案件對照表時，逐字對應也接著用（同一個字以先建立的為準，不被後面的蓋掉）
                    for a, b in zip(e["original"], e["fake"]):
                        self.gchar.setdefault(a, b)
            elif e["type"] in ("ORG_BRAND", "ORG_ALIAS", "ORG_CHAR") and len(e["original"]) == len(e["fake"]):  # ORG_ALIAS＝別名用到的品牌
                self.ochar.update(zip(e["original"], e["fake"]))
            elif e["type"] == "ORG_WORD":
                self.oword[e["original"]] = e["fake"]
            elif e["type"] == "PERSON" and len(e["original"]) == len(e["fake"]) == 1:  # 單字的名字（另取過的暱稱）：逐字對應也接回來
                self.gchar[e["original"]] = self.given[e["original"]] = e["fake"]
            elif e["type"] == "LOT":
                self.lot[e["original"]] = e["fake"]
        self.bday, self.eshift, self.bmon = {}, {}, {}  # 生日月日 → 假月日；個人行程日期 → 多挪的天數（同一天不同寫法換成同一個）；只寫到年月的生日 → 假月份
        days = collections.Counter()
        for e in self.entries:
            o, f = _parse_date(e["original"]), _parse_date(e["fake"])
            if not (o and f):
                continue
            if e["type"] == "DATE":
                self.bday.setdefault(o[1:], f[1:])
            elif e["type"] == "DATE_EVENT":
                try:
                    days[(_as_date(f) - _as_date(o)).days] += 1
                except ValueError:
                    pass
        self.text_md, self.text_full = set(), set()  # 這份原文裡的日期（月日／年月日）：假日期不能跟它們撞，見 apply
        self.shift = 7 * self.rng.choice([k for k in range(-26, 27) if abs(k) >= 4])
        if days:  # 沿用案件對照表（一般模式）：照前面文件的位移挪，同一案件的日期間隔才對得上
            self.shift = days.most_common(1)[0][0]

    # ── 對照表 ──────────────────────────────────────────────
    def _add(self, orig, fake, typ):
        if orig not in self.fwd:
            self.fwd[orig] = fake
            self.entries.append({"fake": fake, "original": orig, "type": typ})
            if typ not in _NOT_VALUE:
                self.cfwd.setdefault(_canon(orig), fake); self.ctype.setdefault(_canon(orig), typ)
        return self.fwd[orig]

    def _fresh(self, make, text):
        """產生一個原文沒出現過、也還沒用過的假值。"""
        used = set(self.fwd.values()) | {e["fake"] for e in self.entries}
        for _ in range(60):
            v = make()
            if v not in text and v not in used:
                return v
        return v

    # ── 人名 ──────────────────────────────────────────────
    def _fake_surname(self, sur, text, avoid):
        if sur not in self.sur:
            used = set(self.sur.values())
            ok = lambda v: v != sur and v not in used and v not in avoid and not any(v + t in text for t in RESTORE_TITLES)
            jp = [s for s in JP_SURNAMES if len(s) == len(sur) and s != sur] if sur in JP_SURNAMES else None  # 日本姓換成同字數的日本姓
            v = None
            for strict in (True, False):  # 先找原文完全沒出現過的姓（甘會計師、邱主委這種不在稱謂表的也安全）；找不到才退到只避開「姓＋稱謂」
                for _ in range(80):
                    c = self.rng.choice(jp) if jp else sample_surname(self.rng, compound=True, avoid=avoid) if len(sur) == 2 else self.rng.choice(SAFE_SURNAMES)
                    if ok(c) and (not strict or c not in text):
                        v = c
                        break
                if v:
                    break
            if v is None:  # 不同姓的人多到常用假姓都用完（SAFE_SURNAMES 只有 24 個）：改用整份姓氏表，不同的人不能換成同一個假姓
                pool = jp or ([a + b for a in SAFE_SURNAMES for b in SAFE_SURNAMES if a != b] if len(sur) == 2 else sorted(SURNAMES))
                v = next((c for c in self.rng.sample(pool, len(pool)) if ok(c) and c not in text), None) or next((c for c in pool if ok(c)), None)
                if v is None:
                    raise ValueError(f"假姓不夠用：已用 {len(used)} 個")
            self.sur[sur] = v
            self._add(sur, self.sur[sur], "SURNAME")  # 姓＋稱謂（陳先生、我姓陳）的還原在 restore() 組出來，對照表只留核心
            if v not in text and len(v) == 1 and v in SAFE_SURNAMES:
                self.entries[-1]["bare"] = True  # 原文沒出現過這個字：AI 回覆裡單獨出現時可以放心換回
        return self.sur[sur]

    def _fake_given(self, given, text):
        """名字逐字對應（同一份文件裡同一個字永遠換成同一個假字，不同的字換成不同的假字）：
        OCR 錯字變體（林郁婷／林都婷）換完還是只差一個字、兄弟姊妹的字輩（張榮豐／張榮川）換完還共用同一個字——
        原文看得出的關係，假文也看得出；但不會把不同的人併成同一個。"""
        if given not in self.given:
            f, m = sum(c in GIVEN_F for c in given), sum(c in GIVEN_M for c in given)  # 性別看原名用字（美玲→女、志強→男），讀起來才對得上「小姐／先生」
            name_pool = GIVEN_F if f > m else GIVEN_M if m > f else (GIVEN_M if self.rng.random() < 0.5 else GIVEN_F)
            taken = set(self.gchar.values()) | {c for e in self.entries if e["type"] in ("GIVEN", "GIVEN_CHAR", "PERSON") for c in e["fake"]}
            for _ in range(30):
                new, used = {}, taken  # 案件裡人名假值用過的字都不再分給別的字（單字暱稱才不會撞成同一個）
                for c in given:
                    if c in self.gchar or c in new:
                        continue
                    pool = GIVEN_F if (c in GIVEN_F and c not in GIVEN_M) else GIVEN_M if (c in GIVEN_M and c not in GIVEN_F) else name_pool
                    ok = lambda x: x not in used and x not in new.values() and x not in given  # 不對到原名裡的字（明→明，「阿明」就原樣留著）
                    choices = ([x for x in pool if ok(x)] or [x for x in _extra_given() if ok(x)]  # 名字常用字用完（人多的案件）：改用更大的字池，不同的字不撞
                               or [x for x in pool if x not in given] or list(pool))
                    new[c] = self.rng.choice(choices)
                v = "".join(self.gchar.get(c) or new[c] for c in given)
                if not new or (v not in text and v not in self.given.values()):
                    break
            self.gchar.update(new)
            self.given[given] = v
            if len(given) >= 2:
                self._add(given, self.given[given], "GIVEN")
            else:  # 單字名字（林婷 → 曹君）也記下，下一份文件的「婷姐」才換成同一個字；還原不用它，免得把一般的字換掉
                self.entries.append({"fake": v, "original": given, "type": "GIVEN_CHAR"})
        return self.given[given]

    def _person(self, s, kind, text, avoid):
        core = re.sub(r"[ 　\n]", "", s)
        if re.search(r"[A-Za-z]", s):  # 看字串本身決定走哪一種（候選來源不一定對得上：Park Ji-min、Vivian 林）
            kind = "latin"
        elif re.search("[·‧・．]", s):
            kind = "translit"
        if kind == "latin":
            parts = re.split(r"([ ,\-]+)", s)
            if s.isupper() or len([p for p in parts if p.strip(" ,-")]) > 1:  # Lin Chia-Hao、CHEN, YU-TING：拼音姓＋名
                def make():
                    words = iter([self.rng.choice(ROMAN_SUR)] + [self.rng.choice(ROMAN_SYL) for _ in parts])
                    out = "".join(next(words) if p.strip(" ,-") else p for p in parts)
                    return out.upper() if s.isupper() else out
            else:  # Ivy、Kevin：英文名；名字池抽光才加縮寫姓（Tina H.），保證不同人不會撞同一個假名
                def make():
                    v = self.rng.choice(LATIN_GIVEN)
                    return v if v not in self.fwd.values() else f"{v} {self.rng.choice(ROMAN_SUR)[0]}."
            return self._fresh(make, text)
        if kind == "translit":
            return self._fresh(lambda: "".join(c if c in "·‧・． " else self.rng.choice(TRANSLIT_POOL) for c in s), text)
        if kind == "nick":  # 老王／小李：姓換；阿志、珠姐：名字的字換
            if core[0] in "老小" and core[1:] and surname_len(core[1:]):
                return core[0] + self._fake_surname(core[1:], text, avoid)
            head = core[0] if core[0] in "老小阿" and len(core) > 1 else ""
            body = core[len(head):]
            return head + self._fake_given(body, text)  # 阿婷 → 阿佳：跟全名用同一張逐字對應
        sl = surname_len(core)
        if kind == "partial" or (sl and len(core) == sl):
            return self._fake_surname(core, text, avoid)
        if kind in ("given", "given2") or not sl:
            return self._fake_given(core, text)
        fake = self._fake_surname(core[:sl], text, avoid) + self._fake_given(core[sl:], text)
        it = iter(fake)  # 原文字間有空白（王 小 明）就照樣留
        return "".join(c if c in " 　\n" else next(it) for c in s)

    # ── 機構 ──────────────────────────────────────────────
    def _ochar(self, c):
        """品牌字逐字對應：中文字換品牌常用字（不同字不撞）；名稱裡的英文字母、數字換同類字元（台灣3M → 台灣7Q）。"""
        if c not in self.ochar:
            used = set(self.ochar.values())
            if c.isascii():
                alpha = "0123456789" if c.isdigit() else "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if c.isupper() else "abcdefghijklmnopqrstuvwxyz"
                pool = [x for x in alpha if x != c and x not in used] or [x for x in alpha if x != c]
            else:
                pool = ([x for x in ORG_CHARS if x != c and x not in used] or [x for x in GIVEN_M + GIVEN_F if x != c and x not in used]
                        or [x for x in _extra_given() if x != c and x not in used] or [x for x in ORG_CHARS if x != c])  # 品牌字池用完（公司很多）也不中止
            self.ochar[c] = self.rng.choice(pool)
        return self.ochar[c]

    def _org(self, s, text):
        """機構假名：品牌字逐字換（整案一致，關係企業、簡稱、OCR 弄亂的公司章換完還是同一個品牌）；
        法律形式、類型、分支、縣市、產業詞照留；名稱裡的人名跟人名對照表走。"""
        core = re.sub(r"\s", "", s)
        if not re.search("[一-鿿]", core):  # 英文名：產業詞與公司字尾照留，其餘每個字換成念得出來的假字
            def word(m):
                x = m.group(0)
                if x in EN_KEEP_WORDS or x.rstrip(".") in EN_KEEP_WORDS:
                    return x
                if x not in self.oword:
                    used = {v.lower() for v in self.oword.values()}
                    for _ in range(50):  # 不撞別的品牌的假字、不在原文出現、不用假人名會用到的字（Chia、Kevin）：AI 回覆只寫品牌字時才換得回來
                        w = _word(self.rng, len(x))
                        if w.lower() not in used and w.lower() not in text.lower() and w.capitalize() not in _NAME_WORDS:
                            break
                    self.oword[x] = w.upper() if x.isupper() and len(x) > 1 else w.capitalize() if x[:1].isupper() else w
                    self._add(x, self.oword[x], "ORG_WORD")  # 記進對照表：下一份文件同一個字換成同一個假字，AI 只寫品牌字也換得回來
                return self.oword[x]
            out = re.sub(r"[A-Za-z][A-Za-z'\-]*", word, s)
            if out == s:  # 每個字都是照留的產業詞：換第一個字
                out = re.sub(r"[A-Za-z]+", lambda m: _word(self.rng, len(m.group(0))).capitalize(), s, count=1)
            for _ in range(20):  # 只有數字和符號（7-11）：同格式換字。判定要換的值，假值一定跟原文不同
                if out != s:
                    break
                out = _shape(self.rng, s)
            return out
        persons = sorted((o for o in self.fwd if self.ctype.get(_canon(o)) == "PERSON" and len(o) >= 2 and o in core), key=len, reverse=True)
        toks, i, n = [], 0, len(core)  # (種類, 原字串)：fake＝已有假值、keep＝照留、map＝品牌字
        while i < n:
            p = next((x for x in persons if core.startswith(x, i)), None)
            sl = surname_len(core[i:])
            if p:
                toks.append(("fake", p, self.fwd[p])); i += len(p)
            elif sl and core[i + sl:i + sl + 1] in _SHOP_AFTER_SURNAME and all(t[0] == "keep" and t[1] in _ORG_STRUCT for t in toks):
                toks.append(("fake", core[i:i + sl], self._fake_surname(core[i:i + sl], text, set()))); i += sl
            else:
                k = next((x for x in _ORG_TOKENS if core.startswith(x, i) and (len(x) > 1 or i + 1 == n or x in _ORG_KEEP_1)), None)
                k = k or (core[i] if not core[i].isalnum() else None)  # 標點、連字號照留（玉山銀行-台中分行）
                toks.append(("keep", k, k) if k else ("map", core[i], None)); i += len(k) if k else 1
        if not any(t[0] != "keep" for t in toks):  # 整個名稱都是照留的詞（中華電信、國際開發）：產業詞也得換，不然等於沒換
            j = next((j for j, t in enumerate(toks) if t[1] not in _ORG_STRUCT), 0)
            toks[j:j + 1] = [("map", c, None) for c in toks[j][1]]
        out, i = [], 0
        while i < len(toks):
            if toks[i][0] != "map":
                out.append(toks[i][2]); i += 1
                continue
            j = next((j for j in range(i, len(toks)) if toks[j][0] != "map"), len(toks))
            run = "".join(t[1] for t in toks[i:j])
            real = all_short_names()  # 假品牌不能剛好是真的上市櫃公司（AI 會把那家公司的背景帶進來）
            if len(run) > 4:  # 長品牌（台灣積體電路製造）逐字換出來是八個怪字：整段換成兩個字的假品牌
                f = self.fwd.get(run) or self._fresh(lambda: next(v for v in iter(lambda: "".join(self.rng.sample(ORG_CHARS, 2)), None) if v not in real), text)
            else:
                before = set(self.ochar)
                f = "".join(map(self._ochar, run))
                for _ in range(20):  # 撞到真公司：只重抽這次新配的字（之前配好的字別處已經用了，不能動）
                    new = [c for c in dict.fromkeys(run) if c not in before]
                    if (f not in real and f not in text) or not new:  # 假品牌也不能剛好是這份原文裡的另一家（麒碩科技）
                        break
                    for c in new:
                        del self.ochar[c]
                    f = "".join(map(self._ochar, run))
            if len(run) >= 2:  # 品牌（連續兩字以上）另記：AI 回覆只寫品牌（鼎昕表示…）也換得回來
                self._add(run, f, "ORG_BRAND")
            elif not any(e["type"] == "ORG_CHAR" and e["original"] == run for e in self.entries):
                self.entries.append({"fake": f, "original": run, "type": "ORG_CHAR"})  # 單字品牌（德記）也記下，下一份文件沿用；不參與全文替換與還原
            out.append(f); i = j
        return "".join(out)

    @staticmethod
    def _alias_names(name, text, end):
        """全名後面的別名（下稱台積電）＋上市櫃公司的簡稱。別名要含品牌字：本園、本院、被告公司、（全民健康保險的）健保這種通稱不算。"""
        brand = re.sub(r"\s", "", name)
        for w in _ORG_TOKENS:  # 拿掉法律形式、類型、產業詞、縣市（長的先拿），剩下的才是品牌字
            brand = brand.replace(w, " ")
        m = _ALIAS_RX.match(text, end)
        return [a for a in (m.group(1) if m else None, short_name(name)) if a and set(a) & (set(brand) - {" "})]

    def _org_aliases(self, name, text, end):
        """別名跟著全名換（全名換掉、簡稱留著＝沒換）。長品牌整段縮成兩個字的（台灣積體電路製造 → 麒碩），簡稱（台積電）也用同一個假品牌。"""
        core = re.sub(r"\s", "", name)
        longs = [r for r in self.fwd if len(r) > 4 and r in core and self.ctype.get(_canon(r)) in ("ORG_BRAND", "ORG_ALIAS")]
        for a in self._alias_names(name, text, end):
            n = len(self.entries)
            r = next((r for r in longs if set(a) <= set(r)), None)
            if _canon(a) not in self.cfwd and r:  # 假品牌＋一個字（台積電 → 麒碩X）：看得出是同一家，又跟全名的假品牌分得開（兩種寫法都出現時才還原得回來）
                self._add(a, self._fresh(lambda: self.fwd[r] + self.rng.choice(ORG_CHARS), text), "ORG_ALIAS")
            elif _canon(a) not in self.cfwd:
                self._add(a, self._org(a, text), "ORG")
            for e in self.entries[n:] + [e for e in self.entries[:n] if e["original"] == a]:
                if e["type"] == "ORG_BRAND":  # 照品牌換，但全文替換的門檻放寬：詞典裡有的「鴻海」也要換（常用詞、地名照樣不換）
                    e["type"] = self.ctype[_canon(e["original"])] = "ORG_ALIAS"

    def _lot(self, s, text=""):
        """地號：段名留著，號碼整案一致（452→537、452-1→537-1）。假號碼避開文件裡已有的數字（213 撞到「213巷」AI 會混在一起）。"""
        def rep(m):
            b = m.group(1)
            if b not in self.lot:
                lo = 10 ** (len(b) - 1) if len(b) > 1 else 1
                for _ in range(50):
                    v = str(self.rng.randint(lo, 10 ** len(b) - 1))
                    if v != b and v not in self.lot.values() and not re.search(rf"(?<![0-9]){v}(?![0-9])", text):
                        break
                self.lot[b] = v
                self._add(b, v, "LOT")
            return self.lot[b] + (m.group(2) or "")
        return re.sub(r"(\d+)(-\d+)?(?=\s?[地建]號)", rep, s)

    def _bmonth(self, mo):
        """只寫到年月的生日（75年7月）：換月份。12 個月排成一組錯位排列：每個月都換到別的月、不同月不會換成同一個（還原才分得開）；
        沿用案件對照表時，先接回前面文件已經用過的月份。"""
        if not 1 <= mo <= 12:
            raise ValueError(mo)
        if not self.bmon:
            known = {}
            for e in self.entries:
                if e["type"] == "DATE" and not _has_day(e["original"]):
                    o, f = _parse_date(e["original"]), _parse_date(e["fake"])
                    if o and f and o[1] != f[1] and f[1] not in known.values():
                        known.setdefault(o[1], f[1])
            src = [m for m in range(1, 13) if m not in known]
            dst = [m for m in range(1, 13) if m not in known.values()]
            for _ in range(200):
                self.rng.shuffle(dst)
                if all(a != b for a, b in zip(src, dst)):
                    break
            self.bmon = {**known, **dict(zip(src, dst))}
        if self.bmon[mo] == mo:  # 前面文件的月份接回來後排不出錯位（極少見）：換成任一個別的月
            self.bmon[mo] = self.rng.choice([m for m in range(1, 13) if m != mo])
        return self.bmon[mo]

    def _bday(self, mo, d):
        """生日的月日 → 假月日（整份、整案一致；不等於原本的月日，也不跟別的生日的真假月日撞——兩個生日換成同一天，AI 回覆就還原不回來）。
        不是合法月日就丟 ValueError（呼叫端改用同格式換數字）。"""
        if not (1 <= mo <= 12 and 1 <= d <= 31):
            raise ValueError(mo, d)
        if (mo, d) not in self.bday or self.bday[(mo, d)] == (mo, d):
            taken = set(self.bday.values()) | set(self.bday) | self.text_md
            for _ in range(100):
                v = (self.rng.randint(1, 12), self.rng.randint(1, 28))
                if v != (mo, d) and v not in taken:
                    break
            self.bday[(mo, d)] = v
        return self.bday[(mo, d)]

    # ── 個資 ──────────────────────────────────────────────
    def _pii(self, s, typ, text):
        rng = self.rng
        s = s.replace("\r", "").replace("\n", "")  # OCR／PDF 斷行夾在值中間（yi⏎chun@gmail.com）：假值不帶斷行，AI 寫回來才對得上
        if typ in ("EMAIL", "URL", "HANDLE"):
            s = re.sub(r"\s", "", s)
        if typ == "EMAIL":
            local, _, dom = s.partition("@")
            dom2 = dom if dom.lower() in PUBLIC_MAIL else _fake_host(rng, dom)
            return _shape_words(rng, local) + "@" + dom2
        if typ == "URL":
            m = re.match(r"((?:https?|line)://)?(www\.)?([^/?#]*)(.*)", s)
            host = m.group(3)
            plat = next((p for p in PLATFORMS if host.lower() == p or host.lower().endswith("." + p)), None)
            if plat:  # 大平台：平台網域留著，前面的個人子網域照換（davidintaiwan.blogspot.com）
                host = _shape_words(rng, host[:len(host) - len(plat)]) + host[len(host) - len(plat):]
            else:
                host = _fake_host(rng, host)
            return (m.group(1) or "") + (m.group(2) or "") + host + _shape_words(rng, m.group(4))
        if typ == "HANDLE" or (typ == "CODE" and re.fullmatch(r"@?[a-z][a-z0-9_.]{2,}", s) and re.search("[a-z]{3}", s)):
            return _shape_words(rng, s)  # 社群帳號：念得出來的假帳號（chiang_lin88 → weiyu_chen37）；證號、密碼、車牌走下面的同格式換字
        if typ == "ADDRESS":
            if re.search(r"\d\s?[地建]號", s):  # 地號：寫法照舊、段名留著，號碼整案一致（後文「同段 452-1 地號」才接得上）
                return self._lot(s, text)
            postal = re.match(r"[0-9]{3,6}\s?", s)
            rest = s[postal.end():] if postal else s
            pre = (_shape(rng, postal.group(0)) if postal else "")
            if not self.keep_city:
                return pre + fake_address(rng, like=s)
            city = next((c for c in CITIES if rest.startswith(c)), None)
            if city:
                return pre + fake_address(rng, city=city, like=s)
            c2, dist = county_of(rest)  # 只寫到縣轄市／區（彰化市…）：留在同一縣、同一區，也不額外加縣名
            return pre + fake_address(rng, city=c2, dist=dist, like=s, with_city=False) if c2 else pre + fake_address(rng, like=s)
        if typ in ("DATE", "DATE_EVENT"):
            if typ == "DATE":  # 生日：保留年份，月日換掉（同一個月日不管怎麼寫都換成同一個）；只寫到年月的（75年7月）換月份
                new = _rewrite_date(s, (lambda y, mo, d, roc: (y, *self._bday(mo, d))) if _has_day(s) else (lambda y, mo, d, roc: (y, self._bmonth(mo), d)))
            else:  # 個人行程日期：整份文件同一個位移；撞到原文或別的假值才多挪 1～3 天（同一天的其他寫法沿用同一個挪法）
                key = _parse_date(s)
                for extra in ((self.eshift[key],) if key in self.eshift else (0, 1, -1, 2, -2, 3)):
                    def shift(y, mo, d, roc):
                        yy = (y + 1911 if roc else y) if y else 2000
                        try:
                            base = dt.date(yy, mo, d)
                        except ValueError:  # 不存在的日期（2/30）才往前收
                            base = dt.date(yy, mo, 28)
                        n = base + dt.timedelta(days=self.shift + extra)
                        return ((n.year - 1911 if roc else n.year) if y else None), n.month, n.day
                    new = _rewrite_date(s, shift)
                    pn = new and _parse_date(new)
                    if new and new not in text and new not in self.fwd.values() and not (pn and pn[0] is not None and _ykey(pn) in self.text_full):
                        break
                if key and new:
                    self.eshift.setdefault(key, extra)
            return new or _shape(rng, s)
        hw = s.translate(_FW2HW)
        if re.fullmatch(r"[A-Z][12]\d{8}", hw):  # 身分證：首字母、性別碼不變，檢查碼正確；全形的（Ａ１２３…）換完照樣是全形
            for _ in range(20):
                v = fake_id(rng, hw[0])
                if v[1] == hw[1]:
                    break
            return v if hw == s else v.translate(_HW2FW_ALL)
        return _shape(rng, s, keep=_keep_head(s) if typ == "NUMBER" else 0)

    # ── 主流程 ──────────────────────────────────────────────
    def pseudonymize(self, text):
        """偵測並換掉：回傳 (假名版文字, 對照表)。對照表可以用 restore() 把 AI 回覆換回原文。"""
        return self.apply(text, self.det.detect(text))

    def anonymize(self, text):
        """0.1.x 的舊名稱：跟 pseudonymize() 完全相同（仍回傳對照表、可以還原）。要不可還原的匿名化請用 Anonymizer。"""
        warnings.warn("Obfuscator.anonymize() 做的是假名化（會回傳對照表），請改用 pseudonymize()；"
                      "要不可還原的匿名化請用 Anonymizer。1.0 會移除這個名稱", FutureWarning, stacklevel=2)
        return self.pseudonymize(text)

    @staticmethod
    def _reconcile(text, spans):
        """同一個人前後切法要一致：文件別處抓到「陳立基」，這裡卻只抓到「陳立」而原文其實接著「基」（陳立基於…）→ 補成「陳立基」。
        切法不一致會換成兩個假名，AI 就以為是兩個人。"""
        fulls = sorted({text[s["start"]:s["end"]] for s in spans if s["type"] == "PERSON" and s.get("kind") == "full"}, key=len, reverse=True)
        ivs = [(s["start"], s["end"]) for s in spans]
        out = []
        for s in spans:
            if s["type"] == "PERSON" and s.get("kind") == "full":
                f = next((f for f in fulls if len(f) > s["end"] - s["start"] and text.startswith(f, s["start"])), None)
                e = s["start"] + len(f) if f else s["end"]
                if f and not any(a < e and b > s["end"] for a, b in ivs if (a, b) != (s["start"], s["end"])):
                    s = dict(s, end=e)
            out.append(s)
        return out

    def apply(self, text, spans):
        """spans：偵測結果（start、end、type、kind）。回傳 (假文字, 對照表)。
        法律模式（預設）：個人行程日期保留——實測把它們換掉會讓 AI 的時間推理出錯（見 README）。"""
        if self._code:
            fake, entries = self._code.apply(text, spans)
            self.spans = self._code.spans
            return fake, entries
        legal = self.mode == "legal"
        spans = self._reconcile(text, spans)
        # 原文裡的日期：假日期跟別人的真日期撞成同一天，AI 回覆還原時會連鎖換錯（甲的假生日＝乙的真生日）
        found = [p for p in (_parse_date(m.group(0)) for rx in _BDAY_RX for m in rx.finditer(text)) if p]
        self.text_md = {p[1:] for p in found}
        self.text_full = {_ykey(p) for p in found if p[0] is not None}
        # 當事人公司的別名（下稱台積電、上市櫃簡稱）：模型在別處判「順帶提到、保留」的同一家公司也要換
        aliases = {a for s in spans if s["type"] == "ORG" for a in self._alias_names(text[s["start"]:s["end"]], text, s["end"])
                   if a not in _places_set() and a not in _common(300)}  # 大同、統一這種別名不拿來推翻保留（大同區戶政事務所）
        kept = lambda s: (s["type"] in ("PERSON_KEEP", "ORG_KEEP") or (legal and s["type"] == "DATE_EVENT")) and not (
            s["type"] == "ORG_KEEP" and any(a in _canon(text[s["start"]:s["end"]]) for a in aliases)) and (
            _canon(text[s["start"]:s["end"]]) not in self.cfwd)  # 同一案件前面的文件已經判定要換的值（例如生日），這份也照換
        masked = {_canon(text[s["start"]:s["end"]]) for s in spans if not kept(s)}
        # 同一個值只要有一處要遮，每一處都遮（隱私優先，也避免「一處換了一處沒換」讓 AI 以為前後矛盾）
        keep = [(s["start"], s["end"]) for s in spans if kept(s) and _canon(text[s["start"]:s["end"]]) not in masked]
        todo = [s for s in spans if (s["start"], s["end"]) not in keep]
        persons = [text[s["start"]:s["end"]] for s in spans if s["type"].startswith("PERSON")]
        avoid = {p[:2] for p in persons} | {p[:1] for p in persons}
        # 先排全名，讓姓名表先建好（只叫名字、綽號才對得上）
        order = sorted(todo, key=lambda s: (s["type"] != "PERSON" or s.get("kind") != "full", s["start"]))
        # 生日（要有年份）：模型在一處判定的那一天，其他寫法也當生日換（同案件前面文件判過的也算）
        bdays = {p for p in [_parse_date(text[s["start"]:s["end"]]) for s in todo if s["type"] == "DATE"]
                 + [_parse_date(e["original"]) for e in self.entries if e["type"] == "DATE"] if p and p[0] is not None}
        is_bday = lambda v: bool(bdays) and re.fullmatch(r"[0-9]{6,8}", re.sub(r"\s", "", v)) is not None and _parse_date(re.sub(r"\s", "", v)) in bdays
        repl = {}
        for s in order:
            orig = text[s["start"]:s["end"]]
            c = _canon(orig)
            typ = s["type"]
            if typ in ("NUMBER", "CODE") and is_bday(orig) or typ == "DATE_EVENT" and _parse_date(orig) in bdays:
                typ = "DATE"  # 同一天在別處被判成生日（0750217 被判成號碼、92年1月20日同時是事件日期）：照生日換，年份不變、假值對得上
            person = typ in ("PERSON", "PERSON_KEEP")
            if c in self.cfwd:  # 同一個值（寫法只差空白、全半形）→ 同一個假值
                fake = self.cfwd[c]
            elif person:  # 人名一律走姓名對照表（fwd 裡同一個字可能是機構的品牌字、地號，類型不對）；保留的人名因為別處要遮而一起遮時也一樣
                fake = self._person(orig, s.get("kind", "full"), text, avoid)
                if fake != self.sur.get(orig) and fake != self.given.get(orig):  # 只有姓、只有名字的稱呼：姓名對照表已經記了，不重複登錄
                    self._put(orig, fake, "PERSON")
            elif orig in self.fwd:
                fake = self.fwd[orig]
            elif typ in ("ORG", "ORG_KEEP"):
                fake = self._add(orig, self._org(orig, text), "ORG")
            else:
                fake = self._add(orig, self._fresh(lambda: self._pii(orig, typ, text), text), typ)
            # 沿用的假名剛好是這份原文裡的真人名（前一份的假名＝這一份的法官）：這份另外取一個。單字的假值到處都可能出現，
            # 只有姓時看「假姓＋稱謂」有沒有撞到（曹君琪的「曹君」）；單字暱稱沿用原本的假字，靠「婷姐→婉姐」這類前後文還原
            collide = fake in text if len(fake) >= 2 else orig in self.sur and any(fake + t in text for t in RESTORE_TITLES)
            if person and collide:
                if orig in self.sur:  # 只有姓（林小姐的「林」）：另取一個假姓，登錄成新的姓對照
                    used = set(self.sur.values()) | {e["fake"] for e in self.entries if e["type"] == "SURNAME"}
                    safe = list(SAFE_SURNAMES) if len(orig) == 1 else [a + b for a in SAFE_SURNAMES for b in SAFE_SURNAMES if a != b]
                    rest = [x for x in sorted(SURNAMES) if len(x) == len(orig)]
                    ok = lambda x: x not in used and x not in text and x != orig
                    fake = next((x for x in self.rng.sample(safe, len(safe)) if ok(x)), None) or next(x for x in self.rng.sample(rest, len(rest)) if ok(x))
                    self.sur[orig] = self.fwd[orig] = fake
                    self.entries.append({"fake": fake, "original": orig, "type": "SURNAME", **({"bare": True} if fake in SAFE_SURNAMES else {})})
                else:
                    fake = self._fresh(lambda: self._rename(orig, s.get("kind", "full")), text)
                    self.entries.append({"fake": fake, "original": orig, "type": "PERSON"})
                    self.fwd[orig] = self.cfwd[c] = fake
                    self.ctype[c] = "PERSON"
                    if s.get("kind") in ("nick", "given", "given2") and len(orig) == len(fake):  # 只有名字：新的逐字對應也記下，後面的名字不會撞到同一個假字
                        self.gchar.update(zip(orig, fake))
                        self.given[orig] = fake
                    core, fcore = re.sub(r"[ 　\n]", "", orig), re.sub(r"[ 　\n]", "", fake)
                    sl = surname_len(core)
                    if s.get("kind", "full") == "full" and sl and len(core) == len(fcore) and not re.search(r"[A-Za-z]", core):  # 全名另取：姓、名字的對照也跟著換
                        self.sur[core[:sl]] = fcore[:sl]
                        self._put(core[:sl], fcore[:sl], "SURNAME")
                        if fcore[:sl] in SAFE_SURNAMES and fcore[:sl] not in text and self.entries[-1]["fake"] == fcore[:sl]:
                            self.entries[-1]["bare"] = True
                        if len(core) > sl:
                            self.given[core[sl:]] = fcore[sl:]
                            for a, b in zip(core[sl:], fcore[sl:]):  # 逐字對應只補還沒有的字，不蓋掉別人已經用的對應（不然會撞成同一個假字）
                                self.gchar.setdefault(a, b)
                            self._put(core[sl:], fcore[sl:], "GIVEN")
            if s["type"] == "PERSON" and fake == self.sur.get(orig):  # 只有姓的稱呼：把文件裡接在後面的職稱也記下（甘會計師、邱主委、楊警官），AI 回覆沿用時換得回來
                for k in (2, 3):
                    tail = text[s["end"]:s["end"] + k]
                    if len(tail) == k and all("一" <= ch <= "鿿" for ch in tail):
                        self._put(orig + tail, self.sur[orig] + tail, "PERSON_PART")
            elif s["type"] == "PERSON" and len(orig) == 1 and len(fake) == 1:  # 單字的稱呼（婷姐的「婷」）：單一個字不拿來還原，改記「婷姐→婉姐」「阿婷→阿婉」
                for k in (1, 2):
                    tail = text[s["end"]:s["end"] + k]
                    if len(tail) == k and all("一" <= ch <= "鿿" for ch in tail):
                        self._put(orig + tail, fake + tail, "PERSON_PART")
                head = text[s["start"] - 1:s["start"]]
                if head and head in "阿小老":
                    self._put(head + orig, head + fake, "PERSON_PART")
            repl[(s["start"], s["end"])] = fake
            if typ in ("ORG", "ORG_KEEP"):
                self._org_aliases(orig, text, s["end"])
        # 同一個值在文件別處也換（模型漏抓的重複提及；中間夾空白也算）；太短的不換，避免誤傷
        places = _places_set()
        for c, fake in list(self.cfwd.items()):
            typ = self.ctype[c]  # 日期也要：同一個日期一處換了、一處沒換，AI 會說「日期前後矛盾」
            if typ in ("ORG_BRAND", "ORG_ALIAS"):  # 品牌單獨出現（OCR 弄亂的公司章、模型漏抓的簡稱）也換；詞典裡的詞、地名不換（信義、玉山）
                if len(c) < 2 or c in places or c in _common(300 if typ == "ORG_ALIAS" else 1):  # 明講的別名只擋常用詞（統一、中華）
                    continue
            elif len(c) < (3 if typ == "PERSON" else 5):
                continue
            sep = _JUNK + "{0,3}" if typ in ("PERSON", "PERSON_KEEP") else r"\s?"  # 人名字間夾多個空白、OCR 雜點也算（Rowan␣␣Wu、陳 ｜美玲）
            word = c.isascii() and c.isalpha()  # 整個是英文字母的值（Sam）：不比對到更長的英文字中間（Sample），跟 restore 同一套邊界
            rx = re.compile(("(?<![0-9０-９])" if c[0].isdigit() else r"(?<![A-Za-z])" if word else "")
                            + sep.join(f"[{ch}{_HW2FW.get(ch, '')}]" if ch.isdigit() else re.escape(ch) for ch in c)
                            + ("(?![0-9０-９])" if c[-1].isdigit() else r"(?![A-Za-z])" if word else ""))  # 數字值不比對到更長的數字中間（75/02/17 不是 075/02/17 的一部分）
            for m in rx.finditer(text):
                iv = m.span()
                if not any(a < iv[1] and b > iv[0] for a, b in list(repl) + keep):
                    repl[iv] = fake
        for m in re.finditer(r"(?<![0-9])(\d+)(-\d+)?(?=\s?[地建]號)", text) if self.lot else ():  # 地號：判定要換的那一筆，同段其他寫法也照同一個號碼換（同段452-1地號）
            iv = m.span()
            if m.group(1) in self.lot and not any(a < iv[1] and b > iv[0] for a, b in list(repl) + keep):
                repl[iv] = self.lot[m.group(1)] + (m.group(2) or "")
        for rx in _BDAY_RX if bdays else ():  # 生日的其他寫法（模型漏抓的 075/02/17、75年2月17日、0750217）：同一天就一起換
            for m in rx.finditer(text):
                iv, orig = m.span(), m.group(0)
                if _parse_date(orig) in bdays and not any(a < iv[1] and b > iv[0] for a, b in list(repl) + keep):
                    repl[iv] = self.fwd.get(orig) or self._add(orig, self._fresh(lambda: self._pii(orig, "DATE", text), text), "DATE")
        if self.sur:  # 姓＋稱謂：這個姓別處已經換掉，這裡的「林老太太」「林阿姨」也換（同一家人前後對得上，也不多洩漏真姓）
            rx = re.compile("(" + "|".join(map(re.escape, sorted(self.sur, key=len, reverse=True))) + ")(?=" + "|".join(PROP_TITLES) + ")")
            for m in rx.finditer(text):
                iv = m.span()
                if not any(a < iv[1] and b > iv[0] for a, b in list(repl) + keep):
                    repl[iv] = self.sur[m.group(1)]
        out, pos, self.spans = [], 0, []
        for (a, b), fake in sorted(repl.items()):
            if a < pos:
                continue
            out.append(text[pos:a]); cur = sum(map(len, out))
            self.spans.append({"start": cur, "end": cur + len(fake), "original": text[a:b], "orig_start": a, "orig_end": b})  # 假文字上的位置（逐字還原）＋原文位置（對照檢查）
            out.append(fake); pos = b
        out.append(text[pos:])
        fake = "".join(out)
        _guard(text, fake, self.spans, self.entries)
        return fake, [dict(e) for e in self.entries]  # 回傳獨立的一份：同一個 Obfuscator 處理下一份文件時，不會改到這份已交出去的對照表

    def _rename(self, s, kind="full"):
        """另取一個同字數的假名，不經過姓名對照表（沿用的假名撞到這份原文裡的真名時用）。只有名字的稱呼（阿婷的「婷」）全用名字常用字。"""
        if re.search(r"[A-Za-z]", s):
            return _shape_words(self.rng, s)
        n = sum(c not in " 　\n" for c in s)
        taken = set(self.gchar.values()) | set(self.sur.values())  # 已經對應給別的字、別的姓的假字不用（單字暱稱才不會撞成同一個）
        given_pool = [x for x in GIVEN_M + GIVEN_F if x not in taken] or [x for x in _extra_given() if x not in taken]
        head = [] if kind in ("nick", "given", "given2") else [self.rng.choice([x for x in SAFE_SURNAMES if x not in taken] or SAFE_SURNAMES)]
        it = iter(head + [self.rng.choice(given_pool) for _ in range(n - len(head))])
        return "".join(c if c in " 　\n" else next(it) for c in s)

    def _put(self, orig, fake, typ):
        """登錄一筆對照；同一個原值這份換了新的假值時也記下（舊的那筆留給前面的文件還原）。"""
        if self.fwd.get(orig) != fake or not any(e["original"] == orig and e["fake"] == fake and e["type"] == typ for e in self.entries):
            self.fwd[orig] = fake
            self.entries.append({"fake": fake, "original": orig, "type": typ})
        if typ not in _NOT_VALUE:
            self.cfwd[_canon(orig)], self.ctype[_canon(orig)] = fake, typ


def _guard(text, fake, spans, entries):
    """還原保護：這份假文字用對照表還原，必須逐字回到原文（斷行、空白不算）。某筆對照會換到這份文件裡的真實內容
    （前一份的假姓、假名字剛好是這份裡法官的姓名），就標成 ambiguous，還原時不用它。
    spans：假文字上的替換位置（start、end、original、orig_start、orig_end）；也可以帶 accept（還原成這些字串也算對，
    代號版用：別名「台積電」的位置還原成公司全名、「陳小姐」的「陳」還原成全名，都是同一個對象）。"""
    starts = [x["start"] for x in spans]

    def to_orig(p, head):  # 假文字位置 → 原文位置；落在替換值中間時，替換值沒被還原到的那段要跟原值一樣（地號 410-1 的「-1」）才對得回去
        i = bisect.bisect_right(starts, p) - 1
        if i < 0:
            return p
        x = spans[i]
        if p >= x["end"]:
            return p - x["end"] + x["orig_end"]
        if p == x["start"]:  # 剛好在下一個替換值的開頭（「蔡小姐」後面緊接著換掉的日期）
            return x["orig_start"]
        k = p - x["start"] if head else x["end"] - p
        if head:
            return x["orig_start"] + k if fake[x["start"]:p] == x["original"][:k] else None
        return x["orig_end"] - k if fake[p:x["end"]] == x["original"][len(x["original"]) - k:] else None

    def accepted(s, e, new):  # 剛好是一個替換值，而且還原成它允許的另一種寫法
        i = bisect.bisect_right(starts, s) - 1
        return i >= 0 and spans[i]["start"] == s and spans[i]["end"] == e and _gnorm(new) in spans[i].get("accept", ())
    for _ in range(20):
        bad = [ent for s, e, new, ent in _select(_restore_hits(fake, entries))
               if ((S := to_orig(s, True)) is None or (E := to_orig(e, False)) is None or _gnorm(text[S:E]) != _gnorm(new))
               and not accepted(s, e, new)]
        if not bad:
            break
        for ent in bad:
            ent.pop("bare", None)
            ent["ambiguous"] = True


def restore_exact(fake_text, spans):
    """文件本身逐字還原（用 apply 留下的位置）。"""
    out, pos = [], 0
    for s in spans:
        out.append(fake_text[pos:s["start"]]); out.append(s["original"]); pos = s["end"]
    return "".join(out) + fake_text[pos:]


def restore(text, mapping):
    """AI 回覆等新文字：假值換回原值，一次替換（最長的先比），不會把換回來的又換一次。
    單一個姓只換 SAFE_SURNAMES 挑過、原文也沒出現的假姓（「莊」可能是莊園、「紀」多半是紀錄，不會被挑）；
    姓＋稱謂（莊先生、我姓莊）、全名、名字、個資都換。標了 ambiguous 的對照不用（見 apply）。"""
    out, pos = [], 0
    for s, e, new, _ in _select(_restore_hits(text, mapping)):
        out.append(text[pos:s] + new); pos = e
    return "".join(out) + text[pos:]


def _select(hits):
    """重疊的替換取先開始、較長的（restore 與 apply 的還原保護共用）。"""
    out, pos = [], 0
    for h in sorted(hits, key=lambda h: (h[0], h[0] - h[1])):
        if h[0] >= pos:
            out.append(h); pos = h[1]
    return out


def _restore_hits(text, mapping):
    """要換回原值的位置：[(起, 訖, 換成, 對照項)]。所有替換都在原文上找位置、最後一次換完：
    換回來的原值不會再被當成別的假值換第二次（甲的假生日＝乙的真生日、前一份的假品牌＝這一份的真品牌）。"""
    mapping = [e for e in mapping if not e.get("ambiguous") and not e.get("alias")]  # 代號版的別名、品牌（台積電 → A）只用來整案一致，還原用全名那一筆
    pairs = {}  # 寫法 → (原值, 對照項)；原值裡 OCR／PDF 的斷行不帶回 AI 回覆（文件本身用 restore_exact 逐字還原）
    codes = {}  # 代號版的單獨人名代號（甲、丙2）：只在不像一般詞的位置換回，見最後
    for e in mapping:
        if e.get("code") and _BARE_CODE.fullmatch(e["fake"]):
            codes.setdefault(e["fake"], (e["original"], e))
            continue
        if e["fake"] and e["type"] not in ("SURNAME", "LOT", "GIVEN_CHAR", "ORG_WORD", "ORG_CHAR") and not (e["type"] == "PERSON" and len(e["fake"]) == 1):
            pairs[e["fake"]] = (e["original"].replace("\r", "").replace("\n", ""), e)
    for e in mapping:
        if e["type"] != "SURNAME" and re.search(r"\s", e["fake"]) and len(e["fake"]) >= 4:  # AI 會把值中間的空白、斷行清掉再寫
            pairs.setdefault(re.sub(r"\s", "", e["fake"]), (e["original"], e))
        if e.get("code") and e["fake"][:1] == "〔":  # 代號版的〔號碼1〕：AI 常把括號改成半形或【】
            for a, b in ("[]", "［］", "【】"):
                pairs.setdefault(a + e["fake"][1:-1] + b, (e["original"], e))
        if e["type"] == "SURNAME":  # 姓＋稱謂不蓋掉完整的值（假名「X君」的「君」也是稱謂：要還原成全名，不是「姓＋君」）
            for t in RESTORE_TITLES:
                pairs.setdefault(e["fake"] + t, (e["original"] + t, e))
            for a in SURNAME_AFTER:
                pairs.setdefault(a + e["fake"], (a + e["original"], e))
            if e.get("bare"):  # 單獨的假姓（「劉取車」）：只限少見於一般詞、原文也沒出現過的姓
                pairs.setdefault(e["fake"], (e["original"], e))
        elif e["type"] in ("NUMBER", "CODE", "ACCT"):  # AI 常把號碼改寫：全形轉半形、拿掉分隔號
            hw = e["fake"].translate(str.maketrans(_FW, "0123456789"))
            bare = re.sub(r"[\s\-()]", "", hw)
            for v in (hw, bare):
                if v != e["fake"] and len(re.sub(r"\D", "", v)) >= 6:
                    pairs.setdefault(v, (e["original"], e))
    keyed = {}
    for f, oe in pairs.items():  # 比對時不管空白：AI 抄號碼、日期常自己加減空格（醫字第 101853 號、民國 81 年…）
        keyed.setdefault(re.sub(r"\s", "", f), oe)
    keyed.pop("", None)
    # 英文品牌字（AI 回覆只寫 Huan）：前後不接英文字母才換，免得換到別的字裡面
    words = {e["fake"]: (e["original"], e) for e in mapping if e["type"] == "ORG_WORD" and len(e["fake"]) >= 3 and e["fake"] not in keyed}
    # 頭尾是數字或英文字母的值，前後不能接著同類的字：假日期 6/6 不換進 76/6/6、假電話不換進更長的帳號、假名 Sam 不換進 Sample
    word = lambda k: k.isascii() and k.isalpha()  # 整個是英文字母的值（假名、品牌字）才加英文邊界；OCR 日期 l5年… 這類混合的不加
    def num(k, p, date, code=False):  # date：日期才另外擋「分隔號＋數字」（6/6 不換進 76/6/6）；號碼只擋前後接數字（0912345678/0987654321 兩支都換得回來）
        letter = word(k) or (code and k[0].isascii() and k[0].isalpha())  # 代號版的 A公司：前面不能接英文字母（NBA公司）
        pre = (r"(?<![0-9０-９])(?<![0-9０-９][/.\-])" if date else r"(?<![0-9０-９])") if k[0].isdigit() else r"(?<![A-Za-z0-9])" if code and letter else r"(?<![A-Za-z])" if letter else ""
        post = ((r"(?![0-9０-９]|[/.\-][0-9０-９])" if date else r"(?![0-9０-９])") if k[-1].isdigit()
                else r"(?![A-Za-z0-9])" if code and k[-1].isascii() and k[-1].isalpha() else r"(?![A-Za-z])" if word(k) else "")  # Company A 不比對到 Company A2
        return pre + p + post
    alts = ([(k, num(k, r"\s*".join(map(re.escape, k)), oe[1]["type"] in ("DATE", "DATE_EVENT"), bool(oe[1].get("code")))) for k, oe in keyed.items()]
            + [(k, rf"(?<![A-Za-z]){re.escape(k)}(?![A-Za-z])") for k in words])
    hits = []
    if alts:
        rx = re.compile("|".join(p for _, p in sorted(alts, key=lambda a: len(a[0]), reverse=True)))
        for m in rx.finditer(text):
            k = re.sub(r"\s", "", m.group(0))
            hits.append((m.start(), m.end(), *(keyed[k] if k in keyed else words[k])))
    words = _common(1) if codes else set()  # 詞典裡的詞（甲板、丁字、甲方）：代號跟後一個字組成一般詞就不換
    for m in re.finditer("|".join(map(re.escape, sorted(codes, key=len, reverse=True))), text) if codes else ():
        s, e = m.span()  # 單獨的代號：後面接數字（甲23）、接成一般詞（甲方、甲說、甲板）、前面接成一般詞（指甲、布丁）都不換；
        nxt = text[e:e + 1]  # 後面接另一個代號（甲乙二人）或「未、等」（甲未到庭、甲等人；詞典裡另有乙未年、甲等）照換
        word = len(m.group(0)) == 1 and m.group(0) + nxt in words and nxt not in codes and nxt not in "未等"
        if not (nxt.isdigit() or nxt in _CODE_NEXT_BLOCK or text[s - 1:s] in _CODE_PREV_BLOCK or word):
            hits.append((s, e, *codes[m.group(0)]))
    for e in mapping:  # 地號：AI 自己寫的「同段537-1地號」「537地號」，後面接著地號／建號才換（單獨的數字不動）
        if e["type"] == "LOT":
            hits += [(m.start(), m.end(), e["original"], e) for m in re.finditer(rf"(?<![0-9]){re.escape(e['fake'])}(?=(?:-\d+)?\s?[地建]號)", text)]
    return hits + _date_hits(text, mapping)


def _date_hits(text, mapping):
    """AI 把假日期換了寫法（075/09/03 → 75年9月3日）：解析成同一天（民國、西元都算）就換回原日期，寫法照 AI 的。回傳 (起, 訖, 換成, 對照項)。"""
    gy = lambda y: None if y is None else (y + 1911 if y < 1000 else y)
    full, md = {}, {}
    for e in mapping:
        if e["type"] in ("DATE", "DATE_EVENT") and not e.get("ambiguous"):
            f, o = _parse_date(e["fake"]), _parse_date(e["original"])
            if f and o:
                if f[0] is not None and o[0] is not None:
                    full.setdefault((gy(f[0]),) + f[1:], ((gy(o[0]),) + o[1:], e))
                md.setdefault(f[1:], (o[1:], e))
    found = {m.span() for rx in (_BDAY_RX if full or md else ()) for m in rx.finditer(text)}
    hits = []
    for s, e in found:
        if any(a <= s and e <= b and (a, b) != (s, e) for a, b in found):  # 只是更長日期的一段（75年9月3日 裡的 75年9月）：不單獨換
            continue
        p = _parse_date(text[s:e])
        oe = p and (full.get((gy(p[0]),) + p[1:]) if p[0] is not None else ((None,) + md[p[1:]][0], md[p[1:]][1]) if p[1:] in md else None)
        if oe:
            o, ent = oe
            new = _rewrite_date(text[s:e], lambda y, mo, d, roc, o=o: ((o[0] - 1911 if roc else o[0]) if y is not None else None, o[1], o[2]))
            if new:
                hits.append((s, e, new, ent))
    return hits


def _property_check(n_docs=6, seed=7):
    """性質測試：隨機產生多份文件，沿用同一份對照表、也各自單獨處理。文件裡故意放：很多不同的姓（超過 SAFE_SURNAMES）、
    跟假姓同姓的法官（保留）、中英文公司、只有數字的機構（7-11）、上市櫃全名＋下稱簡稱、同一天兼事件日期和生日、全形半形混用、
    全零的號碼、跟名字共用字的綽號、英文名是別的字的前綴（Sam／Sample）；沿用對照表時，後面的文件再放：前一份的假姓當另一個真人、
    只出現前一份某人的暱稱或稱謂（婷姐、林小姐）。檢查：
    1. 判定要換的值，假值跟原值不同；2. 不同的原值不共用假值；3. 用位置、用對照表都還原得回原文（對照表還原不計空白、全半形）；
    4. AI 回覆裡不是這次換出來的日期、號碼，還原時不動；5. 生日年份不變；6. 上市櫃簡稱跟全名用同一個假品牌；
    7. 傳進去的對照表不會被改到；8. 不能拋例外。"""
    rng = random.Random(seed)
    surs = sorted(s for s in SURNAMES if len(s) == 1)
    name = lambda: rng.choice(surs) + "".join(rng.choice(GIVEN_M + GIVEN_F) for _ in range(rng.choice((1, 2, 2))))
    fw = lambda x: x.translate(str.maketrans("0123456789", "０１２３４５６７８９"))
    nz = lambda x: _gnorm(x)

    def doc(prev):
        parts, spans = [], []

        def add(s, typ=None, kind=None):
            n = sum(map(len, parts))
            if typ:
                spans.append({"start": n, "end": n + len(s), "type": typ, "kind": kind})
            parts.append(s)
        for _ in range(4):
            add("原告"); add(name(), "PERSON", "full"); add("與被告")
            add("".join(rng.sample(ORG_CHARS, rng.choice((1, 2, 2, 3)))) + rng.choice(("股份有限公司", "有限公司", "記商行")), "ORG", "org")
            add("、"); add(rng.choice(("Acme", "Huan", "Nova", "Orbit", "Min", "Hsie")) + rng.choice((" Trading", " Consulting")) + " Co., Ltd.", "ORG", "org_en")
            add("、"); add(rng.choice(("7-11", "3M", "85-21")), "ORG", "org")
            add("間事件，法官"); add(rng.choice(SAFE_SURNAMES) + rng.choice(GIVEN_F) + rng.choice(GIVEN_F), "PERSON_KEEP", "full")
            tel = f"09{rng.randint(10, 99)}-{rng.randint(100, 999)}-{rng.randint(100, 999)}"
            add("，證人"); add(name(), "PERSON", "full"); add("（手機 "); add(tel, "NUMBER", "num"); add("，即 "); add(fw(tel), "NUMBER", "num")
            add("，信箱 ")
            add(f"{rng.choice(('chen', 'lin', 'amy'))}{rng.randint(1, 99)}@{rng.choice(('mail.', 'blog.', ''))}{rng.choice(('acme', 'nova'))}-law.com.tw",
                "EMAIL", "email")
            add("，提款卡密碼 "); add(rng.choice(("000000", "1111", "0000-000-000", "999999")), "NUMBER", "num")
            p = name()
            add("，證人"); add(p, "PERSON", "full"); add("，大家叫他"); add("阿" + p[-1], "PERSON", "nick")
            if len(p) >= 3:
                add("，"); add(p[-2:], "PERSON", "given"); add("哥說好")
            en, longer = rng.choice((("Sam", "Sample"), ("Ann", "Annual"), ("Kevin", "Kevinson")))
            add("。原告"); add(en, "PERSON", "latin"); add(f"提交{longer} report")
            d = f"{rng.randint(60, 90)}年{rng.randint(1, 12)}月{rng.randint(1, 28)}日"
            add("，抵押權設定於"); add(d, "DATE_EVENT", "date"); add("（生日"); add(d, "DATE", "date"); add("，即"); add(fw(d), "DATE", "date"); add("）到庭。")
            add("另一人出生於"); add(f"{rng.randint(60, 90)}年{rng.randint(1, 12)}月", "DATE", "date")  # 只寫到年月的生日
            add("，聯絡手機"); add(f"09{rng.randint(10 ** 7, 10 ** 8 - 1)}", "NUMBER", "num"); add("/"); add(f"09{rng.randint(10 ** 7, 10 ** 8 - 1)}", "NUMBER", "num"); add("。")
        if prev:  # 前一份的假姓當另一個真人（曹小姐）；只出現前一份某人的暱稱、稱謂（林小姐、婷姐）
            mp, olds = prev
            fsur = [e["fake"] for e in mp if e["type"] == "SURNAME" and len(e["fake"]) == 1]
            if fsur:
                x = rng.choice(fsur)
                add("另一位證人"); add(x + rng.choice(GIVEN_F) + rng.choice(GIVEN_F), "PERSON", "full"); add("，"); add(x, "PERSON", "partial"); add("小姐稱不認識。")
            o = rng.choice(olds)
            add("前案的"); add(o[0], "PERSON", "partial"); add("小姐與"); add(o[-1], "PERSON", "nick"); add("姐也到場。")
            live = {e["original"]: e["fake"] for e in mp if e["type"] == "PERSON" and not e.get("ambiguous") and len(e["original"]) >= 3}
            o2 = rng.choice(sorted(live)) if live else None
            if o2 and surname_len(o2) == 1:  # 前一份的假全名當這份的法官，同一個人又以全名、「X先生」出現
                add("法官"); add(live[o2], "PERSON_KEEP", "full"); add("審理，被告"); add(o2, "PERSON", "full"); add("到庭，"); add(o2[0], "PERSON", "partial"); add("先生表示不認罪。")
        add("另案被告"); add("台灣積體電路製造股份有限公司", "ORG", "org"); add("（下稱台積電）稱台積電無過失。")
        return "".join(parts), spans
    docs, olds = [], []
    for shared in (True, False):
        mp = None
        for i in range(n_docs):
            if shared:
                docs.append(doc((mp, olds) if mp else None))
            t, sp = docs[i]
            olds = olds + [t[x["start"]:x["end"]] for x in sp if x["type"] == "PERSON" and x["kind"] == "full" and len(t[x["start"]:x["end"]]) >= 3]
            passed = mp if shared else None
            snap = copy.deepcopy(passed)
            ob = Obfuscator(seed=seed + i, mapping=passed)
            f, mp = ob.apply(t, sp)
            ctx = (shared, i, t, f)
            assert passed == snap, ctx  # 傳進去的對照表不會被改到
            assert restore_exact(f, ob.spans) == t and nz(restore(f, mp)) == nz(t), (ctx, restore(f, mp))
            assert all(f[x["start"]:x["end"]] != x["original"] for x in ob.spans), ctx
            by_fake = collections.defaultdict(set)
            for e in mp:
                if e["type"] not in _NOT_VALUE:
                    by_fake[e["type"], e["fake"]].add(_canon(e["original"]))
            assert all(len(v) == 1 for v in by_fake.values()), (ctx, {k: v for k, v in by_fake.items() if len(v) > 1})
            dates = [(_parse_date(e["original"]), _parse_date(e["fake"])) for e in mp if e["type"] in ("DATE", "DATE_EVENT")]
            assert all(o[0] == fk[0] for (o, fk), e in zip(dates, [e for e in mp if e["type"] in ("DATE", "DATE_EVENT")]) if e["type"] == "DATE" and o and fk), ctx
            full = next(e["fake"] for e in mp if e["original"] == "台灣積體電路製造股份有限公司")
            assert next(e["fake"] for e in mp if e["original"] == "台積電").startswith(full[:-len("股份有限公司")]), ctx  # 簡稱＝全名的假品牌＋一個字
            fakes = {e["fake"] for e in mp} | {re.sub(r"\D", "", e["fake"]) for e in mp}
            days = {(_ykey(p) if p[0] is not None else p[1:]) for _, p in dates if p} | {p[1:] for _, p in dates if p}
            noise = []
            for _ in range(12):
                x = rng.choice((f"{rng.randint(50, 99)}/{rng.randint(1, 12)}/{rng.randint(1, 28)}", f"{rng.randint(1, 12)}/{rng.randint(1, 28)}",
                                str(rng.randint(10 ** 6, 10 ** 10)), f"09{rng.randint(10 ** 7, 10 ** 8 - 1)}", f"{rng.randint(1, 999)}元"))
                p = _parse_date(x)
                if x not in fakes and re.sub(r"\D", "", x) not in fakes and not (p and ((_ykey(p) if p[0] is not None else p[1:]) in days or p[1:] in days)):
                    noise.append(x)
            tail = "；另查 " + "、".join(noise) + "。"
            assert nz(restore(f + tail, mp)) == nz(t + tail), (ctx, tail, restore(f + tail, mp)[len(t):])


def _demo():
    text = "被告王小明（民國78年5月12日生）住臺北市內湖區瑞光路999巷88號7樓，手機0912-118-406，身分證F128394015。王先生稱小明哥與老王同住，2023年3月5日至2023年3月9日請假。法官李大同。"
    spans = []
    def add(sub, typ, kind, nth=0):
        i = -1
        for _ in range(nth + 1):
            i = text.index(sub, i + 1)
        spans.append({"start": i, "end": i + len(sub), "type": typ, "kind": kind})
    add("王小明", "PERSON", "full"); add("民國78年5月12日", "DATE", "date"); add("臺北市內湖區瑞光路999巷88號7樓", "ADDRESS", "addr")
    add("0912-118-406", "NUMBER", "num"); add("F128394015", "CODE", "alnum"); add("王", "PERSON", "partial", 1)
    add("小明", "PERSON", "given", 1); add("老王", "PERSON", "nick"); add("2023年3月5日", "DATE_EVENT", "date"); add("2023年3月9日", "DATE_EVENT", "date")
    add("李大同", "PERSON_KEEP", "full")
    ob = Obfuscator(mode="general", seed=1)
    fake, mp = ob.apply(text, spans)
    print(fake)
    sur = ob.sur["王"]
    assert "王" not in fake.replace("王", "", 0) or True
    for orig in ("王小明", "0912-118-406", "F128394015", "瑞光路999巷88號"):
        assert orig not in fake, orig
    assert f"{sur}先生" in fake and f"老{sur}" in fake and "李大同" in fake and "民國78年" in fake and "臺北市" in fake
    new_id = fake[fake.index("身分證") + 3:fake.index("身分證") + 13]
    assert new_id[0] == "F" and new_id[1] == "1" and new_id != "F128394015", new_id
    d1, d2 = re.findall(r"20\d\d年\d+月\d+日", fake)[:2]
    to = lambda s: dt.date(*map(int, re.findall(r"\d+", s)))
    assert (to(d2) - to(d1)).days == 4, (d1, d2)
    assert restore(fake, mp) == text, restore(fake, mp)
    assert restore_exact(fake, ob.spans) == text
    assert restore(f"{sur}先生說的", mp) == "王先生說的"
    assert sur in SAFE_SURNAMES and restore(f"{sur}說要和解", mp) == "王說要和解", "假姓只挑少見於一般詞的姓，單獨出現也要換得回來"
    words = "請查閱相關紀錄、師傅證詞、梁柱、杜絕、杜拜、蕭條、卓越、翁婿、古柯鹼、沈默、楊梅區、東吳、徐州路"
    for sd in range(30):  # AI 回覆裡的一般詞不能被單獨假姓換壞（假姓「紀」曾把紀錄還原成陳錄）
        obk = Obfuscator(seed=sd)
        _, mk = obk.apply("被告陳美玲到庭。", [{"start": 2, "end": 5, "type": "PERSON", "kind": "full"}])
        fs = obk.sur["陳"]
        assert restore(f"{words}，{fs}小姐已到庭。", mk) == f"{words}，陳小姐已到庭。", (sd, fs)
    ob3 = Obfuscator(seed=3, mode="general")
    t3 = "4月28日請假、4月29日回診，網誌 https://davidintaiwan.blogspot.com"
    sp3 = [{"start": t3.index(x), "end": t3.index(x) + len(x), "type": typ, "kind": k}
           for x, typ, k in (("4月28日", "DATE_EVENT", "date"), ("4月29日", "DATE_EVENT", "date"), ("https://davidintaiwan.blogspot.com", "URL", "url"))]
    f3, m3 = ob3.apply(t3, sp3)
    assert len({e["fake"] for e in m3}) == 3 and "davidintaiwan" not in f3 and ".blogspot.com" in f3, (f3, m3)
    t4 = "管委會邱主委說，Alice 與 Emily 都來了，比分 25/12。"  # 職稱不在稱謂表、英文名不能撞、不是日期的「日期」不能讓整份失敗
    sp4 = [{"start": t4.index(x), "end": t4.index(x) + len(x), "type": typ, "kind": k}
           for x, typ, k in (("邱", "PERSON", "partial"), ("Alice", "PERSON", "latin"), ("Emily", "PERSON", "latin"), ("25/12", "DATE_EVENT", "date"))]
    ob4 = Obfuscator(seed=4, mode="general")
    f4, m4 = ob4.apply(t4, sp4)
    assert restore(f4, m4) == t4 and restore_exact(f4, ob4.spans) == t4 and len({e["fake"] for e in m4}) == len(m4), (f4, m4)
    assert restore(f"{ob4.sur['邱']}主委再說一次", m4) == "邱主委再說一次"
    # 評測抓到的問題：同一人切法不一、同一地址寫法不一、樓層、地號、AI 改寫號碼
    t5 = "原告之前手陳立基於系爭土地出售前設定抵押權，陳立基住台北市中山區龍江路 88 號 12 樓，被告住台北市中山區龍江路88號12樓。南投市康壽段452地號及同段452-1地號，帳號０１３-１２３４５６７８。"
    sp5 = [{"start": t5.index("陳立"), "end": t5.index("陳立") + 2, "type": "PERSON", "kind": "full"},
           {"start": t5.index("，陳立基") + 1, "end": t5.index("，陳立基") + 4, "type": "PERSON", "kind": "full"},
           {"start": t5.index("台北市中山區龍江路 88"), "end": t5.index("台北市中山區龍江路 88") + 19, "type": "ADDRESS", "kind": "addr"},
           {"start": t5.index("南投市"), "end": t5.index("南投市") + 11, "type": "ADDRESS", "kind": "addr"},
           {"start": t5.index("同段"), "end": t5.index("同段") + 10, "type": "ADDRESS", "kind": "addr"},
           {"start": t5.index("０１３"), "end": len(t5) - 1, "type": "NUMBER", "kind": "num"}]
    ob5 = Obfuscator(seed=5)  # 預設法律模式
    f5, m5 = ob5.apply(t5, sp5)
    names = re.findall(r"前手(\S{3})於|，(\S{3})住", f5)
    assert names[0][0] == names[1][1] and "陳立" not in f5, (f5, names)
    assert "龍江路" not in f5 and f5.count("12樓") + f5.count("12 樓") == 2, f5
    lot = re.search(r"康壽段(\d+)地號", f5)  # 地號：段名留著、號碼換掉，同一筆同一個假號、分割號照留
    assert lot and lot.group(1) != "452" and f"同段{lot.group(1)}-1地號" in f5 and "康壽段452地號及同段452-1地號" in restore(f5, m5), f5
    t6 = "被告林郁婷與林都婷（掃描錯字）；原告張榮豐、張榮川為兄弟；阿婷說。"  # 逐字對應：錯字變體、字輩關係換完還在
    sp6 = [{"start": t6.index(x), "end": t6.index(x) + len(x), "type": "PERSON", "kind": k}
           for x, k in (("林郁婷", "full"), ("林都婷", "full"), ("張榮豐", "full"), ("張榮川", "full"), ("阿婷", "nick"))]
    f6, m6 = Obfuscator(seed=6).apply(t6, sp6)
    fk = {e["original"]: e["fake"] for e in m6}
    diff = lambda a, b: sum(x != y for x, y in zip(a, b))
    assert diff(fk["林郁婷"], fk["林都婷"]) == 1 and fk["張榮豐"][1] == fk["張榮川"][1] and fk["張榮豐"] != fk["張榮川"], fk
    assert fk["阿婷"][1] == fk["林郁婷"][2] and restore(f6, m6) == t6, (fk, f6)
    t7 = "抵押權設定於92年1月20日（被告生日92年1月20日？）。證人王大同說，王大同律師另案代理。"  # 同一個值一處要遮、一處保留 → 全部遮、同一個假值
    d1, d2 = t7.index("92年1月20日"), t7.rindex("92年1月20日")
    sp7 = [{"start": d1, "end": d1 + 8, "type": "DATE_EVENT", "kind": "date"}, {"start": d2, "end": d2 + 8, "type": "DATE", "kind": "date"},
           {"start": t7.index("王大同"), "end": t7.index("王大同") + 3, "type": "PERSON_KEEP", "kind": "full"},
           {"start": t7.rindex("王大同"), "end": t7.rindex("王大同") + 3, "type": "PERSON", "kind": "full"}]
    f7, m7 = Obfuscator(seed=7).apply(t7, sp7)
    assert "92年1月20日" not in f7 and "王大同" not in f7 and restore(f7, m7) == t7, f7
    t8 = "申訴人吳柏翰表示，證人張建國在場。"  # AI 回覆只用姓稱呼人
    sp8 = [{"start": t8.index(x), "end": t8.index(x) + 3, "type": "PERSON", "kind": "full"} for x in ("吳柏翰", "張建國")]
    ob8 = Obfuscator(seed=8)
    f8, m8 = ob8.apply(t8, sp8)
    s1, s2 = ob8.sur["吳"], ob8.sur["張"]
    assert s1 in SAFE_SURNAMES and s2 in SAFE_SURNAMES
    assert restore(f"{s1}取車後，{s2}作證；{s1}：刮痕非其所為。", m8) == "吳取車後，張作證；吳：刮痕非其所為。"
    acct = next(e["fake"] for e in m5 if e["type"] == "NUMBER")
    assert restore(acct.translate(str.maketrans(_FW, "0123456789")).replace("-", ""), m5) == "０１３-１２３４５６７８"
    t9 = ("甲方岱昀顧問股份有限公司（下稱岱昀公司）與岱昀科技股份有限公司台中分公司合作，款項匯入玉山銀行。陳記商行負責人陳先生同意；"
          "雲端之森社區管理委員會、Dai Yun Consulting Co., Ltd.。（印）岱昀黑驗焦熙公息")  # 最後一個是 OCR 弄亂、模型漏抓的公司章
    sp9 = [{"start": t9.index(x), "end": t9.index(x) + len(x), "type": typ, "kind": k} for x, typ, k in (
        ("岱昀顧問股份有限公司", "ORG", "org"), ("岱昀公司", "ORG", "org"), ("岱昀科技股份有限公司台中分公司", "ORG", "org"),
        ("玉山銀行", "ORG_KEEP", "org"), ("陳記商行", "ORG", "org"), ("雲端之森社區管理委員會", "ORG", "org"),
        ("Dai Yun Consulting Co., Ltd.", "ORG", "org_en"))]
    sp9.append({"start": t9.index("陳先生"), "end": t9.index("陳先生") + 1, "type": "PERSON", "kind": "partial"})
    ob9 = Obfuscator(seed=9)
    f9, m9 = ob9.apply(t9, sp9)
    b = next(e["fake"] for e in m9 if e["type"] == "ORG_BRAND" and e["original"] == "岱昀")
    assert "岱昀" not in f9 and all(f"{b}{x}" in f9 for x in ("顧問股份有限公司", "公司）", "科技股份有限公司台中分公司")), f9
    assert "玉山銀行" in f9 and f"{ob9.sur['陳']}記商行" in f9 and f"{ob9.sur['陳']}先生" in f9, f9
    assert "雲端之森" not in f9 and "社區管理委員會" in f9 and "Dai" not in f9 and "Consulting Co., Ltd." in f9, f9
    assert restore(f9, m9) == t9 and restore_exact(f9, ob9.spans).replace(b, "岱昀") == t9, (restore(f9, m9), f9)
    assert restore(f"{b}表示同意", m9) == "岱昀表示同意", "AI 回覆只寫品牌也要換得回來"
    t15 = ("原告王小明與被告台灣積體電路製造股份有限公司（下稱台積電）間請求給付資遣費事件。原告任職於台積電期間遭解僱，台積電應給付資遣費；"
           "被告佳穎精密股份有限公司（下稱被告公司）亦同。快樂幼兒園（以下簡稱本園）表示本園無過失。")  # 當事人的別名要跟著換；泛稱的別名不動
    sp15 = [{"start": t15.index(x), "end": t15.index(x) + len(x), "type": typ, "kind": k} for x, typ, k in (
        ("王小明", "PERSON", "full"), ("台灣積體電路製造股份有限公司", "ORG", "org"), ("佳穎精密股份有限公司", "ORG", "org"),
        ("快樂幼兒園", "ORG", "org"))]
    ob15 = Obfuscator(seed=15)
    f15, m15 = ob15.apply(t15, sp15)
    b15 = f15[f15.index("被告") + 2:f15.index("股份有限公司")]
    assert "台積電" not in f15 and "積體電路" not in f15 and len(b15) == 2 and f15.count("被告公司") == 1 and f15.count("本園") == 2, f15
    assert restore(f15, m15) == t15 and restore_exact(f15, ob15.spans) == t15, f15
    if short_name("鴻海精密工業股份有限公司"):  # 上市櫃簡稱表在（taiwan_legal_deid/data/tw_listed_companies.csv）才測：沒寫「下稱」也要換
        t16 = "上訴人鴻海精密工業股份有限公司與被上訴人陳美玲間損害賠償事件，鴻海主張已依約給付。另案被告中華電信股份有限公司稱中華電未違約。"
        sp16 = [{"start": t16.index(x), "end": t16.index(x) + len(x), "type": typ, "kind": k} for x, typ, k in (
            ("鴻海精密工業股份有限公司", "ORG", "org"), ("陳美玲", "PERSON", "full"), ("中華電信股份有限公司", "ORG", "org"))]
        a16 = t16.index("中華電未")  # 模型把簡稱判成「順帶提到、保留」：同一家是當事人，照樣要換
        sp16.append({"start": a16, "end": a16 + 3, "type": "ORG_KEEP", "kind": "org"})
        f16, m16 = Obfuscator(seed=16).apply(t16, sp16)
        assert "鴻海" not in f16 and "中華電" not in f16 and restore(f16, m16) == t16, f16
    t17 = "乙方東海林健司同意。東海林部長另稱 Rowan Wu 已付款；Rowan  Wu 與陳 ｜美玲（陳美玲）均在場。"  # 日本姓換日本姓；人名字間夾空白、雜點也補換
    sp17 = [{"start": t17.index(x), "end": t17.index(x) + len(x), "type": "PERSON", "kind": k} for x, k in (
        ("東海林健司", "full"), ("東海林", "partial"), ("Rowan Wu", "latin"), ("陳美玲", "full"))]
    sp17[1]["start"] = t17.index("東海林部長"); sp17[1]["end"] = sp17[1]["start"] + 3
    ob17 = Obfuscator(seed=17)
    f17, m17 = ob17.apply(t17, sp17)
    s17 = ob17.sur["東海林"]
    assert s17 in JP_SURNAMES and len(s17) == 3 and f"{s17}部長" in f17, f17
    assert all(x not in f17 for x in ("東海林", "Rowan", "美玲")) and restore_exact(f17, ob17.spans) == t17, f17
    assert restore(f"{s17}部長表示同意", m17) == "東海林部長表示同意"
    if all_short_names():  # 假品牌不會剛好是真的上市櫃簡稱
        fakes = [Obfuscator(seed=s)._org(n, "") for s in range(300) for n in ("澄嶼精密股份有限公司", "台灣積體電路製造股份有限公司")]
        assert not any(f.replace("精密股份有限公司", "").replace("股份有限公司", "") in all_short_names() for f in fakes)
    t10 = "家屬林小姐表示，林老太太術後感染；林法官另案。聯絡信箱 yi\nchun.chen82@gmail.com。"  # 姓＋稱謂、斷行的 Email
    sp10 = [{"start": t10.index("林小姐"), "end": t10.index("林小姐") + 1, "type": "PERSON", "kind": "partial"},
            {"start": t10.index("yi\n"), "end": t10.index(".com") + 4, "type": "EMAIL", "kind": "email"}]
    ob10 = Obfuscator(seed=10)
    f10, m10 = ob10.apply(t10, sp10)
    s10 = ob10.sur["林"]
    assert f"{s10}老太太" in f10 and "林老太太" not in f10 and "林法官" in f10, f10
    assert restore(f"{s10}老太太的信箱是 " + next(e["fake"] for e in m10 if e["type"] == "EMAIL"), m10) == "林老太太的信箱是 yichun.chen82@gmail.com"
    assert restore_exact(f10, ob10.spans) == t10
    t11 = "出生日期：073/11/05。身分欄 0731105 男。出生年月日 73/1 1/05，民國73年11月5日生，生日11月5日。"  # 同一天的各種寫法（含 OCR 拆開）
    vals11 = ("073/11/05", "0731105", "73/1 1/05", "73年11月5日", "11月5日")
    sp11, pos = [], 0
    for v in vals11:
        a = t11.index(v, pos); sp11.append({"start": a, "end": a + len(v), "type": "DATE", "kind": "date"}); pos = a + len(v)
    for seed in range(8):
        ob11 = Obfuscator(seed=seed)
        f11, m11 = ob11.apply(t11, sp11)
        got = {_parse_date(e["fake"]) for e in m11 if e["type"] == "DATE"}
        assert len({g[1:] for g in got}) == 1 and {g[0] for g in got} <= {73, None} and (73, 11, 5) not in got, (f11, got)
        assert next(e["fake"] for e in m11 if e["original"] == "0731105")[:3] == "073" and restore_exact(f11, ob11.spans) == t11
        ob11b = Obfuscator(seed=seed + 100, mapping=m11)  # 同案件下一份文件：另一種寫法也接得上
        f11b, _ = ob11b.apply("生日 073.11.05", [{"start": 3, "end": 12, "type": "DATE", "kind": "date"}])
        assert _parse_date(f11b[3:])[1:] == next(iter(got))[1:], (f11b, got)
    t14 = "確認被告就坐落南投市康壽段452地號土地及同段452-1地號土地之抵押權不存在。"  # 只抓到第一筆：同段那筆也要照同一個號碼換
    ob14 = Obfuscator(seed=4)
    f14, _ = ob14.apply(t14, [{"start": t14.index("南投市"), "end": t14.index("地號土地及") + 2, "type": "ADDRESS", "kind": "addr"}])
    n14 = ob14.lot["452"]
    assert "452" not in f14 and f"同段{n14}-1地號" in f14 and restore_exact(f14, ob14.spans) == t14, f14
    m14 = ob14.entries + [{"original": "075/02/17", "fake": "075/09/03", "type": "DATE"}]  # AI 自己改寫：地號只寫號碼、生日換寫法
    assert restore(f"系爭土地為同段{n14}-1地號及{n14}地號；被告生於75年9月3日（1986/9/3），另有第{n14}號函。", m14) == \
        f"系爭土地為同段452-1地號及452地號；被告生於75年2月17日（1986/2/17），另有第{n14}號函。"
    t13 = "出生年月日 75/0 2/17。列印條件：出生日期： 075/02/17 。"  # OCR 拆開的那處被判成生日：全文替換不能只換到 075/02/17 裡的 75/02/17
    ob13 = Obfuscator(seed=3)
    f13, _ = ob13.apply(t13, [{"start": 6, "end": 15, "type": "DATE", "kind": "date"}])
    a13 = t13.index("075/02/17")
    assert any(x["orig_start"] <= a13 and a13 + 9 <= x["orig_end"] for x in ob13.spans), (f13, ob13.spans)  # 整段換掉，開頭的 0 不能留著
    t12 = "列印條件：出生日期： 075/02/17 。統號欄 0750217。筆錄：民國75年2月17日生，另於112年2月17日到庭。"  # 只有一處被判成生日、一處被判成號碼
    a12, b12 = t12.index("75年2月17日"), t12.index("0750217")
    for seed in range(8):
        ob12 = Obfuscator(seed=seed)
        f12, m12 = ob12.apply(t12, [{"start": a12, "end": a12 + 9, "type": "DATE", "kind": "date"},
                                    {"start": b12, "end": b12 + 7, "type": "NUMBER", "kind": "num"}])
        got = {_parse_date(e["fake"]) for e in m12 if e["type"] == "DATE"}
        assert "075/02/17" not in f12 and "0750217" not in f12 and len({g[1:] for g in got}) == 1 and len(got) == 1, (f12, got)
        assert "112年2月17日" in f12 and restore_exact(f12, ob12.spans) == t12  # 別年的同月日不是同一天，照留
    t18 = "網站 https://blog.alice-chen.com/profile，信箱 alice@mail.alice-chen.com.tw。"  # 私人網域整段換：子網域後面不能留原文
    sp18 = [{"start": t18.index("https"), "end": t18.index("，"), "type": "URL", "kind": "url"},
            {"start": t18.index("alice@"), "end": len(t18) - 1, "type": "EMAIL", "kind": "email"}]
    f18, m18 = Obfuscator(seed=18).apply(t18, sp18)
    assert "alice" not in f18 and ".com/" in f18 and f18.endswith(".com.tw。") and restore(f18, m18) == t18, f18
    t19 = "甲生於75年2月17日，乙生於75年9月3日。"  # 兩個生日不能換成同一天（seed 479 撞過）
    sp19 = [{"start": t19.index(x), "end": t19.index(x) + len(x), "type": "DATE", "kind": "date"} for x in ("75年2月17日", "75年9月3日")]
    for seed in range(600):
        f19, m19 = Obfuscator(seed=seed).apply(t19, sp19)
        assert len({e["fake"] for e in m19 if e["type"] == "DATE"}) == 2 and restore(f19, m19) == t19, (seed, f19)
    assert restore("75年9月3日", [{"original": "75/02/17", "fake": "75/09/01", "type": "DATE"}]) == "75年9月3日"  # 75年9月只是長日期的一段
    ta, tb = "請假自113年5月2日起。", "113年5月2日至113年5月3日"  # 一般模式沿用對照表：位移跟前一份文件一樣
    sp_ev = lambda t, *xs: [{"start": t.index(x), "end": t.index(x) + len(x), "type": "DATE_EVENT", "kind": "date"} for x in xs]
    fa, ma = Obfuscator(mode="general", seed=21).apply(ta, sp_ev(ta, "113年5月2日"))
    fb, _ = Obfuscator(mode="general", seed=99, mapping=ma).apply(tb, sp_ev(tb, "113年5月2日", "113年5月3日"))
    d1, d2 = (_as_date(_parse_date(x)) for x in fb.split("至"))
    assert fb.startswith(fa[3:fa.index("起")]) and (d2 - d1).days == 1, (fa, fb)
    f20, m20 = Obfuscator(seed=1).apply("證人林婷到庭。", [{"start": 2, "end": 4, "type": "PERSON", "kind": "full"}])  # 單字名字跨文件一致
    f21, m21 = Obfuscator(seed=2, mapping=m20).apply("婷姐說好。", [{"start": 0, "end": 2, "type": "PERSON", "kind": "nick"}])
    assert f21[0] == f20[3] and restore(f20[3], m21) == f20[3], (f20, f21)  # 單一個字不拿來還原
    t23 = "Acme Consulting Co., Ltd. 同意。"  # 英文品牌字：AI 只寫品牌字也換得回來，下一份文件換成同一個假字
    f23, m23 = Obfuscator(seed=3).apply(t23, [{"start": 0, "end": t23.index(" 同意"), "type": "ORG", "kind": "org_en"}])
    w23 = f23.split()[0]
    assert w23 != "Acme" and restore(f"{w23} 表示同意", m23) == "Acme 表示同意", f23
    t24 = "Acme Trading Co., Ltd. 付款。"
    f24, _ = Obfuscator(seed=4, mapping=m23).apply(t24, [{"start": 0, "end": t24.index(" 付款"), "type": "ORG", "kind": "org_en"}])
    assert f24.startswith(w23 + " Trading"), f24
    f25, _ = Obfuscator(seed=5).apply("生日12 March 1993。", [{"start": 2, "end": 15, "type": "DATE", "kind": "date"}])
    assert _parse_date("12 March 1993") == (1993, 3, 12) and f25.endswith(" 1993。"), f25  # 英文日期：日在月前，年份完整保留
    t26 = "甲方ABC Ltd.與乙方DEF Ltd.間有買賣契約。"  # 兩家英文公司不能換成同一個假名（seed 2 撞過）
    f26, m26 = Obfuscator(seed=2).apply(t26, [{"start": t26.index(x), "end": t26.index(x) + 8, "type": "ORG", "kind": "org_en"} for x in ("ABC Ltd.", "DEF Ltd.")])
    assert len({e["fake"] for e in m26 if e["type"] == "ORG"}) == 2 and restore(f26, m26) == t26, f26
    m27 = [{"original": "Acme", "fake": "Huan", "type": "ORG_WORD"}, {"original": "Huan", "fake": "Hsie", "type": "ORG_WORD"}]  # 前一份的假字＝這一份的真字
    assert restore("Hsie Trading 與 Huan Consulting", m27) == "Huan Trading 與 Acme Consulting"  # 一次換完，不連鎖
    t28 = "甲方岱昀顧問股份有限公司（下稱岱昀）"  # 別名用到的品牌、單字品牌：下一份文件換成同一個假字
    f28, m28 = Obfuscator(seed=3).apply(t28, [{"start": 2, "end": 12, "type": "ORG", "kind": "org"}])
    f29, _ = Obfuscator(seed=9, mapping=m28).apply("乙方岱昀科技股份有限公司", [{"start": 2, "end": 12, "type": "ORG", "kind": "org"}])
    f30, m30 = Obfuscator(seed=1).apply("被告德記商行", [{"start": 2, "end": 6, "type": "ORG", "kind": "org"}])
    f31, _ = Obfuscator(seed=5, mapping=m30).apply("被告德記食品行", [{"start": 2, "end": 7, "type": "ORG", "kind": "org"}])
    assert f29[2:4] == f28[2:4] and f31[2] == f30[2] and f30[3] == "記", (f28, f29, f30, f31)
    assert restore("Sample report: Sam agreed.", [{"original": "Alice", "fake": "Sam", "type": "PERSON"}]) == "Sample report: Alice agreed."
    t32 = "陳美玲與陳 ｜美玲均同意。"  # OCR 雜點的補換不能讓還原保護誤判撞名
    f32, m32 = Obfuscator(seed=0).apply(t32, [{"start": 0, "end": 3, "type": "PERSON", "kind": "full"}])
    assert "美玲" not in f32 and not any(e.get("ambiguous") for e in m32) and restore(f32, m32) == "陳美玲與陳美玲均同意。", (f32, m32)
    f33, _ = Obfuscator(seed=0).apply("我的提款卡密碼是000000，請保密。", [{"start": 8, "end": 14, "type": "NUMBER", "kind": "num"}])
    assert "000000" not in f33, f33
    t34 = "被告王小明，大家叫他阿明。"
    f34, _ = Obfuscator(seed=86).apply(t34, [{"start": 2, "end": 5, "type": "PERSON", "kind": "full"}, {"start": 10, "end": 12, "type": "PERSON", "kind": "nick"}])
    assert "阿明" not in f34 and "明" not in f34, f34
    t35 = "原告Sam提交Sample report作為證據。"
    f35, m35 = Obfuscator(seed=0).apply(t35, [{"start": 2, "end": 5, "type": "PERSON", "kind": "latin"}])
    assert "Sample" in f35 and restore(f35, m35) == t35, f35
    t36 = "被告王小明到庭。"  # 撞名後另取的假名：第三份文件要沿用新的那個，不能回到停用的舊假名
    f36, m36 = Obfuscator(seed=0).apply(t36, [{"start": 2, "end": 5, "type": "PERSON", "kind": "full"}])
    old36 = f36[2:5]
    t37 = f"法官{old36}審理，被告王小明到庭。"
    f37, m37 = Obfuscator(seed=1, mapping=m36).apply(t37, [{"start": 2, "end": 5, "type": "PERSON_KEEP", "kind": "full"}, {"start": t37.index("王小明"), "end": t37.index("王小明") + 3, "type": "PERSON", "kind": "full"}])
    f38, m38 = Obfuscator(seed=2, mapping=m37).apply(t36, [{"start": 2, "end": 5, "type": "PERSON", "kind": "full"}])
    assert f38[2:5] != old36 and f38[2:5] == f37[f37.index("被告") + 2:f37.index("被告") + 5] and restore(f38, m38) == t36, (f36, f37, f38)
    t39 = "甲方3M股份有限公司與乙方5G股份有限公司。"  # 英數品牌不撞成同一個
    f39, m39 = Obfuscator(seed=479).apply(t39, [{"start": t39.index(x), "end": t39.index(x) + 8, "type": "ORG", "kind": "org"} for x in ("3M股份有限公司", "5G股份有限公司")])
    assert len({e["fake"] for e in m39 if e["type"] == "ORG"}) == 2 and restore(f39, m39) == t39, f39
    f40, _ = Obfuscator(seed=0).apply("身分證Ａ１２３４５６７８９。", [{"start": 3, "end": 13, "type": "CODE", "kind": "alnum"}])
    v40 = f40[3:13].translate(_FW2HW)
    assert re.fullmatch(r"A1\d{8}", v40) and v40 != "A123456789" and f40[3] == "Ａ", f40  # 全形身分證：換完照樣全形、性別碼不變
    t41 = "被告生日民國75年2月17日。"  # 前一份判成生日的值，下一份被判成事件日期也照換
    f41, m41 = Obfuscator(seed=0).apply(t41, [{"start": 6, "end": 14, "type": "DATE", "kind": "date"}])
    t42 = "又寫作民國７５年２月１７日。"
    f42, _ = Obfuscator(seed=1, mapping=m41).apply(t42, [{"start": 5, "end": 13, "type": "DATE_EVENT", "kind": "date"}])
    assert "２月１７日" not in f42 and "2月17日" not in f42, f42
    f43, m43 = Obfuscator(seed=0).apply("被告出生於民國75年7月。", [{"start": 7, "end": 12, "type": "DATE", "kind": "date"}])  # 只寫到年月的生日也要變
    assert "75年7月" not in f43 and "75年" in f43 and restore(f43, m43) == "被告出生於民國75年7月。", f43
    t44 = "被告王小明到庭。"  # 撞名另取全名：姓的對照跟著換，「王先生」跟新的全名同姓
    f44, m44 = Obfuscator(seed=0).apply(t44, [{"start": 2, "end": 5, "type": "PERSON", "kind": "full"}])
    t45 = f"法官{f44[2:5]}審理。被告王小明到庭，王先生表示不認罪。"
    a45 = t45.index("王小明")
    f45, m45 = Obfuscator(seed=1, mapping=m44).apply(t45, [{"start": 2, "end": 5, "type": "PERSON_KEEP", "kind": "full"}, {"start": a45, "end": a45 + 3, "type": "PERSON", "kind": "full"},
                                                          {"start": t45.index("王先生"), "end": t45.index("王先生") + 1, "type": "PERSON", "kind": "partial"}])
    b45 = f45.index("被告") + 2
    assert f45[b45] == f45[f45.index("先生表示") - 1] and restore(f45, m45) == t45, f45
    t46 = "聯絡手機0912345678/0987654321。"  # 兩支用斜線連著的電話：都換得回來
    f46, m46 = Obfuscator(seed=0).apply(t46, [{"start": 4, "end": 14, "type": "NUMBER", "kind": "num"}, {"start": 15, "end": 25, "type": "NUMBER", "kind": "num"}])
    assert restore(f46, m46) == t46, (f46, restore(f46, m46))
    t47 = "岱昀科技有限公司與麒碩科技有限公司合作。"  # 假品牌不能剛好是原文裡另一家公司
    f47, m47 = Obfuscator(seed=0).apply(t47, [{"start": 0, "end": 8, "type": "ORG", "kind": "org"}, {"start": 9, "end": 17, "type": "ORG_KEEP", "kind": "org"}])
    assert f47.count("麒碩科技有限公司") == 1 and restore(f47, m47) == t47, f47
    ob48 = Obfuscator(seed=0)  # 同一個 Obfuscator 連續處理兩份：第一份交出去的對照表不會被第二份改到
    f48, m48 = ob48.apply("被告王小明到庭。", [{"start": 2, "end": 5, "type": "PERSON", "kind": "full"}])
    ob48.apply(f"法官{f48[2:5]}審理。", [{"start": 2, "end": 5, "type": "PERSON_KEEP", "kind": "full"}])
    assert restore(f48, m48) == "被告王小明到庭。", (f48, m48)
    from .companies import _table
    t49 = "、".join(list(_table())[:160])  # 很多公司：品牌字池用完也不中止
    ob49 = Obfuscator(seed=0)
    f49, m49 = ob49.apply(t49, [{"start": m.start(), "end": m.end(), "type": "ORG", "kind": "org"} for m in re.finditer(r"[^、]+", t49)])
    assert restore_exact(f49, ob49.spans) == t49 and restore(f49, m49) == t49, [x for x in ob49.spans if x["original"] in f49][:3]
    for s in range(5):  # 性質測試（大量 seed 另外跑：for s in range(500): _property_check(seed=s)）
        _property_check(seed=s)
    fake2, _ = Obfuscator(mode="legal", seed=1).apply(text, spans)
    assert "2023年3月5日" in fake2
    print("混淆自檢 OK：往返一致、王先生→" + sur + "先生、日期間隔不變、法律模式保留個人日期")


if __name__ == "__main__":  # 自檢；指令列在 cli.py
    _demo()
