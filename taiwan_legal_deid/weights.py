"""模型權重：第一次用到時從 GitHub Release（weights-v1）下載，驗 sha256 後存在本機，之後不再連網。
- 存放位置：環境變數 TAIWAN_LEGAL_DEID_HOME；沒設就用 $XDG_CACHE_HOME/taiwan-legal-deid（預設 ~/.cache/taiwan-legal-deid）。
- 離線：TAIWAN_LEGAL_DEID_OFFLINE=1 時一律不連網，檔案不在就報錯。
  先在有網路的機器執行 taiwan-legal-deid --download，再把整個資料夾複製到同一個位置（或用 TAIWAN_LEGAL_DEID_HOME 指過去）。
權重授權：Apache-2.0（見 LICENSES/Apache-2.0.txt）。
"""
from __future__ import annotations

import hashlib, http.client, os, sys, tempfile, time, urllib.error, urllib.request

RELEASE = "https://github.com/lawchat-oss/taiwan-legal-deid/releases/download/weights-v1"
MODELS = {  # 名稱 → (檔名, sha256)
    "6l": ("model-6l.onnx", "13d03c7be03d85626b69a4bedd8834085298ca45fb428152aa2b7e13695fef83"),  # 6 層：預設，較準
    "3l": ("model-3l.onnx", "7b6cdebd991389cad6e5ab4f9d8d000ce6cf47a75c573805cc0e0770875144aa"),  # 3 層：較快
}
N_KINDS = 19  # weights-v1 認得的候選來源類型數（labels.KINDS 前 19 種）


class DownloadError(RuntimeError):
    """模型下載失敗（網路中斷、逾時、檔案的 sha256 不符）。訊息是一行說明，指令列直接顯示。"""


def home() -> str:
    return os.environ.get("TAIWAN_LEGAL_DEID_HOME") or os.path.join(
        os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache"), "taiwan-legal-deid")


def path(name: str = "6l") -> str:
    """模型檔的本機路徑；還沒有就下載（離線模式除外）。"""
    fname, sha = MODELS[name]
    p = os.path.join(home(), "weights-v1", fname)
    if os.path.exists(p):
        return p
    if os.environ.get("TAIWAN_LEGAL_DEID_OFFLINE", "") not in ("", "0"):
        raise FileNotFoundError(f"離線模式找不到模型 {p}：請先在有網路的機器執行 taiwan-legal-deid --download --model {name}，再把檔案複製過來")
    _download(f"{RELEASE}/{fname}", p, sha)
    return p


def _download(url: str, dest: str, sha: str, tries: int = 3) -> None:
    """下載到同資料夾的暫存檔（GitHub 會轉址到 objects.githubusercontent.com，urllib 會跟著走），sha256 對了才改名成正式檔。
    網路中斷、逾時、檔案不完整都自動重試；都失敗丟 DownloadError（一行說明，不留半個檔案）。"""
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    for i in range(tries):
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(dest), suffix=".part")
        h = hashlib.sha256()
        try:
            with os.fdopen(fd, "wb") as f, urllib.request.urlopen(url, timeout=60) as r:
                print(f"下載模型 {url}（{int(r.headers.get('Content-Length') or 0) / 1e6:.0f} MB）→ {dest}", file=sys.stderr)
                while chunk := r.read(1 << 20):
                    f.write(chunk); h.update(chunk)
            if h.hexdigest() == sha:
                os.replace(tmp, dest)
                return
            err = f"模型檔 sha256 不符（{h.hexdigest()}）"
        except urllib.error.HTTPError as e:
            if 400 <= e.code < 500:  # 網址不對（404）：重試也沒用
                raise DownloadError(f"模型下載失敗（HTTP {e.code}）：{url}") from e
            err = f"HTTP {e.code}"
        except (OSError, http.client.HTTPException) as e:  # 網路中斷、逾時（URLError、TimeoutError、ConnectionError 都是 OSError）
            err = str(e) or type(e).__name__
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
        if i < tries - 1:
            print(f"下載中斷（{err}），{2 ** i} 秒後重試…", file=sys.stderr)
            time.sleep(2 ** i)
    raise DownloadError(f"模型下載失敗（{err}）：請確認網路後重新執行；一直失敗請回報")
