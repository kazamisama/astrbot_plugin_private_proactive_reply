# 更新日志

astrbot_plugin_private_proactive_reply 的所有版本变更记录。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [v0.6.2] - 2026-06-14

### Fixed

- **`_cfg_int` 缺少 `max_value` 参数 (TypeError 修复)**：
  v0.4.0 引入 `open_threads_max` 时，在 `_prepare_llm_request` 和
  `_apply_thread_action` 写成了 `_cfg_int("open_threads_max", 3, 1, 5)`，
  模仿 `_cfg_float` 的 `(key, default, min, max)` 形态，意图把
  `open_threads_max` 限制在 `[1, 5]`。但 `_cfg_int` 当时只升级到了
  `(key, default, min_value=None)`，没有 `max_value`。
  - 结果：每次主动消息生成都抛 `TypeError: _cfg_int() takes from
    3 to 4 positional arguments but 5 were given`，流程在
    `_prepare_llm_request` 处中断，主动消息一条也发不出去。
  - `_apply_thread_action` 处的同型调用未当场爆炸，是因为 LLM
    尚未输出过 `THREAD:push`，调用路径未走到。
  - v0.6.2 把 `_cfg_int` 升级到与 `_cfg_float` 对称的
    `(key, default, min_value=None, max_value=None)`，两处
    调用终于真正生效。

### Added

- 6 个单元测试覆盖：
  - 4 位置参数回归（曾经的 TypeError 现场）。
  - 超过 max → 上限裁剪。
  - 低于 min → 下限裁剪。
  - 3 位置参数旧形态继续工作（向后兼容）。
  - 非数字字符串 → 回退到 default。
  - 仅 `(key, default)` → 不裁剪。

## [v0.6.1] - 2026-06-14

### Fixed

- **`_cfg_float` NaN/inf hardens**:
  Hand-edited `config.json` (or programmatic writes) can carry
  the literal strings `"NaN"` / `"Infinity"` / `"-Infinity"`.
  Python `float()` accepts all three without raising, so a value
  like `idle_probability_start = NaN` was silently propagating
  into `_compute_idle_probability`, making `random.random() < prob`
  always False (silent loss of proactive replies); `idle_after_minutes`
  NaN/inf multiplied into `asyncio.sleep(...)` raised ValueError
  on inf and hung on NaN -- either way the scan loop broke.
  `_cfg_float` now rejects non-finite values via `math.isfinite`,
  logs a WARNING, and falls back to the default. Aligns with
  `emotion_state_machine` v0.3.1 and `social_context` v0.8.4.

### Added

- 6 new unit tests in `tests/test_helpers.py` covering the
  NaN / +inf / -inf string + numeric cases and a regression guard
  for normal value passthrough (including `min_value` / `max_value`
  clamps).

## [v0.6.0] - 2026-06-14

### Changed
- **适配 `astrbot_plugin_emotion_state_machine` v0.3.0 的 HTML 哨兵包裹**：
  esm 自 v0.3.0 起给 `build_prompt_block` 的输出包了
  `<!-- esm:emotion-block:start -->` / `<!-- esm:emotion-block:end -->`
  HTML 注释哨兵（用于自身 `_inject_emotion_block` 的去重/替换）。本插件
  在 `_build_emotion_block` 末尾用正则剥离哨兵后再拼到 system prompt，
  LLM 不会看到标记，只有纯情绪状态描述。
  - 哨兵格式常量（`ESM_SENTINEL_START` / `ESM_SENTINEL_END`）定义在
    模块级，re.escape 后做非贪婪 + DOTALL 匹配，容忍空行/前后空白变体。
  - 哨兵格式若未来变更，正则失配会自然降级为「原样透传」—— LLM 忽略
    HTML 注释，不会爆。

### Added
- 4 个新单元测试覆盖哨兵剥除：
  - 标准 `start\n{inner}\nend` 形态 → 剥除。
  - 带额外空行/缩进的变体 → 剥除。
  - 上游未来去掉哨兵时透传。
  - 端到端：append 后最终 system_prompt 不含哨兵。

### Backward compatibility
- 完全向后兼容：未安装 esm、或 esm 版本 < v0.3.0（未引入哨兵）的用户
  行为与 v0.5.0 一致。
- 不需要 esm 配合做任何改动。

## [v0.5.0] - 2026-06-14

### Added
- **跨插件联动 `astrbot_plugin_emotion_state_machine`**：在生成主动回复的 system prompt 末尾注入情绪状态机输出的 prompt block，让模型语气与当前情绪状态对齐。注入在 `_get_system_prompt` 内部完成，对原有 prompt 模板零侵入。
- **新增配置 `emotion_inject_enabled`**（默认 `true`）：一键关闭情绪注入。当情绪插件未装/未启用/未初始化时，**自动降级为空注入**，不需要用户做任何额外配置。
- 新增内部 helper：`_get_emotion_plugin()`（懒加载 + 防御性获取实例）、`_build_emotion_block()`（取 prompt block 并做类型/异常降级）、`_append_emotion_block()`（拼接到 system prompt）。
- 16 个新单元测试覆盖：常量、配置关闭、插件未装、插件不带公开方法、注册器抛错、远端调用抛错、远端返回非字符串、正常 happy path、append 拼接、尾部空白处理、空 persona fallback、user_id 透传与缺失、context 缺 `get_registered_star` 方法。

### Backward compatibility
- 完全向后兼容：未安装情绪插件的用户行为与 v0.4.0 一致。
- `_get_system_prompt` 在没有 persona 时仍允许情绪 block 单独出现，兼容「裸 system prompt」场景。

## [v0.4.0] - 2026-06-14

### Changed
- **default prompt 模板重构为多段式**：从单一「当前状态」段拆为「当前时间语境 / 对方近况 / 未完话题 / 排期线索 / 触发性质 / 风格档 / 安全风格 / 收尾指令」八段，LLM 能感知到时段、星期、是否周末、上次主动消息、未完话题列表等多维上下文。

### Added
- **THREAD: 控制行协议**：LLM 输出末尾可附 `THREAD: push|pop|none:<topic>` 一行；插件解析后维护 session 的 `open_threads` 列表（最多 `open_threads_max` 个），下次主动消息时 LLM 能看到这些未完话题，从而做到「承接上次未完话题」或「自然收尾」。
- **风格档（style_phase）**：根据 trigger 性质 + 是否有未完话题 + 未回复次数，自动归类到 `normal` / `followup` / `gentle_stepback` / `scheduled` 四档，prompt 中给出对应引导语。
- **时段感知**：新增 `_compute_time_context`，给出「清晨/午间/下午/晚上/深夜」+ 星期 + 是否周末，注入 prompt。
- **state schema v1 → v2**：v1 state 加载时**只在内存里**补全 v2 新字段（`last_proactive_time` / `last_proactive_reason` / `last_proactive_text_preview` / `open_threads` / `thread_updated_at`），不立即落盘；下一次有 state 变更时随 flush 一起升级到 v2（零侵入迁移）。
- 新增配置 `open_threads_max`（默认 3，slider 1~10）。
- 7 个新内部 helper：`_compute_time_context` / `_style_phase` / `_style_phase_guidance` / `_reason_guidance` / `_format_open_threads_section` / `_parse_thread_action` / `_apply_thread_action`。
- 18 个新单元测试覆盖时段映射（10 个 hour bucket）、星期判断、style_phase 转换矩阵、reason_guidance 已知 reason + 未知 reason、open_threads 渲染（空/有/超限）、THREAD: 解析（push/pop/none/大小写/无控制行/空输入/多行消息体）。

### Backward compatibility
- v1 state 文件无需手动迁移：插件启动时自动补全字段，首次有 state 变更时落盘升级。
- 旧 `proactive_prompt` 自定义模板仍可用：缺失的新占位符由 v0.2.3 的修复（未知 key 替换为空串）兜底；用户仍可在 prompt 里只引用关心的子集占位符。

### Schema
- `STATE_SCHEMA_VERSION`: 1 → 2。

## [v0.3.0] - 2026-06-14

### Changed
- **idle 触发改为概率曲线**：旧版「到 idle_after_minutes 阈值即触发」改为概率触发。空闲刚到阈值时只以 `idle_probability_start`（默认 0.3）的概率触发，随空闲时间在 `idle_probability_ramp_minutes`（默认 30 分钟）内线性爬升到 1.0；超过 ramp 后必触发。打散「30 分钟必来」的机械感。
- **扫描间隔叠加抖动**：`_scan_loop` 在 `scan_interval_seconds` 基础上叠加 `±scan_jitter_ratio`（默认 0.1，即 ±10%）的随机抖动，避免多会话在同一边界触发。

### Added
- 新增配置 `scan_jitter_ratio`（默认 0.1，范围 0.0~0.5）。
- 新增配置 `idle_probability_start`（默认 0.3，范围 0.0~1.0）。
- 新增配置 `idle_probability_ramp_minutes`（默认 30.0，范围 1.0~240.0）。
- 内部辅助方法：`_idle_probability_value`（纯函数，可独立单测）、`_idle_probability_roll`（掷骰子）。
- 内部辅助：`_cfg_float` 新增可选 `max_value` 参数，给三个新配置提供上限。
- 7 个新单元测试覆盖概率曲线各边界（threshold 上下、ramp 中点、ramp 末尾、ramp 之后、ramp=0、roll 极端值）。

### Backward compatibility
- 新配置都有默认值，向前兼容：旧配置实例无需任何变更即可享受新行为（保留默认值时）。
- 旧 `state.json` 不需要迁移（本次未改 schema）。
- 旧 `proactive_prompt` 自定义模板不受影响：新增占位符不会出现在旧模板中。

### Infrastructure
- 新增 `conftest.py`：在 pytest 独立运行时把 AstrBot 源码树注入 `sys.path`（v0.2.3 时代测试需要手动 `PYTHONPATH`，现可 `pytest` 直跑）。自动识别 `ASTRBOT_PATH` 环境变量 / AstrBot embedded layout / 默认 `C:/application/AstrBot/backend/app`。

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
