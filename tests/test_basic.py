"""不連網的基本測試：各模組自檢、權重下載（用本機檔案假裝 Release）。有下載好的模型時另測偵測。
執行：pip install -e . pytest && pytest
"""
import hashlib, os, re, runpy, warnings

import pytest

from taiwan_legal_deid import weights


@pytest.mark.filterwarnings("ignore::RuntimeWarning")  # runpy：模組已被別的測試載入過
@pytest.mark.parametrize("mod", ["candidates", "pii_candidates", "org_candidates", "examples", "obfuscate", "codes", "fakes", "ocr_noise"])
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
    from taiwan_legal_deid import Anonymizer, Detector, Obfuscator, restore
    text = "原告林郁婷（手機 0912-345-678）與被告岱昀顧問股份有限公司間給付工資事件，法官王大同。"
    det = Detector()
    fake, mapping = Obfuscator(det, seed=0).pseudonymize(text)
    assert "林郁婷" not in fake and "0912-345-678" not in fake and "岱昀" not in fake and "法官王大同" in fake, fake
    assert restore(fake, mapping) == text
    fake, mapping = Obfuscator(det, style="code").pseudonymize(text)
    assert fake == "原告甲（手機 〔電話1〕）與被告A公司間給付工資事件，法官王大同。", fake
    assert restore("甲可向A公司請求，〔電話1〕。", mapping) == "林郁婷可向岱昀顧問股份有限公司請求，0912-345-678。"
    assert Anonymizer(det).anonymize(text) == fake


class _FakeDet:
    """不用模型的偵測器：名字、手機用固定規則找（測替換、CLI 用）。"""
    def __init__(self, *a, **k):
        pass

    def detect(self, text):
        out = [{"start": m.start(), "end": m.end(), "type": "PERSON", "kind": "full"} for m in re.finditer("林志強|陳美玲", text)]
        return out + [{"start": m.start(), "end": m.end(), "type": "NUMBER"} for m in re.finditer(r"09\d{2}-\d{3}-\d{3}", text)]


def test_anonymize_alias_warns():
    from taiwan_legal_deid import Obfuscator
    text = "證人林志強（0912-345-678）到庭。"
    new = Obfuscator(_FakeDet(), seed=3).pseudonymize(text)
    with pytest.warns(FutureWarning, match="pseudonymize"):
        old = Obfuscator(_FakeDet(), seed=3).anonymize(text)
    assert old == new and old[1]  # 舊名稱行為不變：照樣回傳對照表


def test_cli_anonymize(tmp_path, monkeypatch, capsys):
    from taiwan_legal_deid import cli, detect_onnx
    monkeypatch.setattr(detect_onnx, "Detector", _FakeDet)
    a, b = tmp_path / "a.txt", tmp_path / "b.txt"
    a.write_text("證人林志強（0912-345-678）與陳美玲到庭。", encoding="utf-8")
    b.write_text("甲方乙方約定：林志強負責。", encoding="utf-8")  # 原文已經有甲、乙：整批從丙開始編
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        cli.main([str(a), str(b), "--anonymize"])
    assert sorted(os.listdir(tmp_path)) == ["a.txt", "a.txt.anon.txt", "b.txt", "b.txt.anon.txt"]  # 沒有任何對照表
    assert (tmp_path / "a.txt.anon.txt").read_text(encoding="utf-8") == "證人丙（〔電話1〕）與丁到庭。"
    assert (tmp_path / "b.txt.anon.txt").read_text(encoding="utf-8") == "甲方乙方約定：丙負責。"
    for args in ([str(a), "--anonymize", "--map", str(tmp_path / "case.json")], [str(a), str(b)]):
        with pytest.raises(SystemExit):
            cli.main(args)


def test_extend_long():
    from taiwan_legal_deid.decode import extend_long
    url = "https://example.com/" + "a" * 250 + "&private=chen"  # 比一個視窗還長
    text = "網址 " + url + " 結束"
    s = text.index("https")
    spans = [{"start": s + 230, "end": s + len(url), "type": "HANDLE", "kind": "handle", "score": 0.9, "p_mask": 0.9}]
    out = extend_long(text, spans)  # 模型只判到後段：延伸成整個網址
    assert [(x["start"], x["end"], x["type"]) for x in out] == [(s, s + len(url), "URL")]
    assert extend_long(text, []) == []  # 沒被判定要換的不會變成要換
