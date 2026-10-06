"""台灣法律文件去識別化：程式列出候選，模型判斷要遮／保留／不是，再換掉。三種輸出：

    from taiwan_legal_deid import Detector, Obfuscator, Anonymizer, restore
    det = Detector()                                       # 預設 6 層；Detector("3l") 較快；第一次用時下載模型
    fake, mapping = Obfuscator(det).pseudonymize(text)     # 假名化：擬真假名＋對照表（留在自己電腦）
    restore(ai_reply, mapping)                             # AI 回覆換回原文
    fake, mapping = Obfuscator(det, style="code").pseudonymize(text)  # 假名化的代號版：甲、A公司、〔號碼1〕＋對照表
    anon = Anonymizer(det).anonymize(text)                 # 匿名化：代號、不留對照表，無法還原
"""
__version__ = "0.2.1"


def __getattr__(name):  # 用到才載入：訓練、匯出環境不必裝 onnxruntime，python -m taiwan_legal_deid.<模組> 也不會載入兩次
    if name == "Detector":
        from .detect_onnx import Detector
        return Detector
    if name in ("Obfuscator", "restore", "restore_exact"):
        from . import obfuscate
        return getattr(obfuscate, name)
    if name in ("Anonymizer", "CodeObfuscator"):
        from . import codes
        return getattr(codes, name)
    raise AttributeError(name)
