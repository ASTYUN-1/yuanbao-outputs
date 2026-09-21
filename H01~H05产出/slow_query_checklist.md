# Tilt · H03 · 慢查询检查清单（本机执行用）

> 用途：本机把 `tools/gen_events.py` 造出的数据导入本地 Postgres 后，照本清单逐条跑 `EXPLAIN`，找出慢查询并留下可对比的记录。
> 本文件只给出 SQL 与判定方法，**不含任何执行结果**（云端未连库，未执行 SQL）。
> 方言：**PostgreSQL 14+**。表名固定：`users` / `task_events` / `weekly_reports` / `user_coordinates` / `weekly_metrics`。

---

## 0 · 前置：导入数据并刷新统计信息

先造数（默认：1000 用户 × 28 天 × 4 事件 = **112,000** 条 `task_events`）：

```bash
python3 tools/gen_events.py --out ./out          # 默认 seed=42，同 seed 可复现
python3 tools/gen_events.py --out ./out_big --users 5000 --days 28 --events-per-user-day 8   # 约 112 万条，压第二轮
```

导入（顺序有外键依赖时按 users → user_coordinates → task_events → weekly_metrics 走）：

```sql
\COPY users (user_id, created_at) FROM 'out/users.csv' WITH (FORMAT csv, HEADER true);

\COPY user_coordinates (user_id,version,cognitive_style,energy_source,feedback_speed,value_orientation,risk_attitude,abstraction_level,created_at)
  FROM 'out/user_coordinates.copy.tsv' WITH (FORMAT text, DELIMITER E'\t', NULL '\N');

\COPY task_events (event_id,user_id,session_id,domain_id,task_id,task_type,task_level,event_type,evaluator_type,timestamp,duration_seconds,completion_rate,objective_score,success)
  FROM 'out/events_copy.tsv' WITH (FORMAT text, DELIMITER E'\t', NULL '\N');

\COPY weekly_metrics (user_id,domain_id,week_no,week_start,week_end,event_count,total_duration_seconds,completion_rate,objective_score,bounce_back,repetition,detail_sensitivity,proactive_optimization,pain_tolerance,created_at)
  FROM 'out/weekly_metrics.copy.tsv' WITH (FORMAT text, DELIMITER E'\t', NULL '\N');
```

> `.copy.tsv` 为 text 格式：无引号包裹、NULL 写 `\N`。若 `db/schema.sql` 字段名与本清单不一致，以 schema 为准改 SQL 列名，查询形态不变。

导入后**必须**刷新统计信息，否则 planner 会用默认估行，EXPLAIN 结论不可信：

```sql
ANALYZE users;
ANALYZE task_events;
ANALYZE weekly_metrics;
ANALYZE user_coordinates;
SELECT relname, n_live_tup FROM pg_stat_user_tables ORDER BY n_live_tup DESC;  -- 确认行数
```

---

## 1 · 待测查询（完整 SQL）

### Q1 · 某用户在某领域某时间段的全部事件（最热路径）

对应产品动作：打开某个领域的 4 周进度页 / 复盘单领域轨迹。**这是最高频查询。**

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT event_id, task_id, task_level, event_type, timestamp,
       duration_seconds, completion_rate, objective_score, success
FROM task_events
WHERE user_id    = 'u_000123'
  AND domain_id  = 'go'
  AND timestamp >= '2026-09-01T00:00:00Z'
  AND timestamp <  '2026-09-08T00:00:00Z'
ORDER BY timestamp;
```

期望形态：`Index Scan` 走 `(user_id, domain_id, timestamp)`；不应出现 `Seq Scan` 或 `Sort` 节点（排序应被索引顺序消化）。

---

### Q2 · 某用户某周的指标（`weekly_metrics` 唯一键查询）

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT user_id, domain_id, week_no, week_start, week_end,
       event_count, total_duration_seconds, completion_rate, objective_score,
       bounce_back, repetition, detail_sensitivity, proactive_optimization, pain_tolerance
FROM weekly_metrics
WHERE user_id   = 'u_000123'
  AND domain_id = 'go'
  AND week_no   = 3;
```

期望形态：`Index Scan`（唯一索引），`rows=1`、`Buffers: shared hit=3~5`。出现 `Seq Scan` 即为缺唯一索引。

---

### Q3 · 某用户最新坐标系（按 version / created_at 取最新）

```sql
-- 3a 按 version 取最新（推荐，version 是显式单调的）
EXPLAIN (ANALYZE, BUFFERS)
SELECT user_id, version, cognitive_style, energy_source, feedback_speed,
       value_orientation, risk_attitude, abstraction_level, created_at
FROM user_coordinates
WHERE user_id = 'u_000123'
ORDER BY version DESC
LIMIT 1;

-- 3b 按 created_at 取最新（若 schema 没有 version 列，用这条）
EXPLAIN (ANALYZE, BUFFERS)
SELECT user_id, version, cognitive_style, energy_source, feedback_speed,
       value_orientation, risk_attitude, abstraction_level, created_at
FROM user_coordinates
WHERE user_id = 'u_000123'
ORDER BY created_at DESC
LIMIT 1;
```

期望形态：`Index Scan ... LIMIT 1` 后直接停止，无 `Sort`（`Sort` 意味着全取用户所有版本再排，数据量小但会随版本数线性变差）。

---

### Q4 · 全站某领域的斜率分布（跨用户聚合，用于分位计算）

对应产品动作：算"你在某领域的斜率处于全站什么位置"。斜率用 PG 内置 `regr_slope` 对每个用户的周序列做最小二乘拟合，不依赖未冻结的中间字段。

```sql
EXPLAIN (ANALYZE, BUFFERS)
WITH per_user AS (
    SELECT user_id,
           regr_slope(objective_score, week_no) AS slope,
           count(*)                            AS week_cnt
    FROM weekly_metrics
    WHERE domain_id = 'go'
    GROUP BY user_id
    HAVING count(*) >= 3        -- 少于 3 周不拟合，斜率无意义
)
SELECT count(*)                                                AS n_users,
       percentile_cont(0.25) WITHIN GROUP (ORDER BY slope)     AS p25,
       percentile_cont(0.50) WITHIN GROUP (ORDER BY slope)     AS p50,
       percentile_cont(0.75) WITHIN GROUP (ORDER BY slope)     AS p75,
       percentile_cont(0.90) WITHIN GROUP (ORDER BY slope)     AS p90
FROM per_user;
```

期望形态：`(domain_id)` 索引下的 `Bitmap Heap Scan` 或 `Index Scan` + `HashAggregate`；`weekly_metrics` 只有万级行时 `Seq Scan` 也可接受（见第 3 节阈值）。

---

### Q5 · 按 `task_level` 分组统计某领域成功率

对应产品动作：判断某领域在 L1-L5 上的难度曲线是否合理（任务分级校准）。

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT task_level,
       count(*)                                                        AS total,
       count(*) FILTER (WHERE success)                                 AS succeeded,
       round(100.0 * count(*) FILTER (WHERE success) / NULLIF(count(*), 0), 2) AS success_rate_pct,
       round(avg(objective_score), 2)                                  AS avg_score
FROM task_events
WHERE domain_id = 'go'
  AND success IS NOT NULL
GROUP BY task_level
ORDER BY task_level;
```

期望形态：`(domain_id, task_level)` 上的 `Index Only Scan`（`success` 进 `INCLUDE`）或 `Bitmap Index Scan`；不应是 11 万行全表扫描。

---

### Q6（补充）· 某用户最近 N 条事件

**补充理由：** 首页"继续上次"与断点续做是每次启动都走的路径，且它是 Q1 的镜像（有时间过滤、无领域过滤），能单独验证"仅按用户+时间"索引是否必要——只建 Q1 的 `(user_id, domain_id, timestamp)` 索引时，这条查询无法有效利用前导列。

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT event_id, domain_id, task_id, task_level, event_type, timestamp, success
FROM task_events
WHERE user_id = 'u_000123'
ORDER BY timestamp DESC
LIMIT 20;
```

期望形态：`Index Scan Backward` + `LIMIT`，无 `Sort`、无全表扫描。

---

### Q7（补充）· 按天事件吞吐（运维看板 / 容量观测）

**补充理由：** 这是唯一"必须全量扫"的查询，用来测**分区前后的基线差值**：分区建立后，若加 `WHERE timestamp >= ...` 约束应出现分区裁剪（`Append` 下只挂 1 个子分区），可直接量化分区收益。

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT date_trunc('day', timestamp) AS day,
       count(*)                     AS events,
       count(DISTINCT user_id)      AS dau,
       sum(duration_seconds)        AS total_seconds
FROM task_events
WHERE timestamp >= '2026-08-24T00:00:00Z'
  AND timestamp <  '2026-09-21T00:00:00Z'
GROUP BY 1
ORDER BY 1;
```

---

### Q8（补充）· 领域弃坑率排行（推荐排序路径）

**补充理由：** 领域推荐排序依赖各领域的 `task_abandon` 率，跨用户、按领域分组、**无时间过滤**——它是分区之后唯一无法靠时间裁剪的聚合查询，用来验证"按月分区是否反而伤害了这条路径"，是第 6.3 节分区方案的决策依据。

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT domain_id,
       count(*)                                                                   AS total,
       count(*) FILTER (WHERE event_type = 'task_abandon')                        AS abandons,
       round(100.0 * count(*) FILTER (WHERE event_type = 'task_abandon')
             / NULLIF(count(*), 0), 2)                                            AS abandon_rate_pct
FROM task_events
WHERE event_type IN ('task_complete', 'task_abandon')
GROUP BY domain_id
ORDER BY abandon_rate_pct DESC;
```

---

## 2 · 测试方法

### 2.1 通用步骤

```sql
-- 可选：开启 I/O 计时，让 EXPLAIN 输出 I/O Timing（需 superuser 或 pg_monitor 权限；
-- 无权限也不影响执行时间测量，只是少了 I/O Timing 一行）
SET track_io_timing = on;

-- 每查询跑 6 次：第 1 次丢弃（冷缓存），后 5 次取中位数
EXPLAIN (ANALYZE, BUFFERS) <上面的 SQL>;
```

判定顺序：

1. **跑 5 次取中位数**，单次结果会被冷缓存 / 检查点 / autovacuum 干扰，不要用一次结果下结论。
2. 只看 `Execution Time` 与 `Planning Time` 之和；`EXPLAIN ANALYZE` 自身有插桩开销（通常 5%-20%），量级判断够用，微优化时以 `pg_stat_statements` 为准。
3. **冷热分开记**：`Buffers: shared hit=` 是命中缓存的页数，`read=` 是真实磁盘读页数。若 `read` 很大，说明查询受 I/O 支配，应单独记一份"冷缓存耗时"。

### 2.2 看哪些指标

| 指标 | 在哪看 | 怎么判 |
|---|---|---|
| `Execution Time` | 末尾 | 与第 3 节阈值比 |
| `Planning Time` | 末尾 | > 5ms 说明分区数过多或统计信息异常 |
| `rows=` 估计 vs `actual=` | 每个节点 | 偏差 > 10 倍 → 统计信息不准或多列相关性问题，先看这个再谈加索引 |
| `Seq Scan` | 节点类型 | 结果集 < 总行数 5% 却走 Seq Scan → 缺索引或索引失效 |
| `Sort Method: external merge` | Sort 节点 | 出现即说明 `work_mem` 不足或排序集过大，应靠索引消除排序 |
| `Buffers: shared read=` | 末尾 | 远大于 0 → 冷缓存路径，需配合索引/分区减少扫描页 |
| `Rows Removed by Filter` | Scan 节点 | 远大于返回行数 → 索引选择性不足或被过滤列未进索引 |

### 2.3 全量复核（可选但推荐）

```sql
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
-- 用脚本循环跑 100 个随机 user_id / domain_id 的 Q1、Q6，跑完后：
SELECT substring(query, 1, 60) AS q, calls,
       round(mean_exec_time::numeric, 2) AS mean_ms,
       round(p95_exec_time::numeric, 2) AS p95_ms,
       shared_blks_read, shared_blks_hit
FROM pg_stat_statements
ORDER BY mean_exec_time DESC
LIMIT 20;
```

随机取 `user_id` 是为了避免只测到缓存里的那几个用户——真实负载是均匀打散的，固定 ID 反复测会把结论测偏。

---

## 3 · 合格阈值建议（11.2 万条 `task_events` 基线）

| 查询 | 阈值（中位数） | 依据 |
|---|---|---|
| Q1 用户×领域×时间段 | **< 50 ms** | 最热路径，占接口端到端预算的一部分；索引点查 + 少量行回表，正常应 1-10 ms，50 ms 是留了 5 倍冗余的上限 |
| Q2 `weekly_metrics` 唯一键 | **< 5 ms** | 唯一索引点查，命中 3-5 个 buffer，仅一次索引下降；超过 5 ms 基本等于没走索引 |
| Q3 最新坐标系 | **< 5 ms** | 同上，`LIMIT 1` 索引扫描 |
| Q4 全站斜率分位 | **< 300 ms** | 跨用户聚合，扫描 `weekly_metrics` 全量（默认 1.5 万行）；PG 聚合吞吐约每百万行 100-300 ms 量级，万级行应远低于此 |
| Q5 领域 × level 成功率 | **< 150 ms** | 需扫 `task_events` 中该领域的全部行（约 2000-3000 行）+ 分组；走索引可到 10-30 ms，150 ms 是容忍 Seq Scan 的上限 |
| Q6 最近 20 条 | **< 20 ms** | `LIMIT 20` 反向索引扫描，只取索引尾部，常数级 |
| Q7 按天吞吐 | **< 500 ms** | 唯一允许全表扫描的查询（11.2 万行 × 约 200 B/行 ≈ 25 MB），冷缓存全扫约 100-300 ms，500 ms 留冗余 |
| Q8 领域弃坑率 | **< 400 ms** | 跨领域分组聚合，量级与 Q7 相同但输出更少 |

**通用依据说明：**

- 阈值锚定的是**端到端接口预算**：产品侧单个页面请求的 P95 预算按 200 ms 计，数据库单条查询占其中 1/4-1/2，故热路径定在 50 ms 以内。
- 索引点查的物理下限是 3-4 次 buffer 访问（根→枝→叶→堆页），本地 SSD 上就是个位数毫秒，所以 Q2/Q3 定 5 ms。**这两条超过阈值一定是索引缺失，不要靠调参掩盖。**
- 全表扫描的量级估算：11.2 万行、行宽约 200 B，顺序扫描吞吐在本地 SSD 上约 500 MB/s 以上，即 25 MB 数据约 50 ms 起，加上聚合与输出开销，百毫秒级属正常。
- **换数据量时按线性放宽**：压第二轮（约 112 万条，10 倍）时，Q1/Q6 仍应 < 50 ms（索引扫描与总量弱相关，只与 B 树层数相关），Q4/Q5 放宽到 1 s，Q7/Q8 放宽到 3 s。**若 Q1/Q6 随数据量线性劣化，说明索引没生效，这是最重要的告警信号。**
- 任何一条查询出现 `rows` 估计与 `actual` 偏差 > 10 倍，先 `ANALYZE` 并重测；仍偏差再考虑 `CREATE STATISTICS`（多列相关性：`user_id` 与 `domain_id` 存在用户维度上的相关）。

---

## 4 · 结果记录表模板

### 4.1 Markdown 版（填进本机验证报告）

| 查询名 | SQL 编号 | 数据量(events) | 执行时间中位数(ms) | Planning(ms) | 扫描方式 | 是否走索引 | 估计行/实际行 | shared hit / read | 是否合格 | 备注 |
|---|---|---|---|---|---|---|---|---|---|---|
| 用户×领域×时间段 | Q1 | 112000 |  |  |  |  | / | / |  |  |
| 周指标唯一键 | Q2 | 112000 |  |  |  |  | / | / |  |  |
| 最新坐标系 | Q3 | 112000 |  |  |  |  | / | / |  |  |
| 全站斜率分位 | Q4 | 112000 |  |  |  |  | / | / |  |  |
| 领域×level 成功率 | Q5 | 112000 |  |  |  |  | / | / |  |  |
| 最近 20 条 | Q6 | 112000 |  |  |  |  | / | / |  |  |
| 按天吞吐 | Q7 | 112000 |  |  |  |  | / | / |  |  |
| 领域弃坑率 | Q8 | 112000 |  |  |  |  | / | / |  |  |

### 4.2 CSV 版（`docs/query_bench_log.csv`，便于多轮对比）

```csv
run_id,run_at,query_id,query_name,events_rows,exec_ms_median,planning_ms,scan_type,index_used,rows_est,rows_actual,shared_hit,shared_read,passed,note
b1-112k,2026-09-21T10:30:00Z,Q1,user_domain_time,112000,,,,,,/,,,
b2-1120k,2026-09-21T11:00:00Z,Q1,user_domain_time,1120000,,,,,,/,,,
```

字段说明：`passed` 填 `ok` / `ng`；`scan_type` 填 `Seq Scan` / `Index Scan` / `Index Only Scan` / `Bitmap Heap Scan`；`index_used` 填实际命中的索引名，未命中填 `-`。

---

## 5 · 执行顺序建议

1. 建库建表 → 导入 → `ANALYZE`（第 0 节）
2. 先跑 **Q1 / Q2 / Q3**（三条点查，最快暴露索引缺失）
3. 再跑 **Q6**（验证"用户+时间"索引是否独立必要）
4. 再跑 **Q4 / Q5**（聚合类，确认索引对分组统计的帮助）
5. 最后跑 **Q7 / Q8**（全量扫描类，作为分区前后的对照基线）
6. 把结果填进第 4 节表格；**不合格项按 `docs/index_tuning.md` 逐条处理**，处理后重跑同一张表并保留前后两行记录

---

<!-- === TILT-CONTRACT-MANIFEST ===
# task_id: H03
# spec_version: V1.3
# ssot_checksum: TL-SSOT-2026-09-20-A
# baseline_version: B1.0
# produced_by: 元宝(Yuanbao)
# produced_at: 2026-09-21
# batch: all
# output_files:
#   - docs/slow_query_checklist.md   (rows: 8 条待测查询)
# unverified_count: 1
# self_check:
#   frozen_ids_only: true
#   enum_from_spec: true
#   no_absolute_claims: true
#   no_new_concepts: true
#   spec_numbers_unchanged: true
# known_deviations:
#   - Q4/Q5 用到 weekly_metrics 与 task_events 的列名（week_no / objective_score / success），
#     这些列名取自 H03 造数脚本常量，待与 C12c db/schema.sql 核对 [待核验:任务书未下发字段清单]
#   - 阈值中的"每百万行 100-300ms"为工程经验量级，非 SPEC 给定值，需本机实测校准
# === END MANIFEST === -->
