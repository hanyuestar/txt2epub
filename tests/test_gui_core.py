"""GUI 核心模块（models / worker / app 过滤）独立 headless 测试 — QA 严过关补充。

设计原则：
- 不依赖 Tkinter 窗口（不实例化 `GUIApp`）。`src.gui.app` 在 import 时仅定义类，
  不创建 Tk 根窗口，因此可安全 import 以测试纯函数 `scan_txt_files`。
- worker 行为测试分两类：
  1. 真实转换（少量、覆盖端到端正确性 + 输出文件存在/非空/可被 ebooklib 读回）；
  2. spy/stub 注入（`Txt2Epub.create_epub` 打桩），快速且精确验证调用参数与
     各种失败路径，避免逐个真实写大文件。
- 全部可在无显示环境下 `python -m pytest tests/test_gui_core.py` 运行。
"""

import queue
import tempfile
from pathlib import Path
from unittest import mock

from ebooklib import epub as ebooklib_epub

import src.gui.app as gui_app
import src.gui.worker as gui_worker
from src.gui.models import (
    DEFAULT_OVERWRITE,
    GUI_TITLE,
    POLL_INTERVAL_MS,
    SCAN_RECURSIVE,
    TXT_SUFFIX,
    ConversionSummary,
    FileItem,
    FileStatus,
    ProgressMessage,
    status_text,
)
from src.gui.worker import ConversionWorker


# --------------------------------------------------------------------------- #
# 模块导入回归
# --------------------------------------------------------------------------- #
class TestGuiAppImportable:
    def test_app_module_imports_without_tk_window(self):
        # import 本身不应创建 Tk 根窗口（headless 安全）
        assert hasattr(gui_app, "GUIApp")
        assert hasattr(gui_app, "main")
        # 文件过滤纯函数已被抽出，可供 headless 测试
        assert hasattr(gui_app, "scan_txt_files")


# --------------------------------------------------------------------------- #
# models.py — 常量与枚举
# --------------------------------------------------------------------------- #
class TestModelsConstants:
    def test_constants(self):
        assert DEFAULT_OVERWRITE is True
        assert TXT_SUFFIX == ".txt"
        assert GUI_TITLE == "txt2epub 转换器"
        assert SCAN_RECURSIVE is False
        assert isinstance(POLL_INTERVAL_MS, int) and POLL_INTERVAL_MS > 0


class TestFileStatusEnum:
    def test_status_constants(self):
        assert FileStatus.PENDING == "pending"
        assert FileStatus.CONVERTING == "converting"
        assert FileStatus.DONE == "done"
        assert FileStatus.FAILED == "failed"


class TestStatusText:
    def test_known_statuses(self):
        assert status_text(FileStatus.PENDING) == "待转换"
        assert status_text(FileStatus.CONVERTING) == "转换中"
        assert status_text(FileStatus.DONE) == "成功"
        assert status_text(FileStatus.FAILED) == "失败"

    def test_unknown_passthrough(self):
        assert status_text("weird") == "weird"
        assert status_text("") == ""


# --------------------------------------------------------------------------- #
# models.py — FileItem
# --------------------------------------------------------------------------- #
class TestFileItem:
    def test_defaults(self):
        item = FileItem(path=Path("/tmp/a.txt"))
        assert item.name == "a.txt"
        assert item.selected is True
        assert item.status == FileStatus.PENDING
        assert isinstance(item.path, Path)

    def test_custom_fields(self):
        item = FileItem(path=Path("x.txt"), selected=False, status=FileStatus.DONE)
        assert item.selected is False
        assert item.status == FileStatus.DONE

    def test_name_property_keeps_suffix(self):
        assert FileItem(path=Path("dir/sub/novel_01.txt")).name == "novel_01.txt"


# --------------------------------------------------------------------------- #
# models.py — ProgressMessage
# --------------------------------------------------------------------------- #
class TestProgressMessage:
    def test_defaults(self):
        m = ProgressMessage(type="progress")
        assert m.type == "progress"
        assert m.index == 0
        assert m.total == 0
        assert m.filename == ""
        assert m.ok is False
        assert m.error == ""
        assert m.summary is None

    def test_make_progress_happy(self):
        m = ProgressMessage.make_progress(2, 5, "b.txt", True)
        assert m.type == "progress"
        assert m.index == 2
        assert m.total == 5
        assert m.filename == "b.txt"
        assert m.ok is True
        assert m.error == ""

    def test_make_progress_with_error(self):
        m = ProgressMessage.make_progress(1, 3, "bad.txt", False, error="boom")
        assert m.ok is False
        assert m.error == "boom"

    def test_make_summary_attaches_summary(self):
        s = ConversionSummary(total=1)
        m = ProgressMessage.make_summary(s)
        assert m.type == "summary"
        assert m.summary is s


# --------------------------------------------------------------------------- #
# models.py — ConversionSummary
# --------------------------------------------------------------------------- #
class TestConversionSummary:
    def test_defaults(self):
        s = ConversionSummary()
        assert s.total == 0
        assert s.success_count == 0
        assert s.fail_count == 0
        assert s.failures == []

    def test_failure_list_is_per_instance(self):
        # 关键：dataclass default_factory 不应在实例间共享同一个 list
        a = ConversionSummary()
        b = ConversionSummary()
        a.add_failure("x.txt", "e")
        assert a.failures == [("x.txt", "e")]
        assert b.failures == []

    def test_add_failure(self):
        s = ConversionSummary(total=2)
        s.success_count = 1
        s.fail_count = 1
        s.add_failure("bad.txt", "boom")
        assert s.success_count == 1
        assert s.fail_count == 1
        assert s.failures == [("bad.txt", "boom")]


# --------------------------------------------------------------------------- #
# worker.py — 输出路径命名（spy 验证传参，而非依赖内核默认行为）
# --------------------------------------------------------------------------- #
class TestWorkerOutputNaming:
    def test_worker_passes_output_dir_stem_epub_to_create_epub(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            out_dir = tmp_path / "out"
            f1 = tmp_path / "小说一.txt"
            f2 = tmp_path / "novel_two.txt"
            f1.write_text("《小说一》\n\n第一章 开始\n\n正文。\n", encoding="utf-8")
            f2.write_text("《novel two》\n\nChapter 1\n\nbody\n", encoding="utf-8")
            items = [FileItem(path=f1), FileItem(path=f2)]
            q: "queue.Queue" = queue.Queue()
            with mock.patch.object(
                gui_worker.Txt2Epub, "create_epub", return_value=True
            ) as spy:
                ConversionWorker(
                    file_items=items,
                    output_dir=out_dir,
                    queue=q,
                    overwrite=DEFAULT_OVERWRITE,
                ).run()
                assert spy.call_count == 2
                calls = {c.kwargs["input_file"]: c.kwargs["output_file"] for c in spy.call_args_list}
                assert calls[f1] == out_dir / "小说一.epub"
                assert calls[f2] == out_dir / "novel_two.epub"
                # 确认并非内核「写到输入同目录」的缺省行为
                assert calls[f1] != f1.with_suffix(".epub")
                assert calls[f2] != f2.with_suffix(".epub")
                # 确认 overwrite 透传
                assert all(
                    c.kwargs["overwrite"] is DEFAULT_OVERWRITE
                    for c in spy.call_args_list
                )

    def test_output_dir_created_if_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            out_dir = tmp_path / "nested" / "out"
            f = tmp_path / "z.txt"
            f.write_text("《Z》\n\n第一章\n\n正文。\n", encoding="utf-8")
            q: "queue.Queue" = queue.Queue()
            with mock.patch.object(gui_worker.Txt2Epub, "create_epub", return_value=True):
                ConversionWorker(
                    file_items=[FileItem(path=f)],
                    output_dir=out_dir,
                    queue=q,
                    overwrite=True,
                ).run()
                assert out_dir.is_dir()


# --------------------------------------------------------------------------- #
# worker.py — 真实转换（端到端正确性）
# --------------------------------------------------------------------------- #
class TestWorkerRealConversion:
    def test_real_conversion_produces_nonempty_valid_epub(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            out_dir = tmp_path / "out"
            src_file = tmp_path / "demo.txt"
            src_file.write_text(
                "《演示》\n\n第一章 开场\n\n这是第一段正文。\n\n"
                "第二章 发展\n\n这是第二段正文。\n",
                encoding="utf-8",
            )
            items = [FileItem(path=src_file)]
            q: "queue.Queue" = queue.Queue()
            ConversionWorker(
                file_items=items,
                output_dir=out_dir,
                queue=q,
                overwrite=True,
            ).run()

            epub_path = out_dir / "demo.epub"
            assert epub_path.is_file()
            assert epub_path.stat().st_size > 0  # 非空，非残缺 epub

            # 真 EPUB：能用 ebooklib 读回，且包含章节文档项
            book = ebooklib_epub.read_epub(str(epub_path))
            item_ids = [it.get_id() for it in book.get_items()]
            assert any(item_ids)

            msgs = _drain(q)
            assert msgs[-1].type == "summary"
            assert msgs[-1].summary.success_count == 1
            assert msgs[-1].summary.fail_count == 0
            assert (out_dir / "demo.epub").stat().st_size > 0


# --------------------------------------------------------------------------- #
# worker.py — 失败路径（spy 注入异常 / 返回 False）
# --------------------------------------------------------------------------- #
class TestWorkerFailureHandling:
    def test_missing_file_is_captured_as_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            out_dir = tmp_path / "out"
            missing = tmp_path / "ghost.txt"
            items = [FileItem(path=missing)]
            q: "queue.Queue" = queue.Queue()
            with mock.patch.object(
                gui_worker.Txt2Epub,
                "create_epub",
                side_effect=FileNotFoundError("no such file"),
            ) as spy:
                ConversionWorker(
                    file_items=items,
                    output_dir=out_dir,
                    queue=q,
                    overwrite=True,
                ).run()
                assert spy.call_count == 1
                msgs = _drain(q)
                progress = [m for m in msgs if m.type == "progress"]
                assert len(progress) == 1
                assert progress[0].ok is False
                assert "no such file" in progress[0].error
                summary = msgs[-1].summary
                assert summary.total == 1
                assert summary.success_count == 0
                assert summary.fail_count == 1
                assert summary.failures == [("ghost.txt", progress[0].error)]
                # 失败文件不应产生残缺 epub
                assert not (out_dir / "ghost.epub").exists()

    def test_various_convert_exceptions_caught(self):
        for exc in (
            ValueError("bad value"),
            FileExistsError("exists"),
            OSError("os err"),
            UnicodeError("unicode"),
        ):
            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp)
                out_dir = tmp_path / "out"
                f = tmp_path / "x.txt"
                f.write_text("《X》\n\n第一章\n\n正文。\n", encoding="utf-8")
                items = [FileItem(path=f)]
                q: "queue.Queue" = queue.Queue()
                with mock.patch.object(
                    gui_worker.Txt2Epub, "create_epub", side_effect=exc
                ):
                    ConversionWorker(
                        file_items=items,
                        output_dir=out_dir,
                        queue=q,
                        overwrite=True,
                    ).run()
                    msgs = _drain(q)
                    progress = [m for m in msgs if m.type == "progress"]
                    assert progress[0].ok is False
                    assert progress[0].error == str(exc)
                    assert msgs[-1].summary.fail_count == 1

    def test_create_epub_returning_false_is_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            out_dir = tmp_path / "out"
            f = tmp_path / "y.txt"
            f.write_text("《Y》\n\n第一章\n\n正文。\n", encoding="utf-8")
            items = [FileItem(path=f)]
            q: "queue.Queue" = queue.Queue()
            with mock.patch.object(gui_worker.Txt2Epub, "create_epub", return_value=False):
                ConversionWorker(
                    file_items=items,
                    output_dir=out_dir,
                    queue=q,
                    overwrite=True,
                ).run()
                msgs = _drain(q)
                progress = [m for m in msgs if m.type == "progress"]
                assert progress[0].ok is False
                assert "未产生输出" in progress[0].error
                assert msgs[-1].summary.fail_count == 1


# --------------------------------------------------------------------------- #
# worker.py — 混合场景 + 消息序列 + 不变量
# --------------------------------------------------------------------------- #
class TestWorkerMixedAndSequence:
    def test_mixed_success_and_failure_invariant(self):
        # 真实转换：good 真实写出 epub；bad 文件不存在被捕获为失败。
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            out_dir = tmp_path / "out"
            good = tmp_path / "ok.txt"
            bad = tmp_path / "nope.txt"
            good.write_text("《OK》\n\n第一章\n\n正文。\n", encoding="utf-8")
            items = [FileItem(path=good), FileItem(path=bad)]

            q: "queue.Queue" = queue.Queue()
            ConversionWorker(
                file_items=items,
                output_dir=out_dir,
                queue=q,
                overwrite=True,
            ).run()
            msgs = _drain(q)
            progress = [m for m in msgs if m.type == "progress"]
            # 顺序正确：先成功 ok.txt，后失败 nope.txt
            assert [m.filename for m in progress] == ["ok.txt", "nope.txt"]
            assert [m.ok for m in progress] == [True, False]
            assert [m.index for m in progress] == [1, 2]
            assert [m.total for m in progress] == [2, 2]
            summary = msgs[-1].summary
            assert summary.total == 2
            assert summary.success_count == 1
            assert summary.fail_count == 1
            # 核心不变量：成功 + 失败 == 总数
            assert summary.success_count + summary.fail_count == summary.total
            assert summary.failures == [("nope.txt", progress[1].error)]
            # 成功文件有真实 epub；失败文件无残缺 epub（原子写入保证）
            assert (out_dir / "ok.epub").is_file()
            assert not (out_dir / "nope.epub").exists()

    def test_message_count_is_total_plus_one_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            out_dir = tmp_path / "out"
            files = []
            for i in range(4):
                f = tmp_path / f"f{i}.txt"
                f.write_text(f"《F{i}》\n\n第一章\n\n正文。\n", encoding="utf-8")
                files.append(FileItem(path=f))
            q: "queue.Queue" = queue.Queue()
            with mock.patch.object(gui_worker.Txt2Epub, "create_epub", return_value=True):
                ConversionWorker(
                    file_items=files,
                    output_dir=out_dir,
                    queue=q,
                    overwrite=True,
                ).run()
                msgs = _drain(q)
                # 4 条 progress + 1 条 summary
                assert len(msgs) == 5
                assert msgs[-1].type == "summary"
                assert [m.type for m in msgs[:-1]] == ["progress"] * 4

    def test_empty_items_still_emits_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            out_dir = tmp_path / "out"
            q: "queue.Queue" = queue.Queue()
            ConversionWorker(
                file_items=[],
                output_dir=out_dir,
                queue=q,
                overwrite=True,
            ).run()
            msgs = _drain(q)
            assert len(msgs) == 1
            assert msgs[0].type == "summary"
            assert msgs[0].summary.total == 0
            assert msgs[0].summary.success_count == 0
            assert msgs[0].summary.fail_count == 0


# --------------------------------------------------------------------------- #
# app.scan_txt_files — 选文件夹时的顶层 *.txt 过滤（headless）
# --------------------------------------------------------------------------- #
class TestScanTxtFiles:
    def test_only_top_level_txt_collected(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "a.txt").write_text("x")
            (folder / "b.txt").write_text("x")
            (folder / "c.md").write_text("x")  # 非 txt 忽略
            (folder / "notes.log").write_text("x")  # 非 txt 忽略
            (folder / "readme").write_text("x")  # 无后缀忽略
            sub = folder / "sub"
            sub.mkdir()
            (sub / "deep.txt").write_text("x")  # 子目录递归忽略
            found = gui_app.scan_txt_files(folder)
            names = sorted(p.name for p in found)
            assert names == ["a.txt", "b.txt"]

    def test_empty_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            assert gui_app.scan_txt_files(Path(tmp)) == []

    def test_case_insensitive_suffix(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "UP.TXT").write_text("x")
            (folder / "low.txt").write_text("x")
            found = gui_app.scan_txt_files(folder)
            assert sorted(p.name for p in found) == ["UP.TXT", "low.txt"]

    def test_dirs_are_not_collected(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "plain.txt").write_text("x")
            (folder / "looks_like_txt_dir.txt").mkdir()  # 同名但为目录
            found = gui_app.scan_txt_files(folder)
            assert [p.name for p in found] == ["plain.txt"]


# --------------------------------------------------------------------------- #
# 工具函数
# --------------------------------------------------------------------------- #
def _drain(q: "queue.Queue"):
    """排空队列，返回有序消息列表。"""
    msgs = []
    while not q.empty():
        msgs.append(q.get_nowait())
    return msgs
