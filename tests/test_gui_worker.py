"""GUI worker 与数据模型的 headless 自测（不依赖 Tkinter / 图形界面）。

验证重点：
1. `models.py` 纯数据结构构造正确。
2. `ConversionWorker` 逐文件调用内核、回报 `ProgressMessage` 序列、
   统计成功/失败、生成 ``stem.epub`` 输出，且单文件失败不阻断整体。
3. `worker` 不依赖任何 GUI 对象即可独立运行（注入真实 `queue.Queue`）。
"""

import queue
import tempfile
import unittest
from pathlib import Path

from src.gui.models import (
    DEFAULT_OVERWRITE,
    FileItem,
    FileStatus,
    ProgressMessage,
    ConversionSummary,
    status_text,
)
from src.gui.worker import ConversionWorker


def _make_valid_txt(path: Path, title: str) -> None:
    """写一个带章节标题的合法 TXT，确保内核能成功转换。"""
    path.write_text(
        f"《{title}》\n\n第一章 开始\n\n这是正文内容，用于测试转换。\n\n"
        "第二章 发展\n\n更多正文内容。\n",
        encoding="utf-8",
    )


class ModelsTests(unittest.TestCase):
    def test_file_item_defaults(self):
        item = FileItem(path=Path("/tmp/a.txt"))
        self.assertEqual(item.name, "a.txt")
        self.assertTrue(item.selected)
        self.assertEqual(item.status, FileStatus.PENDING)

    def test_status_text(self):
        self.assertEqual(status_text(FileStatus.DONE), "成功")
        self.assertEqual(status_text(FileStatus.FAILED), "失败")
        self.assertEqual(status_text("unknown"), "unknown")

    def test_progress_message_factories(self):
        p = ProgressMessage.make_progress(1, 3, "a.txt", True)
        self.assertEqual(p.type, "progress")
        self.assertTrue(p.ok)
        self.assertEqual(p.index, 1)
        self.assertEqual(p.total, 3)

        summary = ConversionSummary(total=1)
        s = ProgressMessage.make_summary(summary)
        self.assertEqual(s.type, "summary")
        self.assertIs(s.summary, summary)

    def test_conversion_summary(self):
        summary = ConversionSummary(total=2)
        summary.success_count += 1
        summary.fail_count += 1  # 失败计数由 worker 在记录失败时累加
        summary.add_failure("bad.txt", "boom")
        self.assertEqual(summary.success_count, 1)
        self.assertEqual(summary.fail_count, 1)
        self.assertEqual(summary.failures, [("bad.txt", "boom")])
        self.assertEqual(len(summary.failures), 1)


class WorkerTests(unittest.TestCase):
    def test_worker_runs_real_conversions_headlessly(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            out_dir = tmp_path / "out"
            # 两个合法文件（应成功）
            good_a = tmp_path / "novel_a.txt"
            good_b = tmp_path / "novel_b.txt"
            _make_valid_txt(good_a, "小说A")
            _make_valid_txt(good_b, "小说B")
            # 一个不存在的输入文件（应失败：FileNotFoundError 属 OSError 子类）
            missing = tmp_path / "missing.txt"

            items = [
                FileItem(path=good_a),
                FileItem(path=good_b),
                FileItem(path=missing),
            ]
            q: "queue.Queue" = queue.Queue()
            worker = ConversionWorker(
                file_items=items,
                output_dir=out_dir,
                queue=q,
                overwrite=DEFAULT_OVERWRITE,
            )

            # 直接调用 run() 同步执行（等价于 start()+join()，便于断言）
            worker.run()

            # 收集所有消息：每个文件一条 progress + 一条 summary
            messages = []
            while not q.empty():
                messages.append(q.get_nowait())

            self.assertEqual(len(messages), len(items) + 1)
            self.assertEqual(messages[-1].type, "summary")

            # 校验 progress 消息序列与统计
            progress_msgs = [m for m in messages if m.type == "progress"]
            self.assertEqual([m.index for m in progress_msgs], [1, 2, 3])
            self.assertEqual([m.total for m in progress_msgs], [3, 3, 3])
            self.assertEqual(
                [m.filename for m in progress_msgs],
                ["novel_a.txt", "novel_b.txt", "missing.txt"],
            )
            self.assertEqual([m.ok for m in progress_msgs], [True, True, False])
            self.assertTrue(progress_msgs[2].error)  # 失败消息带原因

            summary = messages[-1].summary
            self.assertEqual(summary.total, 3)
            self.assertEqual(summary.success_count, 2)
            self.assertEqual(summary.fail_count, 1)
            self.assertEqual(summary.failures, [("missing.txt", progress_msgs[2].error)])

            # 输出目录应生成两个 .epub，文件名 = stem
            self.assertTrue(out_dir.is_dir())
            self.assertTrue((out_dir / "novel_a.epub").is_file())
            self.assertTrue((out_dir / "novel_b.epub").is_file())
            # 失败文件不应产生残缺 epub
            self.assertFalse((out_dir / "missing.epub").exists())


if __name__ == "__main__":
    unittest.main()
