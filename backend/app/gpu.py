"""Make pip-installed NVIDIA libraries (cuBLAS, cuDNN) visible to CTranslate2 on Windows.

`pip install nvidia-cublas-cu12 nvidia-cudnn-cu12` drops the DLLs inside
site-packages/nvidia/*/bin, which Windows won't search by default.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_done = False


def register_cuda_dlls() -> list[str]:
    global _done
    if _done or sys.platform != "win32":
        return []
    _done = True
    added = []
    for sp in map(Path, sys.path):
        root = sp / "nvidia"
        if not root.is_dir():
            continue
        for bin_dir in root.glob("*/bin"):
            os.add_dll_directory(str(bin_dir))
            os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")
            added.append(str(bin_dir))
    return added
