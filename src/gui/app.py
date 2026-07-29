"""GUI 主窗口控制器与启动入口。

`GUIApp` 是单窗口控制器（MVC-lite）：持有数据（文件列表、输出目录、队列、
worker）与全部事件处理，负责布局三大区（文件区 / 输出目录区 / 进度区）与
底部「确认转换」按钮，并编排 worker 启动与队列轮询。所有 UI 更新只在主线程
发生；worker 子线程只通过 `queue.Queue` 回报进度（GUI-010、§7）。
"""

from __future__ import annotations

import queue
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
import tkinter as tk

from .models import (
    DEFAULT_OVERWRITE,
    GUI_TITLE,
    POLL_INTERVAL_MS,
    TXT_SUFFIX,
    ConversionSummary,
    FileItem,
    FileStatus,
    ProgressMessage,
    status_text,
)
from .worker import ConversionWorker


def scan_txt_files(folder: Path) -> list[Path]:
    """扫描文件夹顶层，返回所有后缀为 `TXT_SUFFIX` 的普通文件（不递归）。

    抽成纯函数以便 headless 单元测试（GUI-002：仅顶层、非递归）。
    不依赖任何 Tkinter 对象，可独立调用与断言。
    """
    folder = Path(folder)
    return [
        p
        for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() == TXT_SUFFIX
    ]


class GUIApp(tk.Tk):
    """txt2epub 图形界面主窗口。"""

    def __init__(self) -> None:
        """初始化窗口与三大区布局，并禁用「确认转换」直到条件满足。"""
        super().__init__()
        self.title(GUI_TITLE)

        # ---- 控制器持有的数据 ----
        self.file_items: list[FileItem] = []
        self.output_dir: Path | None = None
        self.progress_queue: queue.Queue | None = None
        self.worker: ConversionWorker | None = None
        # 转换期间锁定输入控件；re-render 列表时据此禁用「移除」按钮
        self._input_locked: bool = False

        self.build_layout()
        self.refresh_controls()

    # ------------------------------------------------------------------ #
    # 布局
    # ------------------------------------------------------------------ #
    def build_layout(self) -> None:
        """构建「文件区 / 输出目录区 / 进度区 + 确认转换」四大区块。"""
        self._build_menu()

        # ① 文件选择区 -------------------------------------------------- #
        file_frame = ttk.LabelFrame(self, text="① 文件选择区", padding=8)
        file_frame.pack(fill="both", expand=True, padx=10, pady=(10, 4))

        button_row = ttk.Frame(file_frame)
        button_row.pack(fill="x")
        self.select_files_btn = ttk.Button(
            button_row, text="选择文件...", command=self.on_select_files
        )
        self.select_files_btn.pack(side="left")
        self.select_folder_btn = ttk.Button(
            button_row, text="选择文件夹...", command=self.on_select_folder
        )
        self.select_folder_btn.pack(side="left", padx=(6, 0))
        self.clear_btn = ttk.Button(
            button_row, text="清空列表", command=self.on_clear
        )
        self.clear_btn.pack(side="left", padx=(6, 0))
        self.count_label = ttk.Label(button_row, text="已加载 0 个文件")
        self.count_label.pack(side="right")

        # 可滚动的文件列表（每行一个 Frame：文件名 + 状态 + 移除按钮）
        list_outer = ttk.Frame(file_frame)
        list_outer.pack(fill="both", expand=True, pady=(8, 0))
        self.list_canvas = tk.Canvas(list_outer, height=180, borderwidth=0)
        self.list_scrollbar = ttk.Scrollbar(
            list_outer, orient="vertical", command=self.list_canvas.yview
        )
        self.list_canvas.configure(yscrollcommand=self.list_scrollbar.set)
        self.list_canvas.pack(side="left", fill="both", expand=True)
        self.list_scrollbar.pack(side="right", fill="y")
        self.list_inner = ttk.Frame(self.list_canvas)
        self.list_canvas.create_window((0, 0), window=self.list_inner, anchor="nw")
        # 列表内容变化时刷新滚动区域；画布宽度变化时让内部框架自适应
        self.list_inner.bind(
            "<Configure>",
            lambda _e: self.list_canvas.configure(
                scrollregion=self.list_canvas.bbox("all")
            ),
        )
        self.list_canvas.bind(
            "<Configure>",
            lambda e: self.list_inner.configure(width=e.width),
        )

        # ② 输出目录区 -------------------------------------------------- #
        output_frame = ttk.LabelFrame(self, text="② 输出目录区", padding=8)
        output_frame.pack(fill="x", padx=10, pady=4)
        self.output_var = tk.StringVar()
        self.output_entry = ttk.Entry(
            output_frame, textvariable=self.output_var, state="readonly"
        )
        self.output_entry.pack(side="left", fill="x", expand=True)
        self.browse_btn = ttk.Button(
            output_frame, text="浏览...", command=self.on_select_output
        )
        self.browse_btn.pack(side="left", padx=(6, 0))

        # ③ 进度区 ----------------------------------------------------- #
        progress_frame = ttk.LabelFrame(self, text="③ 进度区", padding=8)
        progress_frame.pack(fill="x", padx=10, pady=4)
        self.progress_bar = ttk.Progressbar(
            progress_frame, orient="horizontal", maximum=100, value=0, mode="determinate"
        )
        self.progress_bar.pack(fill="x")
        self.status_label = ttk.Label(progress_frame, text="状态: 待命")
        self.status_label.pack(anchor="w", pady=(4, 0))

        # 底部：确认转换（受 GUI-014 校验与转换锁双重控制）---------------- #
        self.confirm_btn = ttk.Button(
            self, text="确认转换", command=self.on_confirm
        )
        self.confirm_btn.pack(fill="x", padx=10, pady=(6, 10))

    def _build_menu(self) -> None:
        """构建极简菜单栏（仅「关于」）。"""
        menubar = tk.Menu(self)
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="关于", command=self._show_about)
        menubar.add_cascade(label="帮助", menu=help_menu)
        self.configure(menu=menubar)

    # ------------------------------------------------------------------ #
    # 文件列表交互（T2）
    # ------------------------------------------------------------------ #
    def on_select_files(self) -> None:
        """多选文件对话框，仅收 .txt，加入列表。"""
        paths = filedialog.askopenfilenames(
            title="选择 TXT 文件", filetypes=[("文本文件", f"*{TXT_SUFFIX}"), ("全部", "*.*")]
        )
        self._add_files([Path(p) for p in paths])

    def on_select_folder(self) -> None:
        """选文件夹后扫描顶层 *.txt 加入列表（非递归，SCAN_RECURSIVE=False）。"""
        directory = filedialog.askdirectory(title="选择包含 TXT 的文件夹")
        if not directory:
            return
        folder = Path(directory)
        self._add_files(scan_txt_files(folder))

    def _add_files(self, paths: list[Path]) -> None:
        """去重后将若干 .txt 路径追加为 `FileItem` 并刷新界面。"""
        existing = {item.path.resolve() for item in self.file_items}
        added = False
        for path in paths:
            path = Path(path)
            # 仅接受 .txt；非 txt 静默忽略（也可在此加提示）
            if path.suffix.lower() != TXT_SUFFIX:
                continue
            if not path.exists():
                continue
            if path.resolve() in existing:
                continue
            self.file_items.append(FileItem(path=path))
            existing.add(path.resolve())
            added = True
        if added:
            self.render_file_list()
            self.refresh_controls()

    def on_remove_item(self, item: FileItem) -> None:
        """从列表中移除单个文件（GUI-003）。"""
        if self._input_locked:
            return
        self.file_items = [it for it in self.file_items if it is not item]
        self.render_file_list()
        self.refresh_controls()

    def on_clear(self) -> None:
        """清空整个文件列表（GUI-003）。"""
        if self._input_locked:
            return
        self.file_items.clear()
        self.render_file_list()
        self.refresh_controls()

    def render_file_list(self) -> None:
        """重建文件列表的可视行（文件名 + 状态 + 移除按钮）。"""
        for child in self.list_inner.winfo_children():
            child.destroy()

        if not self.file_items:
            empty = ttk.Label(self.list_inner, text="（尚未选择文件）")
            empty.pack(anchor="w", padx=4, pady=4)
            return

        remove_state = "disabled" if self._input_locked else "normal"
        for item in self.file_items:
            row = ttk.Frame(self.list_inner)
            row.pack(fill="x", padx=2, pady=1)
            name_label = ttk.Label(row, text=item.name, anchor="w")
            name_label.pack(side="left", fill="x", expand=True)
            status_label = ttk.Label(
                row, text=status_text(item.status), width=8, anchor="e"
            )
            status_label.pack(side="left", padx=(4, 8))
            remove_btn = ttk.Button(
                row,
                text="移除",
                width=6,
                state=remove_state,
                command=lambda it=item: self.on_remove_item(it),
            )
            remove_btn.pack(side="right")

    # ------------------------------------------------------------------ #
    # 输出目录（T3）
    # ------------------------------------------------------------------ #
    def on_select_output(self) -> None:
        """选输出目录并回填只读输入框。"""
        directory = filedialog.askdirectory(title="选择输出目录")
        if not directory:
            return
        self.output_dir = Path(directory)
        self.output_var.set(str(self.output_dir))
        self.refresh_controls()

    def refresh_controls(self) -> None:
        """依据「列表非空 且 输出目录合法」启用/禁用「确认转换」（GUI-014）。"""
        count = len(self.file_items)
        self.count_label.configure(text=f"已加载 {count} 个文件")
        valid = (
            count > 0
            and self.output_dir is not None
            and self.output_dir.is_dir()
        )
        self.confirm_btn.configure(state="normal" if valid else "disabled")

    # ------------------------------------------------------------------ #
    # 确认转换 + worker 编排（T4/T5）
    # ------------------------------------------------------------------ #
    def on_confirm(self) -> None:
        """校验后启动 worker；先判重入以防重复点击并发（GUI-005）。"""
        # 防重入：转换进行中再次点击直接忽略
        if self.worker is not None and self.worker.is_alive():
            return
        if not self.file_items or not (
            self.output_dir is not None and self.output_dir.is_dir()
        ):
            return

        # 锁定输入控件，避免转换期间状态错乱（GUI-015）
        self.set_controls_enabled(False)
        self.progress_queue = queue.Queue()
        self.progress_bar["value"] = 0
        self.status_label.configure(text="状态: 正在转换…")

        self.worker = ConversionWorker(
            file_items=self.file_items,
            output_dir=self.output_dir,
            queue=self.progress_queue,
            overwrite=DEFAULT_OVERWRITE,
        )
        self.worker.start()
        # 启动主线程轮询：每 POLL_INTERVAL_MS 排空一次队列
        self.after(POLL_INTERVAL_MS, self.poll_queue)

    def poll_queue(self) -> None:
        """主线程轮询进度队列（after 调度，唯一 UI 更新入口，GUI-010）。

        用 `get_nowait()` 一次性排空本轮所有消息，再决定是否续排。收到
        ``summary`` 后停止轮询并触发完成处理。
        """
        if self.progress_queue is None:
            return

        finished = False
        while True:
            try:
                message = self.progress_queue.get_nowait()
            except queue.Empty:
                break
            if message.type == "summary":
                finished = True
                self.on_conversion_done(message.summary)
            else:
                self.update_progress(message)

        if not finished:
            self.after(POLL_INTERVAL_MS, self.poll_queue)

    def update_progress(self, message: ProgressMessage) -> None:
        """用一条 progress 消息更新进度条、当前文件名与已处理计数（GUI-006/012）。"""
        if message.total > 0:
            self.progress_bar["value"] = message.index / message.total * 100
        self.status_label.configure(
            text=(
                f"状态: 正在转换 {message.filename}"
                f"　已处理 {message.index} / {message.total}"
            )
        )
        # 标记对应文件条目状态（供完成后再渲染着色）
        for item in self.file_items:
            if item.name == message.filename:
                item.status = (
                    FileStatus.DONE if message.ok else FileStatus.FAILED
                )
                break

    # ------------------------------------------------------------------ #
    # 完成处理（T6）
    # ------------------------------------------------------------------ #
    def on_conversion_done(self, summary: ConversionSummary) -> None:
        """收到汇总后：恢复输入、进度置满、弹「转换完成」对话框（GUI-007/013）。"""
        self.set_controls_enabled(True)
        self.progress_bar["value"] = 100
        self.status_label.configure(text="状态: 转换完成")
        self.render_file_list()  # 反映最终成功/失败着色
        self.refresh_controls()
        self._show_completion_dialog(summary)

    def _show_completion_dialog(self, summary: ConversionSummary) -> None:
        """弹窗展示成功/失败统计与可滚动失败清单（GUI-013）。"""
        dialog = tk.Toplevel(self)
        dialog.title("转换完成")
        dialog.transient(self)
        dialog.grab_set()
        dialog.geometry("440x320")

        info = (
            f"总计：{summary.total} 个\n"
            f"成功：{summary.success_count} 个\n"
            f"失败：{summary.fail_count} 个"
        )
        ttk.Label(dialog, text=info, justify="left").pack(
            anchor="w", padx=12, pady=(12, 6)
        )

        if summary.failures:
            ttk.Label(dialog, text="失败清单（文件名 — 原因）：").pack(
                anchor="w", padx=12
            )
            text_frame = ttk.Frame(dialog)
            text_frame.pack(fill="both", expand=True, padx=12, pady=(0, 8))
            text_widget = tk.Text(text_frame, wrap="word", height=10)
            text_scrollbar = ttk.Scrollbar(
                text_frame, orient="vertical", command=text_widget.yview
            )
            text_widget.configure(yscrollcommand=text_scrollbar.set)
            text_widget.pack(side="left", fill="both", expand=True)
            text_scrollbar.pack(side="right", fill="y")
            for filename, reason in summary.failures:
                text_widget.insert("end", f"• {filename}\n  {reason}\n")
            text_widget.configure(state="disabled")  # 只读，不可编辑

        ttk.Button(dialog, text="确定", command=dialog.destroy).pack(pady=(0, 12))
        dialog.wait_window(dialog)

    # ------------------------------------------------------------------ #
    # 控件锁定（GUI-015）
    # ------------------------------------------------------------------ #
    def set_controls_enabled(self, enabled: bool) -> None:
        """统一启用/禁用所有输入控件（转换期间置 False）。"""
        state = "normal" if enabled else "disabled"
        for widget in (
            self.select_files_btn,
            self.select_folder_btn,
            self.clear_btn,
            self.browse_btn,
            self.confirm_btn,
        ):
            widget.configure(state=state)
        self._input_locked = not enabled
        self.render_file_list()  # 应用「移除」按钮的禁用态

    def _show_about(self) -> None:
        """「关于」弹窗。"""
        try:
            from src import __version__ as version
        except Exception:  # pragma: no cover - 防御性兜底
            version = "未知"
        messagebox.showinfo(
            "关于 txt2epub GUI",
            f"{GUI_TITLE}\n版本：{version}\n\n"
            "批量 TXT → EPUB 转换工具图形界面。\n转换内核由命令行工具复用，零额外依赖。",
        )


def main() -> None:
    """GUI 启动入口。"""
    app = GUIApp()
    app.mainloop()


if __name__ == "__main__":
    main()
