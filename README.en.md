# taiwan-legal-deid

[中文](README.md)

De-identification for Taiwanese legal documents. On your own computer, it finds names, personal data and private companies and replaces them with realistic fakes or codes; if you want to turn an AI's answer back into the original text, it keeps a mapping table. It is built for Taiwanese legal documents and also works on general text.

It is designed with reference to the de-identification technique classification of ISO/IEC 20889 and offers two modes: pseudonymization (reversible) and anonymization (irreversible). This is a design reference, not a certification or compliance assessment.

| Output | Looks like | Mapping table | Reversible | Use it when |
|---|---|---|---|---|
| Realistic pseudonymization (default) | 陳美玲 → 郭淑瑩 | kept | yes | you send the text to an AI and turn the answer back into the original |
| Code pseudonymization (`--codes`) | 陳美玲 → 甲, phone → 〔電話1〕 | kept | yes (birthdays reduced to the year stay that way) | readers should see at a glance what was replaced, and you still want to restore it |
| Anonymization (`--anonymize`) | 陳美玲 → 甲, phone → 〔電話1〕, 113年5月2日 → 113年5月 | none | no | you share with third parties or publish, after checking by hand |

- **Tells what to replace from what to keep**: the program lists every possible name, personal-data value and organization; a model then decides for each one whether to *replace*, *keep*, or *ignore* it. Judges, prosecutors, lawyers and clerks acting in their official roles are kept; parties, witnesses and other private persons are replaced. Government agencies are kept; private companies are replaced.
- **Realistic fakes**: the same person gets the same fake name across the whole document, with surname and given name mapped separately (陳小姐 → 郭小姐). Addresses become real road names in the same city, national IDs get a valid checksum, birthdays keep the year (so ages stay the same), and listed-company short names and "下稱" aliases follow the full name.
- **Codes**: people become 甲, 乙 and so on (the same person gets the same code across the document; references by surname, given name or nickname get that code when they match exactly one full name, and become 〇 when several people share the surname, so no one is mixed up). Companies keep everything but the brand, which becomes a letter (岱昀顧問股份有限公司 → A顧問股份有限公司), and their "下稱" aliases follow (岱昀公司 → A公司). Numbers, emails and URLs become numbered tokens such as 〔電話1〕. Codes avoid characters the text already uses (if the text has 甲方, 甲 is not used as a code). Birthdays keep only the year and addresses only the city or county.
- **Anonymization**: uses codes and keeps no mapping table; dates of personal events are also reduced to year and month (court and filing dates are kept; adjustable in Python).
- **Legal mode (default)**: when pseudonymizing, dates of personal events are left unchanged, so an AI can still reason about periods and deadlines. Land lot numbers keep the section name and are replaced consistently across the case.
- **Runs locally on CPU**: no GPU needed, and no network access except for downloading the model the first time. The mapping table is a JSON file on your computer.

> Pseudonymization keeps a mapping table, and anyone with it can restore the original text: keep the table as carefully as the personal data itself, and store it separately from the pseudonymized text. Anonymization keeps no table and cannot be reversed, but it does not guarantee anonymity in the legal sense: the story told in the text can still reveal who someone is, and whether the output is anonymous in the legal sense depends on the context and is for you to judge. The tool will miss things; always check by hand before sharing. Anonymized output consists of codes, so a missed real name stands out: check it all the more carefully before it leaves your hands.

## Example

Input (fictional):

> 原告陳美玲（身分證 F223456781，民國71年3月8日生，住臺中市西屯區文心路三段1999號7樓，手機 0912-345-678）與被告岱昀顧問股份有限公司（下稱岱昀公司）間確認僱傭關係存在事件。原告自113年5月2日起任職於岱昀公司，陳小姐主張岱昀公司違法解僱。被告訴訟代理人王大同律師。法官宋芷蘅。

Realistic pseudonymization (fake names differ on every run):

> 原告郭淑瑩（身分證 F249390925，民國71年7月21日生，住臺中市后里區九甲七路五段381號7樓，手機 0978-400-575）與被告冠頡顧問股份有限公司（下稱冠頡公司）間確認僱傭關係存在事件。原告自113年5月2日起任職於冠頡公司，郭小姐主張冠頡公司違法解僱。被告訴訟代理人王大同律師。法官宋芷蘅。

Code pseudonymization:

> 原告甲（身分證 〔身分證1〕，民國71年生，住臺中市〔地址1〕，手機 〔電話1〕）與被告A顧問股份有限公司（下稱A公司）間確認僱傭關係存在事件。原告自113年5月2日起任職於A公司，甲小姐主張A公司違法解僱。被告訴訟代理人王大同律師。法官宋芷蘅。

Anonymization (the only differences from the code version: personal-event dates keep just year and month, and there is no mapping table):

> 原告甲（身分證 〔身分證1〕，民國71年生，住臺中市〔地址1〕，手機 〔電話1〕）與被告A顧問股份有限公司（下稱A公司）間確認僱傭關係存在事件。原告自113年5月起任職於A公司，甲小姐主張A公司違法解僱。被告訴訟代理人王大同律師。法官宋芷蘅。

All examples are fictional. The IDs, phone numbers and addresses produced by the realistic version are random and may happen to match real ones.

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
taiwan-legal-deid complaint.txt --codes                        # code version: 甲, A公司, 〔電話1〕, still with a mapping table
taiwan-legal-deid exhibit.txt --map case-map.json             # reuse a case's mapping: same person, same fake name in every document
taiwan-legal-deid --restore reply.txt complaint.txt.map.json   # turn an AI reply back into the original names
taiwan-legal-deid complaint.txt exhibit.txt --anonymize        # anonymize: writes <file>.anon.txt for each, no mapping; codes consistent across the batch
taiwan-legal-deid complaint.txt --model 3l                     # faster 3-layer model
taiwan-legal-deid record.txt --general                         # general mode: also process personal-event dates (shifted for realistic, year and month for codes)
```

Input is UTF-8 plain text; convert PDF or Word files to text first.

Each document gets its own mapping file next to it (`<file>.map.json`); use it to restore AI replies about that document. The shared case mapping (`--map`) occasionally disables a few entries: when a fake name from an earlier document happens to be a real name in a later one, that fake name becomes ambiguous. Use the same style for a whole case (always or never `--codes`).

Anonymized output cannot be restored. `--anonymize` always uses codes and keeps no mapping table (with or without `--codes`), and cannot be combined with `--map` or `--general`.

### Python

```python
from taiwan_legal_deid import Anonymizer, Detector, Obfuscator, restore

det = Detector()                                                  # 6-layer by default; Detector("3l") is faster
fake, mapping = Obfuscator(det).pseudonymize(text)                # realistic pseudonymization: text and mapping table
original = restore(ai_reply, mapping)                             # restore an AI reply
fake, mapping = Obfuscator(det, style="code").pseudonymize(text)  # code pseudonymization: 甲, A公司, 〔電話1〕, still reversible
anon = Anonymizer(det).anonymize(text)                            # anonymization: text only, no mapping table
```

For several documents in the same case, create a new `Obfuscator` for each document and pass in the mapping returned for the previous one (the same as `--map` on the command line). Don't reuse one `Obfuscator` across documents.

```python
mapping = None
for text in texts:
    fake, mapping = Obfuscator(det, mapping=mapping).pseudonymize(text)  # restore AI replies about this document with this mapping
```

To anonymize a batch: `Anonymizer(det).anonymize_many(texts)` (it scans all the texts first and avoids codes they already use; documents processed by the same `Anonymizer` share codes). `Anonymizer` options: `event_dates` (personal events: `month` by default, `year`, `keep`), `other_dates` (court and other dates: `keep` by default, `month`, `year`), `addr` (addresses: `city` by default, `district` keeps the district too).

`Obfuscator.anonymize()` from 0.1.x still works and returns the same result as before (it pseudonymizes and returns a mapping table), with a FutureWarning asking you to switch to `pseudonymize()`; it will be removed in 1.0. For irreversible anonymization use `Anonymizer`.

Detection only: `Detector().detect(text)` returns the position, type and score of each value.

### Offline use

Run `taiwan-legal-deid --download` (add `--model 3l` for the 3-layer model) on a machine with network access, then copy `~/.cache/taiwan-legal-deid` to the same place on the offline machine, or point `TAIWAN_LEGAL_DEID_HOME` to the folder. With `TAIWAN_LEGAL_DEID_OFFLINE=1` the tool never connects to the network.

## Accuracy and speed

Measured with weights-v1 (package 0.2.1). Reproduce with `python eval/reproduce.py` (also needs `pip install pyarrow`). All three outputs share one detection step, so a value the detector misses is missed by all three.

| Pseudonymization | 6-layer (default) | 3-layer |
|---|---|---|
| Synthetic legal documents: names to replace, fully replaced | 93.3% | 91.1% |
| Synthetic legal documents: names in official roles kept | 98.0% | 98.0% |
| Synthetic legal documents: other personal data, fully replaced (general mode) | 93.6% | 93.0% |
| tw-PII-bench test half: personal data other than names, fully replaced | 95.7% | 95.1% |
| Speed: find and replace in one document of about 100,000 characters (Apple M5 Max CPU) | about 12 s | about 8 s |

| Anonymization (`Anonymizer` defaults) | 6-layer (default) | 3-layer |
|---|---|---|
| Synthetic legal documents: direct identifiers fully masked | 94.5% | 93.2% |
| Synthetic legal documents: birthdays reduced to the year | 95.1% | 95.1% |
| Synthetic legal documents: addresses reduced to the city or county | 83.3% | 80.0% |
| Synthetic legal documents: personal-event dates reduced to year and month | 95.8% | 95.8% |
| Synthetic legal documents: names in official roles kept | 96.1% | 96.1% |
| tw-PII-bench test half: direct identifiers other than names, fully masked | 96.7% | 96.2% |
| tw-PII-bench test half: addresses reduced to the city or county | 93.8% | 91.2% |
| tw-PII-bench test half: dates generalized | 89.6% | 89.9% |

**All numbers on this page come from synthetic test sets. Synthetic data is usually simpler than real documents, so real-world results may be lower. Always check by hand before sharing.**

- **Synthetic legal test set** (`eval/data/synthetic_legal_test.jsonl`): 75 fictional complaints, judgments, transcripts, certified letters, chat logs, emails and similar documents, 21,823 characters in total. The set was sealed before any evaluation, and its errors were never inspected during development. It marks 462 names to replace, 51 names in official roles, and 498 other personal-data values. Each document is tagged with its difficulty types: 1 rare surnames, indigenous and foreign names; 2 names that look like ordinary words; 3 OCR noise; 4 the same value written in several ways; 5 names to keep next to names to replace; 6 general documents.
- **tw-PII-bench** ([lianghsun/tw-PII-bench](https://huggingface.co/datasets/lianghsun/tw-PII-bench), Liang Hsun Huang, Apache-2.0): the 453 items with `crc32(id) % 2 == 1`, scored in general mode. The person-name category is not reported because person names across the whole benchmark were inspected during development, before the split.
- "Fully replaced" and "fully masked" mean every character of the annotated value was replaced; partial replacement counts as a miss. Direct identifiers are names, national IDs, phone numbers, emails, URLs, account numbers, passwords, license plates, social-media handles and similar values; indirect identifiers (birthdays, addresses, dates) count as generalized when they were reduced, with the kept city or county excluded for addresses.
- The pseudonymization table measures detection (model decisions); the anonymization table measures actual output (a name is also replaced where it must be replaced elsewhere in the document, so names in official roles are kept less often there).
- Anonymization numbers are measured on the actual output: a direct identifier's output must not keep any of the original value (a password replaced as if it were a date, leaving 1986年, counts as a miss), a birthday may keep only the year, and a date may not keep the day.
- Code pseudonymization uses the same replacement as anonymization: direct identifiers, birthdays, addresses and names in official roles score the same as in the table above; the difference is that personal-event dates are kept (98.3% on the synthetic legal documents, same for both models).
- In legal mode, birthdays are fully replaced 95.1% of the time and personal-event dates are kept 98.3% of the time (same for both models).

## Scope and known limitations

**Scope**: Traditional Chinese documents from Taiwan. Japanese text (names written only in katakana, 株式会社, Japanese addresses, Japanese era dates) is out of scope.

**Detection will miss things** (limits of the model, see the tables above); always check by hand before sharing:

- People referred to only by given name or nickname in chats are often missed.
- Address boundaries are hard to get exactly right (addresses fully replaced in the synthetic set: 88% for 6-layer, 84% for 3-layer).
- Names of lawyers or judges that appear on their own, without a title, in page headers or lists are sometimes treated as names to replace.
- Very long URLs (over about 220 characters) are sometimes missed entirely.
- Some chain stores and state-owned companies are kept when they are parties.

**Design trade-offs** (working as designed; good to know before use):

- Anonymization only handles the direct and indirect identifiers listed above; ages, occupations, schools, family relationships and details of events are not handled.
- When restoring the code version, a lone code is not restored where it forms an ordinary word (甲方, 甲說, 甲級); a lone company letter is restored only after a party reference such as 被告A or （下稱A）; in A公司 and A科技 only the letter goes back to the brand and the rest stays (岱昀公司); A棟, 維生素A and A/B測試 are left alone; values reduced to a year, a month or a city are not restored (the details are gone); a token such as 〔電話1〕 rewritten in some other form is not restored either.
- When several people share a surname, a reference by surname alone (陳小姐) cannot be tied to one person and becomes 〇小姐.
- Codes are consistent only within one `Anonymizer` or one command; across separate batches, 甲 in one batch is not the same person as 甲 in another. When `Anonymizer.anonymize()` is called document by document and a later document already uses a code assigned earlier, that person gets a new code in that document and a warning is issued; process a batch with `anonymize_many()` or the command line instead.
- With a shared case mapping (`--map`), if a fake name from an earlier document happens to be a real name in a later one, that entry is disabled and later documents use a new fake name; restore AI replies about each document with that document's own mapping file.

## How it works

1. **Candidates (program)**: possible name spans from a surname list (Ministry of the Interior) and titles; personal data such as national IDs, phone numbers, account numbers, emails, URLs, addresses (Ministry of the Interior road names) and dates; names of companies, shops, communities and schools, plus listed-company short names. The program over-generates on purpose and makes no decisions.
2. **Decisions (model)**: each text window goes through the model once, which decides *replace / keep / ignore* for every candidate in it. The model is fine-tuned from bert-base-chinese and distilled from 12 layers into 6 and 3 layers, running on CPU through ONNX.
3. **Replacement (program)**: realistic fakes, or codes and generalization by type (pseudonymization, masking and generalization in the terms of ISO/IEC 20889); consistent across the document, and other spellings of the same value elsewhere are replaced too.

Training data: public court judgments (the names of parties, representatives, judges, clerks and others listed in each judgment are first replaced consistently with fake names), synthetic legal documents, and programmatic augmentation. The training code is in `taiwan_legal_deid/train.py` (MLX, Apple Silicon) and must be run from the repository, since it reads and writes the repository's `data/` folder; the training data is not published.

## About

Maintained by [LawChat](https://lawchat.com.tw) — a Taiwan legal AI platform.

- Issues and questions: [GitHub Issues](https://github.com/lawchat-oss/taiwan-legal-deid/issues)
- Website: [lawchat.com.tw](https://lawchat.com.tw)
- Contact: opensource@lawchat.com.tw

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
