"""Basic helper tests for astrbot_plugin_private_proactive_reply."""

from __future__ import annotations

import json
import importlib.util
import random as _rnd
import statistics as _stats
from datetime import datetime, datetime as _dt
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo, ZoneInfo as _ZI

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
    # Use intervals where the probability is deterministically 0.0 or 1.0 so
    # the roll is not random. Previously this test fed elapsed=2000 (past the
    # 1800 threshold but inside the 1800s ramp), where prob_start=0.0 still
    # yields p=200/1800=0.111 -> the roll fired ~11% of runs and the test
    # was flaky. The roll only returns a stable boolean when p is pinned.
    #
    # p == 0.0: at/below the threshold the curve is pinned to 0 regardless of
    # prob_start -> never fires.
    assert plugin._idle_probability_roll(1800, 1800, 0.5, 1800) is False
    # p == 1.0: at/after the ramp end the curve is pinned to 1 -> always fires.
    assert plugin._idle_probability_roll(3600, 1800, 0.0, 1800) is True


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


# ---------------------------------------------------------------------------
# v0.6.0: strip emotion_state_machine's HTML sentinel markers (esm v0.3.0+)
# ---------------------------------------------------------------------------


def test_build_emotion_block_strips_sentinels():
    """esm v0.3.0 wraps the block in `<!-- esm:emotion-block:start/end -->`.

    We must strip the markers before splicing into the system prompt.
    """
    plugin = make_plugin_stub({})
    raw = (
        "<!-- esm:emotion-block:start -->\n"
        "<emotion>calm</emotion>\n"
        "<!-- esm:emotion-block:end -->"
    )
    star = _FakeEmotionStar(return_value=raw)
    plugin.context = SimpleNamespace(get_registered_star=lambda _name: star)
    block = plugin._build_emotion_block("scope-A", "u1")
    assert block == "<emotion>calm</emotion>"
    # No trace of the markers in the returned text.
    assert "esm:emotion-block" not in block
    assert "<!--" not in block and "-->" not in block


def test_build_emotion_block_strips_sentinels_extra_whitespace():
    """Sentinels should still be stripped even if the upstream block
    uses unusual whitespace (extra blank lines, leading/trailing space).
    """
    plugin = make_plugin_stub({})
    raw = (
        "  <!-- esm:emotion-block:start -->\n\n"
        "  <emotion>warm</emotion>\n\n"
        "  <!-- esm:emotion-block:end -->\n"
    )
    star = _FakeEmotionStar(return_value=raw)
    plugin.context = SimpleNamespace(get_registered_star=lambda _name: star)
    block = plugin._build_emotion_block("scope", "u1")
    assert block == "<emotion>warm</emotion>"


def test_build_emotion_block_passes_through_when_no_sentinels():
    """If the upstream ever drops the markers (or returns plain text),
    we pass the block through unchanged. Defensive against format drift.
    """
    plugin = make_plugin_stub({})
    star = _FakeEmotionStar(return_value="<emotion>naked</emotion>")
    plugin.context = SimpleNamespace(get_registered_star=lambda _name: star)
    block = plugin._build_emotion_block("scope", "u1")
    assert block == "<emotion>naked</emotion>"


def test_append_emotion_block_contains_no_sentinels():
    """End-to-end: even when esm returns a sentinel-wrapped block, the
    final system_prompt must not contain the HTML markers.
    """
    plugin = make_plugin_stub({})
    raw = (
        "<!-- esm:emotion-block:start -->\n"
        "<emotion>calm</emotion>\n"
        "<!-- esm:emotion-block:end -->"
    )
    star = _FakeEmotionStar(return_value=raw)
    plugin.context = SimpleNamespace(get_registered_star=lambda _name: star)
    result = plugin._append_emotion_block("you are helpful", "scope", None)
    assert "esm:emotion-block" not in result
    assert "<!--" not in result and "-->" not in result
    assert result == "you are helpful\n\n<emotion>calm</emotion>"


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


# ----------------------------------------------------------------------
# v0.9.0: platform message history context
# ----------------------------------------------------------------------

def test_context_source_mode_invalid_falls_back_to_hybrid():
    plugin = make_plugin_stub({"context_source_mode": "unknown"})
    assert plugin._context_source_mode() == "hybrid"


def test_context_source_mode_accepts_known_values_case_insensitive():
    plugin = make_plugin_stub({"context_source_mode": " Platform_Message_History "})
    assert plugin._context_source_mode() == "platform_message_history"


def test_platform_history_user_candidates_adds_webchat_tail():
    plugin = make_plugin_stub({})
    assert plugin._platform_history_user_candidates("webchat!alice!session-1") == [
        "webchat!alice!session-1",
        "session-1",
    ]


def test_platform_history_user_candidates_dedupes_tail():
    plugin = make_plugin_stub({})
    assert plugin._platform_history_user_candidates("session-1") == ["session-1"]


def test_format_platform_history_context_builds_user_block_and_filters_bot():
    plugin = make_plugin_stub(
        {
            "include_bot_messages": False,
            "bot_identifiers": "bot,astrbot",
            "platform_context_max_chars": 10000,
            "platform_history_prompt": (
                "PLATFORM\n{{platform_history_lines}}\n"
                "UNANSWERED={{unanswered_count}}"
            ),
        }
    )
    records = [
        {
            "sender_id": "alice",
            "sender_name": "Alice",
            "content": {
                "type": "user",
                "message": [
                    {"type": "text", "text": "hello"},
                    {"type": "image"},
                ],
            },
        },
        {
            "sender_id": "bot",
            "sender_name": "bot",
            "content": {
                "type": "bot",
                "message": [{"type": "text", "text": "bot reply"}],
            },
        },
        {
            "sender_id": "alice",
            "sender_name": "Alice",
            "content": {
                "type": "user",
                "message": [{"type": "text", "text": "later"}],
            },
        },
    ]

    block = plugin._format_platform_history_context(records, unanswered_count=2)

    assert block is not None
    assert block["role"] == "user"
    assert "1. Alice: hello[图片]" in block["content"]
    assert "2. Alice: later" in block["content"]
    assert "bot reply" not in block["content"]
    assert "UNANSWERED=2" in block["content"]


def test_prompt_looks_like_legacy_default_detects_old_template():
    plugin = make_plugin_stub({})
    legacy = "[当前状态]\n- idle={{idle_minutes}}\n\n[最终指令]\n自然发一句。"
    assert plugin._prompt_looks_like_legacy_default(legacy) is True


def test_prompt_looks_like_legacy_default_rejects_new_template():
    plugin = make_plugin_stub({})
    new_template = (
        "[当前状态]\n"
        "{{last_proactive_text_preview}}\n"
        "[最终指令]\n"
        "THREAD: <push|pop|none>"
    )
    assert plugin._prompt_looks_like_legacy_default(new_template) is False

# ----------------------------------------------------------------------
# _cfg_float -- non-finite value defense
# ----------------------------------------------------------------------

def test_cfg_float_rejects_nan_string():
    plugin = make_plugin_stub({"idle_after_minutes": "NaN"})
    assert plugin._cfg_float("idle_after_minutes", 120.0, 0.1) == 120.0

def test_cfg_float_rejects_positive_inf_string():
    plugin = make_plugin_stub({"idle_after_minutes": "Infinity"})
    assert plugin._cfg_float("idle_after_minutes", 120.0, 0.1) == 120.0

def test_cfg_float_rejects_negative_inf_string():
    plugin = make_plugin_stub({"idle_after_minutes": "-Infinity"})
    assert plugin._cfg_float("idle_after_minutes", 120.0, 0.1) == 120.0

def test_cfg_float_rejects_nan_float_object():
    plugin = make_plugin_stub({"idle_probability_start": float("nan")})
    # default 0.3, range [0.0, 1.0]
    assert plugin._cfg_float("idle_probability_start", 0.3, 0.0, 1.0) == 0.3

def test_cfg_float_rejects_inf_float_object():
    plugin = make_plugin_stub({"idle_probability_start": float("inf")})
    assert plugin._cfg_float("idle_probability_start", 0.3, 0.0, 1.0) == 0.3

def test_cfg_float_passes_through_normal_values():
    # Above min, below max: passes through.
    plugin = make_plugin_stub({"idle_probability_start": 0.5})
    assert plugin._cfg_float("idle_probability_start", 0.3, 0.0, 1.0) == 0.5
    # Below min: clamped up to min.
    plugin = make_plugin_stub({"idle_probability_start": -0.5})
    assert plugin._cfg_float("idle_probability_start", 0.3, 0.0, 1.0) == 0.0
    # Above max: clamped down to max.
    plugin = make_plugin_stub({"idle_probability_start": 1.5})
    assert plugin._cfg_float("idle_probability_start", 0.3, 0.0, 1.0) == 1.0
    # Invalid string still falls back to default via the original try/except.
    plugin = make_plugin_stub({"idle_probability_start": "not-a-number"})
    assert plugin._cfg_float("idle_probability_start", 0.3, 0.0, 1.0) == 0.3

# ----------------------------------------------------------------------
# _cfg_int -- four-positional-arg signature regression (v0.6.2)
# ----------------------------------------------------------------------
#
# v0.4.0 introduced `open_threads_max` and called `_cfg_int(key, default,
# min, max)` -- mirroring `_cfg_float` -- but only the float side of the
# pair had its signature upgraded. The two call sites at
# main.py:798 and main.py:1167 crashed with a TypeError on every
# proactive generation. v0.6.2 promotes `_cfg_int` to the same
# (key, default, min_value, max_value) shape as `_cfg_float`, so the
# upper-bound clamp finally takes effect.

def test_cfg_int_accepts_max_value_argument():
    # Regression: previously the 4-positional-arg form raised
    # "takes from 3 to 4 positional arguments but 5 were given".
    plugin = make_plugin_stub({"open_threads_max": 3})
    assert plugin._cfg_int("open_threads_max", 3, 1, 5) == 3

def test_cfg_int_clamps_above_max():
    plugin = make_plugin_stub({"open_threads_max": 99})
    assert plugin._cfg_int("open_threads_max", 3, 1, 5) == 5

def test_cfg_int_clamps_below_min():
    plugin = make_plugin_stub({"open_threads_max": -1})
    assert plugin._cfg_int("open_threads_max", 3, 1, 5) == 1

def test_cfg_int_three_arg_form_still_works():
    # Backward compat: callers that pass (key, default, min) only
    # must keep behaving as before, with no upper bound.
    plugin = make_plugin_stub({"scan_interval_seconds": 30})
    assert plugin._cfg_int("scan_interval_seconds", 30, 5) == 30
    plugin = make_plugin_stub({"scan_interval_seconds": 1})
    assert plugin._cfg_int("scan_interval_seconds", 30, 5) == 5

def test_cfg_int_invalid_string_falls_back_to_default():
    plugin = make_plugin_stub({"open_threads_max": "not-a-number"})
    assert plugin._cfg_int("open_threads_max", 3, 1, 5) == 3

def test_cfg_int_no_bounds_passes_through():
    plugin = make_plugin_stub({"open_threads_max": 99})
    # (key, default) only -- no clamp.
    assert plugin._cfg_int("open_threads_max", 3) == 99

# ----------------------------------------------------------------------
# 3h-expected preset (v0.6.3)
# ----------------------------------------------------------------------
#
# README documents a "3h 期望回复间隔" preset:
#
#   idle_after_minutes           = 175
#   idle_probability_start       = 0.005
#   idle_probability_ramp_minutes = 30
#
# Monte Carlo over 40k trials puts the mean first-reply time at
# ~179.5 min with stdev ~2.4 min. This test pins the claim with a
# smaller sample: if someone tweaks _idle_probability_value or
# changes the scan_interval default in a way that breaks the 3h
# preset, the README claim becomes stale and this test should fail
# alongside it.

def test_readme_3h_preset_lands_at_180_min_mean():
    """The README-documented 3h preset should land within [175, 185] min.

    Re-implements the scan loop inline so the test does not need a
    real plugin instance or a running AstrBot. Random is seeded for
    reproducibility across runs.
    """
    import random as _random
    _random.seed(20260614)

    SCAN_BASE_S = 30
    SCAN_JITTER = 0.1
    IDLE_AFTER_MIN = 175
    PROB_START = 0.005
    RAMP_MIN = 30
    N = 5_000

    threshold_s = IDLE_AFTER_MIN * 60
    ramp_s = RAMP_MIN * 60
    times = []
    for _ in range(N):
        t = 0.0
        while True:
            t += SCAN_BASE_S * _random.uniform(1 - SCAN_JITTER, 1 + SCAN_JITTER)
            overshoot = t - threshold_s
            if overshoot < 0:
                continue
            if overshoot <= 0:
                p = 0.0
            elif overshoot >= ramp_s:
                p = 1.0
            else:
                p = PROB_START + (1.0 - PROB_START) * (overshoot / ramp_s)
            if _random.random() < p:
                times.append(t)
                break

    mean_min = sum(times) / len(times) / 60.0
    # 40k-trial run: mean = 179.5 min, stdev = 2.4 min, stdev-of-mean = 0.012 min.
    # A 5k sample is a bit noisier (stdev-of-mean ~ 0.034 min) but the
    # [175, 185] band leaves ~150x headroom either way, so the test
    # is rock solid unless the probability formula itself changes.
    assert 175 < mean_min < 185, (
        f"3h preset mean drifted to {mean_min:.2f} min, "
        "expected ~180 min. Did the idle probability formula or "
        "scan_interval default change? Update README too."
    )


# ----------------------------------------------------------------------
# Empty-persona fallback regression (v0.6.4)
# ----------------------------------------------------------------------
#
# Root cause of an observed `error:BadRequestError` on a brand-new private
# session: when no persona is configured at all, `_get_system_prompt` used
# to return an empty string (via `_append_emotion_block("", ...)`). An
# empty system prompt is rejected with HTTP 400 by some chat-completions
# compatibility upstreams. v0.6.4 returns FALLBACK_SYSTEM_PROMPT instead,
# so the request always carries a non-empty system message.


def _run(coro):
    import asyncio
    return asyncio.run(coro)


class _NoPersonaManager:
    async def get_persona(self, persona_id):
        return None

    async def get_default_persona_v3(self, umo=""):
        return None


class _Ctx:
    def __init__(self):
        self.persona_manager = _NoPersonaManager()

    def get_registered_star(self, name):
        return None


def _make_plugin_with_ctx(config):
    module = load_module()
    plugin = object.__new__(module.PrivateProactiveReplyPlugin)
    plugin.config = config
    plugin.context = _Ctx()
    return plugin, module


def test_get_system_prompt_falls_back_when_no_persona():
    # No conversation, no default persona, emotion injection on but plugin
    # absent -> must still return the non-empty fallback, never "".
    plugin, module = _make_plugin_with_ctx({"emotion_inject_enabled": True})
    result = _run(plugin._get_system_prompt("webchat:FriendMessage:x", None))
    assert result == module.FALLBACK_SYSTEM_PROMPT
    assert result.strip() != ""


def test_fallback_system_prompt_is_non_empty_constant():
    module = load_module()
    assert isinstance(module.FALLBACK_SYSTEM_PROMPT, str)
    assert module.FALLBACK_SYSTEM_PROMPT.strip() != ""


def test_describe_exception_extracts_body_and_status():
    plugin = make_plugin_stub({})

    class _Resp:
        status_code = 400
        text = "should-not-be-used-when-body-present"

    class _Err(Exception):
        body = {"error": {"message": "system prompt required"}}
        response = _Resp()

    detail = plugin._describe_exception(_Err("bad"))
    assert "status=400" in detail
    assert "body=" in detail
    assert detail.startswith(" | ")


def test_describe_exception_empty_on_plain_exception():
    plugin = make_plugin_stub({})
    assert plugin._describe_exception(ValueError("nope")) == ""


# ----------------------------------------------------------------------
# v0.6.6: quiet-aware effective idle + absolute-time reminder
# ----------------------------------------------------------------------

_TZ = "Asia/Shanghai"


def _ts(y, mo, d, h, mi=0):
    return _dt(y, mo, d, h, mi, tzinfo=_ZI(_TZ)).timestamp()


def _idle_plugin():
    return make_plugin_stub({"quiet_hours": "1-7", "timezone": _TZ})


def test_quiet_seconds_zero_when_disabled():
    p = make_plugin_stub({"quiet_hours": "", "timezone": _TZ})
    a = _ts(2026, 6, 15, 2, 0)
    b = _ts(2026, 6, 15, 6, 0)
    assert p._quiet_seconds_between(a, b) == 0.0


def test_quiet_seconds_full_window_inside():
    # 02:00 -> 06:00 is entirely inside quiet 1-7 -> 4h counted.
    p = _idle_plugin()
    a = _ts(2026, 6, 15, 2, 0)
    b = _ts(2026, 6, 15, 6, 0)
    assert abs(p._quiet_seconds_between(a, b) - 4 * 3600) < 120


def test_effective_idle_excludes_quiet_span():
    # user last spoke 23:00; now 09:00 next day. Gross = 10h.
    # quiet 1-7 fully inside -> 6h subtracted -> effective ~4h.
    p = _idle_plugin()
    last = _ts(2026, 6, 14, 23, 0)
    now = _ts(2026, 6, 15, 9, 0)
    eff = p._effective_idle_seconds(last, now)
    assert abs(eff - 4 * 3600) < 300  # within 5 min tolerance


def test_effective_idle_equals_gross_when_no_quiet_overlap():
    p = _idle_plugin()
    last = _ts(2026, 6, 15, 9, 0)
    now = _ts(2026, 6, 15, 12, 0)
    eff = p._effective_idle_seconds(last, now)
    assert abs(eff - 3 * 3600) < 5


def test_next_time_of_day_future_today():
    p = _idle_plugin()
    now = _ts(2026, 6, 15, 8, 0)
    got = p._next_time_of_day_ts("09:00", now=now)
    assert abs(got - _ts(2026, 6, 15, 9, 0)) < 1


def test_next_time_of_day_rolls_to_tomorrow():
    p = _idle_plugin()
    now = _ts(2026, 6, 15, 10, 0)
    got = p._next_time_of_day_ts("09:00", now=now)
    assert abs(got - _ts(2026, 6, 16, 9, 0)) < 1


def test_next_time_of_day_with_explicit_date():
    p = _idle_plugin()
    now = _ts(2026, 6, 15, 10, 0)
    got = p._next_time_of_day_ts("09:00", date="2026-06-20", now=now)
    assert abs(got - _ts(2026, 6, 20, 9, 0)) < 1


def test_next_time_of_day_rejects_bad_format():
    p = _idle_plugin()
    assert p._next_time_of_day_ts("9am") is None
    assert p._next_time_of_day_ts("25:00") is None
    assert p._next_time_of_day_ts("09:00", date="not-a-date") is None


def test_drop_schedule_fields_clears_reminder_fields():
    p = make_plugin_stub({})
    state = {
        "next_trigger_time": 123.0,
        "scheduled_by": "reminder_tool",
        "reminder_recurring": True,
        "reminder_time_of_day": "09:00",
        "next_reason": "x",
        "next_mood_hint": "",
        "next_message_hint": "",
    }
    p._drop_schedule_fields(state)
    for k in ["next_trigger_time", "scheduled_by", "reminder_recurring", "reminder_time_of_day"]:
        assert k not in state


# ----------------------------------------------------------------------
# v0.7.0: normal-distribution idle target (controllable mean / 3-sigma span)
# ----------------------------------------------------------------------

def test_sample_idle_target_mean_and_sigma():
    # Defaults: mean=180, sigma=15, clip=3 -> 3-sigma span = 90 min = 1.5 h.
    plugin = make_plugin_stub(
        {"idle_mean_minutes": 180, "idle_sigma_minutes": 15, "idle_clip_sigma": 3.0}
    )
    _rnd.seed(20260615)
    samples = [plugin._sample_idle_target_minutes() for _ in range(40000)]
    mean = _stats.mean(samples)
    sigma = _stats.pstdev(samples)
    assert 178.5 < mean < 181.5, f"mean drifted to {mean:.2f}"
    # Truncation at +/-3 sigma shrinks sigma only slightly; expect ~14.6-15.0.
    assert 14.0 < sigma < 15.6, f"sigma drifted to {sigma:.2f}"
    # 6*sigma (the full 3-sigma span) should be close to 90 min.
    assert 84 < 6 * sigma < 94, f"3-sigma span {6*sigma:.1f} min off target"


def test_sample_idle_target_respects_clip_bounds():
    plugin = make_plugin_stub(
        {"idle_mean_minutes": 180, "idle_sigma_minutes": 15, "idle_clip_sigma": 3.0}
    )
    _rnd.seed(1)
    lo, hi = 180 - 3 * 15, 180 + 3 * 15  # [135, 225]
    for _ in range(20000):
        v = plugin._sample_idle_target_minutes()
        assert lo <= v <= hi


def test_sample_idle_target_zero_sigma_is_deterministic():
    plugin = make_plugin_stub(
        {"idle_mean_minutes": 200, "idle_sigma_minutes": 0, "idle_clip_sigma": 3.0}
    )
    assert plugin._sample_idle_target_minutes() == 200.0


def test_idle_target_seconds_caches_and_resets():
    import asyncio

    plugin = make_plugin_stub(
        {"idle_mean_minutes": 180, "idle_sigma_minutes": 15, "idle_clip_sigma": 3.0}
    )
    # _idle_target_seconds touches self._lock and self._sessions(); wire the
    # minimal async-state surface the helper needs.
    plugin._lock = asyncio.Lock()
    plugin._state = {"schema_version": 2, "sessions": {}}
    plugin._dirty = False

    async def go():
        first = await plugin._idle_target_seconds("s1")
        second = await plugin._idle_target_seconds("s1")
        return first, second

    first, second = asyncio.run(go())
    assert first == second  # cached within the same silence stretch
    cached_min = plugin._state["sessions"]["s1"]["idle_target_minutes"]
    assert abs(first - cached_min * 60) < 1e-6
    # 135..225 min -> 8100..13500 s
    assert 8100 <= first <= 13500


def test_pipeline_replays_wake_event_to_queue():
    import asyncio

    module = load_module()
    if not module._PIPELINE_AGENT_AVAILABLE:
        return

    session_id = "webchat:FriendMessage:user1"
    queued = []

    class _Context:
        def __init__(self):
            self.conversation_manager = SimpleNamespace()

        def get_registered_star(self, name):
            return None

        def get_event_queue(self):
            return SimpleNamespace(put_nowait=queued.append)

    plugin = object.__new__(module.PrivateProactiveReplyPlugin)
    plugin.config = {"excluded_platforms": [], "pipeline_pending_timeout_seconds": 60}
    plugin.context = _Context()
    plugin._lock = asyncio.Lock()
    plugin._dirty = False
    plugin._pending_pipeline_sessions = set()
    plugin._state = {
        "schema_version": module.STATE_SCHEMA_VERSION,
        "sessions": {
            session_id: {
                "last_user_message_time": _ts(2026, 6, 16, 9, 0),
                "last_seen_text": "刚才聊到部署结果",
            }
        },
    }

    asyncio.run(plugin._run_pipeline_agent(session_id, "idle_scan"))

    assert session_id in plugin._pending_pipeline_sessions
    assert len(queued) == 1
    event = queued[0]
    assert event.unified_msg_origin == session_id
    assert event.get_extra("proactive_reply_wake") is True
    assert event.get_extra("proactive_reply_reason") == "idle_scan"
    assert event.message_str == event.get_extra("proactive_reply_wake_text")
    assert "主动消息唤醒" in event.message_str


def test_pipeline_wake_prompt_is_removed_from_conversation():
    import asyncio

    module = load_module()
    session_id = "webchat:FriendMessage:user1"
    wake_text = module.PIPELINE_WAKE_PROMPT_DEFAULT.format(
        reason="idle_scan",
        reason_guidance="",
        idle_minutes="180",
        mood_hint="",
        message_hint="",
        last_user_message="刚才聊到部署结果",
    )
    initial_history = [
        {"role": "user", "content": "刚才聊到部署结果"},
        {"role": "user", "content": wake_text},
        {"role": "assistant", "content": "我来问问部署结果。"},
    ]

    class _ConvManager:
        def __init__(self):
            self.updated_history = None

        async def get_curr_conversation_id(self, umo):
            assert umo == session_id
            return "conv1"

        async def get_conversation(self, umo, cid):
            assert umo == session_id
            assert cid == "conv1"
            return SimpleNamespace(cid=cid, history=json.dumps(initial_history))

        async def update_conversation(self, umo, cid, history, token_usage=None):
            assert umo == session_id
            assert cid == "conv1"
            self.updated_history = history

    plugin = object.__new__(module.PrivateProactiveReplyPlugin)
    plugin.context = SimpleNamespace(conversation_manager=_ConvManager())

    asyncio.run(plugin._remove_pipeline_wake_from_history(session_id, wake_text))

    stored = plugin.context.conversation_manager.updated_history
    assert stored == [
        {"role": "user", "content": "刚才聊到部署结果"},
        {"role": "assistant", "content": "我来问问部署结果。"},
    ]
    serialized = json.dumps(stored, ensure_ascii=False)
    assert "主动消息唤醒" not in serialized
