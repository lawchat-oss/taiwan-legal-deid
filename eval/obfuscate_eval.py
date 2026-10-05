"""混淆端到端評測：用偵測結果（run_ours 的輸出）跑混淆，看
1. 往返：restore(混淆後) 是否逐字等於原文；
2. 殘留：標準答案標的個資（4 字以上），混淆後的文字裡還找得到原字串的比例——使用者真正在意的「洩漏」；
   另算「只換模型抓到的位置、不補重複提及」的殘留，看補換的效果。
用法：python eval/obfuscate_eval.py <bench.jsonl> <pred.jsonl> [general|legal]   （HALF=dev|test 同 score_bench）
"""
import json, os, sys, zlib
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from taiwan_legal_deid.obfuscate import Obfuscator, restore, restore_exact

bench = [json.loads(l) for l in open(sys.argv[1])]
half = os.environ.get("HALF")
if half:
    bench = [r for r in bench if zlib.crc32(r["id"].encode()) % 2 == (0 if half == "dev" else 1)]
P = {p["id"]: p for p in map(json.loads, open(sys.argv[2]))}
mode = sys.argv[3] if len(sys.argv) > 3 else "general"

same = exact = 0
tot, leak, leak_raw = Counter(), Counter(), Counter()
for r in bench:
    p = P[r["id"]]
    spans = p["spans"] + p.get("keep", []) + p.get("pii", [])
    ob = Obfuscator(mode=mode, seed=zlib.crc32(r["id"].encode()))
    fake, mp = ob.apply(r["text"], spans)
    same += restore(fake, mp) == r["text"]
    exact += restore_exact(fake, ob.spans) == r["text"]
    raw = r["text"]  # 只換模型抓到的位置：把那些位置挖空，看原字串還在不在
    masked = sorted((s["start"], s["end"]) for s in spans if s["type"] != "PERSON_KEEP" and not (mode == "legal" and s["type"] == "DATE_EVENT"))
    chars = list(raw)
    for a, b in masked:
        for i in range(a, b):
            chars[i] = "\0"
    raw = "".join(chars)
    for g in r["spans"]:
        if len(g["text"].strip()) < 4:
            continue
        tot[g["label"]] += 1
        leak[g["label"]] += g["text"] in fake
        leak_raw[g["label"]] += g["text"] in raw
T, L, R = sum(tot.values()), sum(leak.values()), sum(leak_raw.values())
print(f"{len(bench)} 份（{mode}）：文件依位置還原逐字一致 {exact}/{len(bench)}｜用對照表字串還原（AI 回覆的做法）逐字一致 {same}/{len(bench)}")
print(f"標準答案的個資（4 字以上）{T} 個：混淆後殘留 {L}（{L / T:.2%}）｜只換模型抓到的位置會殘留 {R}（{R / T:.2%}）")
for k in sorted(tot, key=lambda k: -leak[k] / tot[k])[:8]:
    print(f"  {k:20s} 殘留 {leak[k]}/{tot[k]}（只換抓到位置 {leak_raw[k]}）")
