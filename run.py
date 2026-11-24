#!/usr/bin/env python3
"""命令行启动脚本。

显式把脚本所在目录加入 sys.path，使 `python3 -I run.py ...`
在隔离模式（忽略 PYTHONPATH 与当前目录）下也能导入本地 apprenticeship 包。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from apprenticeship.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
