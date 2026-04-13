"""CRX download engine.

This module mirrors the Rust backend in ``src-tauri/src/commands/download.rs``.
It downloads Edge extension CRX files, validates the CRX magic bytes, and
reports progress via Qt signals.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Optional

import requests

from .extension import DownloadInputPayload, extract_extension_id

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EDGE_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0"
)
CRX_MAGIC = b"Cr24"
DOWNLOAD_URL_TEMPLATE = (
    "https://edge.microsoft.com/extensionwebstorebase/v1/crx"
    "?response=redirect&prod=chromiumcrx&prodchannel="
    "&x=id%3D{id}%26installsource%3Dondemand%26uc"
)
REQUEST_TIMEOUT = 600  # seconds
CHUNK_SIZE = 65_536  # 64 KiB


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

class EventType(Enum):
    BATCH_STARTED = auto()
    ITEM_STARTED = auto()
    ITEM_PROGRESS = auto()
    ITEM_SUCCEEDED = auto()
    ITEM_FAILED = auto()


@dataclass
class DownloadEvent:
    """Progress event emitted during a batch download."""

    event_type: EventType
    index: int = 0
    total: int = 0
    line_number: int = 0
    extension_id: str = ""
    file_name: str = ""
    downloaded_bytes: int = 0
    total_bytes: Optional[int] = None
    file_path: str = ""
    bytes_written: int = 0
    input_value: str = ""
    reason: str = ""


@dataclass
class DownloadOutcome:
    line_number: int
    extension_id: str
    file_path: str
    bytes_written: int


@dataclass
class DownloadFailure:
    line_number: int
    input_value: str
    reason: str


@dataclass
class DownloadTarget:
    line_number: int
    extension_id: str


@dataclass
class DownloadSummary:
    total: int = 0
    success_count: int = 0
    failure_count: int = 0
    succeeded: list[DownloadOutcome] = field(default_factory=list)
    failed: list[DownloadFailure] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Error helper
# ---------------------------------------------------------------------------

class DownloadError(Exception):
    """Error raised during download operations."""


# ---------------------------------------------------------------------------
# Resolve input → target
# ---------------------------------------------------------------------------

def resolve_target(inp: DownloadInputPayload) -> DownloadTarget:
    """Parse a user input line into a validated :class:`DownloadTarget`.

    Raises :class:`DownloadError` if the input is not a valid extension ID or
    Edge store URL.
    """
    ext_id = extract_extension_id(inp.value)
    if ext_id is None:
        raise DownloadError("请填写 32 位扩展 ID，或 Edge 商店详情页 URL")
    return DownloadTarget(line_number=inp.line_number, extension_id=ext_id)


# ---------------------------------------------------------------------------
# Single-item download
# ---------------------------------------------------------------------------

def _build_session() -> requests.Session:
    session = requests.Session()
    session.headers["User-Agent"] = EDGE_USER_AGENT
    return session


def download_one(
    session: requests.Session,
    save_dir: Path,
    target: DownloadTarget,
    index: int,
    total: int,
    on_progress: object,
) -> DownloadOutcome:
    """Download a single CRX file and return its outcome.

    *on_progress* must be a callable accepting a :class:`DownloadEvent`.
    Raises :class:`DownloadError` on failure.
    """
    file_name = f"{target.extension_id}.crx"
    output_path = save_dir / file_name
    temp_fd, temp_path_str = tempfile.mkstemp(
        suffix=".partial", prefix=file_name, dir=str(save_dir)
    )
    temp_path = Path(temp_path_str)

    on_progress(DownloadEvent(
        event_type=EventType.ITEM_STARTED,
        index=index, total=total,
        line_number=target.line_number,
        extension_id=target.extension_id,
        file_name=file_name,
    ))

    try:
        url = DOWNLOAD_URL_TEMPLATE.replace("{id}", target.extension_id)
        resp = session.get(url, stream=True, timeout=REQUEST_TIMEOUT)

        if not resp.ok:
            raise DownloadError(f"HTTP 响应异常：{resp.status_code}")

        total_bytes: Optional[int] = None
        content_length = resp.headers.get("Content-Length")
        if content_length and content_length.isdigit():
            total_bytes = int(content_length)

        downloaded_bytes = 0
        with os.fdopen(temp_fd, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
                fh.write(chunk)
                downloaded_bytes += len(chunk)
                on_progress(DownloadEvent(
                    event_type=EventType.ITEM_PROGRESS,
                    index=index, total=total,
                    line_number=target.line_number,
                    downloaded_bytes=downloaded_bytes,
                    total_bytes=total_bytes,
                ))

        # Validate CRX magic bytes
        with open(temp_path, "rb") as fh:
            magic = fh.read(4)

        if len(magic) < 4:
            raise DownloadError("下载的文件过小，可能不是有效的 CRX 文件")

        if magic != CRX_MAGIC:
            raise DownloadError("文件头不匹配 CRX 格式，服务器可能返回了错误页面")

        # Atomic replace
        if output_path.exists():
            output_path.unlink()
        temp_path.rename(output_path)

        outcome = DownloadOutcome(
            line_number=target.line_number,
            extension_id=target.extension_id,
            file_path=str(output_path),
            bytes_written=downloaded_bytes,
        )

        on_progress(DownloadEvent(
            event_type=EventType.ITEM_SUCCEEDED,
            index=index, total=total,
            line_number=target.line_number,
            extension_id=target.extension_id,
            file_path=str(output_path),
            bytes_written=downloaded_bytes,
        ))
        return outcome

    except Exception:
        # Clean up temp file on error
        try:
            if temp_path.exists():
                temp_path.unlink()
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Batch download (entry point)
# ---------------------------------------------------------------------------

def download_extensions(
    inputs: list[DownloadInputPayload],
    save_dir: str,
    on_progress: object,
) -> DownloadSummary:
    """Execute a batch download.

    *on_progress* is called with a :class:`DownloadEvent` for every state
    transition.  Returns a :class:`DownloadSummary`.

    Raises :class:`DownloadError` for fatal issues (empty input, bad dir).
    """
    if not inputs:
        raise DownloadError("输入不能为空")

    save_path = Path(save_dir.strip())
    if not str(save_path):
        raise DownloadError("保存目录无效：路径为空")

    save_path.mkdir(parents=True, exist_ok=True)

    session = _build_session()
    total = len(inputs)

    on_progress(DownloadEvent(
        event_type=EventType.BATCH_STARTED,
        total=total,
    ))

    succeeded: list[DownloadOutcome] = []
    failed: list[DownloadFailure] = []

    for idx, inp in enumerate(inputs):
        item_index = idx + 1
        try:
            target = resolve_target(inp)
            outcome = download_one(session, save_path, target, item_index, total, on_progress)
            succeeded.append(outcome)
        except (DownloadError, requests.RequestException, OSError) as exc:
            reason = str(exc)
            failed.append(DownloadFailure(
                line_number=inp.line_number,
                input_value=inp.value,
                reason=reason,
            ))
            on_progress(DownloadEvent(
                event_type=EventType.ITEM_FAILED,
                index=item_index, total=total,
                line_number=inp.line_number,
                input_value=inp.value,
                reason=reason,
            ))

    return DownloadSummary(
        total=total,
        success_count=len(succeeded),
        failure_count=len(failed),
        succeeded=succeeded,
        failed=failed,
    )
