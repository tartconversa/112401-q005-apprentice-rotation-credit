"""测试共享引导：把项目根目录显式加入 sys.path，兼容 python3 -I 运行。"""
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SAMPLES = ROOT / "samples"
AS_OF = date(2026, 11, 25)
