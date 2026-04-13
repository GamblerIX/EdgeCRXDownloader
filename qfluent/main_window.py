"""Main window for Edge CRX Downloader (QFluentWidgets version).

Implements a Fluent Design desktop UI that is functionally equivalent to the
Tauri/Nuxt version defined in ``tauri/pages/index.vue``.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QThread, Signal, Slot, Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QSizePolicy,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    FluentIcon,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    PlainTextEdit,
    ProgressBar,
    PrimaryPushButton,
    PushButton,
    StrongBodyLabel,
    SubtitleLabel,
    TableWidget,
    TextEdit,
    FluentWindow,
    NavigationItemPosition,
)

from core.downloader import (
    DownloadEvent,
    DownloadSummary,
    EventType,
    download_extensions,
)
from core.extension import (
    DownloadInputPayload,
    extract_extension_id,
    format_bytes,
    format_percent,
    parse_extension_inputs,
)
from core.error import get_user_facing_error

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SAMPLE_INPUT = (
    "iikmkjmpaadaobahmlepeloendndfphd\n"
    "https://microsoftedge.microsoft.com/addons/detail/"
    "edge-crx-downloader/iikmkjmpaadaobahmlepeloendndfphd?hl=zh-CN"
)


# ---------------------------------------------------------------------------
# Background worker
# ---------------------------------------------------------------------------

class DownloadWorker(QThread):
    """Runs ``download_extensions`` in a background thread."""

    progress = Signal(object)  # DownloadEvent
    finished_signal = Signal(object)  # DownloadSummary | Exception

    def __init__(
        self,
        inputs: list[DownloadInputPayload],
        save_dir: str,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._inputs = inputs
        self._save_dir = save_dir

    def run(self) -> None:  # noqa: D401 – Qt override
        try:
            summary = download_extensions(
                self._inputs,
                self._save_dir,
                on_progress=lambda evt: self.progress.emit(evt),
            )
            self.finished_signal.emit(summary)
        except Exception as exc:
            self.finished_signal.emit(exc)


# ---------------------------------------------------------------------------
# Queue item model
# ---------------------------------------------------------------------------

class QueueItem:
    """In-memory model for a single queue row."""

    def __init__(self, line_number: int, raw: str) -> None:
        self.line_number = line_number
        self.raw = raw
        self.extension_id: Optional[str] = extract_extension_id(raw)
        self.status: str = "waiting" if self.extension_id else "invalid"
        self.downloaded_bytes: int = 0
        self.total_bytes: Optional[int] = None
        self.file_path: Optional[str] = None
        self.error: Optional[str] = None


# ---------------------------------------------------------------------------
# Download page widget
# ---------------------------------------------------------------------------

class DownloadPage(QWidget):
    """Single-page widget containing the entire downloader UI."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("downloadPage")

        self._queue: list[QueueItem] = []
        self._logs: list[str] = []
        self._summary: Optional[DownloadSummary] = None
        self._is_running = False
        self._worker: Optional[DownloadWorker] = None

        self._init_ui()
        self._restore_sample()

    # -- Layout ------------------------------------------------------------

    def _init_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(16)

        # Title
        title = SubtitleLabel("Edge CRX Downloader")
        root.addWidget(title)

        # Status card
        self._status_card = CardWidget(self)
        status_layout = QVBoxLayout(self._status_card)
        self._status_title = StrongBodyLabel("准备就绪")
        self._status_message = BodyLabel("输入扩展 ID 或 Edge 商店详情页 URL。")
        status_layout.addWidget(self._status_title)
        status_layout.addWidget(self._status_message)
        root.addWidget(self._status_card)

        # Input area
        input_label = StrongBodyLabel("扩展输入")
        root.addWidget(input_label)

        self._input_edit = PlainTextEdit(self)
        self._input_edit.setPlaceholderText(
            "每行填写一个扩展 ID 或 Edge 商店详情页 URL"
        )
        self._input_edit.setMinimumHeight(80)
        self._input_edit.setMaximumHeight(120)
        root.addWidget(self._input_edit)

        # Input action buttons
        input_btn_row = QHBoxLayout()
        self._sample_btn = PushButton(FluentIcon.PASTE, "载入示例")
        self._sample_btn.clicked.connect(self._restore_sample)
        self._clear_btn = PushButton(FluentIcon.DELETE, "清空输入")
        self._clear_btn.clicked.connect(self._clear_input)
        input_btn_row.addWidget(self._sample_btn)
        input_btn_row.addWidget(self._clear_btn)
        input_btn_row.addStretch()
        root.addLayout(input_btn_row)

        # Save directory
        dir_label = StrongBodyLabel("保存目录")
        root.addWidget(dir_label)

        dir_row = QHBoxLayout()
        self._dir_edit = LineEdit(self)
        self._dir_edit.setPlaceholderText("选择 CRX 保存目录")
        self._dir_edit.setReadOnly(True)
        dir_row.addWidget(self._dir_edit)

        self._browse_btn = PushButton(FluentIcon.FOLDER, "浏览")
        self._browse_btn.clicked.connect(self._choose_directory)
        dir_row.addWidget(self._browse_btn)
        root.addLayout(dir_row)

        # Metrics row
        metrics_row = QHBoxLayout()
        self._metric_total = self._make_metric_card("队列总数", "0")
        self._metric_success = self._make_metric_card("成功率", "0%")
        self._metric_written = self._make_metric_card("已写入", "0 B")
        metrics_row.addWidget(self._metric_total)
        metrics_row.addWidget(self._metric_success)
        metrics_row.addWidget(self._metric_written)
        root.addLayout(metrics_row)

        # Overall progress bar
        self._progress_bar = ProgressBar(self)
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        root.addWidget(self._progress_bar)

        # Queue table
        queue_label = StrongBodyLabel("下载队列")
        root.addWidget(queue_label)

        self._queue_table = TableWidget(self)
        self._queue_table.setColumnCount(4)
        self._queue_table.setHorizontalHeaderLabels(
            ["行号", "扩展 ID", "状态", "详情"]
        )
        self._queue_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self._queue_table.setEditTriggers(
            TableWidget.EditTrigger.NoEditTriggers
        )
        self._queue_table.setMinimumHeight(120)
        root.addWidget(self._queue_table)

        # Start button
        self._start_btn = PrimaryPushButton(FluentIcon.PLAY, "开始下载")
        self._start_btn.clicked.connect(self._start_download)
        root.addWidget(self._start_btn)

        # Log area
        log_label = StrongBodyLabel("执行日志")
        root.addWidget(log_label)

        self._log_edit = TextEdit(self)
        self._log_edit.setReadOnly(True)
        self._log_edit.setMinimumHeight(100)
        root.addWidget(self._log_edit)

        self._append_log("[准备] 选择保存目录后即可开始下载。")

    # -- Metric card helper ------------------------------------------------

    def _make_metric_card(self, label: str, value: str) -> CardWidget:
        card = CardWidget(self)
        layout = QVBoxLayout(card)
        lbl = CaptionLabel(label)
        val = StrongBodyLabel(value)
        val.setObjectName(f"metric_{label}")
        layout.addWidget(lbl)
        layout.addWidget(val)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        return card

    def _update_metric(self, card: CardWidget, value: str) -> None:
        for child in card.findChildren(StrongBodyLabel):
            child.setText(value)
            break

    # -- Actions -----------------------------------------------------------

    @Slot()
    def _restore_sample(self) -> None:
        if self._is_running:
            return
        self._input_edit.setPlainText(SAMPLE_INPUT)
        self._summary = None
        self._set_status("示例已载入", "已填入示例扩展 ID 与详情页地址。")
        self._append_log("输入区已填入示例内容。")
        self._rebuild_queue()

    @Slot()
    def _clear_input(self) -> None:
        if self._is_running:
            return
        self._input_edit.clear()
        self._summary = None
        self._set_status("输入已清空", "当前输入区已清空，可重新粘贴扩展 ID 或 URL。")
        self._append_log("输入区已清空。")
        self._rebuild_queue()

    @Slot()
    def _choose_directory(self) -> None:
        if self._is_running:
            return
        directory = QFileDialog.getExistingDirectory(
            self, "选择 CRX 保存目录", os.path.expanduser("~")
        )
        if directory:
            self._dir_edit.setText(directory)
            self._set_status("目录已就绪", f"输出目录已设置为 {directory}")
            self._append_log(f"保存目录已更新为 {directory}")

    @Slot()
    def _start_download(self) -> None:
        if self._is_running:
            return

        raw = self._input_edit.toPlainText()
        inputs = parse_extension_inputs(raw)
        if not inputs:
            self._set_status("缺少输入", "至少填写一条扩展 ID 或商店详情页 URL。")
            self._append_log("开始下载被拒绝：输入为空。")
            return

        save_dir = self._dir_edit.text().strip()
        if not save_dir:
            self._set_status("缺少目录", "请先选择 CRX 保存目录。")
            self._append_log("开始下载被拒绝：未选择保存目录。")
            return

        self._rebuild_queue()
        self._summary = None
        self._is_running = True
        self._start_btn.setEnabled(False)

        self._set_status("准备执行", f"即将处理 {len(inputs)} 条输入。")
        self._append_log(
            f"队列已锁定，共 {len(inputs)} 项，输出目录：{save_dir}"
        )

        self._worker = DownloadWorker(inputs, save_dir, self)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_signal.connect(self._on_finished)
        self._worker.start()

    # -- Progress handling -------------------------------------------------

    @Slot(object)
    def _on_progress(self, event: DownloadEvent) -> None:
        if event.event_type == EventType.BATCH_STARTED:
            self._append_log(f"开始执行，共 {event.total} 项。")
            self._set_status(
                "执行中", f"下载队列已启动，共 {event.total} 条输入。"
            )

        elif event.event_type == EventType.ITEM_STARTED:
            item = self._find_queue_item(event.line_number)
            if item:
                item.status = "running"
                item.extension_id = event.extension_id
                item.error = None
            self._append_log(
                f"第 {event.line_number} 行开始下载 {event.extension_id}。"
            )
            self._update_batch_progress(event.index, event.total, 0.02)

        elif event.event_type == EventType.ITEM_PROGRESS:
            item = self._find_queue_item(event.line_number)
            if item:
                item.status = "running"
                item.downloaded_bytes = event.downloaded_bytes
                item.total_bytes = event.total_bytes
            frac = (
                event.downloaded_bytes / event.total_bytes
                if event.total_bytes and event.total_bytes > 0
                else 0.45
            )
            self._update_batch_progress(event.index, event.total, frac)

        elif event.event_type == EventType.ITEM_SUCCEEDED:
            item = self._find_queue_item(event.line_number)
            if item:
                item.status = "success"
                item.extension_id = event.extension_id
                item.downloaded_bytes = event.bytes_written
                item.total_bytes = event.bytes_written
                item.file_path = event.file_path
                item.error = None
            self._append_log(
                f"第 {event.line_number} 行已完成，输出到 {event.file_path}。"
            )
            self._update_batch_progress(event.index, event.total, 1.0)

        elif event.event_type == EventType.ITEM_FAILED:
            item = self._find_queue_item(event.line_number)
            if item:
                item.status = "failed" if item.extension_id else "invalid"
                item.error = event.reason
            self._append_log(
                f"第 {event.line_number} 行失败：{event.reason}"
            )

        self._refresh_queue_table()
        self._refresh_metrics()

    @Slot(object)
    def _on_finished(self, result: object) -> None:
        self._is_running = False
        self._start_btn.setEnabled(True)
        self._worker = None

        if isinstance(result, DownloadSummary):
            self._summary = result
            total_written = sum(o.bytes_written for o in result.succeeded)

            if result.failure_count == 0:
                self._set_status(
                    "下载完成",
                    f"成功写入 {result.success_count} 个 CRX 文件。",
                )
            elif result.success_count == 0:
                self._set_status(
                    "执行失败",
                    f"全部 {result.failure_count} 项均未完成。",
                )
            else:
                self._set_status(
                    "部分完成",
                    f"成功 {result.success_count} 项，失败 {result.failure_count} 项。",
                )

            self._append_log(
                f"任务结束：成功 {result.success_count} 项，"
                f"失败 {result.failure_count} 项，"
                f"总写入 {format_bytes(total_written)}。"
            )
        elif isinstance(result, Exception):
            msg = get_user_facing_error(result)
            self._set_status("执行异常", msg)
            self._append_log(msg)

        self._progress_bar.setValue(100 if isinstance(result, DownloadSummary) else 0)
        self._refresh_metrics()

    # -- Queue helpers -----------------------------------------------------

    def _rebuild_queue(self) -> None:
        raw = self._input_edit.toPlainText()
        payloads = parse_extension_inputs(raw)
        self._queue = [QueueItem(p.line_number, p.value) for p in payloads]
        self._refresh_queue_table()
        self._refresh_metrics()

    def _find_queue_item(self, line_number: int) -> Optional[QueueItem]:
        for item in self._queue:
            if item.line_number == line_number:
                return item
        return None

    def _refresh_queue_table(self) -> None:
        self._queue_table.setRowCount(len(self._queue))
        for row, item in enumerate(self._queue):
            self._queue_table.setItem(row, 0, QTableWidgetItem(str(item.line_number)))
            self._queue_table.setItem(
                row, 1, QTableWidgetItem(item.extension_id or item.raw)
            )
            self._queue_table.setItem(
                row, 2, QTableWidgetItem(self._format_status(item.status))
            )
            self._queue_table.setItem(
                row, 3, QTableWidgetItem(self._describe_item(item))
            )

    def _refresh_metrics(self) -> None:
        total = len(self._queue)
        success = sum(1 for q in self._queue if q.status == "success")
        written = sum(q.downloaded_bytes for q in self._queue)

        rate = f"{round(success / total * 100)}%" if total > 0 else "0%"
        self._update_metric(self._metric_total, str(total))
        self._update_metric(self._metric_success, rate)
        self._update_metric(self._metric_written, format_bytes(written))

    # -- Batch progress ----------------------------------------------------

    def _update_batch_progress(
        self, index: int, total: int, item_fraction: float
    ) -> None:
        if total <= 0:
            return
        clamped = max(0.0, min(1.0, item_fraction))
        finished = max(0, index - 1)
        pct = max(1, min(100, round(((finished + clamped) / total) * 100)))
        self._progress_bar.setValue(pct)

    # -- Status / log helpers ----------------------------------------------

    def _set_status(self, title: str, message: str) -> None:
        self._status_title.setText(title)
        self._status_message.setText(message)

    def _append_log(self, message: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{stamp}] {message}"
        self._logs.append(line)
        self._log_edit.append(line)

    @staticmethod
    def _format_status(status: str) -> str:
        return {
            "waiting": "等待",
            "running": "下载中",
            "success": "完成",
            "failed": "失败",
            "invalid": "无效",
        }.get(status, status)

    @staticmethod
    def _describe_item(item: QueueItem) -> str:
        if item.status == "success":
            return f"{format_bytes(item.downloaded_bytes)} 已写入"
        if item.status == "running":
            total = format_bytes(item.total_bytes) if item.total_bytes else "未知大小"
            return f"{format_bytes(item.downloaded_bytes)} / {total}"
        if item.status in ("failed", "invalid"):
            return item.error or "处理失败"
        return (
            f"扩展 ID: {item.extension_id}"
            if item.extension_id
            else "将被标记为无效输入"
        )


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class MainWindow(FluentWindow):
    """Application main window using Fluent Design."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Edge CRX Downloader")
        self.resize(960, 640)
        self.setMinimumSize(760, 640)

        self._download_page = DownloadPage(self)
        self.addSubInterface(
            self._download_page,
            FluentIcon.DOWNLOAD,
            "下载",
            NavigationItemPosition.TOP,
        )

        # Center on screen
        desktop = self.screen().availableGeometry()
        self.move(
            (desktop.width() - self.width()) // 2,
            (desktop.height() - self.height()) // 2,
        )
