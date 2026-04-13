"""Tests for ``core.downloader`` – resolve_target logic."""

from __future__ import annotations

import pytest

from core.downloader import DownloadError, resolve_target
from core.extension import DownloadInputPayload


class TestResolveTarget:
    def test_valid_direct_id(self) -> None:
        inp = DownloadInputPayload(line_number=1, value="iikmkjmpaadaobahmlepeloendndfphd")
        target = resolve_target(inp)
        assert target.extension_id == "iikmkjmpaadaobahmlepeloendndfphd"
        assert target.line_number == 1

    def test_valid_url(self) -> None:
        inp = DownloadInputPayload(
            line_number=2,
            value="https://microsoftedge.microsoft.com/addons/detail/name/iikmkjmpaadaobahmlepeloendndfphd",
        )
        target = resolve_target(inp)
        assert target.extension_id == "iikmkjmpaadaobahmlepeloendndfphd"

    def test_invalid_raises(self) -> None:
        inp = DownloadInputPayload(line_number=3, value="not-valid")
        with pytest.raises(DownloadError):
            resolve_target(inp)

    def test_empty_raises(self) -> None:
        inp = DownloadInputPayload(line_number=4, value="")
        with pytest.raises(DownloadError):
            resolve_target(inp)
