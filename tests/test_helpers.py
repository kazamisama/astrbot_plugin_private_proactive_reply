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
