# Tilt · 5 维客观指标计算契约（`metrics_spec.md`）

- 任务：`C12a` · 算法规格书（5 维指标计算契约）
- SPEC 版本：V1.3 ｜ SSOT 校验码：`TL-SSOT-2026-09-20-A` ｜ baseline：B1.0
- 覆盖批次：第 1 批（`bounce_back` / `repetition` / `detail_sensitivity`）+ 第 2 批（`proactive_optimization` / `pain_tolerance` / 6 个边界用例总表 / 文档汇总）—— 即完整 5 指标
- 状态：两批已合并为一份完整文档

---

## 0. 通用约定（五个指标共用）

### 0.1 计算粒度与窗口

| 项 | 约定 |
|---|---|
| 计算粒度 | `user_id` × `domain_id`（领域 ID 取自 3.1，50 个之一） |
| 计算窗口 | 该用户在该领域上的 4 周投入窗口（首事件日至首事件日 + 28 天，或至数据截止时间 `t_cut`，取较早者） |
| 输入 | 该窗口内的埋点事件流（`event_type` 取自 3.6 的 12 个枚举） |
| 输出 | 见 0.4 |

### 0.2 输入字段清单

> ⚠️ 字段名以 SPEC 4.2 的 event schema 为准。本任务文件未随附 SPEC 4.2，下表除 3.x 冻结项（`event_type` / `domain_id` / `task_id` / `level`）外，其余字段名为建议名，已就地标注 `[待核验:...]`，工程落地时请按 SPEC 4.2 实际字段名替换。

| 字段 | 类型 | 用途（指标 × 用途） | 缺失 / 为 null 时的兜底 |
|---|---|---|---|
| `user_id` | string | 分组键 | **丢弃该 event**（无法归属，计入 `dropped_events`） |
| `event_type` | enum（3.6） | 全部判定 | **丢弃该 event**（取值不在 12 个枚举内同样丢弃） |
| `domain_id` | enum（3.1） | 分组键 | **丢弃该 event**（五个指标均为领域内计算，无领域即不可用） |
| `occurred_at` | ISO 8601，如 `2026-09-19T10:30:00Z` `[待核验:SPEC 4.2 event schema 未随 C12a 下发，时间戳字段名待确认]` | 时序、时间差 | **丢弃该 event**（五个指标全部依赖时序，不允许用写入时间猜测） |
| `task_id` | string（3.7 格式） | 任务级配对（回炉 / 打磨对 / 返工 / 投入段） | **降级使用**：该 event 不进入任务级因子（R1、D1、D2、O1、T1），仅保留领域级判定（`bounce_back` 锚点与恢复判定、T2 连败链判定不依赖 `task_id`） |
| `session_id` | string `[待核验:SPEC 4.2 event schema 未随 C12a 下发]` | 不使用（段划分以 `task_start` / `task_resume` 为准，`session_end` 仅作段终点的兜底终止条件） | 无影响 |
| `duration` | int（秒） `[待核验:SPEC 4.2 event schema 未随 C12a 下发，字段名及语义（本次投入时长 / 事件自身时长）待确认]` | 仅 `pain_tolerance` 的 T1（第 5 节） | ≤0 或缺失 → 该投入段回退用时间戳差；两者皆不可得 → 剔除该段（见 5.2 步骤 2） |
| `level` | int（1-10，MVP 用 L1-L5） | 仅 `pain_tolerance` 的预留因子 T3（MVP 默认关闭） | T3 置 `null` 并触发权重重分配（见 5.2 第 6 步） |
| `evaluator_score` | number `[待核验:SPEC 4.2 event schema 未随 C12a 下发，评估分字段名与取值区间待确认]` | 仅 `detail_sensitivity` 的预留因子 D3（MVP 默认关闭） | D3 置 `null` 并触发权重重分配（见 3.2 第 5 步） |

### 0.3 通用预处理（所有指标计算前必须执行）

```
P1 过滤：丢弃 event_type 不在 3.6 枚举、occurred_at 为空、domain_id 不在 3.1 的 event
P2 排序：按 occurred_at 升序；时间戳相同者按事件写入序号升序（稳定排序，保证结果可复现）
        # 为什么先排序：输入允许乱序到达（见第 6 节边界用例 5），所有"相邻配对""上一次事件"判定都依赖时间序
P3 分组：先按 domain_id 分组，组内再按 task_id 建子序列；跨领域事件不互相污染
        # domain_switch 本身不产生任务行为，不参与任一因子计算（跨领域归属见第 6 节边界用例 6）
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

### 0.5 兜底总原则（五个指标一致）

- **分母为 0（或有效观测数为 0）时一律返回 `value = null`、`status = "insufficient_data"`，绝不返回 0。**
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
| 不足时返回 | `value = null`、`status = "insufficient_data"`。理由：从未失败 ⇒ 不存在"反弹"的观测窗口（对应第 6 节边界用例 1）；这与"失败后再也不回来"（真实 0 分）是两件事 |

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
    # 为什么限制同一 domain：跨领域的动作属于第 6 节边界用例 6 的范畴，不计入本领域的反弹。

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

## 4. `proactive_optimization`（主动优化倾向）

### 4.1 输入数据契约

| 项 | 内容 |
|---|---|
| 需要的 `event_type` | `task_retry`（主动返工）、`task_complete`（分母与"已完成"前置条件）、`task_start`（用于识别任务实例）、`task_abandon`（用于**排除**补救性重做）、`task_share`（主动求反馈）、`report_view`（预留因子 O3，MVP 默认关闭） |
| 不需要的 `event_type` | `task_pause` / `task_resume` / `session_start` / `session_end` / `domain_switch` / `settings_change` |
| 关键字段 | `event_type`、`occurred_at`、`domain_id`、`task_id`（`task_id` 必需：返工判定是任务级的） |
| 字段缺失兜底 | `task_id` 缺失 → 该 event 不参与 O1（无法配对），不丢弃；`occurred_at` / `domain_id` 缺失 → 丢弃 |
| 最少 event 数 | **≥1 个 `task_complete`**（已完成任务数是 O1、O2 的分母；一个都没做完 ⇒ 不存在"主动改进产出"的机会） |
| 不足时返回 | `value = null`、`status = "insufficient_data"` |
| 与 `bounce_back` 的分工 | 失败后的 `task_retry`（前序为 `task_abandon`）是**补救**，只归 `bounce_back`，不计入 O1 |
| 与 `detail_sensitivity` 的分工 | 同一条 `task_retry` 可同时进入 D2 与 O1，但口径不同：D2 看"返工后是否收敛到完成"，O1 看"这次返工是不是没人逼、自己发起的"；两个指标测的不是同一件事，允许共享原始信号 |

> `task_share` 的语义假设：本契约假定 `task_share` 是用户把产出提交/分享出去以寻求外部反馈的主动动作
> `[待核验:SPEC 4.2 未随 C12a 下发，task_share 的触发条件（用户主动 / 系统自动）待确认]`。
> 若其为系统自动触发，O2 需改为关闭或改为人工标记字段。

### 4.2 计算步骤（伪代码）

```
输入：events（单 user × 单 domain，已执行 P1-P5）
常量：w1 = 0.6（O1 主动返工率权重）、w2 = 0.4（O2 反馈寻求率权重）、w3 = 0.2（O3 权重，仅启用时参与）
     USE_REPORT_VIEW = false   # O3 开关

步骤 1 · 样本判定
  completed_task_ids ← 出现过 task_complete 的 task_id 去重集合
  n_task ← |completed_task_ids|
  若 n_task == 0：返回 { metric:"proactive_optimization", value:null, status:"insufficient_data" }
  # 为什么用去重 task 数而不是完成事件条数：主动返工 / 分享的机会以"任务"为单位，
  #   同一任务被完成两次只提供一次"我已做完、要不要再改"的机会；用条数会稀释率值。

步骤 2 · O1 主动返工率
  proactive_retry_tasks ← 空集合
  对 events 中每个 e.event_type == "task_retry"（按时间升序）：
     prev ← 同一 task_id 子序列中 e 之前的最后一个事件
     若 prev 为空 或 prev.event_type == "task_abandon"：跳过
        # 为什么排除：紧跟失败的 retry 是"补救"，动机来自外部挫败，已由 bounce_back 承担；
        #   本指标只测"没有人逼我，我还想做得更好"。
     否则若 同一 task_id 在 e 之前已出现过 >= 1 次 task_complete：
        proactive_retry_tasks.add(e.task_id)
        # 为什么要求"之前已完成过"：做完之后还回头改，才是主动优化；
        #   没做完就重来属于返工流程的一部分，不构成"优化"。
     否则：跳过
  O1 ← min(|proactive_retry_tasks| / n_task, 1)
  # 为什么截到 1：同一任务可被反复返工，比值会 > 1；超过"每个已完成任务平均被主动返工一次"
  #   之后不再加分，避免刷同一道题被读成高优化倾向。

步骤 3 · O2 反馈寻求率
  shared_tasks ← { e.task_id : e.event_type == "task_share" 且 e.task_id ∈ completed_task_ids }
  # 为什么按去重任务计：防止同一产出多次转发把"分享一次"刷成"分享十次"。
  O2 ← min(|shared_tasks| / n_task, 1)
  # 为什么把"主动求反馈"算作优化倾向：没有外部反馈的优化是闭门造车；
  #   把产出交给别人看，是"愿意被修正"的直接行为证据（对应产品第三原则：反馈密度是设计重点）。

步骤 4 · O3 数据自查率（MVP 默认关闭）
  若 USE_REPORT_VIEW == false：O3 ← null
  否则：
     last_complete ← 该 domain 内最后一次 task_complete 的时间
     O3 ← 1.0 若存在 report_view 且 occurred_at > last_complete，否则 0.0
  # 为什么默认关闭：`report_view` 可能由系统推送/红点触发，埋点层面无法区分"主动自查"
  #   与"被通知后点开"；在触发方式明确前启用会引入系统性偏差。
  # [待核验:SPEC 4.2 未随 C12a 下发，report_view 的触发方式待确认]

步骤 5 · 权重重分配
  usable ← { O1, O2, O3 } 中取值非 null 的项
  对 usable 中每一项 i：w'_i ← w_i / (Σ w_j，j ∈ usable)
  raw ← Σ (w'_i * O_i)
  # 为什么重分配而不是置 0：缺失因子表示"没测到"，当 0 分等于凭空扣分；
  #   按剩余因子的相对权重还原到 [0,1]，保证开关前后的分数在同一刻度上可比。
  # 注：O1、O2 恒可计算（无信号即为 0，是真实测量结论），因此只有 O3 关闭时会触发重分配。

步骤 6 · 输出
  value ← clamp(round(raw * 10, 2), 0, 10)
  返回 { metric:"proactive_optimization", value, status:"ok",
        detail: { n_task, proactive_retry_count: |proactive_retry_tasks|, shared_task_count: |shared_tasks|,
                  O1, O2, O3, raw } }
```

**中间变量一览**：`completed_task_ids`、`n_task`、`prev`（同任务前序事件）、`proactive_retry_tasks`、`shared_tasks`、`O1`、`O2`、`O3`、重分配后的 `w'_i`、`raw`。

### 4.3 归一化方式

- 归一化公式：`value = clamp(round(raw × 10, 2), 0, 10)`，`raw` 为按可用因子重分配权重后的加权和。
- **理论最小值 = 0**：从未主动返工（`O1 = 0`）、从未分享（`O2 = 0`）、O3 关闭或为 0。
- **理论最大值 = 10**：`O1 = 1`（每个已完成任务平均至少被主动返工一次）且 `O2 = 1`（每个已完成任务都分享出去）；启用 O3 时还需 `O3 = 1`。
- **10 分上限的依据**：`O1`、`O2`（及 O3）各自是 `[0,1]` 闭区间内的比例，权重重分配后 `raw` 仍在 `[0,1]`，`×10` 是 SPEC 12.3 的刻度映射而非经验截断；`clamp(0, 10)` 仅作防御性断言（防止权重配置变更或时钟回拨导致越界）。
- **不设下限截断**：0 分是真实现象（做完就走、从不回头改），抬高下限会掩盖最需要被看见的信号。

### 4.4 手算示例

事件序列（`domain_id = writing_general`，`user_id = U1`；`USE_REPORT_VIEW = false`）：

| # | `occurred_at` | `event_type` | `task_id` |
|---|---|---|---|
| 1 | 2026-09-01T20:00:00Z | `task_start` | `writing_general_L2_001` |
| 2 | 2026-09-01T20:10:00Z | `task_abandon` | `writing_general_L2_001` |
| 3 | 2026-09-01T20:15:00Z | `task_retry` | `writing_general_L2_001` |
| 4 | 2026-09-01T20:40:00Z | `task_complete` | `writing_general_L2_001` |
| 5 | 2026-09-02T20:00:00Z | `task_start` | `writing_general_L2_002` |
| 6 | 2026-09-02T20:20:00Z | `task_complete` | `writing_general_L2_002` |

逐步计算：

1. `completed_task_ids = { writing_general_L2_001, writing_general_L2_002 }` → `n_task = 2 ≥ 1`，继续。
2. O1：唯一的 `task_retry` 是 #3，其同任务前序事件 #2 为 `task_abandon` → **补救性重做，排除**。
   `proactive_retry_tasks = ∅` → `O1 = min(0 / 2, 1) = 0`
3. O2：序列中无 `task_share` → `shared_tasks = ∅` → `O2 = min(0 / 2, 1) = 0`
4. O3：`USE_REPORT_VIEW = false` → `O3 = null`
5. 权重重分配：可用项 `{O1, O2}` → `w'_1 = 0.6 / 1.0 = 0.6`，`w'_2 = 0.4 / 1.0 = 0.4`
   `raw = 0.6 × 0 + 0.4 × 0 = 0`
6. `value = 0 × 10 = 0.00`

输出：`{ "metric": "proactive_optimization", "value": 0.00, "status": "ok" }`

> 注意：此处 `0.00` 是**有效测量值**（确实观测到"从不主动返工、从不分享"），
> 与 `status = "insufficient_data"` 的 `null` 语义完全不同，不可互相替代。
> 对照：若误把 #3 的补救性重做计入 O1，则 `O1 = 1/2 = 0.5`、`raw = 0.3`、`value = 3.00` —— 虚高 3 分，
> 这正是步骤 2 必须排除 `task_abandon` 后紧跟的 `task_retry` 的原因。

---

## 5. `pain_tolerance`（痛苦耐受度）

### 5.1 输入数据契约

| 项 | 内容 |
|---|---|
| 需要的 `event_type` | `task_start` / `task_resume`（段起点）、`task_complete` / `task_abandon` / `task_pause`（段终点）、`task_retry` / `task_start`（连败链的闭合信号） |
| 不需要的 `event_type` | `session_start` / `session_end` / `domain_switch` / `task_share` / `report_view` / `settings_change`（`session_*` 仅作段边界的兜底终止条件，不直接计分） |
| 关键字段 | `event_type`、`occurred_at`、`domain_id`、`duration`（段时长主源）、`task_id`（段配对，缺失则降级）、`level`（预留因子 T3，MVP 默认关闭） |
| 字段缺失兜底 | `duration` 缺失 / 为 null / ≤ 0 → 回退用"终点时间 − 起点时间"，仍 ≤ 0 → 该段剔除；`task_id` 缺失 → 该段不可配对，剔除但仍计入领域级连败链；`occurred_at` / `domain_id` 缺失 → 丢弃 |
| 最少 event 数 | **≥3 个有效投入段**（T1）**或 ≥1 条闭合连败链**（T2），二者至少满足其一 |
| 不足时返回 | `value = null`、`status = "insufficient_data"`（T1、T2 同时不可算时） |
| 与 `bounce_back` 的分工 | `bounce_back` 只问"失败后多久回来"（时间维度）；`pain_tolerance` 的 T2 问"能连着扛多少次失败还不走"（次数维度），T1 问"单次能投入多久"（强度维度） |

### 5.2 计算步骤（伪代码）

```
输入：events（单 user × 单 domain，已执行 P1-P5）；t_cut
常量：MIN_SEGMENTS = 3    # T1 所需最少有效投入段
     TT_CAP_MIN  = 30    # 段时长归一化基准（分钟）
     STREAK_CAP  = 3     # 连败链归一化基准（次）
     w1 = 0.6（T1 权重）、w2 = 0.4（T2 权重）、w3 = 0.2（T3 权重，仅启用时参与）
     USE_LEVEL = false   # T3 开关

步骤 1 · 切分投入段
  segments ← []
  对 events 按时间升序扫描：
    若 e.event_type ∈ { "task_start", "task_resume" }：open ← { start_time: e.occurred_at, task_id: e.task_id }
    若 open 非空 且 e.event_type ∈ { "task_pause", "task_complete", "task_abandon", "session_end" }：
       segments.append({ 起点: open.start_time, 终点: e.occurred_at, 终点事件: e }；open ← 空
  窗口末仍 open 的段：右删失，剔除
  # 为什么这样切：一段"连续投入"的语义是"从开始动手到停下来/交卷/放弃"，
  #   task_resume 表示被打断后重新开始，因此也作为新段起点，避免把中断时长算进耐受。

步骤 2 · 段时长与异常剔除
  对每个段 s：
    若 s.终点事件 的 duration 存在且 > 0：s.minutes ← duration / 60
        # 为什么优先用 duration：客户端上报的 duration 是"实际投入时长"，天然扣除暂停与中断；
        #   时间戳差包含中断，会高估耐受。
    否则：s.minutes ← (s.终点时间 − s.起点时间) 换算为分钟
        # 为什么回退：duration 缺失或为 0 是采集故障的典型特征（上报早退、字段未赋值），
        #   不是"用户投入了 0 分钟"；能用时间戳差救回来就救。
    若 s.minutes <= 0：剔除该段   # 时间倒序或同刻上报，不可信
  valid_segments ← 剩余段
  # 为什么剔除而不是当 0 分：0 时长是设备故障特征，当成"0 耐受"会把设备/埋点问题读成用户素质。

步骤 3 · T1 时长耐受
  若 |valid_segments| < MIN_SEGMENTS：T1 ← null
     # 为什么要求 3 段：单段无法区分"耐受"与"偶然一次的长投入"，2 段没有中位数可言，
     #   3 段是能取中位数、且能观察一次波动的最小样本。
  否则：
     med ← median(valid_segments 的 minutes)
        # 为什么用中位数：抗挂机 / 忘记结束任务造成的长尾，一次 3 小时的异常段不该代表用户。
     T1 ← min(med / TT_CAP_MIN, 1)
        # 为什么基准是 30 分钟：产品约束为"每天每领域 15-30 分钟"（第 1 节），
     #   30 分钟是设计上的单次投入上限；超过 30 分钟更多反映"挂着没退"而非耐受差异，故截断。

步骤 4 · T2 连败耐受
  在领域时间序列中，把"连续相邻的 task_abandon（其间不出现 task_complete）"划为一条连败链，
  记录链长 L = 该链中 task_abandon 的个数
     # 为什么用"其间不出现 task_complete"划界：一旦完成，说明已经扛过去了，链就该重新开始。
  对每条链 c：
     若 c 之后（同 domain）存在 task_start 或 task_retry 且发生在 t_cut 之前：c.closed ← true
     否则：c.censored ← true   # 一直失败到窗口末 —— 观察窗未闭合，剔除（同 P4）
        # 为什么剔除未闭合链：还留在失败里不代表"不耐受"，可能只是数据还没产生；
        #   与 bounce_back 的右删失处理保持一致。
  closed_streaks ← 所有 c.closed == true 的链
  若 |closed_streaks| == 0：T2 ← null
     # 为什么置 null 而不是 0：从未失败 ⇒ 没有耐受的观测窗口（与 bounce_back 边界用例 1 同口径）。
  否则：
     L_max ← max(c.L，c ∈ closed_streaks)
     T2 ← min(L_max / STREAK_CAP, 1)
        # 为什么基准是 3 次：3.9 的周节奏下每周围绕 1-2 个 Level 推进，连败 3 次仍返回已属高耐受；
     #   更长的链更可能反映任务难度错配（3.7 / 3.8 的 Level 设计问题）而非用户耐受，
     #   且长链样本稀疏、噪声大 —— 因此截在 3，连败 20 次与连败 3 次同分，不爆表。

步骤 5 · T3 高难度耐受（MVP 默认关闭）
  若 USE_LEVEL == false：T3 ← null
  否则：T3 ← (level >= 4 的 valid_segments 数) / |valid_segments|
  # 为什么默认关闭：MVP 只做 L1-L5，且 Level 由 3.9 的周节奏强制推进，并非用户自主选择；
  #   把"被安排到更高 Level"归因于用户耐受度是错误归因。待产品支持自主选 Level 后再启用。

步骤 6 · 权重重分配
  usable ← { T1, T2, T3 } 中取值非 null 的项
  若 usable 为空：返回 { metric:"pain_tolerance", value:null, status:"insufficient_data" }
  对 usable 中每一项 i：w'_i ← w_i / (Σ w_j，j ∈ usable)
  raw ← Σ (w'_i * T_i)

步骤 7 · 输出
  value ← clamp(round(raw * 10, 2), 0, 10)
  返回 { metric:"pain_tolerance", value, status:"ok",
        detail: { segment_count: |valid_segments|, median_minutes: med, T1,
                  closed_streak_count: |closed_streaks|, L_max, T2, T3, raw } }
```

**中间变量一览**：`segments`、`valid_segments`、`s.minutes`、`med`（段时长中位数，分钟）、`L`（链长）、`closed_streaks`、`L_max`、`T1`、`T2`、`T3`、重分配后的 `w'_i`、`raw`。

### 5.3 归一化方式

- 归一化公式：`value = clamp(round(raw × 10, 2), 0, 10)`，`raw` 为按可用因子重分配权重后的加权和。
- **理论最小值 = 0**：`T1 = 0`（段时长中位数为 0，即每次都几乎立刻退出）且 `T2` 无观测（`null`）时，`raw = 0`。
  **注意 T2 的下界**：只要存在闭合连败链，`L ≥ 1` ⇒ `T2 ≥ 1/3`。这是有意设计——"扛过 1 次失败还回来"就该拿到耐受度的最低信用分，不应与"完全没被观测到"同分。
- **理论最大值 = 10**：`T1 = 1`（段时长中位数 ≥ 30 分钟）且 `T2 = 1`（存在 ≥3 次的闭合连败链）；启用 T3 时还需 `T3 = 1`。
- **`TT_CAP_MIN = 30` 的截断依据**：产品约束"每天每领域 15-30 分钟"（第 1 节），30 分钟是设计上限；超出部分多为挂机/忘记结束，与耐受度无关，截断后可避免"忘记退出"被读成高耐受。
- **`STREAK_CAP = 3` 的截断依据**：连败 3 次仍返回已属高耐受；更长的链更可能反映任务难度错配而非用户素质，且长链样本稀疏、噪声大；不做截断会让"连败 20 次"把分数推到与单次失败完全不同的量级，破坏 5 维之间的可比性。
- **`clamp(0, 10)` 仅作防御性断言**：`T1`、`T2`（及 T3）各自是 `[0,1]` 闭区间内的比例，重分配后 `raw ∈ [0,1]`；保留 clamp 是防止权重配置变更或 `duration` 语义变化导致越界。

### 5.4 手算示例

事件序列（`domain_id = running`，`user_id = U1`；`USE_LEVEL = false`）：

| # | `occurred_at` | `event_type` | `task_id` | `duration` |
|---|---|---|---|---|
| 1 | 2026-09-01T20:00:00Z | `task_start` | `running_L2_001` | — |
| 2 | 2026-09-01T20:20:00Z | `task_complete` | `running_L2_001` | 1200 |
| 3 | 2026-09-02T20:00:00Z | `task_start` | `running_L2_002` | — |
| 4 | 2026-09-02T20:15:00Z | `task_pause` | `running_L2_002` | 900 |
| 5 | 2026-09-03T20:00:00Z | `task_start` | `running_L2_003` | — |
| 6 | 2026-09-03T20:30:00Z | `task_complete` | `running_L2_003` | 1800 |

逐步计算：

1. 切分投入段（起点 `#1/#3/#5`，终点 `#2/#4/#6`）：
   - S1：`running_L2_001`，终点 `duration = 1200s` → `20.0` 分钟
   - S2：`running_L2_002`，终点 `duration = 900s` → `15.0` 分钟
   - S3：`running_L2_003`，终点 `duration = 1800s` → `30.0` 分钟
   三段 `duration` 均 > 0，无需回退时间戳差；`valid_segments = 3`。
2. T1：`|valid_segments| = 3 ≥ MIN_SEGMENTS` → `med = median(20, 15, 30) = 20.0`
   `T1 = min(20.0 / 30, 1) = 0.6667`
3. T2：序列中无 `task_abandon` → `closed_streaks = ∅` → `T2 = null`（无观测窗口）。
4. T3：`USE_LEVEL = false` → `T3 = null`。
5. 权重重分配：可用项只有 T1 → `w'_1 = 0.6 / 0.6 = 1.0`
   `raw = 1.0 × 0.6667 = 0.6667`
6. `value = 0.6667 × 10 = 6.6667 → 6.67`

输出：`{ "metric": "pain_tolerance", "value": 6.67, "status": "ok" }`

> 对照：若序列中还存在一条闭合连败链 `L = 1`（`task_abandon` 后出现 `task_retry`），
> 则 `T2 = min(1/3, 1) = 0.3333`，重分配后 `w'_1 = 0.6`、`w'_2 = 0.4`，
> `raw = 0.6 × 0.6667 + 0.4 × 0.3333 = 0.4 + 0.1333 = 0.5333` → `value = 5.33`。
> 两个结果均可手算复核。

---

## 6. 边界用例总表（6 个，必测）

> 通用前提：`user_id = U1`，单领域 `domain_id = go`（用例 6 涉及跨领域），窗口 `t_cut` 已给定；
> 所有事件均已通过 P1 过滤；下列"输入事件序列"为精简后的关键片段。

| # | 涉及指标 | 场景 | 输入事件序列（精简） | 期望输出 | 理由 |
|---|---|---|---|---|---|
| 1 | `bounce_back`（主）、`pain_tolerance`（T2） | 用户一次都没失败 | `task_start`×3 → `task_complete`×3（全程无 `task_abandon`） | `bounce_back`：`value = null`、`status = "insufficient_data"`；`pain_tolerance` 的 `T2 = null`（权重全给 T1）；其余 3 个指标正常输出有效值 | 分母为 0 时**绝不返回 0**：0 分意味着"观测到失败后从不回来"，而此处是**从未失败、没有观测窗口**。按 0.5 兜底总原则，一律 `null` + `insufficient_data`，且该指标不参与该领域的 5 维画像与斜率对比 |
| 2 | 全部 5 个 | 用户只做了 1 个任务 | `task_start`(`go_L1_001`) → `task_complete`(`go_L1_001`)，仅 1 天、1 个任务 | `repetition` = `0.00`（ok）；`detail_sensitivity` = `0.00`（ok）；`proactive_optimization` = `0.00`（ok）；`bounce_back` = `null`；`pain_tolerance` = `null`（有效段数 1 < `MIN_SEGMENTS`、无连败链 → T1、T2 均不可算） | 单任务只能支撑"事实型"结论（完成了 / 没完成），支撑不了"速率型 / 耐受型"结论：回炉率、打磨率、返工率的分母都存在，故可输出真实 0 分；反弹需要失败锚点、耐受需要 ≥3 个投入段，样本不足 → `null` |
| 3 | `pain_tolerance`（其余 4 个不受影响） | 所有事件 `duration` 都是 0 | 若干 `task_start` → `task_complete`，每条事件的 `duration = 0`（时间差正常、均为 20 分钟） | `pain_tolerance` 正常输出有效值（段时长回退为"终点时间 − 起点时间"，`med = 20` → `T1 = 0.6667`）；其余 4 个指标不受影响（不使用 `duration`）。**特例**：若事件时间戳也全部相同（时间差同为 0）→ 全部段被剔除 → `T1 = null`，此时若 `T2` 也为 `null` → `pain_tolerance` = `null` + `insufficient_data` | `duration = 0` 是采集故障的典型特征（上报早退、字段未赋值），不是"用户投入 0 分钟"：先按 5.2 步骤 2 回退时间戳差；只有当两条路径都不可得时才判定为不可计算，绝不把异常数据读成"0 耐受" |
| 4 | `pain_tolerance`（主）、`bounce_back` | 用户连续失败 20 次 | 同领域 `task_abandon` × 20（其间无 `task_complete`）→ 其后 1 个 `task_start`（窗口内，其后 24h 无 `task_complete`） | `pain_tolerance` 的 `T2 = min(20/3, 1) = 1`（截断，不爆表），`pain_tolerance` 输出有效值；`bounce_back` = `0.00`（`status = ok`，20 个锚点的恢复时延均远超 72h → `F1 = 0`，且无 24h 内完成 → `F2 = 0`）；`repetition` / `detail_sensitivity` / `proactive_optimization` = `null`（`completed_task_ids` 为空） | 连败链长 20 被 `STREAK_CAP = 3` 截断为满分：更长的链更可能反映任务难度错配而非用户耐受，且长链噪声大，不截断会破坏 5 维间的可比性。`bounce_back` 侧：同一恢复事件可被多个锚点共享（判定的是"该锚点之后是否回来"，不设消费唯一性），20 个锚点均未在 72h 内回归，故 `F1 = 0` —— 这是真实测量结论，返回 0 分而非 `null` |
| 5 | 全部 5 个（时序相关） | 事件时间戳乱序 | 到达顺序：`task_complete`(20:30) → `task_start`(20:00) → `task_retry`(20:40)，`task_id` 相同 | **先按 `occurred_at` 升序排序（P2）再计算**：排序后为 `start`(20:00) → `complete`(20:30) → `retry`(20:40)，`retry` 的前序事件为 `complete` → `proactive_optimization` 的 O1 计 1 次主动返工、`detail_sensitivity` 的 D2 纳入返工集合；段时长为正值，`pain_tolerance` 正常 | 所有"前序事件 / 上一次 / 相邻配对"判定依赖**时间序**而非到达序。若不排序：`retry` 的前序会被误判为 `complete` 之前的事件、段时长出现负值（负值段在 5.2 步骤 2 被剔除，会导致样本量被错误削减）、`bounce_back` 的反弹窗口方向反转。**排序是所有指标的前置条件，不可省略** |
| 6 | 全部 5 个（跨领域归属） | 用户中途 `domain_switch` | `go`: `task_start` → `task_abandon`；`domain_switch`；`photography`: `task_start` → `task_complete`；回到 `go`: `task_retry`(`go_L2_001`) | 按 `domain_id` 分组计算：`domain_switch` **不产生任务行为，不计入任一指标的分子或分母**；`photography` 的 `task_complete` **不算** `go` 的"反弹后推进"（F2）与"已完成任务数"；`go` 的 `bounce_back`：其 `task_abandon` 锚点的恢复信号只认同领域的 `task_retry` → 判定成立并按实际时延计分 | 5 个指标均为 `user × domain` 粒度（0.1）。跨领域的动作语义是"换方向"，既不是本领域的反弹，也不是本领域的重复或打磨；若不按领域切断，用户在别处的努力会被错记到当前领域的画像上，直接污染 4 周斜率对比 |

---

## 7. 文档汇总

### 7.1 五指标总表

| 指标 | 主输入 `event_type` | 最少样本（分母） | 样本不足时 | 归一化式 | 因子权重 |
|---|---|---|---|---|---|
| `bounce_back` | `task_abandon`、`task_start`、`task_retry`、`task_complete` | ≥1 个非右删失失败锚点 | `null` + `insufficient_data` | `(0.7·F1 + 0.3·F2) × 10` | F1 0.7 / F2 0.3 |
| `repetition` | `task_start`、`task_complete`、`task_retry`、`task_abandon`、`session_start` | ≥1 个活跃日 且 ≥1 个 `task_complete` | `null` + `insufficient_data` | `(0.6·R1 + 0.4·R2) × 10` | R1 0.6 / R2 0.4 |
| `detail_sensitivity` | `task_pause`、`task_resume`、`task_retry`、`task_complete` | ≥1 个 `task_complete` | `null` + `insufficient_data`（仅在无任何完成事件时） | 重分配后 `raw × 10` | D1 0.6 / D2 0.4 / D3 0.3（默认关闭） |
| `proactive_optimization` | `task_retry`、`task_complete`、`task_abandon`、`task_share`、`report_view`（预留） | ≥1 个 `task_complete` | `null` + `insufficient_data` | 重分配后 `raw × 10` | O1 0.6 / O2 0.4 / O3 0.2（默认关闭） |
| `pain_tolerance` | `task_start`、`task_resume`、`task_pause`、`task_complete`、`task_abandon`、`duration`、`level`（预留） | ≥3 个有效投入段 **或** ≥1 条闭合连败链 | `null` + `insufficient_data` | 重分配后 `raw × 10` | T1 0.6 / T2 0.4 / T3 0.2（默认关闭） |

### 7.2 常量总表（均为本次设计取值，SPEC 未给定，需产品/算法侧校准）

| 常量 | 取值 | 所在指标 | 依据 |
|---|---|---|---|
| `W_recovery` | 72 小时 | `bounce_back` F1 | 覆盖 3.9 周节奏下的"下一次练习窗口"；超过 72h 的回归更接近另起一轮 |
| `W_finish` | 24 小时 | `bounce_back` F2 | 下一次练习窗口粒度，避免把几天后的无关完成计入 |
| `PLANNED_PER_DAY` | 1 | `repetition` R2 | 产品约束"每天每领域 15-30 分钟" `[待核验:SPEC 是否定义每日计划任务数]` |
| `PAIR_CAP` | 2 对/任务 | `detail_sensitivity` D1 | 1 次 pause→resume 可能是外部打断；≥2 次才有把握读作"在抠细节"；更多不再加分以防奖励拖延 |
| `MIN_SEGMENTS` | 3 段 | `pain_tolerance` T1 | 取中位数、且能观察一次波动的最小样本 |
| `TT_CAP_MIN` | 30 分钟 | `pain_tolerance` T1 | 产品约束的每日单领域投入上限；超出多为挂机 |
| `STREAK_CAP` | 3 次 | `pain_tolerance` T2 | 连败 3 次仍返回已属高耐受；更长链多为难度错配，且噪声大 |

### 7.3 兜底语义汇总（5 个指标一致）

1. **分母为 0 / 有效观测数为 0 → `value = null` + `status = "insufficient_data"`**，绝不返回 0。
2. **0 分是有效测量结论**（`status = "ok"`），表示该维度确实观测到"从不 / 从不"的行为，不得与 `null` 互相替代。
3. **`status = "insufficient_data"` 的指标不参与**该领域的 5 维画像与进步斜率计算，也不参与领域间横向对比。
4. **因子缺失（`null`）→ 权重重分配**，不当 0 分；若全部因子均缺失 → 整指标 `null` + `insufficient_data`。
5. **右删失（观察窗未闭合）→ 剔除该观测**，不计入分子与分母。
6. **异常数据（`duration ≤ 0`、时间倒序、同刻上报）→ 剔除该观测**，不当 0 分。

---

## 备注

1. SPEC 4.2 的 event schema 未随 C12a 下发：`occurred_at` / `session_id` / `duration` / `evaluator_score` 等字段名除 3.x 冻结项外均为建议名（正文已标 `[待核验]`），落地请以 SPEC 4.2 实际字段名为准。
2. 输出字段名 `value` / `status` 及 `status` 枚举 `ok | insufficient_data` 为实现层新增（非 3.x 冻结项），若 SPEC 已有定义请覆盖。
3. 所有常量（7.2）与因子权重均为本次设计取值，SPEC 未给定，需产品/算法侧校准；`task_share` / `report_view` 的触发语义未确认，O2 暂按"用户主动分享"启用、O3 默认关闭。
4. 边界用例 4 明确了 `bounce_back` 的"同一恢复事件可被多个失败锚点共享"口径，属对第 1 批规格的澄清补充，非变更。
5. 未产出测试数据（C12b）与 SQL（C12c）；`detail_sensitivity` 的 D3、`pain_tolerance` 的 T3 已留口，字段确认后启用即可，无需改动其他逻辑。

```yaml
# === TILT-CONTRACT-MANIFEST ===
# task_id: C12a
# spec_version: V1.3
# ssot_checksum: TL-SSOT-2026-09-20-A
# baseline_version: B1.0
# produced_by: 元宝
# produced_at: 2026-09-20
# batch: all
# output_files:
#   - docs/metrics_spec.md   (rows: 5 指标 / 6 边界用例)
# unverified_count: 7
# self_check:
#   frozen_ids_only: true
#   enum_from_spec: true
#   no_absolute_claims: true
#   no_new_concepts: true
#   spec_numbers_unchanged: true
# known_deviations:
#   - SPEC 4.2 event schema 未随本任务下发，非冻结字段名按建议名书写并就地标注 [待核验]
#   - 输出字段 value/status 与 status 枚举为实现层新增，非 3.x 冻结项
#   - 常量（W_recovery/PLANNED_PER_DAY/PAIR_CAP/MIN_SEGMENTS/TT_CAP_MIN/STREAK_CAP）与因子权重为设计取值，SPEC 未给定
#   - 边界用例 4 补充澄清 bounce_back 恢复信号可被多个锚点共享（口径澄清，非变更）
# === END MANIFEST ===
```
: true
# known_deviations:
#   - SPEC 4.2 event schema 未随本任务下发，非冻结字段名按建议名书写并就地标注 [待核验]
#   - 输出字段 value/status 与 status 枚举为实现层新增，非 3.x 冻结项
# === END MANIFEST ===
```
ND MANIFEST ===
```
