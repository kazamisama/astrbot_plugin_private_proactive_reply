# 更新日志

astrbot_plugin_private_proactive_reply 的所有版本变更记录。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [v0.2.0] - 2026-06-13

### Added
- 新增 LLM 自主排期工具 `schedule_private_proactive_reply`（`@filter.llm_tool`）。
  - 模型在私聊中可主动决定下一次主动回复的延迟、原因、语气和话题方向。
  - 工具会写入 `next_trigger_time / next_reason / next_mood_hint / next_message_hint / scheduled_by` 状态字段。
- 新增 `on_llm_request` 钩子，仅在真实好友私聊中向模型注入一段简短排期引导：
  - 提示可调用 `schedule_private_proactive_reply`，并明确要求只在确有后续价值时调用。
- 新增临时会话拦截配置 `ignore_non_friend_private` / `allowed_private_sub_types`：
  - 默认读取 aiocqhttp / OneBot 原始事件 `sub_type`，仅允许 `friend`。
  - QQ 群临时会话等 `sub_type != friend` 的私聊不再登记活跃，也不会进入排期/触发。
- 新增 `idle_fallback_enabled` 配置项：关闭后只消费 LLM 排期或管理员手动触发，不再按固定沉默时间兜底。
- 新增 4 个排期相关配置：
  - `llm_schedule_enabled`
  - `llm_schedule_prompt_enabled`
  - `llm_schedule_min_delay_minutes`（默认 10）
  - `llm_schedule_max_delay_minutes`（默认 1440）
- 新增 helper：`_is_blocked_private_event` / `_defer_quiet_time` / `_format_timestamp` / `_drop_schedule_fields` / `_clear_schedule`。

### Changed
- `_should_trigger` 重构为 `_get_trigger_reason`：优先消费模型排期，没有排期时再走 `idle_after_minutes` 兜底（前提是 `idle_fallback_enabled=true`）。
- 主动消息生成 prompt 新增占位符 `{{reason}}` / `{{mood_hint}}` / `{{message_hint}}`，让真正发送消息时能看到模型排期时的语气/话题线索。
- 主动消息发送成功和空响应都会清空 `next_trigger_time` 等排期字段，避免重复触发或无限循环。
- 排期延迟命中 `quiet_hours` 时，自动顺延到免打扰结束后。

### Security
- 排期延迟会被 clamp 到配置允许的最小/最大区间，模型请求无效值会被拒绝。
- 排期工具仍受 `min_interval_minutes` / `max_unanswered_times` / `session_list` 约束。
- 临时会话拦截默认开启，避免群临时会话被登记或被回复。

## [v0.1.0] - 2026-06-12

### Added
- 初版私聊智能主动回复插件。
- `on_private_message` 监听私聊活跃并刷新 `last_user_message_time`。
- `on_after_message_sent` 记录机器人最近一次私聊消息时间，用于最小间隔控制。
- 后台 `asyncio` 扫描器：沉默达到 `idle_after_minutes` 后调用当前会话 LLM 生成自然主动消息。
- 状态持久化到 `data/state.json`，支持 `session_list` 白名单或 `auto_register_sessions` 自动登记。
- 免打扰时段、最小间隔、连续未回复上限、沉默兜底等基础安全规则。
- 管理员命令 `/private_proactive status|list|enable|disable|trigger|reset`。
- README + `_conf_schema.json` + 基础 `tests/test_helpers.py`。
