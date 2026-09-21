# C12b-重算 · 手算推导

## 0 · 两个决策

### 决策 1 · 零失败用户的 bounce_back → 选 **方案 B**

`user_001 / user_004 / user_005` 零失败。SPEC 12.3 的 `if not failures: return 0` 会把「4 周零失败的稳定进步型」写成 0 分，
而 0 分在 0-10 量表上只能被读作「反弹力最差」，与事实相反，直接违反 SPEC 8.2 引导性语言原则。
方案 A 忠于公式但语义错误；方案 C 要改 `metrics_spec.md`，该文件不归本任务管。
**故选 B：返回 `null` + `bounce_back_note`（「零失败，该指标不适用」）。**
建议在下一轮由 `metrics_spec.md` 的负责人补上「零失败时该指标不参与综合分」——即 B 是本次产出、C 是后续衔接动作。

### 决策 2 · ~~补事件~~ **作废**（上一轮该段整体撤回）

上一轮我写的 `go_L3_005 / 006 / 007` 三条 `task_retry` **全部作废**：`go_L3_005` 在流中是 `success=true`，`go_L3_006`、`go_L3_007` 在流中根本不存在。
那三条 task_id 是我按「人设应该是 L3」倒推臆造的，不是读流得到的，**违反第 2 节约束 2（不编造）**。实测 `events_user_003.jsonl` 后，原判「缺重试数据」被推翻：

**事实 1**：3 次失败实际是 `go_L4_001`（09-15T18:00）、`writing_general_L4_001`（18:36）、`photography_L4_001`（19:11），
**全部在 L4、跨三个领域各 1 次**，不是 L3、也不集中在 go。

**事实 2**：user_003 有 9 条独立 `task_retry` 事件，不是缺数据。SPEC 12.3 的判定条件 `e.task_id == fail.task_id and e.timestamp > fail.timestamp`
**不区分 event_type**，`task_retry` 同样计入重试 → 三次失败在 24h 内均有同 task_id 的后续事件 → `retry_rate = 3/3 = 1.0`。

**事实 3**：按领域口径，每领域 1 次失败、1 次 24h 内重试 → `retry_rate = 1/1 = 1.0`（与用户级同值）。

**结论：不补任何事件，全部按现有数据计算。**
**口径 B（已钉死）**：`max_consecutive_failures` 按**领域口径**计算（报告分领域出）。
领域内仅 1 次失败 → `max_consecutive = 1` → `bounce_back = 1.0×5 + 1 = ` **6.0（点值）**。

### 口径 A · `objective_slope` 的周边界（已钉死，不再给区间）

`T0` = 该用户首个事件的当日 00:00；`week N` = 开区间 `(T0+7(N-1), T0+7N]`。
两处边界效应：`user_001` 达成 L2 的时刻 `2026-09-01T09:20:00Z` 按严格边界落在 week2 → week1 = 1；`user_004` 的 T0 = `2026-08-23`（比其他人早一天）。
15 组全部为确定值：user_001 **1.00**；user_002 go **0.25**、其余 **0.00**；user_003 **0.50**；user_004 **0.75**（不变）；user_005 **0.00**。

---

## 1 · user_001（稳定进步型）

45 个完成、45/45 全成功，三领域各 15 → 每领域 L1-L5 各 3 个；28 天无断档。
`level`：每级 3 个满足 ≥3 且 100%>70%，L1→L5 逐级通过 = **5.0**。
`slope`：按**口径 A**，达成 L2 的时刻 `2026-09-01T09:20:00Z` 按严格边界落在 week2 → week1 = 1、week4 = 5 → `(5-1)/4 = ` **1.00**（三领域同值）。
`pain_tolerance = duration_score + [0,5]`：`duration_score` 用**领域级** max duration —
go `1783/60/30 = 0.9906` → **[0.99, 5.99]**；writing `1926/60/30 = 1.07` → **[1.07, 6.07]**；photo `1882/60/30 = 1.0456` → **[1.05, 6.05]**。
`bounce_back`：零失败 → 决策 1 取 `null`；`repetition` = 0（无 task_id 被完成超过 1 次）；`detail_sensitivity` / `proactive_optimization` = 0（SPEC 4.2 event schema 无对应字段）。
level / slope / bounce_back 为点值；pain_tolerance 的 5 分宽度全部来自 `dry_completion` / `next_day_return` 未观测。

## 2 · user_002（三天打鱼型）

23 个完成、21 成功 / 2 失败；只 9 天有事件。**2 次失败全在 go**，writing / photography 零失败（据修正 2）。

**go**（完成 11、失败 2，直方图 L1:3 L2:4 L3:3 L4:1，max_dur 1708s）
失败实测落点：`go_L2_002`（L2，08-28T09:22:12）、`go_L3_001`（L3，09-02T09:22:44）。
`level`：L1 3/3=100% → 1；**L2 3/4=75% > 70% → 2**（含 `go_L2_002` 失败）；**L3 2/3=66.7% ≤ 70% → break**（含 `go_L3_001` 失败）→ **2.0**；L4 仅 1 个 <3 不再参与。
`slope`：口径 A，week1=1、week4=2 → **0.25**（点值）。
`bounce_back`：2 次失败均有 24h 内同 task_id 后续事件 → `retry_rate=2/2=1.0`，口径 B 领域 `max_consecutive=1` → `1.0×5+1 =` **6.0**。
`repetition`：`go_L2_002` 与 `go_L3_001` **各完成 2 次** → `same_task_repetitions=2`、`voluntary_repeats=0` → `min(0×2 + 2×0.5, 10) = ` **1.0**（其余 14 组无 task_id 被完成超过 1 次 → 0）。
`pain_tolerance = 1708/60/30 = 0.9489` + [0,5] → **[0.95, 5.95]**。

**writing_general**（完成 7、失败 0，L1:2 L2:2 L3:2 L4:1，max_dur 1765s）
`level`：**无任何等级凑满 3 个** → L1/L2/L3/L4 全被 ≥3 门槛跳过（不足 3 个不触发 break）→ **0.0**；`slope` = 0.00（口径 A，week1=week4=0）。
`bounce_back`：**零失败 → null**（决策 1·B）。`pain_tolerance = 1765/60/30 = 0.9806` + [0,5] → **[0.98, 5.98]**。

**photography**（完成 5、失败 0，L1:1 L2:2 L3:1 L4:1，max_dur 1953s）
`level`：同上，无等级凑满 3 个 → **0.0**；`slope` = 0.00；`bounce_back`：**零失败 → null**。
`pain_tolerance = 1953/60/30 = 1.085` + [0,5] → **[1.09, 6.09]**。

## 3 · user_003（痛苦耐受高但进步慢）

45 个完成、42 成功 / 3 失败；三领域**各自**完成 15、失败 1，直方图 L1:3 L2:5 L3:5 L4:2，max_dur 7200s；28 天无断档。
失败点：`go_L4_001` / `writing_general_L4_001` / `photography_L4_001`，**每领域 1 次，均在 L4**。
`level`：L1 3/3、L2 5/5、L3 5/5 均 100%>70% → 3；L4 仅 2 个 <3 → 跳过 → **3.0**（三领域同值）。
`slope`：口径 A，week1=1、week4=3 → `(3-1)/4 = ` **0.50**（三领域同值）。
`bounce_back`：`retry_rate = 1/1 = 1.0`（9 条 `task_retry` 中对应 3 条落在失败后 24h 内，SPEC 12.3 不区分 event_type）；口径 B 领域 `max_consecutive=1` → `1.0×5 + min(1,5) = ` **6.0（点值）**（决策 2 已作废补事件方案）。
`pain_tolerance = min(7200/60/30, 5) = 4.0` + [0,5] → **[4.0, 9.0]**（五人中最高，与人设相符）；余三项 6.3 无统计量 → 0。

## 4 · user_004（作弊嫌疑型）

30 个完成、30/30 全成功，每领域 10 个 = L1×3 / L2×2 / L3×2 / L4×3；均值仅 41s。
`level`：L1(3) 与 L4(3) 各自 ≥3 且全成功，L2/L3 各 2 个被 ≥3 门槛**跳过且不触发 break** → 直达 **4.0**。
`slope`：累计口径 week1=1、week4=4 → **0.75**（仅当周口径一致）。
`pain_tolerance` 改用**领域级** max duration：go `133/60/30 = 0.0739` → **[0.07, 5.07]**；writing `124/60/30 = 0.0689` → **[0.07, 5.07]**；photo `140/60/30 = 0.0778` → **[0.08, 5.08]**（全场最低）。
`bounce_back`：零失败 → 决策 1 取 `null`。
⚠ 均值 41s 仍拿 level 4 / slope 0.75：SPEC 4.4 的 ≥3 门槛无法识别刷量，见备注建议 3。

## 5 · user_005（只做 1 周退出）

6 个完成、6/6 全成功，每领域 2 个 = L1×1 / L2×1；仅 5 天有事件，第 8 天起零事件。
`level`：无任何等级凑满 3 个任务 → 按 SPEC 4.4 严格算得 **0.0**（与 6.3 人设「level 只到 2」冲突，见备注建议 1）。
`slope`：week1 = week4 = 0 → **0.0**。
`pain_tolerance` 改用**领域级** max duration：go `1500/60/30 = 0.8333` → **[0.83, 5.83]**；writing `1080/60/30 = 0.6` → **[0.60, 5.60]**；photo `1500/60/30 = 0.8333` → **[0.83, 5.83]**。
`bounce_back`：零失败 → 决策 1 取 `null`。

---

## 备注

1. **决策 2 已作废**：上一轮拟补的 3 条 `task_retry`（`go_L3_005/006/007`）是臆造 task_id，已整体撤回；user_003 实际有 9 条 `task_retry`，按现有数据算。
2. **口径已钉死**：口径 A（周边界 `week N = (T0+7(N-1), T0+7N]`）与口径 B（`max_consecutive_failures` 按领域口径）均由需求方确认，15 组 slope 与 user_003 的 bounce_back 全部为点值，不再给区间。user_002 / go 的两次失败落点已实测确认（`go_L2_002`、`go_L3_001`），level=2.0 成立。
3. **冲突**：6.3 人设称 user_005「level 只到 2」、user_003「只到 4」，但按 SPEC 4.4 的 ≥3 门槛算得 0 与 3——未迁就人设。
4. **建议（未写入正式产出）**：user_004 以 41s 均值拿 level 4，≥3 门槛挡不住刷量，建议后续加「最短有效时长」阈值。
5. **SPEC 缺口（已转需求方待办）**：`detail_sensitivity` / `proactive_optimization` 全为 0，因 SPEC 4.2 event schema 无 `late_edits` / `self_corrections` / `off_task_activities` / `path_deviation` 字段，非本产出遗漏。

```yaml
# === TILT-CONTRACT-MANIFEST ===
# task_id: C12b-重算
# spec_version: V1.3
# ssot_checksum: TL-SSOT-2026-09-20-A
# baseline_version: B1.0
# produced_by: Yuanbao
# produced_at: 2026-09-21
# batch: all
# output_files:
#   - fixtures/manual_derivation.md   (rows: 5)
#   - fixtures/expected_results.json  (rows: 15)
# unverified_count: 0
# self_check:
#   frozen_ids_only: true
#   enum_from_spec: true
#   no_absolute_claims: true
#   no_new_concepts: true
#   spec_numbers_unchanged: true
# known_deviations:
#   - 决策1 选 B：零失败用户 bounce_back 返回 null + bounce_back_note
#   - 决策2 作废：撤回上一轮臆造的 3 条 task_retry，user_003 实有 9 条 task_retry，按现有数据算
#   - 口径 A 已钉死：week N = 开区间 (T0+7(N-1), T0+7N]，T0 = 该用户首个事件的当日 00:00（user_004 的 T0=2026-08-23）；user_001 slope=1.00、user_003 slope=0.50
#   - 口径 B 已钉死：max_consecutive_failures 按领域口径，user_003 各领域 max_consecutive=1 → bounce_back=6.0 点值
#   - user_002 / go 的 repetition=1.0：go_L2_002 与 go_L3_001 各完成 2 次 → same_task_repetitions=2、voluntary_repeats=0 → min(0*2+2*0.5,10)=1.0
#   - 上一轮产出含编造 task_id（go_L3_006/007 不存在、go_L3_005 实为 success=true），本轮已按 events_user_003.jsonl 实测纠正
#   - manifest 位置与 4.2 冲突：4.5 要求写在文件顶部，但 JSON 禁止注释，故以首个顶层键 _manifest 承载
#   - 按 >=3 门槛算得 user_005 level=0、user_002 writing_general/photography level=0、user_003 level=3，与 6.3 人设对照冲突，未迁就
# === END MANIFEST ===
```
