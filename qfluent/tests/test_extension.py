"""Tests for ``core.extension`` – mirrors Tauri's utils/extension.ts logic."""

from __future__ import annotations

import pytest

from core.extension import (
    extract_extension_id,
    format_bytes,
    format_percent,
    parse_extension_inputs,
)


# ---------------------------------------------------------------------------
# extract_extension_id
# ---------------------------------------------------------------------------

class TestExtractExtensionId:
    def test_direct_32char_id(self) -> None:
        assert extract_extension_id("iikmkjmpaadaobahmlepeloendndfphd") == "iikmkjmpaadaobahmlepeloendndfphd"

    def test_direct_id_with_whitespace(self) -> None:
        assert extract_extension_id("  iikmkjmpaadaobahmlepeloendndfphd  ") == "iikmkjmpaadaobahmlepeloendndfphd"

    def test_direct_id_uppercase_normalised(self) -> None:
        assert extract_extension_id("IIKMKJMPAADAOBAHMLEPELOENDNDFPHD") == "iikmkjmpaadaobahmlepeloendndfphd"

    def test_edge_store_url(self) -> None:
        url = "https://microsoftedge.microsoft.com/addons/detail/some-name/iikmkjmpaadaobahmlepeloendndfphd"
        assert extract_extension_id(url) == "iikmkjmpaadaobahmlepeloendndfphd"

    def test_edge_store_url_with_query(self) -> None:
        url = "https://microsoftedge.microsoft.com/addons/detail/edge-crx-downloader/iikmkjmpaadaobahmlepeloendndfphd?hl=zh-CN"
        assert extract_extension_id(url) == "iikmkjmpaadaobahmlepeloendndfphd"

    def test_empty_returns_none(self) -> None:
        assert extract_extension_id("") is None

    def test_whitespace_returns_none(self) -> None:
        assert extract_extension_id("   ") is None

    def test_invalid_short_id(self) -> None:
        assert extract_extension_id("abc") is None

    def test_invalid_with_digits(self) -> None:
        assert extract_extension_id("iikmkjmpaadaobahmlepeloendndfph1") is None

    def test_random_url_returns_none(self) -> None:
        assert extract_extension_id("https://example.com") is None


# ---------------------------------------------------------------------------
# parse_extension_inputs
# ---------------------------------------------------------------------------

class TestParseExtensionInputs:
    def test_single_line(self) -> None:
        result = parse_extension_inputs("iikmkjmpaadaobahmlepeloendndfphd")
        assert len(result) == 1
        assert result[0].line_number == 1
        assert result[0].value == "iikmkjmpaadaobahmlepeloendndfphd"

    def test_multi_line(self) -> None:
        text = "aaa\nbbb\nccc"
        result = parse_extension_inputs(text)
        assert len(result) == 3
        assert result[2].line_number == 3

    def test_blank_lines_skipped(self) -> None:
        text = "aaa\n\n  \nbbb"
        result = parse_extension_inputs(text)
        assert len(result) == 2
        assert result[0].line_number == 1
        assert result[1].line_number == 4

    def test_empty_string(self) -> None:
        assert parse_extension_inputs("") == []

    def test_strips_whitespace(self) -> None:
        result = parse_extension_inputs("  hello  ")
        assert result[0].value == "hello"


# ---------------------------------------------------------------------------
# format_bytes
# ---------------------------------------------------------------------------

class TestFormatBytes:
    def test_zero(self) -> None:
        assert format_bytes(0) == "0 B"

    def test_negative(self) -> None:
        assert format_bytes(-100) == "0 B"

    def test_small_bytes(self) -> None:
        assert format_bytes(512) == "512 B"

    def test_kilobytes(self) -> None:
        assert format_bytes(1024) == "1.0 KB"

    def test_megabytes(self) -> None:
        assert format_bytes(1024 * 1024) == "1.0 MB"

    def test_gigabytes(self) -> None:
        assert format_bytes(1024 ** 3) == "1.0 GB"

    def test_large_kb(self) -> None:
        # 500 KB → "500 KB" (digits == 0 because >= 100)
        assert format_bytes(500 * 1024) == "500 KB"

    def test_inf(self) -> None:
        assert format_bytes(float("inf")) == "0 B"


# ---------------------------------------------------------------------------
# format_percent
# ---------------------------------------------------------------------------

class TestFormatPercent:
    def test_none_total(self) -> None:
        assert format_percent(50) == "..."

    def test_zero_total(self) -> None:
        assert format_percent(50, 0) == "..."

    def test_full(self) -> None:
        assert format_percent(100, 100) == "100%"

    def test_half(self) -> None:
        assert format_percent(50, 100) == "50%"

    def test_small(self) -> None:
        assert format_percent(1, 100) == "1.0%"

    def test_clamp_over_100(self) -> None:
        assert format_percent(200, 100) == "100%"
