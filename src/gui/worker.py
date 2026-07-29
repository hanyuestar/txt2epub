"""后台转换执行单元。

`ConversionWorker` 在独立线程中逐文件调用内核
`Txt2Epub.create_epub`，并通过 `queue.Queue` 向主线程回报进度。
**本模块严禁访问任何 Tkinter 对象**——所有 UI 更新都发生在主线程的
`poll_queue` 中，保证 Tkinter 只在主线程安全操作（GUI-010）。
"""

from __future__ import annotations

import threading
from pathlib import Path
from queue import Queue
from typing import Iterable, List, Tuple

from .models import (
    DEFAULT_OVERWRITE,
    ConversionSummary,
    FileItem,
    ProgressMessage,
)
# 复用内核：GUI 是 `src.gui` 子包，故用 `..` 回到 `src` 包再取内核模块
from ..txt2epub import Txt2Epub


# 内核失败判定：抛这些异常，或返回 False，均视为该文件失败。
# 单文件失败不阻断其余文件（GUI-011）。FileNotFoundError 是 OSError 的子类，
# 因此输入文件不存在也会被此处捕获并记录为失败。
_CONVERT_EXCEPTIONS = (ValueError, FileExistsError, OSError, UnicodeError)


class ConversionWorker(threading.Thread):
    """逐文件调用内核的转换工作线程。"""

    def __init__(
        self,
        file_items: Iterable[FileItem],
        output_dir: Path,
        queue: Queue,
        overwrite: bool = DEFAULT_OVERWRITE,
    ) -> None:
        """初始化工作线程。

        Args:
            file_items: 待转换文件条目集合。
            output_dir: 统一输出目录；文件名固定为 ``输入stem.epub``。
            queue: 主线程传入的进度队列，用于回报进度/汇总。
            overwrite: 是否覆盖已存在输出；默认 True（重跑即重生成）。
        """
        super().__init__(daemon=True)
        # 转成列表，避免迭代器被重复消费；index 从 1 开始更符合用户直觉
        self.file_items: List[FileItem] = list(file_items)
        self.output_dir: Path = Path(output_dir)
        self.queue: Queue = queue
        self.overwrite: bool = overwrite

    def run(self) -> None:
        """线程入口：遍历文件、转换、逐条回报，最后回报汇总。"""
        # 防御性创建输出目录：内核先将临时文件写入输出目录再替换目标，
        # 父目录不存在会触发 OSError，这里提前确保存在。
        self.output_dir.mkdir(parents=True, exist_ok=True)

        total = len(self.file_items)
        summary = ConversionSummary(total=total)

        for index, item in enumerate(self.file_items, start=1):
            ok, error = self.convert_one(item)
            if ok:
                summary.success_count += 1
            else:
                summary.fail_count += 1
                summary.add_failure(item.name, error)
            # 逐文件回报进度（主线程据此更新进度条/当前文件名/计数）
            self.queue.put(
                ProgressMessage.make_progress(
                    index=index,
                    total=total,
                    filename=item.name,
                    ok=ok,
                    error=error,
                )
            )

        # 全部结束，回报汇总消息（type="summary"）
        self.queue.put(ProgressMessage.make_summary(summary))

    def convert_one(self, item: FileItem) -> Tuple[bool, str]:
        """转换单个文件，返回 ``(是否成功, 错误原因)``。

        成功返回 ``(True, "")``；失败返回 ``(False, 原因)``。**绝不向外抛异常**，
        保证单文件失败不影响其余文件（GUI-011）。失败文件不会产生残缺 epub
        （内核为原子写入，PRD §5④）。

        输出文件名由 GUI 显式指定为 ``输出目录 / (输入stem + ".epub")``，
        不依赖内核「写到输入同目录」的缺省行为。
        """
        output_file = self.output_dir / (item.path.stem + ".epub")
        try:
            created = Txt2Epub.create_epub(
                input_file=item.path,
                output_file=output_file,
                overwrite=self.overwrite,
            )
        except _CONVERT_EXCEPTIONS as exc:
            return False, str(exc)

        if created is False:
            return False, "转换未产生输出文件（内核返回 False）"
        return True, ""
