"""擬真假值：訓練資料補值（判決裡法院已遮的帳號、證號、生日、地址），之後真名混淆也用這裡。"""
from __future__ import annotations

import csv, functools, os, random, re

_ID_LETTER = "ABCDEFGHJKLMNPQRSTUVXYWZIO"  # 身分證首字母對應 10～35


def _id_check(L: str, body: list[int]) -> int:
    """身分證、居留證的檢查碼：首字母換成兩位數，加上第 2～9 碼，加權 1,9,8,7,6,5,4,3,2,1。"""
    n = _ID_LETTER.index(L) + 10
    s = n // 10 + (n % 10) * 9 + sum(d * w for d, w in zip(body, range(8, 0, -1)))
    return (10 - s % 10) % 10


def fake_id(rng: random.Random, letter: str | None = None, second: str | None = None) -> str:
    """檢查碼正確的身分證字號。second：第二碼（身分證 1、2；新式居留證 8、9；舊式居留證 A～D 字母）。"""
    L = letter or rng.choice("ABCDEFGHJKLMNPQRSTUVXYWZ")
    sec = second or rng.choice("12")
    s2 = (_ID_LETTER.index(sec) + 10) % 10 if sec.isalpha() else int(sec)  # 舊式居留證：第二碼字母換成數字取個位數
    body = [rng.randrange(10) for _ in range(7)]
    return L + sec + "".join(map(str, body)) + str(_id_check(L, [s2] + body))


def ubn_ok(d: str) -> bool:
    """統一編號（8 碼）檢查碼：加權 1,2,1,2,1,2,4,1，乘積的各位數相加能被 5 整除；第 7 碼是 7 時加 1 也算。"""
    if not re.fullmatch(r"\d{8}", d):
        return False
    s = sum(sum(map(int, str(int(c) * w))) for c, w in zip(d, (1, 2, 1, 2, 1, 2, 4, 1)))
    return s % 5 == 0 or (d[6] == "7" and (s + 1) % 5 == 0)


def luhn_ok(d: str) -> bool:
    """信用卡號（Luhn）檢查碼。"""
    if not re.fullmatch(r"\d{13,19}", d):
        return False
    tot = 0
    for i, c in enumerate(reversed(d)):
        v = int(c) * (2 if i % 2 else 1)
        tot += v - 9 if v > 9 else v
    return tot % 10 == 0


def fake_digits(rng: random.Random, pattern: str, keep_first: int = 0) -> str:
    """同格式換數字（分隔符號、長度不變）。"""
    out, k = [], 0
    for c in pattern:
        if c.isdigit():
            out.append(c if k < keep_first else str(rng.randrange(10))); k += 1
        else:
            out.append(c)
    return "".join(out)


def fake_birth(rng: random.Random, roc: bool = True) -> str:
    y, m, d = rng.randint(30, 95), rng.randint(1, 12), rng.randint(1, 28)
    return f"{y}年{m}月{d}日" if roc else f"{y + 1911}年{m}月{d}日"


@functools.lru_cache(None)
def _roads():
    p = os.path.join(os.path.dirname(__file__), "data", "roads_a.csv")
    with open(p, encoding="utf-8-sig") as f:
        rows = [(r["city"], r["site_id"][len(r["city"]):], r["road"]) for r in csv.DictReader(f)]
    return [r for r in rows if re.search("(路|街|大道)$", r[2])]


def county_of(addr: str) -> tuple[str | None, str | None]:
    """地址開頭是縣轄市或區（彰化市、竹北市、板橋區）而沒寫縣市 → (所屬縣市, 那個區)；查不到 → (None, None)。"""
    hits = {(c, d) for c, d, _ in _roads() if addr.startswith(d) and len(d) >= 2}
    if not hits:
        hits = {(c, d) for c, d, _ in _roads() if addr.startswith(d.replace("臺", "台"))}
    cities = {c for c, _ in hits}
    return (next(iter(hits)) if len(cities) == 1 else (None, None))


def fake_address(rng: random.Random, city: str | None = None, like: str | None = None, dist: str | None = None,
                 with_city: bool = True) -> str:
    """city：沿用原文已經寫出的縣市（只換它後面的部分）。dist：留在同一區。like：原地址，照它的結構（有沒有段、巷、弄、樓）產生。
    with_city＝False：原文沒寫縣市（彰化市聖安路…），假地址也不加。"""
    rows = _roads()
    if city:
        rows = [r for r in rows if r[0].replace("臺", "台") == city.replace("臺", "台")] or rows
    if dist:
        rows = [r for r in rows if r[1] == dist] or rows
    c, d, road = rng.choice(rows)
    c = city or (c.replace("臺", "台") if rng.random() < 0.5 else c)
    has = (lambda ch, p: ch in like) if like is not None else (lambda ch, p: rng.random() < p)
    s = (c if with_city else "") + (dist or d) + road
    if has("段", 0.25) and not re.search("[一二三四五六七八九十]段$", road):
        s += rng.choice("一二三四五") + "段"
    if has("巷", 0.4):
        s += f"{rng.randint(1, 400)}巷"
        if has("弄", 0.3):
            s += f"{rng.randint(1, 30)}弄"
    s += f"{rng.randint(1, 600)}" + (f"之{rng.randint(1, 9)}" if rng.random() < 0.15 else "") + "號"  # 86之9號
    floor = re.search(r"[0-9０-９一二三四五六七八九十]+\s?樓(?:\s?之\s?[0-9０-９一二三四五六七八九十]+)?", like or "")
    if floor:  # 樓層照原文：文件別處常會再提到「我住 8 樓」，換掉反而前後對不上（樓層本身也認不出人）
        s += floor.group(0)
    elif has("樓", 0.5):
        s += f"{rng.randint(2, 20)}樓" + (f"之{rng.randint(1, 5)}" if rng.random() < 0.2 else "")  # 14樓之2
    return s


if __name__ == "__main__":
    rng = random.Random(0)
    ids = [fake_id(rng) for _ in range(50)]
    assert all(re.fullmatch(r"[A-Z][12]\d{8}", x) for x in ids)
    assert fake_id(random.Random(1), "A")[0] == "A"
    # 公開的檢查碼範例：A123456789 是合法號碼 → 用同一套算法驗
    n = _ID_LETTER.index("A") + 10; body = "12345678"
    assert (10 - (n // 10 + (n % 10) * 9 + sum(int(d) * w for d, w in zip(body, range(8, 0, -1)))) % 10) % 10 == 9
    assert re.fullmatch(r"013-\d{12}", fake_digits(rng, "013-000000000000", keep_first=3))
    a = fake_address(rng)
    assert re.search(r"[市縣].+[區鄉鎮市].+(路|街|大道).*\d+號", a), a
    print("假值自檢 OK：", ids[0], fake_birth(rng), a)
