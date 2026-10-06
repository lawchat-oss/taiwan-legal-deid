"""機構名稱候選：公司、商號、團體、學校、醫院、社區、建案、管委會…。程式只負責多抓，要換／保留／不是交給模型。
- 結尾詞（股份有限公司、商行、基金會、管理委員會、社區、醫院、局…）往左 1～12 字都列為起點；後面可再接分公司、分行、門市。
- 英文公司字尾（Co., Ltd.、Inc.、Corp.…）往左 1～6 個字。
- 引號裡的名稱（「雲端之森」社區、下稱「岱昀公司」）。
- 字根：同一份文件已出現的品牌（岱昀顧問股份有限公司 → 岱昀、岱昀顧問）在別處再出現（簡稱、OCR 弄亂的公司章），
  字根本身與往右接到機構字結尾的每一種長度都列。所以要整份文件一次算，再分給各視窗。
只出現在公家機關的結尾（部、署、法院、地檢署）不列：沒有候選＝不會被遮。
"""
from __future__ import annotations

import functools, os, re

from .pii_candidates import CITIES, _normalize, _places

_H = "一-鿿㐀-䶿"
_NAME = rf"[{_H}A-Za-zÀ-ÿ0-9&＆．·\-]"  # 機構名稱可以有的字（台灣3M、ABC國際）
SUFFIXES = sorted(set("""
股份有限公司 有限公司 無限公司 兩合公司 公司 股份有限公 有限公 企業社 企業行 實業社 商行 商號 行號 工作室 事務所 小吃店 小吃部 餐廳 餐館 咖啡館 咖啡廳
商店 門市 超市 藥局 藥房 書局 旅行社 民宿 飯店 酒店 旅館 車行 機車行 當舖 銀樓 店 舖 鋪 坊 館
醫院 診所 醫學中心 護理之家 長照中心 安養中心 托嬰中心 幼兒園 幼稚園 補習班 安親班 才藝班 國小 國中 高中 高職 大學 學院 學校 中學 小學
協會 學會 基金會 公會 工會 合作社 農會 漁會 宗親會 同鄉會 聯誼會 促進會 俱樂部 教會 宮 廟 寺
社區 大樓 大廈 華廈 山莊 別墅 花園 新城 建案 管理委員會 管委會
銀行 信用合作社 證券 投信 投顧 人壽 產險 產物保險 保險 委員會 中心 局 研究所 研究院
美語 英語 外語 教室 汽車 機車 車業 車廠 保養廠 修車廠 工廠 廠 建設 營造 科技 電子 電腦 資訊 生技 食品 餐飲 企業 實業 興業 開發 地產 不動產
物業 保全 貿易 物流 機械 精密 光電 工業 化工 紡織 牙醫 中醫 眼科 骨科 小兒科 婦產科 皮膚科 美容 美甲 髮廊 沙龍 會館 健身房
水電行 工程行 設備行 食品行 水產行 貨運行 材料行 五金行 電器行 布行 米行 茶行 鐵工行 汽車行 實業行 印刷行 冷氣行 家具行 建材行 中藥行
服飾行 鐘錶行 眼鏡行 珠寶行 輪胎行 機械行 水族行 雜貨行 冷凍行 機電行 玻璃行 鋁窗行 木材行 油漆行 瓦斯行 招牌行
服務社 出版社 報社 徵信社 攝影社 貨運社 旅遊社 堂 彩印 印刷 印刷廠 便當 小吃 餐盒 作文 珠心算 書法 圍棋 鋼琴
翻譯社 株式會社 株式会社 會社 農場 牧場 停車場 種苗場 市集 手作 木作 咖啡 校車 自治會 自救會 互助會 更新會 讀書會 後援會
肉圓 碳烤 燒烤 豆花 滷味 雞排 鹹酥雞 牛肉麵 麵線 臭豆腐 早午餐 手搖 茶飲 冰品 烘焙 甜點 鍋物 火鍋 拉麵 壽司 快炒 熱炒 海產 羊肉爐 薑母鴨
科大 高工 高商 附中 文理
""".split()), key=len, reverse=True)
# 開放的「X行／X社」商號（農產行、批發行、單車社）：單字結尾，前一字是動詞或常見複合詞的不算（執行、進行、旅行、社會的社不在結尾）
_HANG_SKIP = set("執進履發施運舉流旅平並單同可實先通排強飛航步修言品德罪暴惡遊例自另逕再擅試推盛風橫隨前後上下外內本該此他銀遂偕徒夜慢快直逆順代暫續盡奉踐篤報結合公會總旅")
SUF_OPEN = re.compile(rf"(?<=[{_H}])(?<![{''.join(sorted(_HANG_SKIP))}])[行社](?![{_H}])|(?<=[{_H}])(?<![{''.join(sorted(_HANG_SKIP))}])[行社](?=[負老闆的之與及、])")
SUF = re.compile(rf"(?:{'|'.join(SUFFIXES)})(?!法)")  # 公司法、銀行法、保險法是法規名
BRANCH = re.compile(rf"(?:[-－]\s?)?[{_H}]{{1,4}}(?:分公司|分行|分店|門市|營業所|營業處|分院|分校|分會|辦事處|服務處|工廠|廠)")  # 玉山銀行-台中分行
# 常見連鎖、國營事業、大品牌（沒有公司字尾，不一定上市）：當雇主、當事人要換，順帶提到要留——交給模型，這裡只負責有候選
BRANDS = tuple("""7-ELEVEN 7-11 統一超商 全家便利商店 萊爾富 OK超商 全聯 全聯福利中心 家樂福 好市多 COSTCO 大潤發 愛買 美廉社 誠品 誠品書店 金石堂
鼎泰豐 王品 王品牛排 瓦城 欣葉 星巴克 路易莎 85度C 麥當勞 肯德基 摩斯漢堡 頂呱呱 八方雲集 50嵐 清心福全 迷客夏 屈臣氏 康是美 寶雅 大樹藥局 燦坤
全國電子 順發3C 台電 臺電 台灣電力公司 臺灣電力公司 中油 台灣中油 台糖 台灣糖業 台水 台灣自來水公司 自來水公司 高鐵 台灣高鐵 台鐵 臺鐵 中華郵政 中華電信
台灣大哥大 遠傳 遠傳電信 亞太電信 台灣之星 長榮航空 華航 中華航空 星宇航空 Uber foodpanda 蝦皮 蝦皮購物 momo PChome 露天拍賣 宏碁 Acer 華碩 ASUS
廣達 仁寶 和碩 緯創 英業達 聯發科 日月光 友達 群創 光陽 三陽 裕隆 和泰 新光三越 遠東百貨 太平洋SOGO SOGO 京站 IKEA 宜家 無印良品 UNIQLO 特力屋
小北百貨 寶島眼鏡""".split())
_BRAND_RX = re.compile("|".join((rf"(?<![A-Za-z0-9]){re.escape(b)}(?![A-Za-z])" if b.isascii() else re.escape(b)) for b in sorted(BRANDS, key=len, reverse=True)))
EN_SUF = re.compile(r"[,，]?\s+(?:Co\.?[,，]?\s*L[tf]?d\.?|Co\.|L[tf]?d\.?|Limited|Inc\.?|Incorporated|Corp\.?|Corporation|LLC|L\.L\.C\.|LLP|PLC|GmbH|AG|S\.A\.|B\.V\.|"
                    r"Pte\.?\s*Ltd\.?|K\.K\.|Company|SPA|Spa|Salon|Studio|Cafe|Café|Bistro|Bakery|Clinic|Hotel|Motel|Inn|Shop|Store|Boutique|Restaurant|"
                    r"Kitchen|Bar|Pub|Gym|Fitness|AS|ASA|AB|Oy|SA|SpA|S\.p\.A\.|Srl|S\.r\.l\.|NV|N\.V\.|BV|KK|Pty\.?\s*Ltd\.?|Sdn\.?\s*Bhd\.?|Bhd|JSC|SAS|SARL|Holdings|Group)(?![A-Za-zÀ-ÿ])")  # OCR：全形逗號、Ltd 認成 Ld／Lfd；店名常只有英文（LULU SPA）
EN_BRANCH = re.compile(r"\s+(?:[A-Z][a-z]+\s+){1,2}(?:Office|Branch|Plant|Factory|Division|Subsidiary)(?![A-Za-z])")  # Inc. Taiwan Branch
QUOTE = re.compile(rf"[「『“\"]({_NAME}{{2,12}})[」』”\"]")
_EN_W = r"(?:[A-ZÀ-Þ][A-Za-zÀ-ÿ'\-]{2,}|[A-Z]{2,}[0-9]*)"
EN_RUN = re.compile(rf"(?<![A-Za-zÀ-ÿ0-9@./_])(?:{_EN_W})(?:\s(?:{_EN_W}|&))*(?![A-Za-zÀ-ÿ0-9@._/])")  # 不含 Email、網址裡的字
_FUNC = set("之的與及或於被係即並將把從讓給跟就而且但若因所其該")  # 名稱幾乎不會從這些字開始（和泰、同欣、經濟部、為恭、向日葵的開頭字不列）
_GENERIC = {"本", "貴", "該", "其", "此", "各", "每", "某", "他", "她", "我", "你", "敝", "前開", "上開", "系爭", "同一", "這家", "那家",
            "這間", "那間", "被告", "原告", "對方", "甲", "乙", "丙", "丁", "本件", "訴外", "貴管", "本管"}
_STEM_SKIP = {"台灣", "臺灣", "中華", "中國", "國際", "全球", "亞洲", "東方", "世界", "大眾", "實業", "企業", "科技", "開發", "建設", "顧問",
              "工程", "貿易", "投資", "管理", "服務", "股份", "有限", "國立", "私立", "市立", "縣立", "財團", "社團", "醫療", "法人"}
_ORGISH_END = set("司行社店館會院所室坊舖鋪園樓廈莊局心班校宮廟寺業")
_ROLES = ("被告", "原告", "上訴人", "抗告人", "相對人", "聲請人", "申請人", "債權人", "債務人", "出租人", "承租人", "出賣人", "買受人",
          "委任人", "受任人", "甲方", "乙方", "丙方", "立約人", "訴外人", "下稱", "簡稱", "受文者", "副本", "正本", "致")


def _after_boundary(text: str, i: int) -> bool:
    """i 前面是開頭、標點、空白、虛詞或角色詞（品牌的起點；名稱中間切出來的字根不會在這種位置出現）。"""
    return i == 0 or not re.fullmatch(_NAME, text[i - 1]) or text[i - 1] in _FUNC or text[:i].endswith(_ROLES)


@functools.lru_cache(None)
def _common(min_freq: int = 300) -> set[str]:
    """jieba 詞典（MIT）裡的詞（頻次 ≥ min_freq）：常用詞當字根會在全文到處冒出來（統一、國際、世界），不拿來當字根。"""
    p = os.path.join(os.path.dirname(__file__), "data", "jieba_dict_big.txt")
    out = set()
    if os.path.exists(p):
        with open(p, encoding="utf-8") as fh:
            for line in fh:
                w, f = (line.split() + ["", ""])[:2]
                if 2 <= len(w) <= 4 and int(f or 0) >= min_freq:
                    out.add(w)
    return out


def _starts(text: str, p: int, maxk: int = 12) -> list[int]:
    """名稱主體從 p 往左的每個起點：中文最多 maxk 字（英文字母不算，整段最多 40 字元；英文只從字首開始）；
    遇到標點就停；英文字後面的空白接著往左（Kiddo Land 美語、Tidewell Apps股份有限公司）；不從虛詞開始；泛稱不算。"""
    out, cjk, s = [], 0, p
    while True:
        s -= 1
        if s < 0 or p - s > 40:
            break
        c = text[s]
        if c == " " and s > 0 and text[s - 1].isascii() and text[s - 1].isalnum():
            continue
        if not re.fullmatch(_NAME, c):
            break
        if not c.isascii():
            cjk += 1
            if cjk > maxk:
                break
        if c in _FUNC or text[s:p] in _GENERIC or (c.isascii() and c.isalnum() and s > 0 and text[s - 1].isascii() and text[s - 1].isalnum()):
            continue
        out.append(s)
    return out


@functools.lru_cache(None)
def _listed_shorts():
    """上市櫃公司簡稱（taiwan_legal_deid.companies）；常用詞、地名、產業詞不列（統一、大同、中華）。"""
    from .companies import all_short_names
    _, dists, cities = _places()
    skip = _common(300) | _STEM_SKIP | CITIES | set(dists) | set(cities) | {d[:-1] for d in dists if len(d) >= 3} | {c[:2] for c in cities}  # 信義、南港
    s = {v for v in all_short_names() if len(v) >= 2 and v not in skip}
    return s, {v[0] for v in s}, max(map(len, s), default=0)


def _raw(text: str) -> set[tuple[int, int, str]]:
    out: set[tuple[int, int, str]] = set()
    bodies = set()  # 名稱主體（結尾詞前面那段），拿來找字根
    for m in list(SUF.finditer(text)) + list(SUF_OPEN.finditer(text)):
        p, e = m.span()
        ends = [e] + [b.end() for b in [BRANCH.match(text, e)] if b]
        for s in _starts(text, p):
            for en in ends:
                out.add((s, en, "org"))
            bodies.add(text[s:p])
    for m in EN_SUF.finditer(text):
        words = list(re.finditer(r"[A-Z0-9À-Þ][A-Za-zÀ-ÿ0-9&.\-']*", text[max(0, m.start() - 80):m.start()]))
        base = max(0, m.start() - 80)
        prev_end = m.start()
        b = EN_BRANCH.match(text, m.end())
        ends = [m.end()] + ([b.end()] if b else [])
        for w in reversed(words[-6:]):  # 往左最多 6 個字，中間只能是空白
            if text[base + w.end():prev_end].strip() not in ("", ","):
                break
            mark = re.match(r"[A-Z0-9]{1,3}[.)](?=[A-Za-z])", w.group(0))  # 清單編號黏在名稱前（B.Evergreen）：另列去掉編號的起點
            for st in [base + w.start()] + ([base + w.start() + mark.end()] if mark else []):
                for en in ends:
                    out.add((st, en, "org_en"))
            prev_end = base + w.start()
    for m in QUOTE.finditer(text):
        out.add((m.start(1), m.end(1), "org_q"))
    for m in EN_RUN.finditer(text):  # 連續的大寫開頭英文字（Halvorsen、Orion Fitness、BRIGHT LIFT）：沒有公司字尾的英文名稱
        ws = list(re.finditer(r"\S+", m.group(0)))
        for a in range(len(ws)):
            for b in range(a, min(len(ws), a + 3)):
                if ws[a].group(0) != "&" and ws[b].group(0) != "&":
                    out.add((m.start() + ws[a].start(), m.start() + ws[b].end(), "org_en"))
    shorts, firsts, maxl = _listed_shorts()  # 上市櫃公司簡稱：只寫「被告台積電」「在鴻海上班」也要有候選
    for i, c in enumerate(text):
        if c in firsts:
            out.update((i, i + k, "org") for k in range(2, min(maxl, len(text) - i) + 1) if text[i:i + k] in shorts)  # 結尾切出來的短字串不能算
    for m in _BRAND_RX.finditer(text):  # 連鎖、國營、大品牌（我在 7-11 上班、被告台電），後面可以接門市、營業處
        out.add((m.start(), m.end(), "org"))
        b = BRANCH.match(text, m.end())
        if b:
            out.add((m.start(), b.end(), "org"))
    for m in re.finditer("郵局", text):  # 大里郵局（任職的那間）
        out.update((m.start() - k, m.end(), "org") for k in range(1, 5) if m.start() - k >= 0 and re.fullmatch(f"[{_H}]{{{k}}}", text[m.start() - k:m.start()]))
    # 字根：主體本身與前 2～4 字（品牌通常在最前面）；常用詞、地名、產業詞不當字根
    _, dists, cities = _places()
    stems = set()
    for b in bodies:
        if not re.fullmatch(f"[{_H}]{{2,}}", b):
            continue
        for k in range(2, min(4, len(b)) + 1):
            st = b[:k]
            if st not in _common(5000) and st not in _STEM_SKIP and st not in CITIES and st not in dists and st not in cities and not set(st) & _FUNC \
                    and text.count(st) >= 2 and any(_after_boundary(text, m.start()) for m in re.finditer(re.escape(st), text)):
                stems.add(st)  # 品牌會重複出現、而且至少一次出現在邊界後；名稱中間切出來的（盛顧、問服）不會
    n = 0
    for st in sorted(stems, key=lambda x: (-len(x), x)):  # 同長度再依字排：碰到上限時每次跑都處理同一批（集合順序會隨執行變）
        for m in re.finditer(re.escape(st), text):
            i = m.start()
            out.add((i, m.end(), "org_stem"))
            j = m.end()
            for j in range(m.end() + 1, min(len(text), m.end() + 10) + 1):
                if not re.fullmatch(_NAME, text[j - 1]):
                    j -= 1
                    break
                if text[j - 1] in _ORGISH_END:
                    out.add((i, j, "org_stem"))
            if j > m.end():  # 一路接到標點前（OCR 弄亂的公司章：岱昀黑驗焦熙公息）
                out.add((i, j, "org_stem"))
            n += 1
            if n > 300:  # ponytail: 每份文件字根出現上限，避免病態文件爆量；真的不夠再調
                return out
    return out


def org_candidates(text: str) -> list[tuple[int, int, str]]:
    """原文找一次；OCR 容錯版（去掉中文字之間的空白與換行）再找一次、位置對回原文。"""
    out = _raw(text)
    norm, idx = _normalize(text)
    if norm != text:
        out |= {(idx[s], idx[e - 1] + 1, k) for s, e, k in _raw(norm)}
    return sorted(out)


if __name__ == "__main__":
    t = ("甲方：岱昀顧問股份有限公司（下稱岱昀公司），乙方：鈞衛保全股份有限公司台中分公司。款項匯入玉山銀行敦南分行。"
         "依公司法第23條，本公司負責人應忠實執行業務。翠湖苑社區管理委員會、「雲端之森」社區、Dai Yun Consulting Co., Ltd.、"
         "小美的韓貨舖、財團法人光語文教基金會。岱昀願絡份真限公司（印）岱昀表示同意，副本：臺北市政府社會局。"
         "鼎岳建設股份有\n限公司")
    got = {(t[s:e], k) for s, e, k in org_candidates(t)}
    names = {x for x, _ in got}
    for want in ["岱昀顧問股份有限公司", "岱昀公司", "鈞衛保全股份有限公司台中分公司", "鈞衛保全股份有限公司", "玉山銀行敦南分行", "玉山銀行",
                 "翠湖苑社區管理委員會", "雲端之森", "Dai Yun Consulting Co., Ltd.", "小美的韓貨舖", "財團法人光語文教基金會",
                 "岱昀願絡份真限公司", "岱昀", "臺北市政府社會局", "鼎岳建設股份有\n限公司"]:
        assert want in names, want
    assert not any(x.endswith("公司法") or x in ("本公司", "公司") for x in names), [x for x in names if "公司法" in x or x in ("本公司", "公司")]
    if _listed_shorts()[0]:  # 上市櫃簡稱表在（taiwan_legal_deid/data/tw_listed_companies.csv）才測
        t2 = "被告台積電應給付工資，我在鴻海上班，任職於中華電期間；統一發票另附。"
        n2 = {t2[s:e] for s, e, _ in org_candidates(t2)}
        assert {"台積電", "鴻海", "中華電"} <= n2 and "統一" not in n2, n2
        t4 = "我在7-11上班；聲請人任職於大里郵局；7-ELEVEN文心門市；台灣電力公司嘉義區營業處；被告台電。"
        n4 = {t4[s:e] for s, e, _ in org_candidates(t4)}
        assert {"7-11", "大里郵局", "7-ELEVEN文心門市", "台灣電力公司嘉義區營業處", "台電"} <= n4, n4
        t3 = "我在鴻海"  # 簡稱剛好在結尾：候選不能超出文字
        assert all(e <= len(t3) for _, e, _ in org_candidates(t3)) and (2, 4, "org") in org_candidates(t3)
    print(f"機構候選自檢 OK：{len(got)} 個候選，{len(t)} 字")
