"""共用常數（不依賴 MLX，CPU 推論也用）。"""
LABELS = ("MASK", "KEEP", "NOT")  # 人名：要遮（私人）／保留（執行職務、公眾人物）／不是人名；日期：身分日期／個人行程日期／非個人；機構：要換／保留／不是機構名
PERSON_KINDS = ("full", "partial", "given", "translit", "latin", "given2", "nick")
PII_KINDS = ("date", "num", "alnum", "email", "url", "handle", "addr", "zi")
ORG_KINDS = ("org", "org_en", "org_q", "org_stem")
KINDS = PERSON_KINDS + PII_KINDS + ORG_KINDS  # 候選來源類型（順序只能往後加：舊 run 的 kind 嵌入靠位置）
GROUP = {k: ("person" if k in PERSON_KINDS else "org" if k in ORG_KINDS else "pii") for k in KINDS}
# 標記 → (標籤, 組)；DATE＝個人行程日期，用 KEEP 這格（一般模式照遮、法律模式保留）；ORGK＝公家機關、事務所、順帶提到的服務
TAGS = {"P": ("MASK", "person"), "K": ("KEEP", "person"), "DATE": ("KEEP", "pii"), "ORG": ("MASK", "org"), "ORGK": ("KEEP", "org"),
        **{t: ("MASK", "pii") for t in ("ID", "TEL", "MAIL", "URL", "ACCT", "SEC", "CAR", "HDL", "ADDR", "BIRTH")}}
# 輸出類型（給遮罩與報表用）：人名、機構看標籤；其他個資看候選來源
PII_TYPE = {"date": "DATE", "num": "NUMBER", "alnum": "CODE", "email": "EMAIL", "url": "URL", "handle": "HANDLE", "addr": "ADDRESS", "zi": "CODE"}
