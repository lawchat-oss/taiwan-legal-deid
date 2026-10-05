"""台灣法律文件去識別化：程式列出候選，模型判斷要遮／保留／不是，再換成擬真假名並留對照表可還原。

    from taiwan_legal_deid import Detector, Obfuscator, restore
    ob = Obfuscator(Detector())          # 預設 6 層；Detector("3l") 較快；第一次用時下載模型
    fake, mapping = ob.anonymize(text)   # 假名版文字、對照表（留在自己電腦）
    restore(ai_reply, mapping)           # AI 回覆換回原文
"""
__version__ = "0.1.0"


def __getattr__(name):  # 用到才載入：訓練、匯出環境不必裝 onnxruntime，python -m taiwan_legal_deid.<模組> 也不會載入兩次
    if name == "Detector":
        from .detect_onnx import Detector
        return Detector
    if name in ("Obfuscator", "restore", "restore_exact"):
        from . import obfuscate
        return getattr(obfuscate, name)
    raise AttributeError(name)
