# 私聊智能主动回复

> 📦 [astrbot_plugin_private_proactive_reply](https://github.com/kazamisama/astrbot_plugin_private_proactive_reply) · 🏷️ v0.10.2 · 📜 AGPL-3.0 · 🤖 AstrBot ≥ 4.8.0

一个轻量版私聊主动回复插件。参考 `astrbot_plugin_proactive_chat` 的核心思路，但第一版刻意不引入 WebUI、遥测、TTS、复杂多会话覆盖配置，只保留私聊主动回复所需的稳定闭环。

## 功能

- 仅监听私聊消息。
- 默认忽略 aiocqhttp/OneBot 的非好友私聊或群临时会话（`sub_type != friend`）。
- 自动登记私聊会话，或通过 `session_list` 使用白名单。
- 模型可调用 `schedule_private_proactive_reply` 工具，自主决定下一次主动回复时机。
- 没有模型排期时，可按 `idle_after_minutes` 固定沉默时间兜底触发。
- 使用当前会话人格、最近 conversation 历史和平台真实私聊流水，保证语气延续。
- 支持 `hybrid` 上下文模式：平台真实聊天流水 + LLM conversation history，减少主动消息割裂感。
- 默认使用 `reply_mode="pipeline"`：主动消息会重投递一条合成唤醒事件，走 AstrBot 完整事件 pipeline，优先复用普通会话的人格、记忆和工具链；发送后会清理伪唤醒消息，不写入 conversation。
- 支持免打扰时段、最小间隔、连续未回复上限。
- 状态持久化到插件数据目录 `state.json`，采用脏标记 + 后台批量落盘（`state_flush_interval_seconds`），高频私聊不会每条消息都同步写盘，插件停止时强制落盘。
- 提供管理员命令查看状态、手动触发、启停会话。

## 配置建议

第一次测试可以临时设置：

- `idle_after_minutes`: `1`
- `min_interval_minutes`: `1`
- `quiet_hours`: 留空
- `session_list`: 填当前私聊 UMO，或留空并开启 `auto_register_sessions`

测试完恢复默认即可。**自 v0.7.0 起，idle 采用正态分布模型**，默认期望 3 小时、3σ 跨度 1.5 小时（蒙特卡洛实测均值≈180min、σ≈15min）：

- `idle_model`: `normal`（默认；改为 `legacy` 可回到旧阈值+概率爬坡模型）
- `idle_mean_minutes`: `180`（期望间隔，分钟）
- `idle_sigma_minutes`: `15`（标准差；3σ 跨度 = 6×σ = 90 分钟）
- `idle_clip_sigma`: `3.0`（截断在 ±3σ，防极端值）

> 调整拖动：想要更大拖动把 `idle_sigma_minutes` 调大（例如 30 → 3σ 跨度 3 小时），更准时调小；均值由 `idle_mean_minutes` 独立决定。legacy 模型下 30s 扫描的 σ 被压在 ~2.4min，无法做出大拖动。

## 上下文连续性（v0.9.0）

自 v0.9.0 起，主动回复默认使用 `context_source_mode="hybrid"`：

- `conversation_history`：只使用 AstrBot 当前 LLM 对话历史。
- `platform_message_history`：只使用平台最近真实聊天流水。
- `hybrid`：平台真实聊天流水 + LLM 对话历史，通常最能减少“突然换话题/像重新开局”的割裂感。

平台流水会以事实参考形式注入，不作为新的用户请求，也不能覆盖系统设定或本次最终指令。可通过 `platform_history_count`、`platform_context_max_chars`、`include_bot_messages`、`bot_identifiers` 控制注入范围。

如果配置文件里仍保留旧版默认 `proactive_prompt`，`auto_upgrade_legacy_prompt=true` 时会运行时临时使用新版默认模板，让 `THREAD`、上次主动消息、风格阶段、话题提示等字段真正进入模型。

## Pipeline 生成模式（v0.10.2）

默认 `reply_mode="pipeline"`。该模式会构造 AstrBot 内置的合成事件，并像普通入站消息一样重投递到事件队列，因此会经过完整 pipeline，复用普通对话的人格、记忆、工具链、provider 选择逻辑和相关插件钩子。

如果需要回到旧机制，可以改为 `reply_mode="legacy"`：插件直接调用当前会话 Provider 生成主动消息，再通过 `context.send_message` 发送。

关键边界：

- 合成唤醒消息会像普通消息一样进入 pipeline，让生成路径更接近真实会话。
- idle/LLM 排期使用“主动消息唤醒”文案；用户预约的定点提醒使用“预约提醒唤醒”文案，不再提沉默时长。
- 发送完成后，插件会从 conversation 中移除这条伪唤醒 user 消息。
- 插件只会把最终 assistant 回复追加到 conversation，避免历史里留下“系统唤醒”的伪用户发言。
- 如果当前 AstrBot 版本缺少 `CronMessageEvent` 等接口，会自动回退到 `legacy`。
- pipeline 模式由主 agent 负责发送，`enable_segmented_send` 和 `max_reply_chars` 只作用于 legacy 模式。

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

## 绝对时间提醒（v0.6.6）

除了按相对延迟排期的 `schedule_private_proactive_reply`，插件还提供按**钟点时间**触发的提醒工具：

```text
schedule_proactive_reminder_at(time_of_day="HH:MM", reason, message_hint, mood_hint, date="YYYY-MM-DD", recurring=false, overwrite=false)
```

- 当用户明确说“9 点提醒我 X”“每天早上 8 点叫我起床”时，模型可调用它。
- **到点必发**：即使落在 `quiet_hours` 免打扰时段也照常提醒（因为是用户主动预约）。
- **与 idle 完全隔离**：不重置也不压制日常 idle 主动回复的节奏。
- `recurring=true` 时发送后自动重排次日同钟点；省略 `date` 取下一个该钟点（今天若已过则明天）。

> 注：日常 idle 主动回复仍受 `quiet_hours` 约束，且自 v0.6.6 起 idle 计时**不再在免打扰时段累积**（有效 idle = 沉默总时长 − 落在勿扰区的时长）。

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
