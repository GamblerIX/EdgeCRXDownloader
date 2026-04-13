"""Tests for ``core.error``."""

from __future__ import annotations

from core.error import get_user_facing_error


class TestGetUserFacingError:
    def test_plain_string(self) -> None:
        assert get_user_facing_error("network failure") == "network failure"

    def test_blank_string_fallback(self) -> None:
        assert get_user_facing_error("   ") == "下载过程中发生未知错误，请稍后再试。"

    def test_exception(self) -> None:
        assert get_user_facing_error(ValueError("bad value")) == "bad value"

    def test_empty_exception(self) -> None:
        assert get_user_facing_error(ValueError("")) == "下载过程中发生未知错误，请稍后再试。"

    def test_object_with_message(self) -> None:
        class Err:
            message = "custom message"

        assert get_user_facing_error(Err()) == "custom message"

    def test_none_fallback(self) -> None:
        assert get_user_facing_error(None) == "下载过程中发生未知错误，请稍后再试。"
