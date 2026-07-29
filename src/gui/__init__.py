"""txt2epub 的 Tkinter GUI 子包。

本包是一个「编排 + 展示」外壳：所有转换能力均来自内核
`src.txt2epub.Txt2Epub.create_epub`，GUI 不重写任何转换逻辑。
可通过 `from src.gui import GUIApp` 引用，也可通过 `python -m src.gui` 启动。
"""

from .app import GUIApp, main

__all__ = ["GUIApp", "main"]
