"""GUI 启动入口。

同时被 `python -m src.gui` 与 PyInstaller spec 作为程序入口引用。
`src/__main__.py`（CLI）保持完全不变。

PyInstaller `-F` 单文件模式下，本文件被抽取为顶层脚本执行，没有
`__package__`，因此**不能**使用 `from .app import main` 之类的相对导入
（会报 `ImportError: attempted relative import with no known parent package`）。
这里显式把项目根加入 `sys.path` 并改用绝对导入 `from src.gui.app import main`，
既能避开 PyInstaller 的坑，也兼容开发模式 `python -m src.gui`。
`app.py` / `worker.py` 内部仍使用包内相对导入——它们通过绝对 import
被加载后 `__package__="src.gui"`，相对导入正常工作。
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))              # .../src/gui
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_HERE))         # .../  (项目根，含 src/)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.gui.app import main  # noqa: E402

if __name__ == "__main__":
    main()
