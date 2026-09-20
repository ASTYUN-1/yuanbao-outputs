# C12b · 手算推导（manual_derivation）

> 本文件说明 `events_5users.jsonl` 的数据是怎么设计的、以及 `expected_results.json` 里的区间为什么是那个宽度。
> 验收方式：本机实现跑出的点估计应落在对应区间内；若落在区间外，先比对 §0 口径，再比对本文件的推导。

## §0 指标口径（本 fixture 的显式定义）

> 任务书引用了 SPEC 4.4 / SPEC 12.3 的公式，但这两个公式未随任务下发。为保证可手算复核，此处把口径写死；
> 若 SPEC 原文口径不同，需按 SPEC 重算期望值（已记入 manifest 的 `known_deviations`）。

| 指标 | 口径 |
|---|---|
| `objective_level` | 以该用户**最后一条事件所在日**为锚点回溯 7 天，取其中 `success=true` 的 `task_complete` 的 `task_level` 均值；样本 <3 条时回溯 14 天 |
| `objective_slope` | 按天 1-7/8-14/15-21/22-28 分周，取每周 `success=true` 任务的 `task_level` 均值，对周序号做 OLS，单位「等级/周」；有效周数 <3 时不可辨识，输出 `[0.0, 0.0]` |
| `bounce_back` | 挫败事件 = `task_abandon` ∪ `success=false` 的 `task_complete`；反弹 = 该事件后 48h 内出现同一 domain 的 `success=true` 任务。得分 = 10 × 反弹数 / 挫败数；无挫败样本时按满分先验记 10.0 |
| `repetition` | 用户级次日复访率：10 × \|{d：第 d 天与第 d+1 天均有事件}\| / \|{d ≤ 27：第 d 天有事件}\| |
| `detail_sensitivity` | 10 × 成功任务中 `pause_count ≥ 1` 的占比 |
| `proactive_optimization` | 10 × 成功任务中 `retry_count ≥ 1` 的占比 |
| `pain_tolerance` | 基准时长 `base(level) = 600 + 300×level` 秒；10 × mean(min(`duration_seconds` / base, 2.0)) / 2.0 |

数据构造约定：`objective_score` / `success` 只出现在 `task_complete` 与 `task_abandon` 两类事件上；
`task_id` 按 3.7 的 `{domain_id}_L{level}_{三位序号}` 逐（用户, 领域, 等级）递增编号。

## §1 user_001 · 稳定进步型

48 次任务按 3.9 排 L1-2→L4-5，周均 1.4→2.5→3.4→4.5，斜率≈1.0、水平 4.5；2 次挫败均 24h 内复练→反弹 10；28 天不断档→复访 27/27；时长 1.25 倍基准→耐受 6.2。

## §2 user_002 · 三天打鱼型

前 10 天密集、11-15 天空窗、后隔天零星；断档后等级停滞，周均 1.4→2.0→2.3→2.2，斜率仅 0.18-0.28；3 次挫败仅 1 次 24h 复练→反弹 3.3；活跃 17 天中 10 天次日活跃→复访 5.9。

## §3 user_003 · 痛苦耐受高但进步慢型

时长恒为基准 1.8 倍（L3 约 2700s）→耐受 9.0；等级压在 L2-L3 缓升，周均 1.5→2.3→2.6→3.0，斜率 0.4-0.6；28 天不断档→复访 10.0；4 次挫败 3 次 24h 复练→反弹 7.5。

## §4 user_004 · 作弊嫌疑型

时长恒 418-421s（基准 0.2 倍）→耐受 1.3；分数恒 90.7-91.3；时间戳全落 12:00/12:01/12:07 整分网格；第 3 周即封顶 L5，违反 3.9 节奏；零暂停零重做→细节与优化为 0。

## §5 user_005 · 只做 1 周就退出型

仅第 1-7 天 41 条事件，第 8 天起为零；等级只到 L1-2（1.33-1.5）；每领域末次任务均 task_abandon 且此后无窗口→反弹 0；有效周数 1<3→斜率不可辨识 [0,0]；复访 6/7→8.6。

<!-- === TILT-CONTRACT-MANIFEST ===
# task_id: C12b
# spec_version: V1.3
# ssot_checksum: TL-SSOT-2026-09-20-A
# baseline_version: B1.0
# produced_by: Yuanbao（元宝）
# produced_at: 2026-09-20
# batch: all
# output_files:
#   - events_5users.jsonl   (rows: 427)
#   - expected_results.json   (rows: 15)
#   - manual_derivation.md   (rows: 5)
# unverified_count: 0
# self_check:
#   frozen_ids_only: true
#   enum_from_spec: true
#   no_absolute_claims: true
#   no_new_concepts: true
#   spec_numbers_unchanged: true
# known_deviations:
#   - SPEC 4.4 / 12.3 的指标公式未随任务下发，§0 为本 fixture 显式定义的口径，若 SPEC 原文不同需重算
#   - 4.5 要求 manifest 置顶，与 4.2/6.6「JSONL 每行可 json.loads、JSON 无注释」冲突，经确认改为独立 sidecar manifest_C12b.yaml
#   - user_004 的等级递进故意违反 3.9 节奏（第 3 周即 L5），属作弊特征，非 SPEC 数值改动
#   - 受 6.3「每人 60-120 条」上限约束，工作日 2 个领域 / 周末 1 个领域，未做到每日 3 个领域全覆盖
# === END MANIFEST === -->
