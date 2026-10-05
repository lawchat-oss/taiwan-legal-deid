"""模擬 OCR／PDF 轉文字的雜訊：形近字、英數混淆、全半形、字間空白、句中換行、雜點，以及整個字被讀成亂碼（灣 → ； ^）。
只做「替換」與「插入」，所以標準答案的位置可以跟著搬（spans 一起回傳）；值中間插進去的雜訊算在值裡面（人工標註也這樣標）。
用法：noise(text, spans, rng, p) → (新文字, 新 spans)；p＝每個字出事的機率（0.02 輕微、0.05 明顯）。
bench 雜訊版評測用預設值（junk、garble 不給＝跟舊版逐字相同）；訓練的 OCR 版副本另外開亂碼。
"""
from __future__ import annotations

import random

SIMILAR = {}
for group in ("己已巳", "未末", "土士", "日曰", "人入", "天夭", "千干", "戊戌戍", "侯候", "茶荼", "析折", "辦辨", "陳陣", "林材", "王玉",
              "0OＯ", "1lI", "5S", "8B", "2Z"):
    for c in group:
        SIMILAR[c] = [x for x in group if x != c]
FW = {chr(c): chr(c + 0xFEE0) for c in range(0x30, 0x3A)} | {",": "，", ":": "：", "(": "（", ")": "）"}
FW_BACK = {v: k for k, v in FW.items()}
JUNK_OCR = "|~·'；^•⑴_¦"  # 掃描件常見的雜點


def noise(text: str, spans: list[dict] | None = None, rng: random.Random | None = None, p: float = 0.03,
          junk: str = "|~·'", garble: float = 0.0):
    rng = rng or random.Random(0)
    out, newpos, newlen, pos = [], [], [], 0
    for c in text:
        r = rng.random()
        if r < p * 0.25 and c in SIMILAR:  # 形近字／英數混淆
            c = rng.choice(SIMILAR[c])
        elif r < p * 0.45 and (c in FW or c in FW_BACK):  # 全半形
            c = FW.get(c) or FW_BACK.get(c)
        elif garble and p * 0.45 <= r < p * 0.45 + garble and "一" <= c <= "鿿":  # 整個字讀成亂碼
            c = "".join(rng.choice(junk + " ") for _ in range(rng.randint(1, 3)))
        newpos.append(pos); newlen.append(len(c))
        out.append(c); pos += len(c)
        r = rng.random()
        if r < p * 0.5 and "一" <= c[-1] <= "鿿":  # 字間空白（直式、表格轉出來最常見）
            out.append(" "); pos += 1
        elif r < p * 0.65:  # 句中斷行
            out.append("\n"); pos += 1
        elif r < p * 0.7:  # 雜點
            out.append(rng.choice(junk)); pos += 1
    newpos.append(pos)
    new_text = "".join(out)
    new_spans = None
    if spans is not None:  # 起點搬到原字的新位置；終點搬到原本最後一個字的新內容之後（中間插進去的雜訊算在裡面）
        new_spans = []
        for s in spans:
            a, b = newpos[s["start"]], newpos[s["end"] - 1] + newlen[s["end"] - 1]
            new_spans.append(dict(s, start=a, end=b, text=new_text[a:b]))
    return new_text, new_spans


if __name__ == "__main__":
    t = "被告王小明於民國112年3月5日匯款至帳號013-123456789012，住臺北市大安區和平東路二段96號。"
    sp = [{"start": t.index("王小明"), "end": t.index("王小明") + 3, "label": "private_person"}]
    nt, ns = noise(t, sp, random.Random(1), p=0.2)
    assert ns[0]["text"].replace(" ", "").replace("\n", "")[0] in "王玉" and len(nt) >= len(t)
    a = t.index("臺北市")
    sp2 = [{"start": a, "end": len(t) - 1}]
    for seed in range(30):  # 開亂碼：標準答案仍然從原本第一個字的新位置開始、到最後一個字的新內容結束
        nt2, ns2 = noise(t, sp2, random.Random(seed), p=0.1, junk=JUNK_OCR, garble=0.05)
        assert nt2[ns2[0]["end"]:].strip("\n " + JUNK_OCR) == "。", (nt2, ns2)
        assert ns2[0]["text"] == nt2[ns2[0]["start"]:ns2[0]["end"]]
    print("OCR 雜訊自檢 OK：", nt.replace("\n", "⏎"), "｜", ns[0]["text"], "｜", ns2[0]["text"].replace("\n", "⏎"))
