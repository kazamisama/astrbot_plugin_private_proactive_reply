# 更新日志

astrbot_plugin_private_proactive_reply 的所有版本变更记录。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [v0.2.3] - 2026-06-14

### Fixed
- **模板替换防二次注入**：原 `_format_template` 按 dict 插入顺序处理占位符，若用户消息（`last_user_message`）中包含 `{{other_key}}` 字面量，且 `other_key` 在 dict 中先于当前 key 被处理，用户值里的 `{{other_key}}` 会被替换为真实变量值，泄漏 prompt 模板结构。
  - 改为按占位符在模板中的出现顺序扫描处理。
  - 对替换值做 `{{` → `{` 脱敏，保证不会在后续 pass 变成新占位符。
  - 顺手补行为：占位符现在允许 `{{ key }}`（含空白）语法；未知 key 替换为空串，不再泄漏 `{{...}}` 字面量到 prompt。

## [v0.2.2] - 2026-06-14

### Fixed
- **状态落盘性能/锁竞争**：消息热路径不再在持锁状态下同步写盘。改为脏标记（`_mark_dirty`）+ 后台 `_flush_loop` 防抖批量落盘，插件停止时强制落盘。新增配置 `state_flush_interval_seconds`（默认 5 秒）。
- **`on_after_message_sent` 绕过白名单/临时会话拦截**：之前所有私聊机器人发言都会被 `_get_session_state` 自动建条目，污染状态并出现在 `list` 中。现在补上 `_is_blocked_private_event` + 白名单校验，且只刷新已登记会话。
- **timer_only 会话永久静默**：`trigger_without_user_message` 场景下用户从不回消息，`unanswered_count` 累加到上限后会永久静默。现在为这类会话标记 `timer_only`，命中上限后按 `min_interval_minutes` 冷却自动复位。
- `max_triggers_per_scan` 代码内默认值由 1 修正为 2，与 `_conf_schema.json` 保持一致。

### Added
- 管理员命令 `/private_proactive schedule [UMO]`：查看会话当前 LLM 排期。
- 管理员命令 `/private_proactive cancel [UMO]`：取消会话尚未触发的排期。
- 新增配置 `state_flush_interval_seconds`（状态落盘间隔）。
- 补充纯函数测试：跨午夜免打扰、`_sanitize_llm_text`、`_split_text`、模板占位符替换与防递归注入（共 13 个测试）。

## [v0.2.1] - 2026-06-13

### Changed
- 放宽主动回复的默认配置，降低触发门槛：
  - `idle_after_minutes`：120 → **30**（用户沉默 30 分钟即可触发）
  - `min_interval_minutes`：360 → **60**（两次机器人消息最小间隔 1 小时）
  - `max_unanswered_times`：3 → **5**（连续未回复上限放宽到 5 次）
  - `scan_interval_seconds`：60 → **30**（后台扫描频率提升到每 30 秒一次）
  - `max_triggers_per_scan`：1 → **2**（单轮扫描最多触发 2 个会话）
  - `llm_schedule_min_delay_minutes`：10 → **5**（LLM 自主排期最短延迟 5 分钟）

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
