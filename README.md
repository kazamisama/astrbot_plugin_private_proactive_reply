# 私聊智能主动回复

> 📦 [astrbot_plugin_private_proactive_reply](https://github.com/kazamisama/astrbot_plugin_private_proactive_reply) · 🏷️ v0.5.0 · 📜 AGPL-3.0 · 🤖 AstrBot ≥ 4.8.0

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

测试完恢复默认即可。**自 v0.6.5 起，默认配置就是“首次主动回复期望约 3 小时”**（按 30s 扫描间隔做 4 万次蒙特卡洛模拟验证），即：

- `idle_after_minutes`: `175`（核心：把阈值拉到 175 min）
- `idle_probability_start`: `0.005`（极低，压制过早触发）
- `idle_probability_ramp_minutes`: `30`（短斜坡，几乎等同于"3 小时准时"）
- `min_interval_minutes`: `180`（两次主动消息硬下限，与 3h 期望对齐）
- `max_unanswered_times`: `5`；`quiet_hours`: `1-7`

实测分布：均值 179.5 min，p10 ≈ 177 min，p90 ≈ 183 min，标准差 ≈ 2.4 min。
若希望 ±4 min 抖动更自然，把 `idle_probability_start` 改为 `0.010`、`idle_probability_ramp_minutes` 改为 `60`（均值 ≈ 181.2 min，标准差 ≈ 3.4 min）。

> 说明：决定期望回复时间的主要旋钮是 `idle_after_minutes`，`idle_probability_start` 与 `idle_probability_ramp_minutes` 在 30s 扫描间隔下只控制方差，对均值影响很小（蒙特卡洛实测 0.005 / 0.010 / 0.020 之间的均值差 < 0.5 min）。

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

## 与情绪状态机联动（v0.5.0）

如果同时安装了 [`astrbot_plugin_emotion_state_machine`](https://github.com/kazamisama/astrbot_plugin_emotion_state_machine)，本插件会在拼装 system prompt 时把情绪插件输出的 prompt block 追加到末尾，让模型主动消息的语气与当前情绪状态对齐。

- 默认开启（`emotion_inject_enabled = true`）。
- 情绪插件**未装/未启用/未初始化**时**自动降级为空注入**，对未装该插件的用户行为完全不变。
- scope 传当前私聊 UMO（与情绪插件内置的 `get_scope(event)` 计算结果一致），user_id 透传会话里的 sender_id，让情绪插件能叠加 per-user relation 层。
- 远程调用抛错只产生 `logger.warning`，**永远不会中断主动消息生成**。

如果你想看情绪插件当前状态，可以在私聊里直接 `/emotion_state`（这是情绪插件自己的命令，与本插件独立）。

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
