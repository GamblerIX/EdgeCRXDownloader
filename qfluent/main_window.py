#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Edge CRX Downloader - 主窗口界面
基于 PySide6 和 QFluent Widgets
"""

import sys
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QSplitter, QFrame, QScrollArea, QFileDialog, QMessageBox
)
from PySide6.QtCore import Qt, Slot, QSize, QUrl
from PySide6.QtGui import QIcon, QFont, QDesktopServices

from qfluentwidgets import (
    FluentWindow, NavigationItemPosition, MSFluentTitleBar,
    TitleLabel, SubtitleLabel, BodyLabel, CaptionLabel,
    PushButton, PrimaryPushButton, StrongBodyLabel, InfoBar,
    InfoBarPosition, ProgressBar, ComboBox, LineEdit,
    TextEdit, TableWidget, TableItemDelegate, TableView,
    setTheme, Theme, FluentIcon as FIF, RoundMenu, Action,
    HyperlinkButton, SearchLineEdit, SmoothScrollArea,
    CardWidget, SimpleCardWidget, TransparentTogglePushButton,
    ToggleButton, IndeterminateProgressRing, MessageBoxBase,
    TeachingTip, TeachingTipTailPosition
)

from main import (
    DownloadInput, DownloadEvent, DownloadEventType,
    DownloadSummary, DownloadOutcome, DownloadFailure,
    DownloadWorker
)


class ProgressItemWidget(CardWidget):
    """单个下载进度项卡片"""
    
    def __init__(self, line_number: int, extension_id: str, file_name: str, parent=None):
        super().__init__(parent)
        self.line_number = line_number
        self.extension_id = extension_id
        self.file_name = file_name
        self.setup_ui()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(16, 12, 16, 12)
        
        # 标题行
        title_layout = QHBoxLayout()
        self.id_label = StrongBodyLabel(f"{self.extension_id[:16]}...")
        self.id_label.setToolTip(self.extension_id)
        title_layout.addWidget(self.id_label)
        
        self.status_label = CaptionLabel("等待中")
        self.status_label.setTextColor((96, 96, 96), (150, 150, 150))
        title_layout.addWidget(self.status_label)
        title_layout.addStretch()
        
        layout.addLayout(title_layout)
        
        # 进度条
        self.progress_bar = ProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)
        
        # 详细信息
        info_layout = QHBoxLayout()
        self.info_label = CaptionLabel("")
        info_layout.addWidget(self.info_label)
        info_layout.addStretch()
        layout.addLayout(info_layout)
    
    def update_progress(self, downloaded: int, total: Optional[int]):
        """更新进度"""
        if total and total > 0:
            percent = int((downloaded / total) * 100)
            self.progress_bar.setValue(percent)
            self.info_label.setText(f"{self._format_size(downloaded)} / {self._format_size(total)}")
        else:
            self.info_label.setText(f"已下载：{self._format_size(downloaded)}")
    
    def set_status(self, status: str, color=None):
        """设置状态"""
        self.status_label.setText(status)
        if color:
            self.status_label.setTextColor(color, color)
    
    def set_success(self, file_path: str, size: int):
        """设置为成功状态"""
        self.progress_bar.setValue(100)
        self.set_status("完成", (16, 124, 16))
        self.info_label.setText(f"{file_path} ({self._format_size(size)})")
    
    def set_failed(self, reason: str):
        """设置为失败状态"""
        self.progress_bar.setValue(0)
        self.set_status("失败", (197, 37, 37))
        self.info_label.setText(reason)
    
    def _format_size(self, size: int) -> str:
        """格式化文件大小"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"


class DownloadInterface(QWidget):
    """下载主界面"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DownloadInterface")
        self.worker: Optional[DownloadWorker] = None
        self.progress_widgets: Dict[int, ProgressItemWidget] = {}
        self.current_inputs: List[DownloadInput] = []
        self.save_directory = str(Path.home() / "Downloads" / "EdgeExtensions")
        
        self.setup_ui()
    
    def setup_ui(self):
        """设置界面"""
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(16)
        main_layout.setContentsMargins(24, 24, 24, 24)
        
        # 标题
        title = TitleLabel("Edge CRX 下载器")
        main_layout.addWidget(title)
        
        subtitle = SubtitleLabel("批量下载 Microsoft Edge 扩展的 CRX 文件")
        subtitle.setTextColor((96, 96, 96), (150, 150, 150))
        main_layout.addWidget(subtitle)
        
        main_layout.addSpacing(20)
        
        # 输入区域
        input_card = SimpleCardWidget()
        input_layout = QVBoxLayout(input_card)
        input_layout.setSpacing(12)
        input_layout.setContentsMargins(16, 16, 16, 16)
        
        input_label = BodyLabel("请输入扩展 ID 或 Edge 商店 URL（每行一个）：")
        input_layout.addWidget(input_label)
        
        self.input_text = TextEdit()
        self.input_text.setPlaceholderText(
            "示例:\n"
            "iikmkjmpaadaobahmlepeloendndfphd\n"
            "https://microsoftedge.microsoft.com/addons/detail/tampermonkey/iikmkjmpaadaobahmlepeloendndfphd"
        )
        self.input_text.setMinimumHeight(200)
        input_layout.addWidget(self.input_text)
        
        # 按钮行
        button_layout = QHBoxLayout()
        
        self.select_dir_btn = PushButton("选择保存目录", icon=FIF.FOLDER)
        self.select_dir_btn.clicked.connect(self.select_save_directory)
        button_layout.addWidget(self.select_dir_btn)
        
        self.dir_label = BodyLabel(self.save_directory)
        self.dir_label.setWordWrap(True)
        button_layout.addWidget(self.dir_label, 1)
        
        button_layout.addStretch()
        main_layout.addLayout(button_layout)
        
        main_layout.addWidget(input_card)
        
        # 控制按钮
        control_layout = QHBoxLayout()
        control_layout.addStretch()
        
        self.start_btn = PrimaryPushButton("开始下载", icon=FIF.PLAY)
        self.start_btn.setMinimumWidth(120)
        self.start_btn.clicked.connect(self.start_download)
        control_layout.addWidget(self.start_btn)
        
        self.stop_btn = PushButton("停止", icon=FIF.CANCEL)
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_download)
        control_layout.addWidget(self.stop_btn)
        
        main_layout.addLayout(control_layout)
        
        main_layout.addSpacing(10)
        
        # 进度区域标题
        progress_title = SubtitleLabel("下载进度")
        main_layout.addWidget(progress_title)
        
        # 进度列表
        self.scroll_area = SmoothScrollArea()
        self.scroll_widget = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_widget)
        self.scroll_layout.setSpacing(8)
        self.scroll_layout.setContentsMargins(0, 0, 0, 0)
        self.scroll_layout.addStretch()
        
        self.scroll_area.setWidget(self.scroll_widget)
        self.scroll_area.setMinimumHeight(300)
        main_layout.addWidget(self.scroll_area)
        
        # 状态栏
        status_layout = QHBoxLayout()
        self.status_label = CaptionLabel("就绪")
        status_layout.addWidget(self.status_label)
        status_layout.addStretch()
        self.count_label = CaptionLabel("共 0 项 | 成功 0 | 失败 0")
        status_layout.addWidget(self.count_label)
        main_layout.addLayout(status_layout)
    
    @Slot()
    def select_save_directory(self):
        """选择保存目录"""
        directory = QFileDialog.getExistingDirectory(
            self, 
            "选择保存目录",
            self.save_directory
        )
        if directory:
            self.save_directory = directory
            self.dir_label.setText(self.save_directory)
            InfoBar.success(
                title="目录已选择",
                content=self.save_directory,
                parent=self,
                duration=2000
            )
    
    @Slot()
    def start_download(self):
        """开始下载"""
        # 解析输入
        text = self.input_text.toPlainText().strip()
        if not text:
            InfoBar.warning(
                title="输入为空",
                content="请输入至少一个扩展 ID 或 URL",
                parent=self,
                duration=3000
            )
            return
        
        # 解析输入行
        self.current_inputs = []
        for i, line in enumerate(text.split('\n'), 1):
            line = line.strip()
            if line and not line.startswith('#'):
                self.current_inputs.append(DownloadInput(line_number=i, value=line))
        
        if not self.current_inputs:
            InfoBar.warning(
                title="没有有效输入",
                content="请检查输入格式，排除空行和注释",
                parent=self,
                duration=3000
            )
            return
        
        # 清理旧的进度项
        self.clear_progress_widgets()
        
        # 为每个输入创建进度项
        for input_item in self.current_inputs:
            # 尝试解析 extension_id 用于显示
            ext_id = self._extract_extension_id(input_item.value)
            file_name = f"{ext_id}.crx" if ext_id else f"line_{input_item.line_number}.crx"
            
            widget = ProgressItemWidget(
                input_item.line_number,
                ext_id or f"Line {input_item.line_number}",
                file_name
            )
            self.progress_widgets[input_item.line_number] = widget
            # 插入到 stretch 之前
            self.scroll_layout.insertWidget(self.scroll_layout.count() - 1, widget)
        
        # 更新状态
        self.set_downloading_state(True)
        self.status_label.setText(f"开始下载 {len(self.current_inputs)} 个扩展...")
        
        # 创建工作线程
        self.worker = DownloadWorker(self.current_inputs, self.save_directory)
        self.worker.event_signal.connect(self.on_download_event)
        self.worker.finished_signal.connect(self.on_download_finished)
        self.worker.error_signal.connect(self.on_download_error)
        self.worker.start()
    
    def _extract_extension_id(self, value: str) -> Optional[str]:
        """从输入中提取扩展 ID"""
        import re
        value = value.strip().lower()
        
        # 直接匹配 32 位 ID
        if re.match(r'^[a-z]{32}$', value):
            return value
        
        # 从 URL 提取
        match = re.search(r'microsoftedge\.microsoft\.com/addons/detail/[^/]+/([a-z]{32})', value)
        if match:
            return match.group(1)
        
        return None
    
    def clear_progress_widgets(self):
        """清空进度部件"""
        self.progress_widgets.clear()
        while self.scroll_layout.count() > 1:  # 保留最后的 stretch
            item = self.scroll_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
    
    def set_downloading_state(self, is_downloading: bool):
        """设置下载状态"""
        self.start_btn.setEnabled(not is_downloading)
        self.stop_btn.setEnabled(is_downloading)
        self.input_text.setEnabled(not is_downloading)
        self.select_dir_btn.setEnabled(not is_downloading)
    
    @Slot(object)
    def on_download_event(self, event: DownloadEvent):
        """处理下载事件"""
        if event.event_type == DownloadEventType.ITEM_STARTED:
            if event.line_number in self.progress_widgets:
                widget = self.progress_widgets[event.line_number]
                widget.set_status("下载中...", (0, 102, 204))
                widget.info_label.setText(f"正在获取 {event.file_name}...")
        
        elif event.event_type == DownloadEventType.ITEM_PROGRESS:
            if event.line_number in self.progress_widgets:
                widget = self.progress_widgets[event.line_number]
                widget.update_progress(event.downloaded_bytes, event.total_bytes)
        
        elif event.event_type == DownloadEventType.ITEM_SUCCEEDED:
            if event.line_number in self.progress_widgets:
                widget = self.progress_widgets[event.line_number]
                widget.set_success(event.file_path, event.bytes_written)
        
        elif event.event_type == DownloadEventType.ITEM_FAILED:
            if event.line_number in self.progress_widgets:
                widget = self.progress_widgets[event.line_number]
                widget.set_failed(event.reason)
        
        elif event.event_type == DownloadEventType.BATCH_STARTED:
            self.status_label.setText(f"批次开始，共 {event.total} 项...")
    
    @Slot(object)
    def on_download_finished(self, summary: DownloadSummary):
        """下载完成"""
        self.set_downloading_state(False)
        self.status_label.setText("下载完成")
        self.count_label.setText(
            f"共 {summary.total} 项 | 成功 {summary.success_count} | 失败 {summary.failure_count}"
        )
        
        if summary.failure_count == 0:
            InfoBar.success(
                title="下载完成",
                content=f"成功下载 {summary.success_count} 个扩展",
                parent=self,
                duration=5000
            )
        else:
            InfoBar.warning(
                title="下载完成",
                content=f"成功 {summary.success_count} 个，失败 {summary.failure_count} 个",
                parent=self,
                duration=5000
            )
        
        self.worker = None
    
    @Slot(str)
    def on_download_error(self, error_msg: str):
        """下载出错"""
        self.set_downloading_state(False)
        self.status_label.setText("下载出错")
        InfoBar.error(
            title="下载失败",
            content=error_msg,
            parent=self,
            duration=5000
        )
        self.worker = None
    
    @Slot()
    def stop_download(self):
        """停止下载"""
        if self.worker:
            self.worker.cancel()
            self.worker = None
            self.set_downloading_state(False)
            self.status_label.setText("已停止")
            InfoBar.info(
                title="已停止",
                content="下载任务已停止",
                parent=self,
                duration=2000
            )


class MainWindow(FluentWindow):
    """主窗口"""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Edge CRX 下载器")
        self.resize(900, 700)
        
        # 设置主题
        setTheme(Theme.AUTO)
        
        self.setup_navigation()
        self.init_interface()
    
    def setup_navigation(self):
        """设置导航栏"""
        # 添加导航项
        self.addSubInterface(
            FIF.DOWNLOAD,
            "下载",
            DownloadInterface(self)
        )
        
        # 底部导航项
        self.navigationInterface.addItem(
            routeKey='help',
            text='帮助',
            icon=FIF.HELP,
            onClick=self.show_help,
            position=NavigationItemPosition.BOTTOM
        )
    
    def init_interface(self):
        """初始化界面"""
        pass
    
    def show_help(self):
        """显示帮助信息"""
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("帮助")
        msg_box.setText("使用说明")
        msg_box.setInformativeText(
            "1. 在文本框中输入扩展 ID 或 Edge 商店 URL，每行一个\n"
            "2. 点击'选择保存目录'设置下载位置\n"
            "3. 点击'开始下载'开始批量下载\n\n"
            "支持的格式:\n"
            "- 32 位扩展 ID: iikmkjmpaadaobahmlepeloendndfphd\n"
            "- Edge 商店 URL: https://microsoftedge.microsoft.com/addons/detail/...\n\n"
            "下载的 CRX 文件将保存为 {extensionId}.crx"
        )
        msg_box.setIcon(QMessageBox.Information)
        msg_box.exec()


def main():
    """主函数"""
    # 启用高 DPI 缩放
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    
    app = QApplication(sys.argv)
    app.setAttribute(Qt.AA_DontCreateNativeWidgetSiblings)
    
    # 设置应用字体
    font = QFont("Microsoft YaHei UI", 9)
    app.setFont(font)
    
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
