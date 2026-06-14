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
    # v0.4.0: state schema bumped to v2 to track open_threads and
    # last_proactive_* fields. Migration is handled by _migrate_state.
    assert module.STATE_SCHEMA_VERSION == 2


def test_default_prompt_contains_placeholders():
    module = load_module()
    prompt = module.PrivateProactiveReplyPlugin._default_prompt(object())
    assert "{{current_time}}" in prompt
    assert "{{idle_minutes}}" in prompt
    assert "{{unanswered_count}}" in prompt
    assert "{{last_user_message}}" in prompt
    # v0.4.0: the bare {{reason}} is replaced by {{reason_guidance}}, a
    # human-readable explanation of the trigger context. {{reason}} is still
    # passed via variables (for back-compat with custom prompts).
    assert "{{reason_guidance}}" in prompt
    assert "{{mood_hint}}" in prompt
    assert "{{message_hint}}" in prompt
    # v0.4.0 additions
    assert "{{time_of_day}}" in prompt
    assert "{{day_of_week}}" in prompt
    assert "{{last_proactive_text_preview}}" in prompt
    assert "{{open_threads_section}}" in prompt
    assert "{{style_phase}}" in prompt
    assert "{{style_phase_guidance}}" in prompt
    assert "THREAD: <push|pop|none>" in prompt


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
    # re-expanded into another variable, regardless of dict iteration order.
    result = plugin._format_template(
        "摘录：{{last_user_message}} 原因：{{reason}}",
        {"last_user_message": "他说 {{reason}}", "reason": "REAL"},
    )
    assert result == "摘录：他说 {reason} 原因：REAL"

    # Reverse insertion order: if the impl still depended on dict order,
    # reason would already have been substituted and the user value would
    # then be re-expanded.
    result = plugin._format_template(
        "摘录：{{last_user_message}} 原因：{{reason}}",
        {"reason": "REAL", "last_user_message": "他说 {{reason}}"},
    )
    assert result == "摘录：他说 {reason} 原因：REAL"


def test_format_template_ignores_unknown_placeholders():
    plugin = make_plugin_stub({})
    # Unknown keys must be replaced with empty string, not left as literal
    # {{...}} in the output (which would either confuse the model or leak
    # template syntax into the prompt).
    result = plugin._format_template("a={{known}} b={{unknown}}", {"known": "X"})
    assert result == "a=X b="


def test_format_template_tolerates_whitespace_in_placeholder():
    plugin = make_plugin_stub({})
    result = plugin._format_template(
        "时间 {{ current_time }} 原因{{reason}}",
        {"current_time": "12:00", "reason": "问进度"},
    )
    assert result == "时间 12:00 原因问进度"


def test_idle_probability_value_below_threshold():
    plugin = make_plugin_stub({})
    # Below threshold: caller should not have called us, but stay defensive.
    assert plugin._idle_probability_value(1500, 1800, 0.3, 1800) == 0.0


def test_idle_probability_value_at_threshold():
    plugin = make_plugin_stub({})
    # At the threshold boundary the curve is still pinned to 0.0 (the
    # probability-curve logic only kicks in strictly past the threshold).
    assert plugin._idle_probability_value(1800, 1800, 0.3, 1800) == 0.0


def test_idle_probability_value_at_midpoint():
    plugin = make_plugin_stub({})
    # Halfway through the ramp: 0.3 + 0.7 * 0.5 = 0.65 (modulo float epsilon).
    value = plugin._idle_probability_value(2700, 1800, 0.3, 1800)
    assert round(value, 6) == 0.65


def test_idle_probability_value_at_ramp_end():
    plugin = make_plugin_stub({})
    assert plugin._idle_probability_value(3600, 1800, 0.3, 1800) == 1.0


def test_idle_probability_value_past_ramp():
    plugin = make_plugin_stub({})
    # Far past the ramp: pinned at 1.0.
    assert plugin._idle_probability_value(7200, 1800, 0.3, 1800) == 1.0


def test_idle_probability_value_zero_ramp():
    plugin = make_plugin_stub({})
    # ramp=0 means the curve has no room to climb; probability stays at
    # prob_start for the lifetime of the idle window.
    assert plugin._idle_probability_value(2000, 1800, 0.3, 0) == 0.3


def test_idle_probability_roll_respects_extremes():
    plugin = make_plugin_stub({})
    # prob_start=0 -> never fires (no matter how long the idle).
    assert plugin._idle_probability_roll(2000, 1800, 0.0, 1800) is False
    # prob_start=1 -> always fires.
    assert plugin._idle_probability_roll(2000, 1800, 1.0, 1800) is True


# ---------------------------------------------------------------------------
# v0.4.0 helpers: time context, style phase, thread actions
# ---------------------------------------------------------------------------


def test_compute_time_context_covers_all_buckets():
    plugin = make_plugin_stub({})
    cases = [
        (5, "清晨"),
        (10, "清晨"),
        (11, "午间"),
        (13, "午间"),
        (14, "下午"),
        (17, "下午"),
        (18, "晚上"),
        (22, "晚上"),
        (23, "深夜"),
        (4, "深夜"),
    ]
    for hour, expected in cases:
        dt = datetime(2026, 6, 15, hour, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        tod, _, _ = plugin._compute_time_context(dt)
        assert tod == expected, f"hour={hour} got {tod} expected {expected}"


def test_compute_time_context_weekday_and_weekend():
    plugin = make_plugin_stub({})
    # 2026-06-15 is a Monday
    dt = datetime(2026, 6, 15, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    _, day, is_weekend = plugin._compute_time_context(dt)
    assert day == "周一"
    assert is_weekend is False
    # 2026-06-20 is a Saturday
    dt = datetime(2026, 6, 20, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    _, day, is_weekend = plugin._compute_time_context(dt)
    assert day == "周六"
    assert is_weekend is True


def test_style_phase_scheduled_wins():
    plugin = make_plugin_stub({})
    # scheduled beats every other condition
    assert plugin._style_phase(0, [], "llm_scheduled") == "scheduled"
    assert plugin._style_phase(5, ["x"], "llm_scheduled") == "scheduled"


def test_style_phase_followup():
    plugin = make_plugin_stub({})
    # has threads + unanswered <= 2 -> followup
    assert plugin._style_phase(0, ["a"], "idle_scan") == "followup"
    assert plugin._style_phase(2, ["a", "b"], "manual") == "followup"
    # unanswered == 2 still followup when threads exist
    assert plugin._style_phase(2, ["a"], "idle_scan") == "followup"


def test_style_phase_gentle_stepback():
    plugin = make_plugin_stub({})
    # unanswered >= 3 -> gentle_stepback
    assert plugin._style_phase(3, [], "idle_scan") == "gentle_stepback"
    assert plugin._style_phase(5, ["a"], "idle_scan") == "gentle_stepback"


def test_style_phase_normal_default():
    plugin = make_plugin_stub({})
    # no threads + unanswered < 3
    assert plugin._style_phase(0, [], "idle_scan") == "normal"
    assert plugin._style_phase(2, [], "idle_scan") == "normal"


def test_style_phase_guidance_all_phases_nonempty():
    plugin = make_plugin_stub({})
    for phase in ["normal", "followup", "gentle_stepback", "scheduled"]:
        text = plugin._style_phase_guidance(phase)
        assert isinstance(text, str) and len(text) > 0, f"empty guidance for {phase}"


# ---------------------------------------------------------------------------
# v0.5.0 helpers: cross-plugin emotion_state_machine integration
# ---------------------------------------------------------------------------


def test_emotion_constants():
    module = load_module()
    assert module.EMOTION_STAR_NAME == "astrbot_plugin_emotion_state_machine"


def test_build_emotion_block_disabled_by_config():
    plugin = make_plugin_stub({"emotion_inject_enabled": False})
    # Even if a context that returns a star is present, config off wins.
    plugin.context = SimpleNamespace(get_registered_star=lambda _name: _FakeEmotionStar())
    assert plugin._build_emotion_block("scope", "u1") == ""


def test_build_emotion_block_plugin_absent():
    plugin = make_plugin_stub({})
    # Context returns None -> "plugin not installed" -> empty block.
    plugin.context = SimpleNamespace(get_registered_star=lambda _name: None)
    assert plugin._build_emotion_block("scope", "u1") == ""


def test_build_emotion_block_registry_missing_method():
    plugin = make_plugin_stub({})
    # Some other plugin shares the name but does not expose the API.
    plugin.context = SimpleNamespace(
        get_registered_star=lambda _name: SimpleNamespace(unrelated=1)
    )
    assert plugin._build_emotion_block("scope", "u1") == ""


def test_build_emotion_block_registry_raises():
    plugin = make_plugin_stub({})

    def boom(_name):
        raise RuntimeError("registry not ready")

    plugin.context = SimpleNamespace(get_registered_star=boom)
    # Must swallow the exception and return empty, not propagate.
    assert plugin._build_emotion_block("scope", "u1") == ""


def test_build_emotion_block_remote_call_raises():
    plugin = make_plugin_stub({})
    star = _FakeEmotionStar(raise_on_call=RuntimeError("engine down"))
    plugin.context = SimpleNamespace(get_registered_star=lambda _name: star)
    assert plugin._build_emotion_block("scope", "u1") == ""


def test_build_emotion_block_remote_call_non_string():
    plugin = make_plugin_stub({})
    star = _FakeEmotionStar(return_value=12345)  # not a str -> ignored
    plugin.context = SimpleNamespace(get_registered_star=lambda _name: star)
    assert plugin._build_emotion_block("scope", "u1") == ""


def test_build_emotion_block_happy_path():
    plugin = make_plugin_stub({})
    star = _FakeEmotionStar(return_value="<emotion>calm</emotion>")
    plugin.context = SimpleNamespace(get_registered_star=lambda _name: star)
    block = plugin._build_emotion_block("scope-A", "u1")
    assert block == "<emotion>calm</emotion>"
    # Verify the star saw the scope + user_id we passed (no normalization
    # tampering on our side).
    assert star.last_scope == "scope-A"
    assert star.last_user_id == "u1"


def test_append_emotion_block_disabled_short_circuits():
    plugin = make_plugin_stub({"emotion_inject_enabled": False})
    plugin.context = SimpleNamespace(get_registered_star=lambda _name: None)
    # No registry call expected; result is the base prompt unchanged.
    assert plugin._append_emotion_block("hello", "scope", None) == "hello"


def test_append_emotion_block_appends_with_blank_line():
    plugin = make_plugin_stub({})
    star = _FakeEmotionStar(return_value="<emotion>warm</emotion>")
    plugin.context = SimpleNamespace(get_registered_star=lambda _name: star)
    result = plugin._append_emotion_block("you are helpful", "scope", None)
    assert result == "you are helpful\n\n<emotion>warm</emotion>"


def test_append_emotion_block_strips_trailing_whitespace():
    plugin = make_plugin_stub({})
    star = _FakeEmotionStar(return_value="<emotion>x</emotion>")
    plugin.context = SimpleNamespace(get_registered_star=lambda _name: star)
    result = plugin._append_emotion_block("persona prompt   \n\n  ", "scope", None)
    # No spurious blank line between the persona and the emotion block.
    assert result == "persona prompt\n\n<emotion>x</emotion>"


def test_append_emotion_block_empty_base_returns_block_only():
    plugin = make_plugin_stub({})
    star = _FakeEmotionStar(return_value="<emotion>solo</emotion>")
    plugin.context = SimpleNamespace(get_registered_star=lambda _name: star)
    # When no persona is available we still want the emotion block to land
    # in the system prompt, not get swallowed.
    assert plugin._append_emotion_block("", "scope", None) == "<emotion>solo</emotion>"


def test_append_emotion_block_passes_user_id_when_present():
    plugin = make_plugin_stub({})
    star = _FakeEmotionStar(return_value="<emotion>u</emotion>")
    plugin.context = SimpleNamespace(get_registered_star=lambda _name: star)
    conversation = SimpleNamespace(user_id="alice", persona_id="p1")
    plugin._append_emotion_block("base", "scope", conversation)
    assert star.last_user_id == "alice"


def test_append_emotion_block_skips_user_id_when_absent():
    plugin = make_plugin_stub({})
    star = _FakeEmotionStar(return_value="<emotion>u</emotion>")
    plugin.context = SimpleNamespace(get_registered_star=lambda _name: star)
    # No user_id/sender_id on the conversation -> empty string -> emotion
    # plugin will skip the per-user relation layer (group snapshot only).
    plugin._append_emotion_block("base", "scope", SimpleNamespace(persona_id="p1"))
    assert star.last_user_id == ""


def test_get_emotion_plugin_uses_get_registered_star():
    plugin = make_plugin_stub({})
    captured = {}

    def fake_get(name):
        captured["name"] = name
        return _FakeEmotionStar()

    plugin.context = SimpleNamespace(get_registered_star=fake_get)
    star = plugin._get_emotion_plugin()
    assert isinstance(star, _FakeEmotionStar)
    assert captured["name"] == "astrbot_plugin_emotion_state_machine"


def test_get_emotion_plugin_context_without_method():
    plugin = make_plugin_stub({})
    # A context that lacks get_registered_star entirely -> None.
    plugin.context = SimpleNamespace()
    assert plugin._get_emotion_plugin() is None


class _FakeEmotionStar:
    """Test double for astrbot_plugin_emotion_state_machine's public API.

    Mirrors the only method this plugin calls (build_prompt_block). If the
    emotion plugin ever renames or removes that method, `_get_emotion_plugin`
    will return None instead of crashing — which is what we want.
    """

    def __init__(self, *, return_value: str = "<emotion>ok</emotion>", raise_on_call: Exception | None = None):
        self._return = return_value
        self._raise = raise_on_call
        self.last_scope: str | None = None
        self.last_user_id: str | None = None

    def build_prompt_block(self, scope: str, user_id: str = "") -> str:
        self.last_scope = scope
        self.last_user_id = user_id
        if self._raise is not None:
            raise self._raise
        return self._return


def test_reason_guidance_known_reasons():
    plugin = make_plugin_stub({})
    assert "沉默" in plugin._reason_guidance("idle_scan")
    assert "自己决定" in plugin._reason_guidance("llm_scheduled")
    assert "手动" in plugin._reason_guidance("manual")


def test_reason_guidance_unknown_returns_empty():
    plugin = make_plugin_stub({})
    assert plugin._reason_guidance("nonsense") == ""


def test_format_open_threads_section_empty():
    plugin = make_plugin_stub({})
    assert plugin._format_open_threads_section([], 3) == "（暂无）"


def test_format_open_threads_section_with_items():
    plugin = make_plugin_stub({})
    section = plugin._format_open_threads_section(["a", "b"], 3)
    assert "- a" in section
    assert "- b" in section


def test_format_open_threads_section_respects_limit():
    plugin = make_plugin_stub({})
    section = plugin._format_open_threads_section(["a", "b", "c", "d"], 2)
    # Only the most recent 2 should be shown
    assert "- a" not in section
    assert "- b" not in section
    assert "- c" in section
    assert "- d" in section


def test_parse_thread_action_push():
    plugin = make_plugin_stub({})
    body, action, payload = plugin._parse_thread_action("你好呀\nTHREAD: push:聊一下部署")
    assert body == "你好呀"
    assert action == "push"
    assert payload == "聊一下部署"


def test_parse_thread_action_pop():
    plugin = make_plugin_stub({})
    body, action, payload = plugin._parse_thread_action("晚安\nTHREAD: pop:聊一下部署")
    assert body == "晚安"
    assert action == "pop"
    assert payload == "聊一下部署"


def test_parse_thread_action_none_default():
    plugin = make_plugin_stub({})
    body, action, payload = plugin._parse_thread_action("只是普通消息")
    assert body == "只是普通消息"
    assert action == "none"
    assert payload is None


def test_parse_thread_action_none_with_colon():
    plugin = make_plugin_stub({})
    body, action, payload = plugin._parse_thread_action("嗯\nTHREAD: none:")
    assert body == "嗯"
    assert action == "none"
    assert payload is None


def test_parse_thread_action_case_insensitive():
    plugin = make_plugin_stub({})
    body, action, payload = plugin._parse_thread_action("x\nthread: PUSH:  Topic  ")
    assert body == "x"
    assert action == "push"
    assert payload == "Topic"


def test_parse_thread_action_empty_input():
    plugin = make_plugin_stub({})
    body, action, payload = plugin._parse_thread_action("")
    assert body == ""
    assert action == "none"
    assert payload is None


def test_parse_thread_action_keeps_unrelated_lines():
    plugin = make_plugin_stub({})
    body, action, payload = plugin._parse_thread_action("第一行\n第二行\nTHREAD: push:t\n第四行")
    assert action == "push"
    assert payload == "t"
    assert "第一行" in body
    assert "第二行" in body
    assert "第四行" in body
    assert "THREAD" not in body
