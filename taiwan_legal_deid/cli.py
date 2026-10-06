"""指令列：
  taiwan-legal-deid 文件.txt                  → 文件.txt.fake.txt（假名版）＋ 文件.txt.map.json（對照表，留在自己電腦）
  taiwan-legal-deid 文件.txt --codes          → 假名化的代號版（甲、A公司、〔號碼1〕），一樣留對照表
  taiwan-legal-deid a.txt b.txt --anonymize   → a.txt.anon.txt、b.txt.anon.txt（匿名化：不留對照表、無法還原；同一批代號一致）
"""
from __future__ import annotations

import argparse, json, os, pathlib, sys

from . import weights
from .obfuscate import Obfuscator, restore


def _read(path):
    return pathlib.Path(path).read_text(encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="taiwan-legal-deid", description="台灣法律文件去識別化：人名、個資、私人機構換成假名或代號；假名化留對照表可還原，匿名化不留。")
    ap.add_argument("files", nargs="*", metavar="file", help="要去識別化的文字檔（UTF-8）；--anonymize 可以一次給多份")
    ap.add_argument("--model", default="6l", help="6l（預設，較準）、3l（較快），或自己訓練的 run 目錄")
    ap.add_argument("--codes", action="store_true", help="假名化的代號版：人名換成甲、乙，機構換成 A公司，號碼換成〔號碼1〕；一樣留對照表、可以還原")
    ap.add_argument("--anonymize", action="store_true", help="匿名化：一律使用代號、不留對照表，無法還原（分享給第三方、對外發表用）")
    ap.add_argument("--general", action="store_true", help="一般模式：個人行程日期也處理（擬真版整份位移、代號版只留年月；預設法律模式：保留）")
    ap.add_argument("--map", help="同一案件共用的對照表：讀進來沿用、處理完更新（同一個人每份文件都換成同一個假名）。每份文件另存自己的 <檔名>.map.json")
    ap.add_argument("--restore", nargs=2, metavar=("REPLY", "MAP"), help="把 AI 回覆裡的假名換回原文，印到螢幕")
    ap.add_argument("--download", action="store_true", help="只下載模型（之後可離線使用）")
    a = ap.parse_args(argv)
    try:
        _run(ap, a)
    except FileNotFoundError as e:  # 檔案不在、離線模式沒有模型：一行訊息就好
        sys.exit(str(e))


def _run(ap, a):
    if a.restore:
        print(restore(_read(a.restore[0]), json.loads(_read(a.restore[1]))))
        return
    if a.download:
        print(weights.path(a.model))
        return
    if not a.files:
        ap.error("請給要去識別化的檔案")
    if a.anonymize:
        if a.map:
            ap.error("匿名化不使用對照表（--anonymize 不能搭配 --map）")
        if a.general:
            ap.error("--anonymize 不能搭配 --general：匿名化的個人行程日期只留年月；要調整請用 Python 的 Anonymizer(event_dates=...)")
        _anonymize(a)
        return
    if len(a.files) > 1:
        ap.error("假名化一次處理一份；同一案件的多份文件請逐份執行，並加 --map 案件對照表")
    from .detect_onnx import Detector
    file = a.files[0]
    mp_path = a.map or file + ".map.json"
    old = json.loads(_read(mp_path)) if a.map and os.path.exists(mp_path) else None
    if old and any(e.get("code") for e in old) != a.codes:
        ap.error(f"案件對照表是{'代號版' if not a.codes else '擬真版'}：同一案件請用同一種（{'加' if not a.codes else '拿掉'} --codes）")
    ob = Obfuscator(Detector(a.model), mode="general" if a.general else "legal", mapping=old, style="code" if a.codes else "realistic")
    fake, mp = ob.pseudonymize(_read(file))
    with open(file + ".fake.txt", "w", encoding="utf-8") as f:
        f.write(fake)
    own = file + ".map.json"  # 這份文件自己的對照表：之後的文件可能讓案件對照表裡少數對照停用（假名撞到真名），還原這份的 AI 回覆時用它
    for path in dict.fromkeys((mp_path, own)):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(mp, f, ensure_ascii=False, indent=1)
    print(fake)
    print(f"→ {file}.fake.txt、{own}" + (f"、{mp_path}（案件對照表）" if mp_path != own else "") + f"（對照表 {len(mp)} 筆）", file=sys.stderr)


def _anonymize(a):
    """匿名化：同一批共用一個 Anonymizer（先掃過全部原文、代號整批一致），每份寫 <檔名>.anon.txt，不寫任何對照表。"""
    from .codes import Anonymizer
    from .detect_onnx import Detector
    texts = [_read(f) for f in a.files]
    for f, out in zip(a.files, Anonymizer(Detector(a.model)).anonymize_many(texts)):
        with open(f + ".anon.txt", "w", encoding="utf-8") as fh:
            fh.write(out)
        print(out)
    print("→ " + "、".join(f + ".anon.txt" for f in a.files) + "（匿名化：沒有對照表，無法還原）", file=sys.stderr)


if __name__ == "__main__":
    main()
