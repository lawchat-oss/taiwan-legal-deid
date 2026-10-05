"""上市櫃公司的全名 → 簡稱（台灣積體電路製造股份有限公司 → 台積電）。混淆時全名換掉，文件裡的簡稱也要跟著換，不然等於沒換。
資料：金融監督管理委員會證券期貨局「上市公司基本資料」「上櫃公司基本資料」（政府資料開放平臺 data.gov.tw/dataset/18419、25036；
政府資料開放授權條款第 1 版，見 data.gov.tw/license），只取公司代號、名稱、簡稱。
重建：python -m taiwan_legal_deid.companies（寫 taiwan_legal_deid/data/tw_listed_companies.csv）
"""
import csv, functools, io, os, urllib.request

PATH = os.path.join(os.path.dirname(__file__), "data", "tw_listed_companies.csv")
_norm = lambda s: "".join(s.split()).replace("臺", "台")


@functools.lru_cache(None)
def _table():
    if not os.path.exists(PATH):
        return {}
    return {_norm(r["name"]): r["short"] for r in csv.DictReader(open(PATH, encoding="utf-8")) if r["short"] and r["short"] != r["name"]}


def all_short_names() -> set[str]:
    return set(_table().values())


def short_name(name: str) -> str | None:
    """全名（可帶分公司）→ 簡稱；不是上市櫃公司回 None。"""
    n = _norm(name)
    t = _table()
    if n in t:
        return t[n]
    return next((s for full, s in t.items() if n.startswith(full)), None)  # 台灣積體電路製造股份有限公司台中分公司


if __name__ == "__main__":
    rows = []
    for src, x in (("twse", "L"), ("tpex", "O")):  # data.gov.tw 兩份資料集的下載點（上市 L、上櫃 O）
        text = urllib.request.urlopen(f"https://mopsfin.twse.com.tw/opendata/t187ap03_{x}.csv", timeout=60).read().decode("utf-8-sig")
        rows += [(r["公司代號"], r["公司名稱"], r["公司簡稱"], src) for r in csv.DictReader(io.StringIO(text))]
    with open(PATH, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["code", "name", "short", "source"])
        w.writerows((c.strip(), n.strip(), s.strip(), src) for c, n, s, src in rows)
    _table.cache_clear()
    print(len(rows), "家 →", PATH, "｜例：", short_name("臺灣積體電路製造股份有限公司"), short_name("鴻海精密工業股份有限公司台中分公司"))
