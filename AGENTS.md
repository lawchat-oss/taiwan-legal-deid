# AGENTS.md

給在這個 repo 工作的程式助理（和人）。使用方式見 `README.md`。

## 架構

1. **候選**（程式，只負責多抓、不做判斷）：`candidates.py`（人名）、`pii_candidates.py`（個資）、`org_candidates.py`（機構）。
2. **判斷**（模型）：`examples.py` 把文件切成視窗（220 字、重疊 60 字），每個視窗跑一次模型，判斷每個候選「要換／保留／不是」。
   CPU 推論在 `detect_onnx.py`，MLX 版在 `detect.py`，`decode.py` 負責合併重疊的結果。
3. **替換**（程式）：
   - `obfuscate.py`：擬真假名化（`Obfuscator`）、對照表與還原（`restore`）；
   - `codes.py`：代號版（`CodeObfuscator`，`Obfuscator(style="code")` 用它）與匿名化（`Anonymizer`，不留對照表）。

其他：`weights.py` 第一次使用時下載 weights-v1 並驗 sha256；`cli.py` 是指令列；`labels.py` 是標籤和候選種類。

## 開發

```bash
python -m venv .venv && .venv/bin/pip install -e . pytest
.venv/bin/pytest -q                                  # 送 PR 前要過；CI 在 Python 3.10–3.12 跑同一組
.venv/bin/python -m taiwan_legal_deid.obfuscate      # 單一模組的自我測試（pytest 會全部跑；代號版是 taiwan_legal_deid.codes）
```

- pytest 不下載模型，沒有模型時偵測測試會跳過。要用模型跑：`taiwan-legal-deid --download`，或用 `TAIWAN_LEGAL_DEID_HOME` 指到放模型的資料夾。
- 改了 `obfuscate.py`，另外多跑幾個 seed 的性質測試：
  `.venv/bin/python -c "from taiwan_legal_deid.obfuscate import _property_check as p; [p(seed=s) for s in range(50)]"`
- 重現 README 的數字：`pip install pyarrow && python eval/reproduce.py`。

## 規則

- **判斷交給模型**：模型判斷之後，不加關鍵詞規則或例外清單。要修錯，只改候選產生、訓練資料、替換與還原程式，或值的範圍（例如 `decode.extend_long`）。
- **還原不能改壞 AI 回覆**：改了替換或還原，要確認 AI 回覆裡的一般詞不會被換掉（擬真版的假姓只挑少組詞的字；代號版的「甲方」「甲板」「A棟」不換）。`obfuscate._property_check` 與 `codes._demo` 都有這類測試，改完要過。
- **測試集只用來量測**：`eval/data/synthetic_legal_test.jsonl` 是封存的考題，不要看錯題來調候選、資料或門檻。
- 會影響準確度的改動，要用 `eval/reproduce.py` 重跑，並同步更新 `README.md` 和 `README.en.md`。
- `labels.KINDS` 只能往後加新種類，不能改順序或插在中間：權重是靠位置認候選種類的。
- 測試、範例、註解一律用虛構的值，不放真實個資。法官、律師、書記官的名字要先在司法院裁判書系統查過、查不到才用（範例曾經用到現任法官的名字）。公司名要先查經濟部商工登記的現存公司（`https://data.gcis.nat.gov.tw/od/data/api/6BBA2268-1367-4B42-9CCA-BC17499EBE8C?$format=json&$filter=Company_Name like 品牌 and Company_Status eq 01&$skip=0&$top=10`），0 家才用（範例曾經用到真公司的品牌）。
- 不 commit `data/`、`runs/`、`base/`、`release/` 和 `.onnx`（`.gitignore` 已排除）。權重另外放在 GitHub Release。
- 註解用繁體中文。
- 從 `main` 開分支、送 PR，squash merge。

## 訓練（Apple Silicon）

訓練資料不公開，要自己準備。訓練程式要從 repo 根目錄執行（讀寫 `data/`）。

```bash
.venv/bin/pip install -e ".[train]"                                          # 訓練（MLX）
python -m venv .venv-export && .venv-export/bin/pip install -e ".[export]"  # 匯出 ONNX（PyTorch）
```

1. **底模**：把 `google-bert/bert-base-chinese`（Apache-2.0）下載到 `base/bert-base-chinese`。
   如果只有 `pytorch_model.bin`，用 `.venv-export/bin/python -m taiwan_legal_deid.convert_base base/bert-base-chinese` 轉成 `model.safetensors`。
2. **資料**（都寫到 `data/train/`）：
   - `python -m taiwan_legal_deid.data_judgments <裁判書快取.db>` → `judg_docs.jsonl`（公開判決，名冊上的真名先換成假名）
   - `python -m taiwan_legal_deid.data_synth` → 合成文件，以及它們的 OCR 版、Markdown 版副本（需要 `data/synth/raw_*.jsonl`；會覆寫既有檔案）
   - `python -m taiwan_legal_deid.data_augment` → `aug_docs.jsonl`（針對已知弱點的擴增）
   - 上市櫃公司簡稱表的更新：`python -m taiwan_legal_deid.companies`
3. **訓練**：先訓 12 層老師，再蒸餾成 6 層、3 層。weights-v1 就是用這組參數訓的。
   ```bash
   python -m taiwan_legal_deid.train --base base/bert-base-chinese --out runs/base --epochs 3
   python -m taiwan_legal_deid.train --base base/bert-base-chinese --out runs/g6 --teacher runs/base --layers 0,1,2,3,4,5 --lr-enc 1e-4 --epochs 4
   python -m taiwan_legal_deid.train --base base/bert-base-chinese --out runs/g3 --teacher runs/base --layers 0,1,2 --lr-enc 1e-4 --epochs 4
   .venv-export/bin/python -m taiwan_legal_deid.export_onnx runs/g6               # 也可以加 --int8
   ```
4. **使用自己的權重**：`Detector("runs/g6")`，或 `taiwan-legal-deid 檔案.txt --model runs/g6`。

## 發版

- **套件**：
  1. 改版本號：`pyproject.toml`、`taiwan_legal_deid/__init__.py`、`CITATION.cff` 三處；
  2. 合併到 `main`；
  3. 推 `v<版本>` tag。GitHub Actions（`release.yml`）會用 Trusted Publishing 發到 PyPI，並建 GitHub Release。
- **權重**：每一版放在自己的 GitHub Release（例如 `weights-v1`）。換權重時：
  - 開一個新的 Release；
  - 更新 `weights.py` 的 `RELEASE`、檔名與 sha256；
  - 新權重認得更多候選種類的話，一併更新 `N_KINDS`。
