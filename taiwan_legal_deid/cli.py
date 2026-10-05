"""指令列：taiwan-legal-deid 文件.txt → 文件.txt.fake.txt（假名版）＋ 文件.txt.map.json（對照表，留在自己電腦）。"""
from __future__ import annotations

import argparse, json, os, sys

from . import weights
from .obfuscate import Obfuscator, restore


def main(argv=None):
    ap = argparse.ArgumentParser(prog="taiwan-legal-deid", description="台灣法律文件去識別化：人名、個資、私人機構換成擬真假名，留對照表可還原。")
    ap.add_argument("file", nargs="?", help="要去識別化的文字檔（UTF-8）")
    ap.add_argument("--model", default="6l", help="6l（預設，較準）、3l（較快），或自己訓練的 run 目錄")
    ap.add_argument("--general", action="store_true", help="一般模式：個人行程日期也整份位移（預設法律模式：保留）")
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
        print(restore(open(a.restore[0], encoding="utf-8").read(), json.load(open(a.restore[1], encoding="utf-8"))))
        return
    if a.download:
        print(weights.path(a.model))
        return
    if not a.file:
        ap.error("請給要去識別化的檔案")
    from .detect_onnx import Detector
    mp_path = a.map or a.file + ".map.json"
    old = json.load(open(mp_path, encoding="utf-8")) if a.map and os.path.exists(mp_path) else None
    ob = Obfuscator(Detector(a.model), mode="general" if a.general else "legal", mapping=old)
    fake, mp = ob.anonymize(open(a.file, encoding="utf-8").read())
    with open(a.file + ".fake.txt", "w", encoding="utf-8") as f:
        f.write(fake)
    own = a.file + ".map.json"  # 這份文件自己的對照表：之後的文件可能讓案件對照表裡少數對照停用（假名撞到真名），還原這份的 AI 回覆時用它
    for path in dict.fromkeys((mp_path, own)):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(mp, f, ensure_ascii=False, indent=1)
    print(fake)
    print(f"→ {a.file}.fake.txt、{own}" + (f"、{mp_path}（案件對照表）" if mp_path != own else "") + f"（對照表 {len(mp)} 筆）", file=sys.stderr)


if __name__ == "__main__":
    main()
