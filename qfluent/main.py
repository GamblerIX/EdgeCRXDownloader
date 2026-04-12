#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Edge CRX Downloader - Python Version
基于 PySide6 和 QFluent 的 Edge 扩展 CRX 批量下载器
"""

import sys
import re
import asyncio
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Callable, List
from enum import Enum, auto

import aiohttp
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QObject, Signal, Slot, Qt, QThread
from PySide6.QtGui import QFont

from qfluentwidgets import FluentIcon as FIF
from qfluentwidgets import Theme, setTheme


# ============== 数据模型 ==============

@dataclass
class DownloadInput:
    """下载输入项"""
    line_number: int
    value: str


@dataclass
class DownloadTarget:
    """解析后的下载目标"""
    line_number: int
    extension_id: str


@dataclass
class DownloadOutcome:
    """下载成功结果"""
    line_number: int
    extension_id: str
    file_path: str
    bytes_written: int


@dataclass
class DownloadFailure:
    """下载失败结果"""
    line_number: int
    input: str
    reason: str


@dataclass
class DownloadSummary:
    """下载汇总"""
    total: int
    success_count: int
    failure_count: int
    succeeded: List[DownloadOutcome] = field(default_factory=list)
    failed: List[DownloadFailure] = field(default_factory=list)


class DownloadEventType(Enum):
    """下载事件类型"""
    BATCH_STARTED = auto()
    ITEM_STARTED = auto()
    ITEM_PROGRESS = auto()
    ITEM_SUCCEEDED = auto()
    ITEM_FAILED = auto()


@dataclass
class DownloadEvent:
    """下载事件"""
    event_type: DownloadEventType
    index: int = 0
    total: int = 0
    line_number: int = 0
    extension_id: str = ""
    file_name: str = ""
    downloaded_bytes: int = 0
    total_bytes: Optional[int] = None
    file_path: str = ""
    bytes_written: int = 0
    input: str = ""
    reason: str = ""


# ============== 异常类 ==============

class DownloadError(Exception):
    """下载异常基类"""
    pass


class EmptyInputError(DownloadError):
    def __init__(self):
        super().__init__("输入不能为空")


class InvalidInputError(DownloadError):
    def __init__(self, message: str = "请填写 32 位扩展 ID，或 Edge 商店详情页 URL"):
        super().__init__(message)


class InvalidSaveDirectoryError(DownloadError):
    def __init__(self, message: str):
        super().__init__(f"无效的保存目录：{message}")


class CreateDirectoryError(DownloadError):
    def __init__(self, path: Path, error: Exception):
        super().__init__(f"无法创建保存目录：{path} ({error})")


class NetworkError(DownloadError):
    def __init__(self, message: str):
        super().__init__(f"网络请求失败：{message}")


class HttpStatusError(DownloadError):
    def __init__(self, status_code: int):
        super().__init__(f"HTTP 响应异常：{status_code}")


class FileWriteError(DownloadError):
    def __init__(self, message: str):
        super().__init__(f"文件写入失败：{message}")


class RenameError(DownloadError):
    def __init__(self, message: str):
        super().__init__(f"无法重命名临时文件到目标文件：{message}")


# ============== 下载引擎 ==============

class DownloadEngine:
    """下载引擎核心逻辑"""
    
    EDGE_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0"
    DOWNLOAD_URL_TEMPLATE = "https://edge.microsoft.com/extensionwebstorebase/v1/crx?response=redirect&prod=chromiumcrx&prodchannel=&x=id%3D{ID}%26installsource%3Dondemand%26uc"
    CRX_MAGIC = b"Cr24"
    
    # 正则表达式模式
    DIRECT_PATTERN = re.compile(r"^[a-z]{32}$")
    URL_PATTERN = re.compile(r"microsoftedge\.microsoft\.com/addons/detail/[^/]+/([a-z]{32})")
    
    def __init__(self, progress_callback: Optional[Callable[[DownloadEvent], None]] = None):
        self.progress_callback = progress_callback
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """获取或创建 HTTP 会话"""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=600)
            headers = {"User-Agent": self.EDGE_USER_AGENT}
            self._session = aiohttp.ClientSession(headers=headers, timeout=timeout)
        return self._session
    
    async def close(self):
        """关闭 HTTP 会话"""
        if self._session and not self._session.closed:
            await self._session.close()
    
    def _send_event(self, event: DownloadEvent):
        """发送进度事件"""
        if self.progress_callback:
            try:
                self.progress_callback(event)
            except Exception:
                pass
    
    def resolve_target(self, input_item: DownloadInput) -> DownloadTarget:
        """解析下载目标"""
        normalized = input_item.value.strip().lower()
        
        if not normalized:
            raise EmptyInputError()
        
        # 直接匹配 32 位扩展 ID
        if self.DIRECT_PATTERN.match(normalized):
            return DownloadTarget(
                line_number=input_item.line_number,
                extension_id=normalized
            )
        
        # 从 URL 中提取扩展 ID
        match = self.URL_PATTERN.search(normalized)
        if match:
            extension_id = match.group(1)
            if extension_id:
                return DownloadTarget(
                    line_number=input_item.line_number,
                    extension_id=extension_id
                )
        
        raise InvalidInputError()
    
    async def download_one(
        self,
        save_dir: Path,
        target: DownloadTarget,
        index: int,
        total: int
    ) -> DownloadOutcome:
        """下载单个扩展"""
        file_name = f"{target.extension_id}.crx"
        output_path = save_dir / file_name
        temp_path = save_dir / f"{file_name}.partial"
        download_url = self.DOWNLOAD_URL_TEMPLATE.replace("{ID}", target.extension_id)
        
        # 发送开始事件
        self._send_event(DownloadEvent(
            event_type=DownloadEventType.ITEM_STARTED,
            index=index,
            total=total,
            line_number=target.line_number,
            extension_id=target.extension_id,
            file_name=file_name
        ))
        
        session = await self._get_session()
        
        try:
            async with session.get(download_url) as response:
                if not response.status < 400:
                    raise HttpStatusError(response.status)
                
                # 删除已存在的临时文件
                if temp_path.exists():
                    temp_path.unlink()
                
                total_bytes = response.content_length
                downloaded_bytes = 0
                
                # 创建临时文件并下载
                with open(temp_path, 'wb') as f:
                    async for chunk in response.content.iter_chunked(8192):
                        f.write(chunk)
                        downloaded_bytes += len(chunk)
                        
                        # 发送进度事件
                        self._send_event(DownloadEvent(
                            event_type=DownloadEventType.ITEM_PROGRESS,
                            index=index,
                            total=total,
                            line_number=target.line_number,
                            downloaded_bytes=downloaded_bytes,
                            total_bytes=total_bytes
                        ))
                
                # 验证 CRX 文件头
                with open(temp_path, 'rb') as f:
                    magic_buf = f.read(4)
                    if len(magic_buf) < 4 or magic_buf != self.CRX_MAGIC:
                        temp_path.unlink()
                        raise FileWriteError("文件头不匹配 CRX 格式，服务器可能返回了错误页面")
                
                # 移动临时文件到目标位置
                if output_path.exists():
                    output_path.unlink()
                
                temp_path.rename(output_path)
                
                # 发送成功事件
                self._send_event(DownloadEvent(
                    event_type=DownloadEventType.ITEM_SUCCEEDED,
                    index=index,
                    total=total,
                    line_number=target.line_number,
                    extension_id=target.extension_id,
                    file_path=str(output_path),
                    bytes_written=downloaded_bytes
                ))
                
                return DownloadOutcome(
                    line_number=target.line_number,
                    extension_id=target.extension_id,
                    file_path=str(output_path),
                    bytes_written=downloaded_bytes
                )
                
        except aiohttp.ClientError as e:
            if temp_path.exists():
                temp_path.unlink()
            raise NetworkError(str(e))
        except Exception as e:
            if temp_path.exists():
                temp_path.unlink()
            raise
    
    async def download_extensions(
        self,
        inputs: List[DownloadInput],
        save_dir: str
    ) -> DownloadSummary:
        """批量下载扩展"""
        if not inputs:
            raise EmptyInputError()
        
        save_dir = Path(save_dir.strip())
        if not save_dir or str(save_dir).strip() == "":
            raise InvalidSaveDirectoryError("路径为空")
        
        # 创建保存目录
        try:
            save_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            raise CreateDirectoryError(save_dir, e)
        
        total = len(inputs)
        
        # 发送批次开始事件
        self._send_event(DownloadEvent(
            event_type=DownloadEventType.BATCH_STARTED,
            total=total
        ))
        
        succeeded = []
        failed = []
        
        for index, input_item in enumerate(inputs):
            item_index = index + 1
            
            try:
                target = self.resolve_target(input_item)
                outcome = await self.download_one(save_dir, target, item_index, total)
                succeeded.append(outcome)
            except DownloadError as e:
                failure = DownloadFailure(
                    line_number=input_item.line_number,
                    input=input_item.value,
                    reason=str(e)
                )
                failed.append(failure)
                
                # 发送失败事件
                self._send_event(DownloadEvent(
                    event_type=DownloadEventType.ITEM_FAILED,
                    index=item_index,
                    total=total,
                    line_number=input_item.line_number,
                    input=input_item.value,
                    reason=str(e)
                ))
        
        return DownloadSummary(
            total=total,
            success_count=len(succeeded),
            failure_count=len(failed),
            succeeded=succeeded,
            failed=failed
        )


# ============== 下载工作线程 ==============

class DownloadWorker(QThread):
    """下载工作线程"""
    
    # 信号定义
    event_signal = Signal(object)  # DownloadEvent
    finished_signal = Signal(object)  # DownloadSummary
    error_signal = Signal(str)  # 错误消息
    
    def __init__(self, inputs: List[DownloadInput], save_dir: str):
        super().__init__()
        self.inputs = inputs
        self.save_dir = save_dir
        self.engine = DownloadEngine(progress_callback=self._on_event)
    
    def _on_event(self, event: DownloadEvent):
        """进度回调（在子线程中调用）"""
        self.event_signal.emit(event)
    
    @Slot()
    def run(self):
        """运行下载任务"""
        async def run_download():
            try:
                summary = await self.engine.download_extensions(self.inputs, self.save_dir)
                self.finished_signal.emit(summary)
            except Exception as e:
                self.error_signal.emit(str(e))
            finally:
                await self.engine.close()
        
        # 创建事件循环并运行
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(run_download())
        finally:
            loop.close()
    
    def cancel(self):
        """取消下载"""
        self.terminate()


if __name__ == "__main__":
    # 简单的测试
    print("Edge CRX Downloader - Python Version")
    print("请使用 main_window.py 启动图形界面")
