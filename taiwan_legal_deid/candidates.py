"""候選產生：程式只負責「找」，而且刻意多抓；要不要遮、哪一種切法，全部交給模型判斷。
同一位置會列出多種切法（王小、王小明、王小明於），讓模型從中選；這裡不做任何「是不是人名」的過濾。
"""
from __future__ import annotations

import re

from .surnames import COMPOUND, JP_SURNAMES, SURNAMES

_CJK = "一-鿿㐀-䶿々"  # 々：日本姓、名的疊字號（佐々木）
LONG_SURNAMES = {k: {s for s in COMPOUND + JP_SURNAMES if len(s) == k} for k in (2, 3, 4)}  # 多字姓（複姓、日本姓）
JP_SET = set(JP_SURNAMES)
KANA_CJK = re.compile(f"[{_CJK}ぁ-ゖァ-ヺー]")  # 日本姓後面的名字可以是假名（久保田ゆかり）
CJK = re.compile(f"[{_CJK}]")
# 姓後面直接接的稱謂：候選是「姓」本身（遮姓、稱謂留在原文）
TITLES = ("先生", "小姐", "女士", "太太", "男", "女", "姓", "某", "董", "總", "老師", "醫師", "護理師", "經理", "主任", "律師", "法官",
          "檢察官", "書記官", "警員", "教授", "里長", "校長", "同學", "阿姨", "伯", "嫂", "哥", "姐", "姊", "弟", "妹", "媽", "爸", "家",
          "專員", "房東", "房客", "店長", "老闆", "組長", "課長", "科長", "處長", "協理", "襄理", "副理", "特助", "秘書", "助理", "業務",
          "師傅", "教練", "社長", "會長", "理事長", "院長", "所長", "站長", "隊長", "班長", "導師", "學長", "學姐", "學姊", "學弟", "學妹",
          "叔", "舅", "姑", "嬸", "奶奶", "爺爺", "阿公", "阿嬤", "代書", "里幹事", "幹事", "議員", "委員", "員警", "巡佐", "所長",
          "嫌", "員", "君", "氏", "（先生）", "（小姐）", "(先生)", "(小姐)", "部長", "取締役", "樣", "様", "さん", "殿")
SURNAME_AFTER = ("我姓", "敝姓", "免貴姓", "姓氏為", "姓")  # 我姓張 → 候選「張」
# 只有名字的稱呼（雅婷姐、Hi 奕辰）：這些線索前後的兩字詞列為候選
GIVEN_BEFORE = ("Hi ", "Hi,", "hi ", "嗨", "Dear ", "親愛的", "@", "給", "致")
GIVEN_AFTER = ("你好", "妳好", "您好", "姐", "姊", "哥", "弟", "妹", "：", ":", "，你", "，妳", "同學", "媽媽", "爸爸", "的媽媽", "的爸爸", "的家長", "的老師")
NICK = re.compile(f"[老小阿][{_CJK}]{{1,2}}")
KIN1 = re.compile(f"[{_CJK}](?=[姐姊哥嫂仔妹弟])")
TRANSLIT = re.compile(f"[{_CJK}]{{1,6}}(?:[·‧・．][{_CJK}]{{1,6}}){{1,3}}")
LATIN = re.compile(r"(?<![A-Za-z])[A-Z][a-z]+(?:[- ][A-Z][a-z]+){1,3}(?![A-Za-z])")  # Lin Chia-Hao、Mary Smith（\b 會把中文當字母，不能用）
LATIN1 = re.compile(r"(?:(?<=Hi )|(?<=Dear )|(?<=@))[A-Z][a-z]{1,15}(?![A-Za-z])")  # Hi Ivy
LATIN_SOLO = re.compile(r"(?<![A-Za-z])[A-Z][a-z]{1,15}(?![A-Za-z])")  # 單一英文名（句首的 Andy、中文裡的 Lowking）；品牌也會進來，交給模型
LATIN_CAPS = re.compile(r"(?<![A-Za-z])[A-Z]{2,}, ?[A-Z]{2,}(?:[- ][A-Z]{2,}){0,3}(?![A-Za-z])")  # 護照式：CHEN, YU-TING
NICK_LATIN = re.compile(r"[老小阿][A-Z][a-z]{1,12}")  # 阿Ben  # 中文裡夾的單一英文名（Lowking）；品牌也會進來，交給模型
LATIN_UP = re.compile(r"(?<![A-Za-z0-9@._/\-])[A-Z]{3,12}(?![A-Za-z0-9@._/\-])")  # 全大寫的暱稱（LINE 聯絡人 IRENE）；LINE、ATM、PDF 也會進來，交給模型
LATIN_UP_MULTI = re.compile(r"(?<![A-Za-z0-9@._/\-])[A-Z]{2,12}(?: [A-Z]{2,12}){1,3}(?![A-Za-z0-9@._/\-])")  # 護照式（移工、外配）：NGUYEN VAN HUNG
_SUR1 = "".join(sorted(SURNAMES))
LATIN_SUR = re.compile(rf"(?<![A-Za-z])[A-Z][A-Za-z]{{1,12}} ?[{_SUR1}](?![A-Za-z])|(?<![{_CJK}A-Za-z])[{_SUR1}] ?[A-Z][A-Za-z]{{1,12}}(?![A-Za-z])")  # LINE 顯示名稱：CINDY林、林Cindy


def surname_len(s: str) -> int:
    return next((k for k in (4, 3, 2) if s[:k] in LONG_SURNAMES[k]), 1 if s[:1] in SURNAMES else 0)


def candidates(text: str) -> list[tuple[int, int, str]]:
    """回傳 [(start, end, kind)]，start/end 是字元位置；kind 只是來源標記（full／partial／given／translit／latin），模型會看到。"""
    out: set[tuple[int, int, str]] = set()
    n = len(text)
    for i in range(n):
        # 複姓、日本姓也可能只是單姓開頭（中村→中＋村？）：每種切法都列
        for sl in [k for k in (4, 3, 2) if text[i:i + k] in LONG_SURNAMES[k]] + [1] * (text[i:i + 1] in SURNAMES):
            # 全名：姓＋1～3 個中文字（日本姓：名字 1～4 字，可以是假名）
            jp = text[i:i + sl] in JP_SET
            for g in (1, 2, 3, 4) if jp else (1, 2, 3):
                j = i + sl + g
                if j <= n and all((KANA_CJK if jp else CJK).match(c) for c in text[i + sl:j]):
                    out.add((i, j, "full"))
            # 字間夾空白或斷行的名字（判決當事人欄「白　安」、OCR「王 小 明」「陳眷⏎穎」）：每個字之間最多一個
            j, got = i + sl, 0
            while j < n and got < 3:
                if text[j] in " 　\n" and j + 1 < n and CJK.match(text[j + 1]):
                    j += 1
                if not CJK.match(text[j]):
                    break
                j += 1; got += 1
                if any(c in text[i:j] for c in " 　\n"):
                    out.add((i, j, "full"))
            # 部分稱呼：姓＋稱謂 → 候選是姓；「我姓張」→ 候選是姓
            if any(text.startswith(t, i + sl) for t in TITLES) or any(text.endswith(a, 0, i) for a in SURNAME_AFTER):
                out.add((i, i + sl, "partial"))
    for m in KIN1.finditer(text):  # 單字名＋稱謂：珠姐、俊哥（大哥、二姐這類親屬稱呼也會進來，交給模型）
        out.add((m.start(), m.start() + 1, "nick"))
    for m in NICK.finditer(text):  # 綽號：老王、小李、阿志、阿源
        out.add((m.start(), m.start() + 2, "nick"))
        if m.end() - m.start() == 3:
            out.add((m.start(), m.end(), "nick"))
    for i in range(n - 1):  # 只有名字：兩字中文詞，前後有稱呼線索
        w = text[i:i + 2]
        if not (CJK.match(w[0]) and CJK.match(w[1])):
            continue
        before, after = text[max(0, i - 8):i], text[i + 2:i + 6]
        line_start = i == 0 or text[i - 1] in "\n\r"
        clause_start = i > 0 and text[i - 1] in "，。！？；、 「（\t"  # 句首、逗號後的兩字名（筱婷說、，品妤已經）
        redup = w[0] == w[1]  # 疊字名（婷婷、欣欣）
        if line_start or clause_start or redup or any(before.endswith(b) for b in GIVEN_BEFORE) or any(after.startswith(a) for a in GIVEN_AFTER):
            out.add((i, i + 2, "given"))
    for m in TRANSLIT.finditer(text):  # 音譯名：前後可能黏到句子的字，列出多種切法
        parts = re.split("[·‧・．]", m.group(0))
        left, right = len(parts[0]), len(parts[-1])
        for a in range(1, min(4, left) + 1):
            for b in range(1, min(4, right) + 1):
                out.add((m.start() + left - a, m.end() - right + b, "translit"))
    for rx in (LATIN, LATIN1, LATIN_SOLO, LATIN_CAPS, NICK_LATIN, LATIN_UP, LATIN_UP_MULTI, LATIN_SUR):
        for m in rx.finditer(text):
            out.add((m.start(), m.end(), "latin"))
    return sorted(out)


def given_candidates(text: str, full_names: set[str]) -> list[tuple[int, int, str]]:
    """第二輪：文件裡已判定要遮的全名，把它的「名」也列為候選（林雅婷 → 雅婷姐）。"""
    out = set()
    for name in full_names:
        sl = surname_len(name)
        given = name[sl:]
        if len(given) < 2:
            continue
        for m in re.finditer(re.escape(given), text):
            out.add((m.start(), m.end(), "given2"))
    return sorted(out)


if __name__ == "__main__":
    t = ("被告王小明於翌日與陳女前往林口區，Hi 奕辰，雅婷姐好，撒韵·武荖與Lin Chia-Hao到場，證人白　安與王 小 明。"
         "玄宇傑、佐藤一郎、中村美和到場，證人鄧\n雅琪。乙方東海林健司、佐々木健太、勅使河原由美子，佐々木部長同意。IRENE 0912345678：用LINE傳。")
    c = candidates(t)
    got = {t[s:e] for s, e, _ in c}
    for want in ("王小明", "王小明於", "陳", "奕辰", "雅婷", "撒韵·武荖", "Lin Chia-Hao", "林口", "白　安", "王 小 明",
                 "玄宇傑", "佐藤一郎", "中村美和", "鄧\n雅琪", "東海林健司", "佐々木健太", "佐々木", "勅使河原由美子", "IRENE"):
        assert want in got, want
    t2 = "CINDY林 0912 收到；林Cindy、ANDY 鄧；移工NGUYEN VAN HUNG與WULAN PERTIWI；久保田ゆかり、一ノ瀬柚葉。"
    got2 = {t2[s:e] for s, e, _ in candidates(t2)}
    for want in ("CINDY林", "林Cindy", "ANDY 鄧", "NGUYEN VAN HUNG", "WULAN PERTIWI", "久保田ゆかり", "一ノ瀬柚葉"):
        assert want in got2, want
    assert ("王小", "full") in {(t[s:e], k) for s, e, k in c}
    assert surname_len("東海林健司") == 3 and surname_len("勅使河原由美子") == 4 and surname_len("佐々木健太") == 3 and surname_len("王小明") == 1
    print(f"候選自檢 OK：{len(c)} 個候選，{len(t)} 字")
