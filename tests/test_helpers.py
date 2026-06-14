"""Basic helper tests for astrbot_plugin_private_proactive_reply."""

from __future__ import annotations

import importlib.util
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

PLUGIN_MAIN = Path(__file__).resolve().parents[1] / "main.py"


def load_module():
    spec = importlib.util.spec_from_file_location("private_proactive_main", PLUGIN_MAIN)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def make_plugin_stub(config: dict):
    module = load_module()
    plugin = object.__new__(module.PrivateProactiveReplyPlugin)
    plugin.config = config
    return plugin


def test_constants():
    module = load_module()
    assert module.PLUGIN_NAME == "astrbot_plugin_private_proactive_reply"
    assert module.STATE_SCHEMA_VERSION == 1


def test_default_prompt_contains_placeholders():
    module = load_module()
    prompt = module.PrivateProactiveReplyPlugin._default_prompt(object())
    assert "{{current_time}}" in prompt
    assert "{{idle_minutes}}" in prompt
    assert "{{unanswered_count}}" in prompt
    assert "{{last_user_message}}" in prompt
    assert "{{reason}}" in prompt
    assert "{{mood_hint}}" in prompt
    assert "{{message_hint}}" in prompt


def test_blocks_group_temporary_private_message():
    plugin = make_plugin_stub(
        {
            "ignore_non_friend_private": True,
            "allowed_private_sub_types": ["friend"],
        }
    )
    event = SimpleNamespace(
        message_obj=SimpleNamespace(
            raw_message={"message_type": "private", "sub_type": "group"}
        )
    )
    assert plugin._is_blocked_private_event(event) is True


def test_allows_friend_private_message():
    plugin = make_plugin_stub(
        {
            "ignore_non_friend_private": True,
            "allowed_private_sub_types": ["friend"],
        }
    )
    event = SimpleNamespace(
        message_obj=SimpleNamespace(
            raw_message={"message_type": "private", "sub_type": "friend"}
        )
    )
    assert plugin._is_blocked_private_event(event) is False


def test_defer_quiet_time_moves_to_non_quiet_hour():
    plugin = make_plugin_stub({"quiet_hours": "1-7", "timezone": "Asia/Shanghai"})
    ts = datetime(2026, 1, 1, 2, 0, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp()
    shifted = plugin._defer_quiet_time(ts)
    shifted_hour = datetime.fromtimestamp(shifted, tz=ZoneInfo("Asia/Shanghai")).hour
    assert shifted_hour == 7


def test_quiet_timestamp_crosses_midnight():
    plugin = make_plugin_stub({"quiet_hours": "23-7", "timezone": "Asia/Shanghai"})

    def hour(h: int) -> float:
        return datetime(2026, 1, 1, h, 30, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp()

    assert plugin._is_quiet_timestamp(hour(23)) is True
    assert plugin._is_quiet_timestamp(hour(2)) is True
    assert plugin._is_quiet_timestamp(hour(6)) is True
    assert plugin._is_quiet_timestamp(hour(7)) is False
    assert plugin._is_quiet_timestamp(hour(12)) is False
    assert plugin._is_quiet_timestamp(hour(22)) is False


def test_quiet_timestamp_empty_disables():
    plugin = make_plugin_stub({"quiet_hours": "", "timezone": "Asia/Shanghai"})
    ts = datetime(2026, 1, 1, 3, 0, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp()
    assert plugin._is_quiet_timestamp(ts) is False


def test_sanitize_llm_text_strips_wrappers():
    plugin = make_plugin_stub({"max_reply_chars": 300})
    assert plugin._sanitize_llm_text("```\n你好呀\n```") == "你好呀"
    assert plugin._sanitize_llm_text("发送：在忙吗") == "在忙吗"
    assert plugin._sanitize_llm_text('"早上好"') == "早上好"
    assert plugin._sanitize_llm_text("“晚安”") == "晚安"
    assert plugin._sanitize_llm_text("[object Object]") is None
    assert plugin._sanitize_llm_text("") is None


def test_sanitize_llm_text_truncates():
    plugin = make_plugin_stub({"max_reply_chars": 5})
    assert plugin._sanitize_llm_text("一二三四五六七") == "一二三四五"


def test_split_text_under_threshold_single_segment():
    plugin = make_plugin_stub({"segment_threshold_chars": 80})
    assert plugin._split_text("短句子") == ["短句子"]


def test_split_text_splits_on_punctuation():
    plugin = make_plugin_stub({"segment_threshold_chars": 4})
    segments = plugin._split_text("吃了吗？在忙吗！晚点聊")
    assert segments == ["吃了吗？", "在忙吗！", "晚点聊"]


def test_format_template_replaces_placeholders():
    plugin = make_plugin_stub({})
    result = plugin._format_template(
        "时间{{current_time}} 原因{{reason}}",
        {"current_time": "12:00", "reason": "问进度"},
    )
    assert result == "时间12:00 原因问进度"


def test_format_template_does_not_recurse_into_user_value():
    plugin = make_plugin_stub({})
    # A user-supplied value containing a placeholder literal must NOT be
    # re-expanded into another variable.
    result = plugin._format_template(
        "摘录：{{last_user_message}} 原因：{{reason}}",
        {"last_user_message": "他说 {{reason}}", "reason": "REAL"},
    )
    assert result == "摘录：他说 {reason} 原因：REAL"
