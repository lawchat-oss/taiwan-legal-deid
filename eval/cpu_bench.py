"""CPU 速度：tw-PII-bench 長文前 N 份（固定版本，見 reproduce.py），量每千字毫秒、找出加替換的總秒數，
以及把長文接成一份約 10 萬字的文件、找出加替換一次的秒數（一份長文件的替換比多份短文件慢）。
用法：python eval/cpu_bench.py [6l|3l|run目錄]… [--n 50] [--threads 1]      （不給模型＝6l、3l 都跑）
"""
import os, sys, time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from reproduce import load_bench
from taiwan_legal_deid import Detector, Obfuscator

opt = {sys.argv[i][2:]: sys.argv[i + 1] for i in range(1, len(sys.argv) - 1) if sys.argv[i].startswith("--")}
args = [a for i, a in enumerate(sys.argv[1:], 1) if not a.startswith("--") and not sys.argv[i - 1].startswith("--")]  # 選項的值不是模型
N, TH = int(opt.get("n", 50)), int(opt.get("threads", 0))
longs = [r["text"] for r in load_bench() if r["split"] == "long"]
texts = longs[:N]
chars = sum(map(len, texts))
big = ""
for x in longs:
    if len(big) >= 100_000:
        break
    big += x + "\n\n"

for m in args or ["6l", "3l"]:
    det = Detector(m, threads=TH)
    det.detect(texts[0])  # 暖機
    t = time.time()
    for x in texts:
        det.detect(x)
    t1 = time.time()
    for x in texts:
        Obfuscator(det).anonymize(x)
    t2 = time.time()
    Obfuscator(det).anonymize(big)
    t3 = time.time()
    print(f"{m:10s} {len(texts)} 份 {chars} 字（執行緒 {TH or '預設'}）：偵測每千字 {(t1 - t) / chars * 1e6:6.1f} ms；"
          f"找出加替換共 {t2 - t1:.1f} 秒｜一份 {len(big)} 字的文件找出加替換 {t3 - t2:.1f} 秒")
