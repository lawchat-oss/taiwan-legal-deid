"""不連網的基本測試：各模組自檢、權重下載（用本機檔案假裝 Release）。有下載好的模型時另測偵測。
執行：pip install -e . pytest && pytest
"""
import hashlib, os, runpy

import pytest

from taiwan_legal_deid import weights


@pytest.mark.filterwarnings("ignore::RuntimeWarning")  # runpy：模組已被別的測試載入過
@pytest.mark.parametrize("mod", ["candidates", "pii_candidates", "org_candidates", "examples", "obfuscate", "fakes", "ocr_noise"])
def test_selfcheck(mod):
    runpy.run_module(f"taiwan_legal_deid.{mod}", run_name="__main__")


def test_download(tmp_path, monkeypatch):
    rel = tmp_path / "release"
    rel.mkdir()
    (rel / "a.onnx").write_bytes(b"onnx")
    monkeypatch.setattr(weights, "RELEASE", rel.as_uri())
    monkeypatch.setattr(weights, "MODELS", {"ok": ("a.onnx", hashlib.sha256(b"onnx").hexdigest()), "bad": ("a.onnx", "0" * 64)})
    monkeypatch.setenv("TAIWAN_LEGAL_DEID_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("TAIWAN_LEGAL_DEID_OFFLINE", raising=False)
    with pytest.raises(RuntimeError):  # sha256 不符：報錯、不留檔
        weights.path("bad")
    assert os.listdir(tmp_path / "home" / "weights-v1") == []
    assert open(weights.path("ok"), "rb").read() == b"onnx"
    monkeypatch.setenv("TAIWAN_LEGAL_DEID_OFFLINE", "1")
    monkeypatch.setenv("TAIWAN_LEGAL_DEID_HOME", str(tmp_path / "empty"))
    with pytest.raises(FileNotFoundError):  # 離線模式不連網
        weights.path("ok")


@pytest.mark.skipif(not os.path.exists(os.path.join(weights.home(), "weights-v1", "model-6l.onnx")), reason="還沒下載模型")
def test_detect():
    from taiwan_legal_deid import Detector, Obfuscator, restore
    text = "原告林郁婷（手機 0912-345-678）與被告岱昀顧問股份有限公司間給付工資事件，法官王大同。"
    ob = Obfuscator(Detector(), seed=0)
    fake, mapping = ob.anonymize(text)
    assert "林郁婷" not in fake and "0912-345-678" not in fake and "岱昀" not in fake and "法官王大同" in fake, fake
    assert restore(fake, mapping) == text


def test_extend_long():
    from taiwan_legal_deid.decode import extend_long
    url = "https://example.com/" + "a" * 250 + "&private=chen"  # 比一個視窗還長
    text = "網址 " + url + " 結束"
    s = text.index("https")
    spans = [{"start": s + 230, "end": s + len(url), "type": "HANDLE", "kind": "handle", "score": 0.9, "p_mask": 0.9}]
    out = extend_long(text, spans)  # 模型只判到後段：延伸成整個網址
    assert [(x["start"], x["end"], x["type"]) for x in out] == [(s, s + len(url), "URL")]
    assert extend_long(text, []) == []  # 沒被判定要換的不會變成要換
