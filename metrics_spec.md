# Tilt · 5 维客观指标计算契约（`metrics_spec.md`）

- 任务：`C12a` · 算法规格书（5 维指标计算契约）
- SPEC 版本：V1.3 ｜ SSOT 校验码：`TL-SSOT-2026-09-20-A` ｜ baseline：B1.0
- 本批次：第 1 批（`bounce_back` / `repetition` / `detail_sensitivity`）
- 待补（第 2 批）：`proactive_optimization`、`pain_tolerance`、6 个边界用例总表（6.3）、文档头尾汇总

---

## 0. 通用约定（三个指标共用）

### 0.1 计算粒度与窗口

| 项 | 约定 |
|---|---|
| 计算粒度 | `user_id` × `domain_id`（领域 ID 取自 3.1，50 个之一） |
| 计算窗口 | 该用户在该领域上的 4 周投入窗口（首事件日至首事件日 + 28 天，或至数据截止时间 `t_cut`，取较早者） |
| 输入 | 该窗口内的埋点事件流（`event_type` 取自 3.6 的 12 个枚举） |
| 输出 | 见 0.4 |

### 0.2 输入字段清单

> ⚠️ 字段名以 SPEC 4.2 的 event schema 为准。本任务文件未随附 SPEC 4.2，下表除 3.x 冻结项（`event_type` / `domain_id` / `task_id` / `level`）外，其余字段名为建议名，已就地标注 `[待核验:...]`，工程落地时请按 SPEC 4.2 实际字段名替换。

| 字段 | 类型 | 本批次用途 | 缺失 / 为 null 时的兜底 |
|---|---|---|---|
| `user_id` | string | 分组键 | **丢弃该 event**（无法归属，计入 `dropped_events`） |
| `event_type` | enum（3.6） | 全部判定 | **丢弃该 event**（取值不在 12 个枚举内同样丢弃） |
| `domain_id` | enum（3.1） | 分组键 | **丢弃该 event**（三指标均为领域内计算，无领域即不可用） |
| `occurred_at` | ISO 8601，如 `2026-09-19T10:30:00Z` `[待核验:SPEC 4.2 event schema 未随 C12a 下发，时间戳字段名待确认]` | 时序、时间差 | **丢弃该 event**（三个指标全部依赖时序，不允许用写入时间猜测） |
| `task_id` | string（3.7 格式） | 任务级配对（回炉 / 打磨对 / 返工） | **降级使用**：该 event 不进入任务级因子（R1、D1、D2），仅保留领域级判定（bounce_back 锚点与恢复判定不依赖 `task_id`） |
| `session_id` | string `[待核验:SPEC 4.2 event schema 未随 C12a 下发]` | 本批次不使用 | 无影响 |
| `duration` | int（秒） `[待核验:SPEC 4.2 event schema 未随 C12a 下发]` | 本批次不使用（第 2 批 `pain_tolerance` 使用） | 无影响 |
| `level` | int（1-10，MVP 用 L1-L5） | 本批次不使用 | 无影响 |
| `evaluator_score` | number `[待核验:SPEC 4.2 event schema 未随 C12a 下发，评估分字段名与取值区间待确认]` | 仅 `detail_sensitivity` 的预留因子 D3（MVP 默认关闭） | D3 置 `null` 并触发权重重分配（见 3.2 第 5 步） |

### 0.3 通用预处理（所有指标计算前必须执行）

```
P1 过滤：丢弃 event_type 不在 3.6 枚举、occurred_at 为空、domain_id 不在 3.1 的 event
P2 排序：按 occurred_at 升序；时间戳相同者按事件写入序号升序（稳定排序，保证结果可复现）
        # 为什么先排序：输入允许乱序到达（见 6.3 边界用例 5），所有"相邻配对""上一次事件"判定都依赖时间序
P3 分组：先按 domain_id 分组，组内再按 task_id 建子序列；跨领域事件不互相污染
        # domain_switch 本身不产生任务行为，不参与任一因子计算（跨领域归属见 6.3 边界用例 6，第 2 批）
P4 右删失：t_cut = 窗口结束时间。任何"等待型判定"（反弹窗口、完成后窗口）若 t_cut − 锚点时间 < 窗口长度，
        该锚点标记 censored = true，不计入分子与分母 —— 观察窗还没走完，不能判用户"没做"
P5 单位：所有时间差统一换算为小时（保留 4 位小数），所有比值保留 6 位小数，最终分数保留 2 位小数
```

### 0.4 输出契约

```
{
  "metric": "bounce_back" | "repetition" | "detail_sensitivity",
  "value": <0-10 的数字> | null,
  "status": "ok" | "insufficient_data"
}
```

### 0.5 兜底总原则（三个指标一致）

- **分母为 0 时一律返回 `value = null`、`status = "insufficient_data"`，绝不返回 0。**
  理由：0 是一个合法且很强的测量结论（"观测到用户从不重复 / 从不打磨"），`null` 表示"没有观测窗口，测不出来"。
  两者混用会让 4 周斜率对比把"没数据"读成"表现极差"，从而误导用户决策。
- `status = "insufficient_data"` 的指标**不参与**该领域的 5 维画像与进步斜率计算，也不参与领域间横向对比。
- `value` 一经输出即在 `[0, 10]` 闭区间内，下游无需再做范围校验。

---

## 1. `bounce_back`（挫败后反弹力）

### 1.1 输入数据契约

| 项 | 内容 |
|---|---|
| 需要的 `event_type` | `task_abandon`（失败锚点）、`task_start` / `task_retry`（恢复信号）、`task_complete`（反弹后是否推进） |
| 不需要的 `event_type` | `task_pause` / `task_resume` / `session_start` / `session_end` / `domain_switch` / `task_share` / `report_view` / `settings_change` |
| 关键字段 | `event_type`、`occurred_at`、`domain_id`；`task_id` 仅用于日志与排查，不参与判定 |
| 字段缺失兜底 | 见 0.2：`occurred_at` / `domain_id` / `event_type` 缺失即丢弃该 event；`task_id` 缺失不影响本指标 |
| 最少 event 数 | **至少 1 个非右删失失败锚点**（即 ≥1 个 `task_abandon`，且距 `t_cut` 已满 72h 或在 72h 内已出现恢复信号） |
| 不足时返回 | `value = null`、`status = "insufficient_data"`。理由：从未失败 ⇒ 不存在"反弹"的观测窗口（对应 6.3 边界用例 1，第 2 批）；这与"失败后再也不回来"（真实 0 分）是两件事 |

> 关于失败锚点的口径：MVP 只用 `task_abandon` 作为锚点。`task_complete` 的成败需要评估分字段
> `[待核验:SPEC 4.2 未随 C12a 下发]`，在字段确认前不把"完成但得分很低"计为失败，以免分母口径漂移。

### 1.2 计算步骤（伪代码）

```
输入：events（单 user × 单 domain，已执行 P1-P5）
     t_cut（窗口结束时间）
常量：W_recovery = 72（小时）    # 反弹等待窗口
     W_finish   = 24（小时）    # 反弹后推进窗口
     w1 = 0.7（F1 恢复速度权重）、w2 = 0.3（F2 反弹后推进权重）

步骤 1 · 生成失败锚点
  anchors ← []
  对 events 按时间升序扫描：
    若 e.event_type == "task_abandon"：
      anchors.append({ time: e.occurred_at, task_id: e.task_id })
  # 为什么：task_abandon 是 3.6 中唯一能直接判定"挫败"的事件，不需要任何额外字段，口径最稳。

步骤 2 · 样本判定
  若 anchors 为空：返回 { metric:"bounce_back", value:null, status:"insufficient_data" }

步骤 3 · 逐锚点判定恢复
  对每个锚点 a：
    a.recovery ← events 中满足以下全部条件的最早事件 r：
        r.occurred_at > a.time
        且 r.event_type ∈ { "task_start", "task_retry" }
        且 r.domain_id == 当前 domain
    # 为什么两种都算恢复：反弹有两种形态——换一个新任务继续（task_start）和原地重来（task_retry），
    #   只要用户仍留在同一领域内，都说明"没有因为挫败而离开"。
    # 为什么限制同一 domain：跨领域的动作属于 6.3 边界用例 6 的范畴，不计入本领域的反弹。

    若 a.recovery 为空 且 (t_cut − a.time) <  W_recovery：a.censored ← true   # 观察窗未闭合，剔除
    若 a.recovery 为空 且 (t_cut − a.time) >= W_recovery：a.censored ← false；a.s ← 0
    若 a.recovery 非空：
        a.dt ← 小时数(a.recovery.occurred_at − a.time)
        a.s ← max(0, 1 − a.dt / W_recovery)
        # 为什么用线性衰减：反弹力的核心是"多久回来"，线性衰减可手算、可复核、无需调参；
        #   72h 的依据是 3.9 的周节奏（每周跨 1-2 个 Level），72h 覆盖"下一次练习窗口"，
        #   超过 72h 的回归更接近"另起一轮"，不再算作对本次挫败的反弹。

步骤 4 · 逐锚点判定反弹后是否推进
  对每个非删失锚点 a（a.recovery 非空）：
    a.finished ← 存在事件 c 满足：
        c.event_type == "task_complete"
        且 c.domain_id == 当前 domain
        且 a.recovery.occurred_at < c.occurred_at <= a.recovery.occurred_at + W_finish
  否则 a.finished ← false
  # 为什么加这一项：只"回来"不算反弹，回来之后把事情做完才算真正的反弹；
  #   24h 取自"下一次练习窗口"的粒度，避免把几天后的无关完成算进来。

步骤 5 · 聚合
  n ← anchors 中 censored != true 的锚点数
  若 n == 0：返回 { metric:"bounce_back", value:null, status:"insufficient_data" }
  F1 ← (Σ a.s) / n                       # 加权恢复速度，∈[0,1]
  F2 ← (Σ 1[a.finished == true]) / n     # 反弹后推进率，∈[0,1]
  raw ← w1 * F1 + w2 * F2

步骤 6 · 输出
  value ← clamp(round(raw * 10, 2), 0, 10)
  返回 { metric:"bounce_back", value, status:"ok",
        detail: { n, censored_count, F1, F2, raw } }
```

**中间变量一览**：`anchors`（失败锚点列表）、`a.recovery`、`a.dt`（恢复时延，小时）、`a.s`（单锚点恢复得分）、`a.finished`、`n`（有效锚点数）、`F1`、`F2`、`raw`。

### 1.3 归一化方式

- 归一化公式：`value = clamp(round(raw × 10, 2), 0, 10)`，其中 `raw = 0.7·F1 + 0.3·F2`。
- **理论最小值 = 0**：所有失败锚点在 72h 内均无 `task_start` / `task_retry`（`F1 = 0`，`F2 = 0`）。
- **理论最大值 = 10**：每一次挫败都在瞬间恢复（`dt → 0`，`s → 1`，`F1 = 1`）且恢复后 24h 内都完成（`F2 = 1`），`raw = 1`，`value = 10`。
- **10 分是刻度上限，不是经验截断值**：SPEC 12.3 规定 5 维统一映射到 0-10 分；由于 `F1`、`F2` 均被构造在 `[0,1]` 闭区间、权重之和为 1，`raw` 数学上不可能越界。仍保留 `clamp(0, 10)` 作为**防御性断言**——防止后续权重配置变更、或 `a.dt` 因时钟回拨出现负值时产出越界分数。
- **不设下限截断**：0 分是真实现象（挫败后彻底离开），抬高下限会掩盖掉最需要被看见的信号。

### 1.4 手算示例

事件序列（`domain_id = go`，`user_id = U1`，均已预处理排序；`t_cut = 2026-09-10T00:00:00Z`）：

| # | `occurred_at` | `event_type` | `task_id` |
|---|---|---|---|
| 1 | 2026-09-01T20:00:00Z | `task_abandon` | `go_L3_001` |
| 2 | 2026-09-02T20:30:00Z | `task_retry` | `go_L3_001` |
| 3 | 2026-09-02T21:10:00Z | `task_complete` | `go_L3_001` |
| 4 | 2026-09-03T20:00:00Z | `task_abandon` | `go_L3_002` |
| 5 | 2026-09-07T20:00:00Z | `task_start` | `go_L3_003` |

逐步计算：

1. 锚点：#1 → A₁（`go_L3_001`，09-01T20:00）；#4 → A₂（`go_L3_002`，09-03T20:00）。`anchors = 2`，非空，继续。
2. A₁：最早的同领域恢复信号是 #2 `task_retry`（09-02T20:30）。
   `dt = 24.5h` → `s₁ = 1 − 24.5/72 = 0.6597`。
   反弹后推进：#3 `task_complete` 在 09-02T21:10，落在 `恢复时间 + 24h` 内 → `finished₁ = true`。
3. A₂：其后同领域最早恢复信号是 #5 `task_start`（09-07T20:00）。
   `dt = 96h > 72h` → `s₂ = max(0, 1 − 96/72) = 0`；`finished₂ = false`。
   （`t_cut − A₂ = 约 6.17 天 ≥ 72h`，窗口已闭合，非右删失。）
4. 有效锚点数 `n = 2`（无右删失）。
   `F1 = (0.6597 + 0) / 2 = 0.3299`
   `F2 = (1 + 0) / 2 = 0.5`
5. `raw = 0.7 × 0.3299 + 0.3 × 0.5 = 0.2309 + 0.15 = 0.3809`
6. `value = 0.3809 × 10 = 3.809 → 3.81`

输出：`{ "metric": "bounce_back", "value": 3.81, "status": "ok" }`

---

## 2. `repetition`（重复意愿）

### 2.1 输入数据契约

| 项 | 内容 |
|---|---|
| 需要的 `event_type` | `task_start`、`task_complete`、`task_retry`、`task_abandon`（用于剔除补救性重做）、`session_start`（辅助判定活跃日） |
| 不需要的 `event_type` | `task_pause` / `task_resume` / `session_end` / `domain_switch` / `task_share` / `report_view` / `settings_change` |
| 关键字段 | `event_type`、`occurred_at`、`domain_id`、`task_id`（`task_id` 必需：回炉判定是任务级的） |
| 字段缺失兜底 | `task_id` 缺失 → 该 event 不参与 R1（回炉判定），仍参与 R2（领域级计数）；`occurred_at` / `domain_id` 缺失 → 丢弃 |
| 最少 event 数 | **≥1 个活跃日 且 ≥1 个 `task_complete`**（R1 的分母是已完成数，R2 的分母是活跃天数，缺任一即不可计算） |
| 不足时返回 | `value = null`、`status = "insufficient_data"` |
| 与 `bounce_back` 的分工 | 紧跟 `task_abandon` / `task_retry` 的重做判为**补救性重做**，只归 `bounce_back`，不重复计入本指标——本指标只测"没有人逼我，我还想再来一次" |

### 2.2 计算步骤（伪代码）

```
输入：events（单 user × 单 domain，已执行 P1-P5）
常量：PLANNED_PER_DAY = 1   # 每日计划任务数
     [待核验:SPEC 4.1/4.2 是否定义每日计划任务数；未定义时按产品背景"每天每领域 15-30 分钟"取 1]
     w1 = 0.6（R1 回炉率权重）、w2 = 0.4（R2 计划外追加率权重）

步骤 1 · 活跃日
  active_days ← 出现过以下任一 event_type 的自然日数量（按用户本地时区）：
               { task_start, task_complete, task_retry, session_start }
  # 为什么剔除 report_view / settings_change：那是"看看"，不是投入；活跃日必须反映真实的练习行为。

步骤 2 · 已完成数
  completed_count ← 该 domain 内 event_type == "task_complete" 的事件条数（同一 task 多次完成分别计数）
  # 为什么按条数而不是按去重 task_id 计数：重复意愿关心的正是"完成了多少次"，去重会丢掉回炉的信号。

步骤 3 · 样本判定
  若 active_days == 0 或 completed_count == 0：
    返回 { metric:"repetition", value:null, status:"insufficient_data" }

步骤 4 · R1 回炉率
  revisit_count ← 0
  对 events 中每个 e.event_type == "task_start"（按时间升序）：
    prev ← 同一 task_id 序列中 e 之前的最后一个事件
    若 prev 存在 且 prev.event_type ∈ { "task_abandon", "task_retry" }：
       跳过  # 补救性重做，由 bounce_back 承担，此处不计
    否则若 同一 task_id 在 e 之前已出现过 >= 1 次 task_complete：
       revisit_count ← revisit_count + 1
  # 为什么这样定义回炉：任务已经做完了还主动再开一遍，是"无人要求下的重复"最直接的行为证据。
  R1 ← min(revisit_count / completed_count, 1)
  # 为什么截到 1：回炉次数可以超过完成数（同一任务反复回炉），比值会 > 1；
  #   超过"每个已完成任务平均被回炉一次"后不再加分，避免刷同一题被读成高意愿，
  #   也避免 completed_count 很小时比值爆表。

步骤 5 · R2 计划外追加率
  planned ← active_days * PLANNED_PER_DAY
  extra   ← max(0, completed_count − planned)
  R2 ← min(extra / planned, 1)
  # 为什么用"超出计划的部分"而不是完成总量：总量高可能只是活跃天数多（坚持），
  #   超出计划的那一截才是"主动加练"。坚持与重复是两件事，必须拆开。
  # 为什么截到 1：追加量达到计划的 100% 已是极端投入；更高值多为数据异常（重复上报、补录），不具区分度。

步骤 6 · 聚合与输出
  raw ← w1 * R1 + w2 * R2
  value ← clamp(round(raw * 10, 2), 0, 10)
  返回 { metric:"repetition", value, status:"ok",
        detail: { active_days, completed_count, revisit_count, R1, R2, raw } }
```

**中间变量一览**：`active_days`、`completed_count`、`planned`、`extra`、`revisit_count`、`R1`、`R2`、`raw`。

### 2.3 归一化方式

- 归一化公式：`value = clamp(round((0.6·R1 + 0.4·R2) × 10, 2), 0, 10)`。
- **理论最小值 = 0**：从不回炉（`R1 = 0`）且完成量恰好等于计划量、没有任何加练（`R2 = 0`）。
- **理论最大值 = 10**：`R1 = 1`（每个已完成任务平均至少被回炉一次）且 `R2 = 1`（完成量达到计划的 2 倍）。
- **10 分上限的依据**：在"每天每领域 15-30 分钟"的产品约束下，日完成量达到计划 2 倍且全部被回炉，已是 4 周窗口内的实务天花板；再高的取值多为数据异常而非意愿差异，故在因子层（`min(·,1)`）就已截断，`×10` 后不再二次截断。`clamp(0, 10)` 同样是防御性断言。
- **为什么不在 `R2` 上用 `completed_count / planned` 直接映射**：那样会把"活跃天数多"当成"重复意愿强"，与本指标定义不符。

### 2.4 手算示例

事件序列（`domain_id = photography`，`user_id = U1`；`PLANNED_PER_DAY = 1`）：

| # | `occurred_at` | `event_type` | `task_id` |
|---|---|---|---|
| 1 | 2026-09-01T19:00:00Z | `task_start` | `photography_L2_001` |
| 2 | 2026-09-01T19:25:00Z | `task_complete` | `photography_L2_001` |
| 3 | 2026-09-01T19:30:00Z | `task_start` | `photography_L2_002` |
| 4 | 2026-09-01T19:55:00Z | `task_complete` | `photography_L2_002` |
| 5 | 2026-09-01T20:20:00Z | `task_start` | `photography_L2_001` |

逐步计算：

1. 活跃日：所有事件都在 09-01 → `active_days = 1`。
2. 已完成数：#2、#4 → `completed_count = 2`。
3. 样本足够（`active_days ≥ 1` 且 `completed_count ≥ 1`），继续。
4. R1：逐个检查 `task_start`
   - #1：`photography_L2_001` 之前无事件 → 首次开始，不计。
   - #3：`photography_L2_002` 之前无事件 → 首次开始，不计。
   - #5：`photography_L2_001`，前序最后事件是 #2 `task_complete`（不在 `{task_abandon, task_retry}` 内），且该 task 之前已完成过 ≥1 次 → **回炉，`revisit_count = 1`**。
   `R1 = min(1 / 2, 1) = 0.5`
5. R2：`planned = 1 × 1 = 1`；`extra = max(0, 2 − 1) = 1`；`R2 = min(1 / 1, 1) = 1`
6. `raw = 0.6 × 0.5 + 0.4 × 1 = 0.3 + 0.4 = 0.7`
7. `value = 0.7 × 10 = 7.00`

输出：`{ "metric": "repetition", "value": 7.00, "status": "ok" }`

---

## 3. `detail_sensitivity`（细节敏感度）

### 3.1 输入数据契约

| 项 | 内容 |
|---|---|
| 需要的 `event_type` | `task_pause`、`task_resume`（打磨对）、`task_retry`（返工）、`task_complete`（任务最终完成，是打磨对的准入条件） |
| 不需要的 `event_type` | `task_start` / `task_abandon` / `session_start` / `session_end` / `domain_switch` / `task_share` / `report_view` / `settings_change` |
| 关键字段 | `event_type`、`occurred_at`、`domain_id`、`task_id`（`task_id` 必需：打磨对与返工都是任务级配对） |
| 字段缺失兜底 | `task_id` 缺失 → 该 event 不参与 D1 与 D2（无法配对），不丢弃（仍计入领域级计数）；`occurred_at` / `domain_id` 缺失 → 丢弃 |
| 最少 event 数 | **≥1 个 `task_complete`**。若只有完成、既无打磨对也无返工，则 D1 按 0 计、D2 置 `null`、权重归给 D1，仍输出有效值（0 是合法测量结论："完成但从不打磨"）。连 1 个 `task_complete` 都没有 → `null` |
| 不足时返回 | `value = null`、`status = "insufficient_data"` |
| 预留因子 | D3（返工后质量改善率）依赖评估分字段 `[待核验:SPEC 4.2 未随 C12a 下发，评估分字段名与取值区间待确认]`，MVP 默认关闭（`USE_EVAL_SCORE = false`），字段确认后再启用 |

### 3.2 计算步骤（伪代码）

```
输入：events（单 user × 单 domain，已执行 P1-P5）
常量：PAIR_CAP = 2（每任务计满的"暂停—继续"往返对数）
     w1 = 0.6（D1 权重）、w2 = 0.4（D2 权重）、w3 = 0.3（D3 权重，仅启用时参与）
     USE_EVAL_SCORE = false

步骤 1 · 样本判定
  completed_task_ids ← 出现过 task_complete 的 task_id 去重集合
  若 completed_task_ids 为空：
    返回 { metric:"detail_sensitivity", value:null, status:"insufficient_data" }

步骤 2 · D1 打磨对密度
  polish_pairs ← 0
  对每个 task_id t ∈ completed_task_ids：
     在 t 的事件子序列中统计相邻的 (task_pause → task_resume) 配对数 k
     # 为什么只认"相邻配对"：pause 之后没有 resume 是中断或放弃，不是打磨；
     #   只有"停下来 → 回来继续 → 最终做完"这一整条链，才是主动的分段打磨。
     polish_pairs ← polish_pairs + k
  D1 ← min(polish_pairs / (|completed_task_ids| * PAIR_CAP), 1)

步骤 3 · D2 返工收敛率
  retried ← 出现过 task_retry 的 task_id 去重集合
  若 retried 为空：D2 ← null
     # 为什么置 null 而不是 0：没有返工 = 没有观测窗口，"从不返工"既可能是不在乎细节，
     #   也可能是一遍就做对了；把无信号当成低分会把高质量用户误判。
  否则：
     converged ← |{ t ∈ retried : t 在其最后一次 task_retry 之后出现了 task_complete }|
     D2 ← converged / |retried|

步骤 4 · D3 质量改善率（MVP 默认关闭）
  若 USE_EVAL_SCORE == false：D3 ← null
  否则：
     scored ← |{ t : t 的 retry 前后各存在一次有效 evaluator_score }|
     若 scored == 0：D3 ← null
     否则：D3 ← |{ t ∈ scored : retry 后评估分 > retry 前评估分 }| / scored
  # [待核验:SPEC 4.2 未随 C12a 下发，评估分字段名与取值区间待确认]

步骤 5 · 权重重分配
  usable ← { D1, D2, D3 } 中取值非 null 的项
  若 usable 为空：返回 { metric:"detail_sensitivity", value:null, status:"insufficient_data" }
  对 usable 中每一项 i：w'_i ← w_i / (Σ w_j，j ∈ usable)
  raw ← Σ (w'_i * D_i)
  # 为什么重分配而不是置 0：缺失的因子表示"没测到"，把它当 0 分等于凭空扣掉用户的分数；
  #   用剩余因子的相对权重还原到 [0,1]，才能保证有/无返工的用户在同一刻度上可比。

步骤 6 · 输出
  value ← clamp(round(raw * 10, 2), 0, 10)
  返回 { metric:"detail_sensitivity", value, status:"ok",
        detail: { completed_task_count: |completed_task_ids|, polish_pairs, D1, D2, D3, raw } }
```

**中间变量一览**：`completed_task_ids`、`polish_pairs`、`k`（单任务打磨对数）、`retried`、`converged`、`D1`、`D2`、`D3`、重分配后的 `w'_i`、`raw`。

### 3.3 归一化方式

- 归一化公式：`value = clamp(round(raw × 10, 2), 0, 10)`，`raw` 为按可用因子重分配权重后的加权和。
- **理论最小值 = 0**：所有已完成任务的打磨对数为 0（`D1 = 0`），且所有返工任务最终都没收敛到完成（`D2 = 0`）。
- **理论最大值 = 10**：`D1 = 1`（平均每个已完成任务有 ≥2 次"暂停—继续"往返）且 `D2 = 1`（所有返工都收敛到完成）；启用 D3 时还需 `D3 = 1`。
- **`PAIR_CAP = 2` 的依据（即"为什么截在 2 对"）**：1 次 `pause → resume` 高度可能来自外部打断（消息、倒水、休息），信号不可靠；出现 ≥2 次往返才有把握读作"在抠细节"。超过 2 次不再加分，是因为"反复纠结"与"细节敏感"在埋点层面无法区分，超额计分等于奖励拖延——这也是对刷分行为的防御。
- **10 分上限的依据**：`D1`、`D2`（及 D3）各自已是 `[0,1]` 闭区间内的比例，权重重分配后 `raw` 仍落在 `[0,1]`，`×10` 是 SPEC 12.3 的刻度映射而非经验截断；`clamp(0, 10)` 仅作防御性断言。

### 3.4 手算示例

事件序列（`domain_id = ui_design`，`user_id = U1`；`USE_EVAL_SCORE = false`）：

| # | `occurred_at` | `event_type` | `task_id` |
|---|---|---|---|
| 1 | 2026-09-01T21:00:00Z | `task_start` | `ui_design_L3_001` |
| 2 | 2026-09-01T21:20:00Z | `task_pause` | `ui_design_L3_001` |
| 3 | 2026-09-01T21:25:00Z | `task_resume` | `ui_design_L3_001` |
| 4 | 2026-09-01T21:40:00Z | `task_complete` | `ui_design_L3_001` |

逐步计算：

1. `completed_task_ids = { ui_design_L3_001 }`，非空，继续。
2. D1：`ui_design_L3_001` 子序列为 `start → pause → resume → complete`，相邻的 `pause → resume` 配对数 `k = 1`；`polish_pairs = 1`。
   `D1 = min(1 / (1 × 2), 1) = 0.5`
3. D2：序列中无 `task_retry` → `retried = ∅` → `D2 = null`（无观测窗口）。
4. D3：`USE_EVAL_SCORE = false` → `D3 = null`。
5. 权重重分配：可用项只有 D1 → `w'_1 = 0.6 / 0.6 = 1.0`。
   `raw = 1.0 × 0.5 = 0.5`
6. `value = 0.5 × 10 = 5.00`

输出：`{ "metric": "detail_sensitivity", "value": 5.00, "status": "ok" }`

> 对照：若把缺失的 D2 当作 0 分（不重分配），结果为 `0.6×0.5 + 0.4×0 = 3.00`，
> 等于凭空扣掉 2 分——这正是 3.2 步骤 5 采用权重重分配的原因。

---

## 备注

1. SPEC 4.2 的 event schema 未随 C12a 下发：`occurred_at` / `session_id` / `duration` / `evaluator_score` 等字段名除 3.x 冻结项外均为建议名（正文已标 `[待核验]`），落地请以 SPEC 4.2 实际字段名为准。
2. 输出字段名 `value` / `status` 及 `status` 枚举 `ok | insufficient_data` 为实现层新增（非 3.x 冻结项），若 SPEC 已有定义请覆盖。
3. MVP 未把「完成但得分很低」计为失败锚点（缺评估分字段）；评估分口径确认后，`bounce_back` 的分母口径需同步复核。
4. 常量 `PLANNED_PER_DAY = 1`、`W_recovery = 72h`、`W_finish = 24h`、`PAIR_CAP = 2`、各组权重均为本次设计取值，SPEC 未给定，如需校准请产品侧确认。
5. 第 2 批需注意口径延续：边界用例 1（一次都没失败）在本批次已按 `insufficient_data` 处理，`proactive_optimization` 与 `pain_tolerance` 建议沿用同一兜底语义。

```yaml
# === TILT-CONTRACT-MANIFEST ===
# task_id: C12a
# spec_version: V1.3
# ssot_checksum: TL-SSOT-2026-09-20-A
# baseline_version: B1.0
# produced_by: 元宝
# produced_at: 2026-09-20
# batch: 1/2
# output_files:
#   - docs/metrics_spec.md   (rows: 3 指标)
# unverified_count: 5
# self_check:
#   frozen_ids_only: true
#   enum_from_spec: true
#   no_absolute_claims: true
#   no_new_concepts: true
#   spec_numbers_unchanged: true
# known_deviations:
#   - SPEC 4.2 event schema 未随本任务下发，非冻结字段名按建议名书写并就地标注 [待核验]
#   - 输出字段 value/status 与 status 枚举为实现层新增，非 3.x 冻结项
# === END MANIFEST ===
```
