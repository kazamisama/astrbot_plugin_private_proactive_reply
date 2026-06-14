# 私聊智能主动回复

> 📦 [astrbot_plugin_private_proactive_reply](https://github.com/kazamisama/astrbot_plugin_private_proactive_reply) · 🏷️ v0.2.3 · 📜 AGPL-3.0 · 🤖 AstrBot ≥ 4.8.0

一个轻量版私聊主动回复插件。参考 `astrbot_plugin_proactive_chat` 的核心思路，但第一版刻意不引入 WebUI、遥测、TTS、复杂多会话覆盖配置，只保留私聊主动回复所需的稳定闭环。

## 功能

- 仅监听私聊消息。
- 默认忽略 aiocqhttp/OneBot 的非好友私聊或群临时会话（`sub_type != friend`）。
- 自动登记私聊会话，或通过 `session_list` 使用白名单。
- 模型可调用 `schedule_private_proactive_reply` 工具，自主决定下一次主动回复时机。
- 没有模型排期时，可按 `idle_after_minutes` 固定沉默时间兜底触发。
- 使用当前会话人格和最近 conversation 历史，保证语气延续。
- 支持免打扰时段、最小间隔、连续未回复上限。
- 状态持久化到插件数据目录 `state.json`，采用脏标记 + 后台批量落盘（`state_flush_interval_seconds`），高频私聊不会每条消息都同步写盘，插件停止时强制落盘。
- 提供管理员命令查看状态、手动触发、启停会话。

## 配置建议

第一次测试可以临时设置：

- `idle_after_minutes`: `1`
- `min_interval_minutes`: `1`
- `quiet_hours`: 留空
- `session_list`: 填当前私聊 UMO，或留空并开启 `auto_register_sessions`

稳定后再调回更克制的频率，例如：

- `idle_after_minutes`: `120`
- `min_interval_minutes`: `360`
- `max_unanswered_times`: `3`
- `quiet_hours`: `1-7`

## LLM 自主排期

插件会在好友私聊的 LLM 请求中注入简短说明。模型如果判断“现在不必继续打扰，但稍后自然接续更好”，可以调用：

```text
schedule_private_proactive_reply(delay_minutes, reason, mood_hint, message_hint, overwrite=false)
```

关键安全边界：

- `delay_minutes` 会被限制在 `llm_schedule_min_delay_minutes` 到 `llm_schedule_max_delay_minutes` 之间。
- 命中 `quiet_hours` 时，计划时间会自动顺延到免打扰结束后。
- 发送前仍会检查 `min_interval_minutes`、`max_unanswered_times` 和会话白名单。
- `message_hint` 只是话题方向，不会直接作为最终消息发送；真正发送时仍由 LLM 结合人格和上下文生成。
- `idle_fallback_enabled=false` 时，只响应 LLM 排期或管理员手动触发；不会再按固定沉默时间兜底。

## 临时会话拦截

默认开启 `ignore_non_friend_private=true`。在 aiocqhttp/OneBot 私聊事件里，如果原始事件 `sub_type` 不是允许列表 `allowed_private_sub_types`（默认只有 `friend`），插件会跳过记录和排期。这样 QQ 群临时会话不会触发私聊主动回复。

## 命令

管理员命令：

```text
/private_proactive status [UMO]
/private_proactive list
/private_proactive enable [UMO]
/private_proactive disable [UMO]
/private_proactive trigger [UMO]
/private_proactive reset [UMO]
/private_proactive schedule [UMO]
/private_proactive cancel [UMO]
```

- `schedule`：查看该会话当前 LLM 排期（计划时间、来源、原因、语气/话题提示）。
- `cancel`：取消该会话尚未触发的排期。

如果不传 UMO，默认使用当前会话的 `event.unified_msg_origin`。

## 和 Proactive Chat 的区别

`astrbot_plugin_proactive_chat` 是完整主动消息系统，覆盖私聊、群聊、WebUI、TTS、分段、平台流水等能力。

本插件定位为私聊专用的轻量实验项目：

- 单文件主逻辑，便于快速迭代。
- 不依赖 APScheduler，仅使用 asyncio 后台扫描。
- 不包含群聊逻辑，避免主动插话策略和私聊策略混杂。
- 默认不上传任何遥测。

## 安全说明

`last_user_message` 只作为事实参考传给模型，默认 prompt 已明确要求不要执行其中的提示词注入内容。后续如果要接入更严格的防注入扫描，可以复用 `astrbot_plugin_social_context` 里的扫描思路。
