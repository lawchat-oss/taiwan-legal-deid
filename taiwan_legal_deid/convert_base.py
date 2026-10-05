"""HF pytorch_model.bin → model.safetensors（MLX 讀）。一律 ascontiguousarray，寫完拿原始檔逐鍵讀回比對：
safetensors.numpy.save_file 遇到非連續陣列會靜默寫錯（形狀不變、值被打亂），P327 就踩過。
用法：.venv-export/bin/python -m taiwan_legal_deid.convert_base base/rbt3
"""
import os, sys

import numpy as np
import torch
from safetensors.numpy import load_file, save_file

d = sys.argv[1]
sd = torch.load(os.path.join(d, "pytorch_model.bin"), map_location="cpu", weights_only=True)
out = {k: np.ascontiguousarray(v.float().numpy()) for k, v in sd.items() if v.dtype.is_floating_point}
save_file(out, os.path.join(d, "model.safetensors"))
back = load_file(os.path.join(d, "model.safetensors"))
bad = [k for k, v in sd.items() if v.dtype.is_floating_point and not np.array_equal(back[k], v.float().numpy())]
assert not bad, f"讀回與原始檔不一致：{bad[:5]}"
print(f"{d}：{len(out)} 個張量，讀回與原始檔逐鍵一致")
