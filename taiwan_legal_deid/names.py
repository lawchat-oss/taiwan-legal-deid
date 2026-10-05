"""假名產生：依台灣姓氏頻率與常見名字用字隨機產生「看起來像真的」姓名。
訓練資料把真名換成假名（模型從頭到尾不看真名），之後的擬真混淆也用這裡。
訓練資料另外用 wild：一部分名字換成罕見姓、或像一般詞的名字（登位、高峰、文化），讓模型靠上下文判斷，不靠「名字用字像不像名字」。
擬真混淆不用 wild（假名要讀起來自然）。
"""
from __future__ import annotations

import csv, functools, os, random

_D = os.path.join(os.path.dirname(__file__), "..", "data")

# 台灣常見姓氏，約依人口多寡排序（內政部姓名統計的前段）；權重用 Zipf 近似
SURNAME_ORDER = ("陳林黃張李王吳劉蔡楊許鄭謝郭洪曾邱廖賴周徐蘇葉莊呂江何蕭羅高潘簡朱鍾游彭詹胡施沈余趙盧梁顏柯翁魏孫戴范宋方"
                 "鄧杜傅侯曹薛丁卓阮馬董温唐藍石蔣古紀姚連馮歐程湯黃田康姜白汪鄒尤巫鐘黎涂龔嚴韓袁金童陸夏柳凃邵錢伍倪溫于譚駱熊任甘秦"
                 "顧毛章史官萬俞雷粘饒張")
COMPOUND_NAMES = ("張簡", "歐陽", "范姜", "司馬", "諸葛", "上官", "司徒", "夏侯", "皇甫", "端木")
GIVEN_M = "志明俊傑建宏文華家豪冠宇承翰柏霖彥廷凱偉哲銘昌榮德正信仁義威軒恩睿晨昱翔崇裕鴻峰毅儒聖賢良平和中英鈞宗祥維育成孟耀達龍勇強輝順興隆福泰豐國忠嘉威"
GIVEN_F = "涵怡君婷雅淑芬美玲佳慧惠欣宜庭筱嘉瑜琪萱晴安心品妤伶瑩蓉鈺婕詩思郁毓容雯靜玉春月秀麗珍敏芳如穎蓁瑄馨綺薇琳潔彤婉茹貞"
_SUR = [c for c in dict.fromkeys(SURNAME_ORDER)]
_W = [1 / (k + 4) for k in range(len(_SUR))]
TRAIN_WILD = 0.2  # 訓練資料的假名：罕見姓、像一般詞的名字各約一成


@functools.lru_cache(None)
def _rare():
    """罕見姓：姓氏表裡不在 SURNAME_ORDER 的單字姓；權重＝人數^0.3（前段不獨占，只有幾十人的姓也抽得到）。"""
    from .surnames import SURNAMES
    pop = {}
    for r in csv.DictReader(open(f"{_D}/open/moi_surnames_112.csv", encoding="utf-8-sig")):
        pop[r["lastname"]] = pop.get(r["lastname"], 0) + int(r["人口數"])
    xs = sorted(s for s in SURNAMES if s not in _SUR)
    return xs, [max(pop.get(s, 1), 1) ** 0.3 for s in xs]


@functools.lru_cache(None)
def _word_given():
    """像一般詞的名字：data/open/word_names.txt（python -m taiwan_legal_deid.names build 重建）。"""
    return [w.strip() for w in open(f"{_D}/open/word_names.txt", encoding="utf-8") if w.strip()]


def sample_name(rng: random.Random, length: int | None = None, compound: bool | None = None, avoid: set[str] | None = None,
                wild: float = 0.0) -> str:
    """length：全名字數（含姓）；compound：要不要複姓。avoid：不能和這些字串相同（例如原文裡已出現的名字）。
    wild：各有 wild/2 的機率換成罕見姓、兩字名換成一般詞（只給訓練資料用；0＝跟原本逐字相同的抽法）。"""
    for _ in range(50):
        comp = (rng.random() < 0.01) if compound is None else compound
        sur = rng.choice(COMPOUND_NAMES) if comp else rng.choices(_SUR, _W)[0]
        if wild and not comp and rng.random() < wild / 2:
            sur = rng.choices(*_rare())[0]
        L = length or (len(sur) + (1 if rng.random() < 0.05 else 2))
        if L == 4 and len(sur) == 1:  # 四字名、不是複姓＝冠夫姓（林徐阿嬌）：兩個常見姓＋兩字名
            sur = sur + rng.choices(_SUR, _W)[0]
        g = max(1, L - len(sur))
        pool = GIVEN_M if rng.random() < 0.5 else GIVEN_F
        if wild and g == 2 and rng.random() < wild / 2:
            name = sur + rng.choice(_word_given())
        else:
            name = sur + "".join(rng.choice(pool) for _ in range(g))
        if not avoid or name not in avoid:
            return name
    return name


def build_word_pool(min_freq=100):
    """jieba 詞典（MIT）的兩字詞（名詞、動詞、形容詞、地名、人名…，詞頻 ≥ min_freq）→ 只留每個字都常見於繁體判決語料的
    （詞典簡繁混雜）→ data/open/word_names.txt。拿掉會跟正常寫法打架的詞：稱謂與角色（王表弟、陳先生是姓＋稱謂）、
    判決裡常緊接在人名後面的詞（王表示、林前往：姓或名字後面接動詞）；也拿掉開發考題裡出現過的名字，免得評測灌水。"""
    import collections, json
    from .candidates import GIVEN_AFTER, SURNAME_AFTER, TITLES
    from .data_judgments import COUNSEL_ROLES, OFFICIAL_ROLES, PRIVATE_ROLES
    cf, after = collections.Counter(), collections.Counter()
    for line in open(f"{_D}/train/judg_docs.jsonl"):
        d = json.loads(line)
        cf.update(d["text"])
        after.update(d["text"][s["end"]:s["end"] + 2] for s in d["spans"])
    POS = {"n", "v", "a", "ns", "nr", "nz", "vn", "an", "t", "nrt", "s", "z"}
    words = set()
    for line in open(os.path.join(os.path.dirname(__file__), "data", "jieba_dict_big.txt"), encoding="utf-8"):
        w, f, p = (line.split() + ["", "", ""])[:3]
        if len(w) == 2 and p in POS and int(f or 0) >= min_freq and all("一" <= c <= "鿿" and cf[c] >= 20 for c in w):
            words.add(w)
    roles = set(TITLES) | set(SURNAME_AFTER) | set(GIVEN_AFTER) | set(PRIVATE_ROLES) | set(COUNSEL_ROLES) | set(OFFICIAL_ROLES)
    kin = set("表堂叔伯姑舅姨嬸嫂哥姐姊弟妹爸媽爹娘公婆爺奶孫兒女夫妻")
    job = set("師長員生士官工匠家子手友者人客主婦仔")  # 職業、身分結尾（王禪師、陳店員、林學生）＝姓＋稱呼
    words = {w for w in words if w not in roles and not (w[0] in kin or w[1] in kin or w[1] in job) and after[w] < 3}
    words -= {"登位"}
    open(f"{_D}/open/word_names.txt", "w", encoding="utf-8").write("\n".join(sorted(words)) + "\n")
    return len(words)


def sample_surname(rng: random.Random, compound: bool = False, avoid: set[str] | None = None) -> str:
    for _ in range(50):
        s = rng.choice(COMPOUND_NAMES) if compound else rng.choices(_SUR, _W)[0]
        if not avoid or s not in avoid:
            return s
    return s


if __name__ == "__main__":
    import sys
    if sys.argv[1:] == ["build"]:
        print("像一般詞的名字", build_word_pool(), "個 → data/open/word_names.txt"); sys.exit()
    rng = random.Random(0)
    ns = [sample_name(rng) for _ in range(2000)]
    assert all(2 <= len(n) <= 4 for n in ns) and len(set(ns)) > 1500
    assert len(sample_name(rng, length=2)) == 2 and sample_name(rng, compound=True)[:2] in COMPOUND_NAMES
    assert [sample_name(random.Random(3)) for _ in range(5)] == [sample_name(random.Random(3), wild=0.0) for _ in range(5)]
    d4 = [sample_name(rng, length=4, compound=False) for _ in range(200)]
    assert all(len(n) == 4 and n[0] in _SUR and n[1] in _SUR for n in d4), d4[:5]  # 冠夫姓
    ws = [sample_name(rng, length=3, wild=0.4) for _ in range(3000)]
    rare = sum(n[0] not in _SUR for n in ws) / len(ws)
    wordy = sum(n[1:] in set(_word_given()) for n in ws) / len(ws)
    assert 0.12 < rare < 0.28 and 0.12 < wordy < 0.28 and all(len(n) == 3 for n in ws), (rare, wordy)
    print("假名自檢 OK：", ns[:6], "｜wild：", [n for n in ws if n[0] not in _SUR][:4], [n for n in ws if n[1:] in set(_word_given())][:4])
