"""GUI 纯数据模型与共享常量。

本模块刻意**不依赖 Tkinter 与线程原语**，便于独立单元测试。GUI 与
worker 线程之间通过 `ProgressMessage` 传递进度，绝不跨线程访问 Tk 对象。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple


# --------------------------------------------------------------------------- #
# 界面与行为常量（集中管理，方便 P2 覆盖开关等扩展统一读取）
# --------------------------------------------------------------------------- #
GUI_TITLE = "txt2epub 转换器"  # 窗口标题（中文界面，PRD §5⑦）
DEFAULT_OVERWRITE = True  # 批量重跑即重生成，不因已存在而整批失败（GUI-020 默认）
TXT_SUFFIX = ".txt"  # 仅接受 .txt 文件
SCAN_RECURSIVE = False  # 扫描文件夹默认仅顶层（GUI-002）
POLL_INTERVAL_MS = 100  # 主线程轮询进度队列间隔（毫秒）


class FileStatus:
    """文件条目状态枚举（字符串常量，便于与 Tk 文本/着色对应）。"""

    PENDING = "pending"  # 待转换
    CONVERTING = "converting"  # 转换中
    DONE = "done"  # 成功
    FAILED = "failed"  # 失败


# 状态 -> 中文展示文本
_STATUS_TEXT = {
    FileStatus.PENDING: "待转换",
    FileStatus.CONVERTING: "转换中",
    FileStatus.DONE: "成功",
    FileStatus.FAILED: "失败",
}


def status_text(status: str) -> str:
    """返回状态对应的中文展示文本；未知状态原样返回。"""
    return _STATUS_TEXT.get(status, status)


@dataclass
class FileItem:
    """待转换文件条目。

    Attributes:
        path: 输入 TXT 文件的路径。
        selected: 是否参与转换（v1 恒为 True，预留给未来逐条跳过）。
        status: 当前状态，取值见 `FileStatus`。
    """

    path: Path
    selected: bool = True
    status: str = FileStatus.PENDING

    @property
    def name(self) -> str:
        """展示用文件名（含后缀）。"""
        return self.path.name


@dataclass
class ProgressMessage:
    """worker 线程 -> 主线程的进度消息（跨线程唯一载体）。

    `type` 为 ``"progress"`` 表示单个文件处理完毕；为 ``"summary"`` 表示全部
    处理完毕，此时 `summary` 字段携带 `ConversionSummary`。
    """

    type: str
    index: int = 0
    total: int = 0
    filename: str = ""
    ok: bool = False
    error: str = ""
    summary: "Optional[ConversionSummary]" = None

    @classmethod
    def make_progress(
        cls,
        index: int,
        total: int,
        filename: str,
        ok: bool,
        error: str = "",
    ) -> "ProgressMessage":
        """构造一条「单文件完成」进度消息。"""
        return cls(
            type="progress",
            index=index,
            total=total,
            filename=filename,
            ok=ok,
            error=error,
        )

    @classmethod
    def make_summary(cls, summary: "ConversionSummary") -> "ProgressMessage":
        """构造一条「全部完成」汇总消息，挂接 `ConversionSummary`。"""
        return cls(type="summary", summary=summary)


@dataclass
class ConversionSummary:
    """一次批量转换的完成统计。"""

    total: int = 0
    success_count: int = 0
    fail_count: int = 0
    failures: "List[Tuple[str, str]]" = field(default_factory=list)

    def add_failure(self, filename: str, reason: str) -> None:
        """记录一个失败文件（文件名 + 错误原因）。"""
        self.failures.append((filename, reason))
