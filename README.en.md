# taiwan-legal-deid

[中文](README.md)

De-identification for Taiwanese legal documents. On your own computer, it finds names, personal data and private companies and replaces them with realistic fakes or codes; if you want to turn an AI's answer back into the original text, it keeps a mapping table. It is built for Taiwanese legal documents and also works on general text.

It is designed with reference to the de-identification technique classification of ISO/IEC 20889 and offers two modes: pseudonymization (reversible) and anonymization (irreversible). This is a design reference, not a certification or compliance assessment.

| Output | Looks like | Mapping table | Reversible | Use it when |
|---|---|---|---|---|
| Realistic pseudonymization (default) | 陳美玲 → 姚靜慧 | kept | yes | you send the text to an AI and turn the answer back into the original |
| Code pseudonymization (`--codes`) | 陳美玲 → 甲, phone → 〔電話1〕 | kept | yes (birthdays reduced to the year stay that way) | readers should see at a glance what was replaced, and you still want to restore it |
| Anonymization (`--anonymize`) | 陳美玲 → 甲, phone → 〔電話1〕, 113年5月2日 → 113年5月 | none | no | you share with third parties or publish, after checking by hand |

- **Tells what to replace from what to keep**: the program lists every possible name, personal-data value and organization; a model then decides for each one whether to *replace*, *keep*, or *ignore* it. Judges, prosecutors, lawyers and clerks acting in their official roles are kept; parties, witnesses and other private persons are replaced. Government agencies are kept; private companies are replaced.
- **Legal mode (default)**: when pseudonymizing, dates of personal events are left unchanged, so an AI can still reason about periods and deadlines. Land lot numbers keep the section name and are replaced consistently across the case.
- **Runs locally on CPU**: no GPU needed, and no network access except for downloading the model the first time. The mapping table is a JSON file on your computer.

> Pseudonymization keeps a mapping table, and anyone with it can restore the original text: keep the table as carefully as the personal data itself, and store it separately from the pseudonymized text. Anonymization keeps no table and cannot be reversed, but it does not guarantee anonymity in the legal sense: the story told in the text can still reveal who someone is, and whether the output is anonymous in the legal sense depends on the context and is for you to judge. The tool will miss things; always check by hand before sharing. Anonymized output consists of codes, so a missed real name stands out: check it all the more carefully before it leaves your hands.

## Example

Input (fictional):

> 原告陳美玲（身分證 F223456781，民國71年3月8日生，住臺中市西屯區文心路三段1999號7樓，手機 0912-345-678）與被告澄嶼顧問股份有限公司（下稱澄嶼公司）間確認僱傭關係存在事件。原告自113年5月2日起任職於澄嶼公司，陳小姐主張澄嶼公司違法解僱。被告訴訟代理人王大同律師。法官宋芷蘅。

Realistic pseudonymization (fake names differ on every run):

> 原告姚靜慧（身分證 F279190746，民國71年9月8日生，住臺中市太平區太平十一街四段554號7樓，手機 0976-232-860）與被告岑智顧問股份有限公司（下稱岑智公司）間確認僱傭關係存在事件。原告自113年5月2日起任職於岑智公司，姚小姐主張岑智公司違法解僱。被告訴訟代理人王大同律師。法官宋芷蘅。

Code pseudonymization:

> 原告甲（身分證 〔身分證1〕，民國71年生，住臺中市〔地址1〕，手機 〔電話1〕）與被告A顧問股份有限公司（下稱A公司）間確認僱傭關係存在事件。原告自113年5月2日起任職於A公司，甲小姐主張A公司違法解僱。被告訴訟代理人王大同律師。法官宋芷蘅。

Anonymization (the only differences from the code version: personal-event dates keep just year and month, and there is no mapping table):

> 原告甲（身分證 〔身分證1〕，民國71年生，住臺中市〔地址1〕，手機 〔電話1〕）與被告A顧問股份有限公司（下稱A公司）間確認僱傭關係存在事件。原告自113年5月起任職於A公司，甲小姐主張A公司違法解僱。被告訴訟代理人王大同律師。法官宋芷蘅。

All examples are fictional. The names, company names, IDs, phone numbers and addresses produced by the realistic version are random and may happen to match real people, companies, numbers or addresses.

### How each kind of value is replaced

| Value | Realistic pseudonymization (default) | Code pseudonymization | Anonymization |
|---|---|---|---|
| Names | The same person gets the same fake name across the document, with surname and given name mapped separately (陳小姐 → 郭小姐) | 甲, 乙 and so on; the same person gets the same code across the document, including references by surname, given name or nickname that match a full name | Same as code pseudonymization |
| Private companies | A realistic fake company name; listed-company short names and "下稱" aliases follow | Only the brand becomes a letter (澄嶼顧問股份有限公司 → A顧問股份有限公司), and "下稱" aliases follow (澄嶼公司 → A公司) | Same as code pseudonymization |
| National IDs | A fake number with a valid checksum | 〔身分證1〕 | Same as code pseudonymization |
| Phone numbers, emails, URLs and similar | Randomly generated fakes | Numbered tokens such as 〔電話1〕 | Same as code pseudonymization |
| Addresses | Real road names in the same city | City or county only | City or county only |
| Birthdays | Year kept (so ages stay the same) | Year only | Year only |
| Personal-event dates | Unchanged in legal mode; shifted across the document in general mode | Unchanged in legal mode; year and month only in general mode | Year and month only (court and filing dates are kept; adjustable in Python) |

Codes avoid characters the text already uses (if the text has 甲方, 甲 is not used as a code). Anonymization uses codes and keeps no mapping table.

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

To anonymize a batch: `Anonymizer(det).anonymize_many(texts)` (it scans all the texts first and avoids codes they already use; documents processed by the same `Anonymizer` share codes). `Anonymizer` options:

| Option | Applies to | Values (the first is the default) |
|---|---|---|
| `event_dates` | Personal-event dates | `month` year and month, `year` year only, `keep` unchanged |
| `other_dates` | Court and other dates | `keep` unchanged, `month` year and month, `year` year only |
| `addr` | Addresses | `city` city or county, `district` down to the district |

`Obfuscator.anonymize()` from 0.1.x still works and returns the same result as before (it pseudonymizes and returns a mapping table), with a FutureWarning asking you to switch to `pseudonymize()`; it will be removed in 1.0. For irreversible anonymization use `Anonymizer`.

Detection only: `Detector().detect(text)` returns the position, type and score of each value.

### Offline use

Run `taiwan-legal-deid --download` (add `--model 3l` for the 3-layer model) on a machine with network access, then copy `~/.cache/taiwan-legal-deid` to the same place on the offline machine, or point `TAIWAN_LEGAL_DEID_HOME` to the folder. With `TAIWAN_LEGAL_DEID_OFFLINE=1` the tool never connects to the network.

## Accuracy and speed

Measured with weights-v2 (package 0.3.0). Reproduce with `python eval/reproduce.py` (also needs `pip install pyarrow`). All three outputs share one detection step, so a value the detector misses is missed by all three.

| Term | Meaning | How it is scored |
|---|---|---|
| Recall | Of the values that should be replaced, the share that were replaced | Every character of the annotated value must be replaced; partial replacement counts as a miss |
| Precision | Of the values replaced, the share that really are personal data (the rest were replaced unnecessarily) | A replaced value counts as correct if it touches any annotation |

**All numbers on this page come from synthetic test sets. Synthetic data is usually simpler than real documents, so real-world results may be lower. Always check by hand before sharing.**

| Summary | 6-layer (default) | 3-layer |
|---|---|---|
| Recall, names (synthetic legal documents) | 92.6% | 91.6% |
| Recall, other personal data (synthetic legal documents, excluding phone numbers) | 93.2% | 94.1% |
| Recall, other personal data (tw-PII-bench, excluding names and phone numbers) | 96.3% | 95.6% |
| Precision (synthetic legal documents, excluding organizations) | 98.5% | 97.9% |
| Precision (tw-PII-bench, excluding names and organizations) * | 86.1% | 84.7% |
| Names in official roles kept (synthetic legal documents) | 98.0% | 98.0% |
| Speed: find and replace in one document of about 100,000 characters (Apple M5 Max CPU) | about 12 s | about 8 s |

\* Some personal emails and personal dates are outside tw-PII-bench's annotation scope, so replacing them counts as unnecessary; some others really were replaced unnecessarily. See the spot check below.

### By category (6-layer)

Recall, by annotated category:

| Category | Synthetic legal documents | tw-PII-bench |
|---|---|---|
| Names | 92.6% (428/462) | — |
| National IDs, resident permits, passports | 92.1% (70/76) | 100.0% (254/254) |
| NHI cards, driver's licenses, household numbers and other IDs | — | 99.2% (528/532) |
| Account and card numbers | 97.6% (40/41) | 92.7% (203/219) |
| Business ID numbers | — | 100.0% (138/138) |
| Passwords and verification codes | 100.0% (9/9) | 99.4% (157/158) |
| License plates | 90.9% (20/22) | 99.4% (169/170) |
| Emails | 91.7% (11/12) | 99.5% (221/222) |
| URLs | 100.0% (4/4) | 87.1% (115/132) |
| Social-media handles | 100.0% (11/11) | 94.2% (245/260) |
| Addresses | 91.1% (82/90) | 94.7% (214/226) |
| Birthdays | 92.7% (38/41) | — |
| Personal-event dates | 93.2% (110/118) | — |
| Dates (birthdays and events not distinguished) | — | 89.9% (277/308) |
| Phone numbers (reference only) | 95.9% (71/74) | 96.1% (268/279) |

Precision, by the type we output:

| Category | Synthetic legal documents | tw-PII-bench |
|---|---|---|
| Names | 99.8% (429/430) | — |
| Alphanumeric codes (IDs, passports, plates, etc.) | 98.1% (103/105) | 95.5% (1050/1099) |
| Digit numbers (accounts, business IDs, etc.) | 94.2% (49/52) | 90.5% (591/653) |
| Emails | 100.0% (11/11) | 66.2% (221/334) |
| URLs | 100.0% (4/4) | 99.1% (116/117) |
| Social-media handles | 100.0% (4/4) | 92.9% (52/56) |
| Addresses | 100.0% (83/83) | 95.1% (214/225) |
| Birthdays and other identity dates | 100.0% (37/37) | 89.4% (101/113) |
| Personal-event dates | 94.0% (109/116) | 53.3% (177/332) |

<details>
<summary>By category, 3-layer</summary>

Recall, by annotated category:

| Category | Synthetic legal documents | tw-PII-bench |
|---|---|---|
| Names | 91.6% (423/462) | — |
| National IDs, resident permits, passports | 96.1% (73/76) | 100.0% (254/254) |
| NHI cards, driver's licenses, household numbers and other IDs | — | 98.5% (524/532) |
| Account and card numbers | 95.1% (39/41) | 95.9% (210/219) |
| Business ID numbers | — | 100.0% (138/138) |
| Passwords and verification codes | 100.0% (9/9) | 95.6% (151/158) |
| License plates | 95.5% (21/22) | 98.8% (168/170) |
| Emails | 91.7% (11/12) | 100.0% (222/222) |
| URLs | 100.0% (4/4) | 90.9% (120/132) |
| Social-media handles | 100.0% (11/11) | 89.6% (233/260) |
| Addresses | 90.0% (81/90) | 89.8% (203/226) |
| Birthdays | 95.1% (39/41) | — |
| Personal-event dates | 94.1% (111/118) | — |
| Dates (birthdays and events not distinguished) | — | 91.2% (281/308) |
| Phone numbers (reference only) | 95.9% (71/74) | 94.6% (264/279) |

Precision, by the type we output:

| Category | Synthetic legal documents | tw-PII-bench |
|---|---|---|
| Names | 99.5% (420/422) | — |
| Alphanumeric codes (IDs, passports, plates, etc.) | 97.2% (105/108) | 95.6% (1031/1079) |
| Digit numbers (accounts, business IDs, etc.) | 98.0% (49/50) | 89.4% (596/667) |
| Emails | 100.0% (11/11) | 65.1% (222/341) |
| URLs | 100.0% (4/4) | 99.2% (121/122) |
| Social-media handles | 100.0% (4/4) | 92.7% (51/55) |
| Addresses | 98.8% (82/83) | 95.3% (203/213) |
| Birthdays and other identity dates | 94.9% (37/39) | 88.4% (99/112) |
| Personal-event dates | 92.5% (111/120) | 49.3% (183/371) |

</details>

- **Phone numbers are for reference only**: while developing 0.3.0, the phone-number errors in both test sets were inspected to find why numbers were missed, so these numbers may be optimistic and are left out of the summary.
- **No names for tw-PII-bench**: person names across the whole benchmark were inspected during development, before the split.
- **No organizations**: neither test set annotates organizations.
- **Precision leaves out phone numbers**: a digit-number prediction that touches a phone annotation is not counted (this removes only correct ones, so the numbers are conservative).
- **Precision is grouped by output type**: alphanumeric codes and digit numbers each cover several kinds of ID, so the two tables do not use exactly the same categories.
- **Low precision for emails and personal-event dates on tw-PII-bench**: we sampled values that matched no annotation in the other half, used for development (which may be inspected):
  - Emails, 40 sampled: 39 were personal addresses of senders and recipients in email headers, outside the benchmark's annotation scope; 1 was an agency's official mailbox that we replaced unnecessarily.
  - Personal-event dates, 40 sampled: about 60% were personal dates such as hospital visits, accidents and lease terms, outside the benchmark's annotation scope; about 40% were letter dates, deadlines and policy effective dates that we replaced unnecessarily. Personal-event dates are replaced only in general mode (`--general`); the default legal mode leaves them alone.
- **6-layer vs 3-layer**: the 3-layer model scores slightly higher on a few categories such as national IDs and birthdays; the 6-layer model is steadier on names and addresses and has higher precision, so it is the default.

### Test sets

| Test set | Contents | Scoring |
|---|---|---|
| Synthetic legal documents (`eval/data/synthetic_legal_test.jsonl`) | 75 fictional complaints, judgments, transcripts, certified letters, chat logs, emails and similar documents, 21,823 characters in total; 462 names to replace, 51 names in official roles, and 498 other personal-data values (74 of them phone numbers). The set was sealed before any evaluation, and its errors were never inspected during development (except for phone numbers) | General mode |
| [tw-PII-bench](https://huggingface.co/datasets/lianghsun/tw-PII-bench) (Liang Hsun Huang, Apache-2.0) | The 453 items with `crc32(id) % 2 == 1` (the test half) | General mode; no names, phone numbers for reference only |

Each synthetic document is tagged with its difficulty types: 1 rare surnames, indigenous and foreign names; 2 names that look like ordinary words; 3 OCR noise; 4 the same value written in several ways; 5 names to keep next to names to replace; 6 general documents.

### Anonymization and code pseudonymization

The numbers above measure detection (model decisions). Anonymization is measured on the actual output: direct identifiers (names, national IDs, phone numbers, emails, URLs, account numbers, passwords, license plates, social-media handles and similar values) must be replaced in full and must not keep any of the original value (a password replaced as if it were a date, leaving 1986年, counts as a miss); a birthday may keep only the year, a date may not keep the day, and an address must be replaced in full apart from the kept city or county. A name is also replaced where it must be replaced elsewhere in the document, so names in official roles are kept less often than in pseudonymization.

| Anonymization (`Anonymizer` defaults) | Synthetic: 6-layer | Synthetic: 3-layer | tw-PII-bench: 6-layer | tw-PII-bench: 3-layer |
|---|---|---|---|---|
| Direct identifiers fully masked (excluding phone numbers; also names for tw-PII-bench) | 94.3% | 93.6% | 97.4% | 97.0% |
| Birthdays reduced to the year | 92.7% | 95.1% | — | — |
| Addresses reduced to the city or county | 86.7% | 85.6% | 94.7% | 89.8% |
| Personal-event dates reduced to year and month | 93.2% | 94.1% | — | — |
| Dates generalized (birthdays and events not distinguished) | — | — | 90.3% | 91.6% |
| Names in official roles kept | 96.1% | 96.1% | — | — |

Code pseudonymization uses the same replacement as anonymization, so direct identifiers, birthdays, addresses and names in official roles score the same as above. How each output handles dates (synthetic legal documents, 6-layer / 3-layer):

| Output | Birthdays | Personal-event dates |
|---|---|---|
| Realistic pseudonymization, legal mode (default) | fully replaced 92.7% / 95.1% | kept 96.6% / 97.5% |
| Realistic pseudonymization, general mode | fully replaced 92.7% / 95.1% | fully replaced 93.2% / 94.1% |
| Code pseudonymization | year only 92.7% / 95.1% | kept 96.6% / 97.5% |
| Anonymization | year only 92.7% / 95.1% | year and month only 93.2% / 94.1% |

## Scope and known limitations

**Scope**: Traditional Chinese documents from Taiwan. Japanese text (names written only in katakana, 株式会社, Japanese addresses, Japanese era dates) is out of scope.

**Detection will miss things and make mistakes** (limits of the model, see the tables above); always check by hand before sharing:

- People referred to only by given name or nickname in chats are often missed.
- Address boundaries are hard to get exactly right (addresses fully replaced in the synthetic set: 91% for 6-layer, 90% for 3-layer).
- Names of lawyers or judges that appear on their own, without a title, in page headers or lists are sometimes treated as names to replace.
- Very long URLs (over about 220 characters) are sometimes missed entirely.
- Firms (law, accounting and land-administration offices), some chain stores and state-owned companies are often kept even when they are a party or a party's employer.

**Design trade-offs** (working as designed; good to know before use):

- Anonymization only handles the direct and indirect identifiers listed above; ages, occupations, schools, family relationships, details of events, and the type, industry and city words kept in company names (顧問 in A顧問股份有限公司) are not handled.
- When several people share a surname, a reference by surname alone (陳小姐) cannot be tied to one person and becomes 〇小姐.
- Codes are consistent only within one `Anonymizer` or one command; across separate batches, 甲 in one batch is not the same person as 甲 in another. When `Anonymizer.anonymize()` is called document by document and a later document already uses a code assigned earlier, that person gets a new code in that document and a warning is issued; process a batch with `anonymize_many()` or the command line instead.
- With a shared case mapping (`--map`), if a fake name from an earlier document happens to be a real name in a later one, that entry is disabled and later documents use a new fake name; restore AI replies about each document with that document's own mapping file.

When restoring AI replies with the code version, these forms are handled as follows:

| Form | Restored? | Examples |
|---|---|---|
| A lone code that forms an ordinary word with the characters around it | No | 甲方, 甲說, 甲級 |
| A lone company letter | Only after a party reference | 被告A, （下稱A） |
| A公司, and a party reference followed by a company type or industry word | When the brand can be separated from the name, only the letter goes back to the brand and the rest stays | A公司 → 澄嶼公司, 被告A科技 → 被告澄嶼科技, 被告A集團 |
| A letter that forms an ordinary word with the next character | No | A棟, A咖, X光; 維生素A and A/B測試 are left alone too |
| Values reduced to a year, a month or a city | No (the details are gone) | 民國71年 |
| A token such as 〔電話1〕 rewritten in some other form | Cannot be restored | — |

## How it works

1. **Candidates (program)**: possible name spans from a surname list (Ministry of the Interior) and titles; personal data such as national IDs, phone numbers, account numbers, emails, URLs, addresses (Ministry of the Interior road names) and dates; names of companies, shops, communities and schools, plus listed-company short names. The program over-generates on purpose and makes no decisions.
2. **Decisions (model)**: each text window goes through the model once, which decides *replace / keep / ignore* for every candidate in it. The model is fine-tuned from bert-base-chinese and distilled from 12 layers into 6 and 3 layers, running on CPU through ONNX.
3. **Replacement (program)**: realistic fakes, or codes and generalization by type (pseudonymization, masking and generalization in the terms of ISO/IEC 20889); consistent across the document, and other spellings of the same value elsewhere are replaced too.

Training data: public court judgments (the names of parties, representatives, judges, clerks and others listed in each judgment are first replaced consistently with fake names), synthetic legal documents, and programmatic augmentation, about 50,000 documents in all; the training data is not published.

## Training on your own data

All the training code is public, so you can train on documents you have annotated yourself. Before you start:

| Item | Details |
|---|---|
| Hardware | Training runs only on Apple Silicon (MLX); once exported to ONNX, the model runs on any CPU |
| Starting point | The released weights are ONNX for inference and cannot be trained further; training starts from bert-base-chinese |
| Data | Our training data is not published, so you need your own annotated documents (format below); the code that builds our data is in the repository, but its inputs are not: a local cache database (SQLite) of public court judgments, and the annotated drafts of our fictional synthetic documents |
| Personal data | If the documents you annotate come from real cases, they are personal data themselves: process them only on your own machines, never upload them or paste them into an issue, and make sure you have a lawful basis for processing them |
| Time | With our roughly 50,000 documents, each model (12, 6 and 3 layers) takes about 30–35 minutes on an Apple M5 Max |

Run from the repository root:

```bash
python -m venv .venv && .venv/bin/pip install -e ".[train]"                  # training (MLX)
python -m venv .venv-export && .venv-export/bin/pip install -e ".[export]"  # ONNX export (PyTorch)
# download google-bert/bert-base-chinese to base/bert-base-chinese; if it only has pytorch_model.bin, first run
#   .venv-export/bin/python -m taiwan_legal_deid.convert_base base/bert-base-chinese
# save your data as data/train/synth_docs.jsonl (the file name is fixed)
.venv/bin/python -m taiwan_legal_deid.train --base base/bert-base-chinese --out runs/base --epochs 3   # train the 12-layer model first
.venv/bin/python -m taiwan_legal_deid.train --base base/bert-base-chinese --out runs/g6 --teacher runs/base --layers 0,1,2,3,4,5 --lr-enc 1e-4 --epochs 4   # distill into 6 layers (3 layers: --out runs/g3 --layers 0,1,2)
.venv-export/bin/python -m taiwan_legal_deid.export_onnx runs/g6             # export to ONNX
taiwan-legal-deid complaint.txt --model runs/g6                              # use your model; in Python, Detector("runs/g6")
```

The data has one JSON document per line (the content is fictional):

```json
{"id": "doc-001", "text": "原告陳美玲，民國71年3月8日生，手機 0912-345-678，113年5月2日到職。被告訴訟代理人王大同律師。", "spans": [{"start": 2, "end": 5, "label": "MASK", "group": "person"}, {"start": 6, "end": 15, "label": "MASK", "group": "pii"}, {"start": 20, "end": 32, "label": "MASK", "group": "pii"}, {"start": 33, "end": 41, "label": "KEEP", "group": "pii"}, {"start": 51, "end": 54, "label": "KEEP", "group": "person"}], "annot": ["person", "pii"]}
```

| Field | Contents |
|---|---|
| `id` | A unique document ID; the training code holds out 10% of documents for validation based on the ID |
| `text` | The original text |
| `spans` | One entry per annotation: `start` and `end` are character offsets (`end` exclusive); `label` is `MASK` (replace) or `KEEP` (keep); `group` is `person` (names), `pii` (other personal data) or `org` (organizations) |
| `annot` | The groups annotated completely in this document. In a listed group, every candidate without an annotation is treated as *ignore*; for groups not listed, only the annotated values are used |

Annotation rules:

| Value | How to annotate |
|---|---|
| Names | Mark only the name itself (王大同, without 律師); private persons such as parties and witnesses are `MASK`, people acting in an official role are `KEEP` |
| Dates | Birthdays and other identity dates are `MASK`; personal-event dates (start of employment, hospital visits and so on) are `KEEP` (replaced in general mode, left alone in legal mode); dates unrelated to a person, such as court dates, are not annotated |
| Organizations | Private companies are `MASK`, government agencies are `KEEP` |
| Boundaries | An annotation must cover exactly the same span as a candidate listed by the program; candidates with different boundaries are treated as *ignore* |

After training, `python eval/reproduce.py --model runs/g6` measures your model on the same test sets. See [`AGENTS.md`](https://github.com/lawchat-oss/taiwan-legal-deid/blob/main/AGENTS.md) for command and option details.

## Enterprise deployment & customization

The open-source version is general-purpose, with all features and models fully open. If your organization needs help with any of the following, email support@lawchat.com.tw (subject: 「去識別化導入」 / "De-identification deployment"):

| Need | What it covers |
|---|---|
| Deployment | Install it on your own machines and connect it to your existing workflow (for example, de-identify automatically before text goes to an external AI, and restore the reply afterwards) |
| Evaluation | Measure actual performance on your own sample documents, on your own machines |
| Customization | Tune the model for your document types, or add categories to handle |

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

Custom models are not in this repository and are offered under a separate commercial license; the licenses of this repository's code (MIT) and model weights (Apache-2.0) are unchanged.

## Disclaimer

**No warranty.** The code (MIT) and the model weights (Apache-2.0) are provided "as is", without warranty of any kind, express or implied. To the extent permitted by law, the maintainers are not liable for any damage arising from the use of this tool or its results.

This tool helps reduce the risk of personal data leaking from documents. It does not guarantee that all personal data is found, and it is not legal advice. Decide for yourself, and check by hand, whether a document can be shared, uploaded or published; you remain responsible for complying with personal data protection laws.

## Citation

See `CITATION.cff`.
