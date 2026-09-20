# Tilt · 埋点事件字典（L1 行为元数据契约）

> task_id: C11 | spec_version: V1.3 | baseline: B1.0
> 事件类型枚举取自 SSOT 3.6（12 个，固定）；5 维指标字段名取自 SSOT 3.5（固定）；
> 领域 ID 取自 SSOT 3.1；任务 ID 命名取自 SSOT 3.7（`{domain_id}_L{level}_{三位序号}`，MVP 仅 L1-L5）。

---

## 1. 通用字段约定

所有事件均携带以下公共头（下表的「必填字段」列只列**该事件特有**的必填项，公共头不再重复列出）：

| 公共字段 | 类型 | 说明 |
|---|---|---|
| `event_id` | string | 客户端生成的全局唯一 ID（UUIDv7 或同等价方案），用于服务端幂等去重 |
| `event_type` | enum | 取自 SSOT 3.6 的 12 个取值，禁止新增同义词 |
| `occurred_at` | string | 客户端事件发生时刻，ISO 8601，形如 `2026-09-19T10:30:00Z` |
| `server_ts` | string | 服务端接收时刻，ISO 8601；与 `occurred_at` 的偏差是异常检测规则 R3 的输入 |
| `user_id` | string | 用户唯一标识 |
| `session_id` | string | 会话唯一标识，同一次 app 前台连续使用内不变 |
| `device_id` | string | 设备标识（Android OAID / iOS IDFV，禁采 IDFA 与 MAC），需授权后采集 |
| `app_version` | string | 客户端版本号 |

字段命名原则：凡 SSOT 未冻结的枚举取值，一律以 `_raw` 后缀原样记录为字符串，**不在本字典内固化新枚举**，避免与并行任务的冻结清单冲突。

---

## 2. 12 个 event_type 完整定义

| event_type | 触发时机(精确描述) | 必填字段 | 可选字段 | 示例JSON | 参与计算的指标 | 常见坑 |
|---|---|---|---|---|---|---|
| `task_start` | 任务详情页内容加载完成、计时器开始计时的**那一帧**触发；非点击"开始"按钮时触发。同一 `task_id` 在同一 `session_id` 内 5 秒内的重复开始只记一条（客户端去抖） | `domain_id`, `task_id`, `level`, `task_type`, `attempt_no` | `entry_source_raw`, `network_type` | `{"event_id":"e_01J8Z","event_type":"task_start","occurred_at":"2026-09-19T10:30:00Z","user_id":"u_10086","session_id":"s_9f2c","domain_id":"go","task_id":"go_L3_001","level":3,"task_type":"standard","attempt_no":1}` | `repetition`（作为分母：主动再次进入同一 domain/task 的次数）、`pain_tolerance`（暴露次数基线） | 把"页面曝光"当 start，导致时长被无限拉长；页面预加载会让 start 早于用户真实开始，须绑定计时器而非生命周期 |
| `task_complete` | 用户提交产出且**服务端已确认接收**（返回 200 并落库产出引用）时触发；客户端仅提交成功不算，需服务端回执 | `domain_id`, `task_id`, `level`, `task_type`, `attempt_no`, `duration_ms`, `active_ms`, `pause_count`, `output_ref` | `evaluator_type`, `word_count`, `output_size_bytes` | `{"event_id":"e_01J90","event_type":"task_complete","occurred_at":"2026-09-19T10:44:02Z","user_id":"u_10086","session_id":"s_9f2c","domain_id":"go","task_id":"go_L3_001","level":3,"task_type":"standard","attempt_no":1,"duration_ms":842000,"active_ms":760000,"pause_count":1,"output_ref":"oss://tilt/u_10086/go_L3_001/a1.sgf"}` | `repetition`（完成次数）、`detail_sensitivity`（产出质量维度的输入源）、`proactive_optimization`（是否提交超出最低要求的版本）、`pain_tolerance`（高 level / 长时长完成）、`bounce_back`（作为"失败后最终完成"链条的终点） | `duration_ms` 用墙钟时间会包含后台挂起，务必用 `active_ms`（扣除 pause 的净活跃时长）参与时长类计算；产出与评分异步，完成事件不等于已评分 |
| `task_abandon` | 用户显式点击"放弃/退出本次任务"并二次确认后触发；**不包括**直接杀进程或切后台（后者走 pause/超时兜底） | `domain_id`, `task_id`, `level`, `attempt_no`, `elapsed_ms`, `progress_pct` | `last_action_raw`, `abandon_stage_raw` | `{"event_id":"e_01J9A","event_type":"task_abandon","occurred_at":"2026-09-19T11:02:10Z","user_id":"u_10086","session_id":"s_9f2c","domain_id":"programming","task_id":"programming_L4_003","level":4,"attempt_no":1,"elapsed_ms":512000,"progress_pct":0.35}` | `pain_tolerance`（负向：未完成的困难任务暴露）、`bounce_back`（作为"受挫事件"起点，用于计算后续是否反弹） | 与 `task_pause` 混淆：放弃是不可恢复的终止，暂停是可恢复；放弃后该 `attempt_no` 不得再产生 resume/complete |
| `task_retry` | 用户对同一 `task_id` 发起**新一次**尝试（`attempt_no` 自增）时触发；覆盖"失败后重做"与"完成后主动再优化"两种场景 | `domain_id`, `task_id`, `level`, `task_type`, `attempt_no`, `prev_attempt_id` | `prev_output_ref`, `is_post_complete`(bool) | `{"event_id":"e_01J9B","event_type":"task_retry","occurred_at":"2026-09-19T11:05:00Z","user_id":"u_10086","session_id":"s_9f2c","domain_id":"go","task_id":"go_L3_001","level":3,"task_type":"standard","attempt_no":2,"prev_attempt_id":"a1","is_post_complete":false}` | `bounce_back`（核心事件：受挫后是否再次尝试）、`proactive_optimization`（`is_post_complete=true` 表示有效完成后仍主动优化） | 未带 `prev_attempt_id` 会导致链条断裂，`bounce_back` 无法归因；`attempt_no` 必须从 1 起连续，跳号视为数据异常 |
| `task_pause` | 用户主动点击暂停，或 app 进入后台 / 失去焦点且超过 10 秒未返回时由客户端自动触发；一个 `attempt_no` 内可多次 | `domain_id`, `task_id`, `attempt_no`, `pause_id`, `active_ms_before_pause` | `pause_trigger_raw`, `network_type` | `{"event_id":"e_01J9C","event_type":"task_pause","occurred_at":"2026-09-19T10:37:20Z","user_id":"u_10086","session_id":"s_9f2c","domain_id":"go","task_id":"go_L3_001","attempt_no":1,"pause_id":"p_7d1","active_ms_before_pause":440000}` | `pain_tolerance`（中断次数，负向）、`bounce_back`（辅助：中断后是否回归），其余仅统计（用于 `active_ms` 校正） | 自动 pause 与用户主动 pause 必须可区分（用 `pause_trigger_raw`），否则把切后台误判成放弃倾向；`pause_id` 缺失会导致无法配对 |
| `task_resume` | 用户回到任务页且计时器恢复计时时触发；**必须**携带与之配对的 `pause_id` | `domain_id`, `task_id`, `attempt_no`, `pause_id`, `pause_duration_ms` | `synthetic`(bool，服务端补发时置 true), `resume_reason_raw` | `{"event_id":"e_01J9D","event_type":"task_resume","occurred_at":"2026-09-19T10:39:05Z","user_id":"u_10086","session_id":"s_9f2c","domain_id":"go","task_id":"go_L3_001","attempt_no":1,"pause_id":"p_7d1","pause_duration_ms":105000}` | `pain_tolerance`（中断后回归，正向）、`bounce_back`（辅助），其余仅统计 | 只发 pause 不发 resume 会造成"永久暂停"脏数据（兜底见第 3 节）；pause 期间不计入 `active_ms`，但 `pause_duration_ms` 超阈值仍要保留用于行为分析 |
| `session_start` | app 冷启动进入前台、或热启动后前台停留超过 3 秒且已完成登录态校验时触发 | `session_id`, `device_id`, `app_version` | `entry_source_raw`, `network_type`, `timezone_raw` | `{"event_id":"e_01J9E","event_type":"session_start","occurred_at":"2026-09-19T10:29:40Z","user_id":"u_10086","session_id":"s_9f2c","device_id":"d_oa_2f9","app_version":"1.0.0"}` | 仅统计（提供日活跃时长、活跃天数与规则 R5 的输入） | 后台唤醒、推送点击、系统拉活都会造成虚假 start，须用"前台 3 秒"门槛过滤；同日多 session 要去重后再算活跃天数 |
| `session_end` | app 进入后台超过 60 秒、或用户主动登出、或进程被系统回收时触发；服务端心跳超时亦可合成 | `session_id`, `duration_ms`, `event_count`, `domain_ids_touched` | `synthetic`(bool), `end_reason_raw` | `{"event_id":"e_01J9F","event_type":"session_end","occurred_at":"2026-09-19T11:30:00Z","user_id":"u_10086","session_id":"s_9f2c","duration_ms":3620000,"event_count":27,"domain_ids_touched":["go","programming"]}` | 仅统计（session 级聚合；同时是第 3 节 pause 兜底的触发边界） | iOS 不保证后台回调，必须依赖服务端心跳超时合成 `synthetic=true` 的 session_end，否则日活与时长系统性偏低 |
| `domain_switch` | 用户在一次 session 内从某一领域的任务上下文切换到**另一不同** `domain_id` 的任务上下文时触发；同领域内换任务不算 | `from_domain_id`, `to_domain_id`, `from_task_id`, `to_task_id` | `dwell_ms_on_prev` | `{"event_id":"e_01J9G","event_type":"domain_switch","occurred_at":"2026-09-19T11:12:00Z","user_id":"u_10086","session_id":"s_9f2c","from_domain_id":"go","to_domain_id":"programming","from_task_id":"go_L3_001","to_task_id":"programming_L2_004","dwell_ms_on_prev":2540000}` | `repetition`（跨领域回流与切换后是否返回），其余仅统计（并行投入 3-5 个领域的节奏校验） | 从列表页/首页进入也算切换，容易重复计数；定义以"任务上下文"为准，列表浏览不计 |
| `task_share` | 用户点击分享并**成功生成分享链接/内容**时触发；仅点击分享按钮未成功不触发 | `domain_id`, `task_id`, `share_channel_raw` | `has_comment`(bool), `comment_length` | `{"event_id":"e_01J9H","event_type":"task_share","occurred_at":"2026-09-19T11:20:30Z","user_id":"u_10086","session_id":"s_9f2c","domain_id":"writing_general","task_id":"writing_general_L2_002","share_channel_raw":"wechat","has_comment":true,"comment_length":42}` | 仅统计（社群与反馈密度，不进入 5 维客观指标计算） | 分享回调在各渠道时序不一致，须以"分享成功回执"为准；不得把分享成功数当作品质量分 |
| `report_view` | 用户打开报告页且报告内容完成渲染时触发；周报告与 4 周结营报告分开记录 | `report_scope_raw` | `report_id`, `view_duration_ms`, `domain_id` | `{"event_id":"e_01J9I","event_type":"report_view","occurred_at":"2026-09-19T21:05:00Z","user_id":"u_10086","session_id":"s_9f2c","report_scope_raw":"weekly_w2","view_duration_ms":96000}` | 仅统计（漏斗与参与度，不进入 5 维客观指标计算，避免"看报告"污染行为指标） | 报告页停留时长不等于阅读完成；预渲染会提前触发，须绑定渲染完成回调 |
| `settings_change` | 用户在设置页完成一次设置项变更并落库成功时触发；一次只记一个设置项 | `setting_key_raw`, `old_value_raw`, `new_value_raw` | `page_raw` | `{"event_id":"e_01J9J","event_type":"settings_change","occurred_at":"2026-09-19T21:30:00Z","user_id":"u_10086","session_id":"s_9f2c","setting_key_raw":"daily_reminder_time","old_value_raw":"20:00","new_value_raw":"07:30"}` | 仅统计（用于解释行为突变，如提醒时间变更导致打卡规律变化） | 连续拖动滑块会产生高频事件，需 500ms 去抖；涉及隐私授权变更需单独可审计 |

---

## 3. `task_pause` / `task_resume` 配对兜底方案（专项）

**问题：** 只收到 `task_pause` 未收到 `task_resume` 时，该 attempt 会永久停留在 paused 状态，导致 ①`active_ms` 虚低、②`pain_tolerance` 的"中断后回归"信号丢失、③任务完成率分母污染。

**采用的兜底方案：以 `session_end` 为兜底边界，由服务端合成 `task_resume`（`synthetic: true`）。**

1. 服务端在收到 `session_end`（含心跳超时 300 秒合成的 `synthetic` session_end）时，检查该 session 内是否仍有 `active_ms_before_pause` 已记录但未配对的 `pause_id`；
2. 若有，补写一条 `task_resume`，字段为：`pause_id` = 原值、`pause_duration_ms` = `session_end.occurred_at - pause.occurred_at`、`synthetic = true`、`resume_reason_raw = "session_end_auto"`；
3. 补写后立即关闭该 attempt（记为未完成），`active_ms` 累计到 pause 时刻为止，**不**把 pause 到 session 结束的时间计入投入时长；
4. 若既无 `task_resume` 也无 `session_end`（崩溃、强杀、断网离线），则在离线补传队列重放时按 `occurred_at` 排序重建；仍无法配对者，以上一次心跳时间作为关闭点，同样不计入 `active_ms`；
5. `synthetic = true` 的 resume **只参与时长校正，不参与 `bounce_back` / `pain_tolerance` 的正向计分**，避免"系统代用户回归"造成指标虚高。

**为什么选 session_end 而不是"下次 task_start 时补发 resume"：**
- session 是 pause 的自然上界：session 结束意味着用户已离开上下文，跨 session 的暂停时长没有行为意义；
- 若在下一次 `task_start` 时补发 resume，会把"离开的几小时甚至几天"算进该 attempt 的时长，直接污染 `pain_tolerance` 与投入时长统计，且会让异常检测规则 R1（完成时间过短）与时长类统计互相矛盾；
- session_end 兜底可在服务端离线重放时按 `occurred_at` 确定性重建，不依赖客户端后续行为，可重复执行且幂等（`pause_id` 唯一）。

**配套约束：** 单次 pause 时长超过 30 分钟的 attempt，其 `active_ms` 只累计 pause 前部分，`task_complete` 若在该 attempt 上仍被上报，需校验 `duration_ms - active_ms` 的一致性，不一致则该条进入规则 R3 的时间校验分支。

---

## 4. 补充事件建议（SPEC 3.6 未包含，MVP 建议纳入）

| 建议 event_type | 理由 | 备注 |
|---|---|---|
| `output_submit` | `task_complete` 语义被"提交 + 接收"占满，而评估是异步的；缺少独立的产出提交事件会导致"已提交未评分"的产出无法追踪，`detail_sensitivity` 的样本可回溯性差 | 建议与 `task_complete` 分离：`output_submit` = 客户端发出产出，`task_complete` = 服务端确认接收。若产品侧判定二者不必拆分，可合并，但需保留 `output_ref` |
| `evaluation_result` | 5 维指标中的 `detail_sensitivity`、以及 4 周进步斜率都依赖评估器回流；SSOT 3.3 已定义 10 个 `evaluator_type`，但没有承载评分结果的事件，评估数据将无处落地 | 必填建议：`task_id`、`attempt_no`、`evaluator_type`（取自 3.3）、`score`、`scored_at`；**不进 5 维指标的原始分不做用户可见展示** |
| `heartbeat` | 第 3 节的 session 超时兜底、iOS 后台无回调、`active_ms` 校正都依赖心跳；无心跳则 session_end 与 pause 兜底均不可靠 | 建议前台 60 秒一次、后台停发；仅用于服务端合成，不参与任何指标计算 |

> 以上 3 个为**建议**，未写入第 2 节正式表的 12 行内，避免破坏 SSOT 3.6 的冻结枚举。是否纳入需产品侧确认。

---

## 备注

1. SSOT 3.x 未冻结事件 payload 字段名，第 1、2 节的字段名（如 `active_ms`、`pause_id`、`attempt_no`）为完成本任务必须新建，已在 manifest `known_deviations` 中声明。
2. 凡取值可能形成新枚举的字段一律使用 `_raw` 后缀原样记录字符串，避免与并行任务冻结清单冲突；如需固化枚举，请由 SSOT 统一发版。
3. 建议补充 `output_submit` / `evaluation_result` / `heartbeat` 三个事件（见第 4 节），其中 `evaluation_result` 对 5 维指标与进步斜率是硬依赖。
4. 本字典只定义"采什么"，不定义"怎么判"；所有阈值与判定见 `docs/anomaly_rules.md`。

```
# === TILT-CONTRACT-MANIFEST ===
# task_id: C11
# spec_version: V1.3
# ssot_checksum: TL-SSOT-2026-09-20-A
# baseline_version: B1.0
# produced_by: Yuanbao
# produced_at: 2026-09-20
# batch: all
# output_files:
#   - docs/tracking_dictionary.md   (rows: 12)
# unverified_count: 0
# self_check:
#   frozen_ids_only: true
#   enum_from_spec: true
#   no_absolute_claims: true
#   no_new_concepts: false
#   spec_numbers_unchanged: true
# known_deviations:
#   - no_new_concepts=false: 新增事件 payload 字段名（SSOT 3.x 未冻结字段级命名，为完成 6.1 必填字段要求必须定义）
#   - no_new_concepts=false: 第 4 节补充建议事件 3 个（output_submit / evaluation_result / heartbeat），按 6.1 第 4 条允许范围提出，未混入 12 行正式表
# === END MANIFEST ===
```
