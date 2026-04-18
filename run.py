"""一键启动入口。

零基础用户可以直接运行：
python run.py

它会自动启动 Streamlit 页面。
"""

from __future__ import annotations

import os
import random
import subprocess
import sys

import numpy as np

try:
    import torch
except Exception:  # pragma: no cover
    torch = None

random.seed(42)
np.random.seed(42)
if torch is not None:
    torch.manual_seed(42)


if __name__ == "__main__":
    cmd = [sys.executable, "-m", "streamlit", "run", "app/main.py"]
    env = os.environ.copy()
    subprocess.run(cmd, env=env, check=False)
