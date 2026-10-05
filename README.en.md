# taiwan-legal-deid

[中文](README.md)

De-identification for Taiwanese legal documents. On your own computer, it replaces names, personal data and private companies with realistic fakes and keeps a mapping table, so an AI's answer can be turned back into the original names afterwards.

- **Replaces only what should be replaced**: the program lists every possible name, personal-data value and organization; a model then decides for each one whether to *replace*, *keep*, or *ignore* it. Judges, prosecutors, lawyers and clerks acting in their official roles are kept; parties, witnesses and other private persons are replaced. Government agencies are kept; private companies are replaced.
- **Realistic fakes, not ○○○**: the same person gets the same fake name across the whole document, with surname and given name mapped separately (陳小姐 → 詹小姐). Addresses become real road names in the same city, national IDs get a valid checksum, birthdays keep the year (so ages stay the same), and listed-company short names and "下稱" aliases follow the full name.
- **Legal mode (default)**: dates of personal events are left unchanged, so an AI can still reason about periods and deadlines. Land lot numbers keep the section name and are replaced consistently across the case.
- **Runs locally on CPU**: no GPU needed, and no network access except for downloading the model the first time. The mapping table is a JSON file on your computer.

> This is pseudonymization, not anonymization: anyone with the mapping table can restore the original text, so keep the table as carefully as the personal data itself. The tool will miss things; always check by hand before sharing.

## Example

Input (fictional):

> 原告陳美玲（身分證 F223456781，民國71年3月8日生，住臺中市西屯區文心路三段100號7樓，手機 0912-345-678）與被告岱昀顧問股份有限公司（下稱岱昀公司）間確認僱傭關係存在事件。原告自113年5月2日起任職於岱昀公司，陳小姐主張岱昀公司違法解僱。被告訴訟代理人王大同律師。法官李佳穎。

Output (fake names differ on every run):

> 原告詹筱怡（身分證 F202201647，民國71年11月1日生，住臺中市沙鹿區北勢二街二段566之6號7樓，手機 0964-883-566）與被告弘邦顧問股份有限公司（下稱弘邦公司）間確認僱傭關係存在事件。原告自113年5月2日起任職於弘邦公司，詹小姐主張弘邦公司違法解僱。被告訴訟代理人王大同律師。法官李佳穎。

## Install

Python 3.10 or later.

```bash
pip install taiwan-legal-deid
```

On first use the model is downloaded from the GitHub Release (6-layer about 244 MB, 3-layer about 159 MB), checked against its sha256, and stored in `~/.cache/taiwan-legal-deid`.

## Usage

### Command line

```bash
taiwan-legal-deid complaint.txt                                # → complaint.txt.fake.txt and complaint.txt.map.json
taiwan-legal-deid exhibit.txt --map case-map.json             # reuse a case's mapping: same person, same fake name in every document
taiwan-legal-deid --restore reply.txt complaint.txt.map.json   # turn an AI reply back into the original names
taiwan-legal-deid complaint.txt --model 3l                     # faster 3-layer model
taiwan-legal-deid record.txt --general                         # general mode: also shift personal-event dates
```

Input is UTF-8 plain text; convert PDF or Word files to text first.

Each document gets its own mapping file next to it (`<file>.map.json`); use it to restore AI replies about that document. The shared case mapping (`--map`) occasionally disables a few entries: when a fake name from an earlier document happens to be a real name in a later one, that fake name becomes ambiguous.

### Python

```python
from taiwan_legal_deid import Detector, Obfuscator, restore

ob = Obfuscator(Detector())            # 6-layer by default; Detector("3l") is faster
fake, mapping = ob.anonymize(text)     # pseudonymized text and the mapping table
original = restore(ai_reply, mapping)  # restore an AI reply
```

For several documents in the same case, create a new `Obfuscator` for each document and pass in the mapping returned for the previous one (the same as `--map` on the command line). Don't reuse one `Obfuscator` across documents.

```python
det = Detector()
mapping = None
for text in texts:
    fake, mapping = Obfuscator(det, mapping=mapping).anonymize(text)  # restore AI replies about this document with this mapping
```

Detection only: `Detector().detect(text)` returns the position, type and score of each value.

### Offline use

Run `taiwan-legal-deid --download` (add `--model 3l` for the 3-layer model) on a machine with network access, then copy `~/.cache/taiwan-legal-deid` to the same place on the offline machine, or point `TAIWAN_LEGAL_DEID_HOME` to the folder. With `TAIWAN_LEGAL_DEID_OFFLINE=1` the tool never connects to the network.

## Accuracy and speed

Measured with weights-v1 (package 0.1.0). Reproduce with `python eval/reproduce.py` (also needs `pip install pyarrow`).

| | 6-layer (default) | 3-layer |
|---|---|---|
| Synthetic legal documents: names to replace, fully replaced | 93.3% | 91.1% |
| Synthetic legal documents: names in official roles kept | 98.0% | 98.0% |
| Synthetic legal documents: other personal data, fully replaced | 93.6% | 93.0% |
| tw-PII-bench test half: personal data other than names, fully replaced | 95.7% | 95.1% |
| Speed: find and replace in one document of about 100,000 characters (Apple M5 Max CPU) | about 12 s | about 8 s |

**All numbers on this page come from synthetic test sets. Synthetic data is usually simpler than real documents, so real-world results may be lower. Always check by hand before sharing.**

- **Synthetic legal test set** (`eval/data/synthetic_legal_test.jsonl`): 75 fictional complaints, judgments, police records, certified letters, chat logs, emails and similar documents, 21,823 characters in total. The set was sealed before any evaluation, and its errors were never inspected during development. It marks 462 names to replace, 51 names in official roles, and 498 other personal-data values. Each document is tagged with its difficulty types: 1 rare surnames, indigenous and foreign names; 2 names that look like ordinary words; 3 OCR noise; 4 the same value written in several ways; 5 names to keep next to names to replace; 6 general documents.
- **tw-PII-bench** ([lianghsun/tw-PII-bench](https://huggingface.co/datasets/lianghsun/tw-PII-bench), Liang Hsun Huang, Apache-2.0): the 453 items with `crc32(id) % 2 == 1`, scored in general mode. The person-name category is not reported because the whole benchmark was used during development before the split.
- "Fully replaced" means every character of the annotated value was replaced; partial replacement counts as a miss.
- In legal mode, birthdays are fully replaced 95.1% of the time and personal-event dates are kept 98.3% of the time (same for both models).

## Known limitations

- It will miss things (see the table above); always check by hand before sharing.
- Japanese names written only in katakana, and people referred to only by given name or nickname in chats, are often missed.
- Address boundaries are hard to get exactly right (addresses fully replaced in the synthetic set: 88% for 6-layer, 84% for 3-layer).
- Names of lawyers or judges that appear on their own, without a title, in page headers or lists are sometimes treated as names to replace.
- Very long URLs (over about 220 characters) are sometimes missed entirely.
- With a shared case mapping (`--map`), if a fake name from an earlier document happens to be a real name in a later one, that person's fake name or form of address may be inconsistent in later documents; restore each document with its own mapping file.
- When a listed company's short name appears before its full name and there is no "下稱" alias, the short name and the full name may get different fake names.
- When a person's name and a company name share the same characters (陳佳穎 and 佳穎科技有限公司), the company's "下稱" alias may get the person's fake name and no longer match the company's fake name.
- Some chain stores and state-owned companies are kept when they are parties. Japanese companies (株式会社), Japanese addresses and Japanese era dates are not handled.

## How it works

1. **Candidates (program)**: possible name spans from a surname list (Ministry of the Interior) and titles; personal data such as national IDs, phone numbers, account numbers, emails, URLs, addresses (Ministry of the Interior road names) and dates; names of companies, shops, communities and schools, plus listed-company short names. The program over-generates on purpose and makes no decisions.
2. **Decisions (model)**: each text window goes through the model once, which decides *replace / keep / ignore* for every candidate in it. The model is fine-tuned from bert-base-chinese and distilled from 12 layers into 6 and 3 layers, running on CPU through ONNX.
3. **Replacement (program)**: realistic fakes by type, consistent across the document; other spellings of the same value elsewhere are replaced too.

Training data: public court judgments (real names on the party lists are first replaced with fake names, so the model never sees them), synthetic legal documents, and programmatic augmentation. The training code is in `taiwan_legal_deid/train.py` (MLX, Apple Silicon) and must be run from the repository, since it reads and writes the repository's `data/` folder; the training data is not published.

## About

Maintained by [LawChat](https://lawchat.com.tw) — a Taiwan legal AI platform.

- Website: [lawchat.com.tw](https://lawchat.com.tw)
- Contact: opensource@lawchat.com.tw
- Issues: [GitHub Issues](https://github.com/lawchat-oss/taiwan-legal-deid/issues)

Best-effort maintenance, no SLA on issues. Reports of missed or wrongly replaced values are welcome; replace any real personal data with made-up values before posting.

## License

- Code: MIT (`LICENSE`).
- Model weights: Apache-2.0 (`LICENSES/Apache-2.0.txt`), fine-tuned from bert-base-chinese (Google, Apache-2.0).
- Bundled third-party data (jieba dictionary; open government data from the Ministry of the Interior and the Securities and Futures Bureau): see `NOTICE`.
- The synthetic legal test set is MIT-licensed, like the code.

## Disclaimer

**No warranty.** The code (MIT) and the model weights (Apache-2.0) are provided "as is", without warranty of any kind, express or implied. To the extent permitted by law, the maintainers are not liable for any damage arising from the use of this tool or its results.

This tool helps reduce the risk of personal data leaking from documents. It does not guarantee that all personal data is found, and it is not legal advice. Decide for yourself, and check by hand, whether a document can be shared, uploaded or published; you remain responsible for complying with personal data protection laws.

## Citation

See `CITATION.cff`.
