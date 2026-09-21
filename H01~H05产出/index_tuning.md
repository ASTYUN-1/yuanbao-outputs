# Tilt · H03 · 索引优化与分区 / 归档建议

> 用途：当 `docs/slow_query_checklist.md` 中出现不合格项时，按本文件逐条优化。
> 本文件只给方案与 DDL，**不含任何执行结果**（云端未连库，未执行 SQL）。
> 方言：**PostgreSQL 14+**。表名固定：`users` / `task_events` / `weekly_reports` / `user_coordinates` / `weekly_metrics`。
> 字段名依 H03 造数脚本常量推导；与 C12c `db/schema.sql` 不一致处，以 schema 为准改列名，**索引形态与理由不变**。

---

## 1 · 现有索引基线

`db/schema.sql`（C12c 产出）未随本任务书下发，下表是**基于已冻结表名/字段名推定的基线**，本机执行前请先跑下面这条 SQL 导出真实清单并逐行核对：

```sql
SELECT tablename, indexname, indexdef
FROM pg_indexes
WHERE schemaname = 'public'
  AND tablename IN ('users','task_events','weekly_reports','user_coordinates','weekly_metrics')
ORDER BY tablename, indexname;
```

### 1.1 推定基线索引（待与 `db/schema.sql` 核对 `[待核验:任务书未下发 schema_notes.md]`）

| 表 | 推定索引 | 来源判断 | 备注 |
|---|---|---|---|
| `users` | `users_pkey (user_id)` | 主键必然存在 | 点查无需额外索引 |
| `task_events` | `task_events_pkey (event_id)` | 主键（uuid） | **对 Q1/Q5/Q6/Q7/Q8 全部无效**，事件查询从不按 event_id 过滤 |
| `task_events` | 可能已有 `(user_id)` 或 `(user_id, timestamp)` | 常见默认设计 | 若有则 Q6 已覆盖，Q1 仍需 `(user_id, domain_id, timestamp)` |
| `weekly_metrics` | `weekly_metrics_pkey` 或唯一约束 `(user_id, domain_id, week_no)` | 业务唯一键 | Q2 的性能全靠它；**若是普通索引而非唯一索引，要改成唯一** |
| `user_coordinates` | 可能只有 `(user_id)` | 常见默认设计 | Q3 需要 `(user_id, version DESC)` 才能免排序 |
| `weekly_reports` | 未知 | 本任务 6.2 未要求测该表 | 本轮不处理 |

### 1.2 索引健康度体检（优化前后各跑一次）

```sql
-- 找出从未被用过的索引：白占写入放大与存储
SELECT relname AS table_name, indexrelname AS index_name, idx_scan,
       pg_size_pretty(pg_relation_size(indexrelid)) AS index_size
FROM pg_stat_user_indexes
WHERE idx_scan = 0
ORDER BY pg_relation_size(indexrelid) DESC;

-- 各索引体积，判断索引是否已超出内存常驻能力
SELECT tablename, indexname, pg_size_pretty(pg_relation_size(indexname::regclass)) AS size
FROM pg_indexes WHERE schemaname='public' ORDER BY pg_relation_size(indexname::regclass) DESC;
```

---

## 2 · 逐查询的索引方案

### 2.1 总览表

| 查询 | 建议索引 | 预期收益 | 写入代价 |
|---|---|---|---|
| Q1 用户×领域×时间段 | `idx_te_user_domain_time`（**必建**） | Seq Scan → Index Scan，11 万行下从数十 ms 降到个位数 ms | 每 INSERT 多 1 个 B 树插入 |
| Q2 周指标唯一键 | `uq_wm_user_domain_week`（**必建，唯一**） | 保证业务唯一 + 点查 O(log n) | 低（该表写入量小，每用户每周每领域 1 行） |
| Q3 最新坐标系 | `uq_uc_user_version`（**必建，唯一**） | 消除 Sort，LIMIT 1 直接命中 | 极低（每用户 1-2 行） |
| Q4 全站斜率分位 | `idx_wm_domain_week`（建议建） | 领域过滤从全表扫变索引扫 | 低 |
| Q5 领域×level 成功率 | `idx_te_domain_level_success`（建议建，**部分索引**） | 仅索引终态事件，体积比全表索引小一个量级 | 中（只对 `success IS NOT NULL` 的行维护） |
| Q6 最近 20 条 | `idx_te_user_time`（建议建） | 反向索引扫描 + LIMIT，常数级 | 每 INSERT 多 1 个 B 树插入，**与 Q1 索引不可互相替代** |
| Q7 按天吞吐 | 不加索引 | — | 靠分区裁剪（第 3 节）解决，加索引无意义 |
| Q8 领域弃坑率 | 不加 B 树索引 | — | 选择性太低（50 个领域），靠**物化汇总表**（第 4 节）解决 |

---

### 2.2 Q1 · 用户 × 领域 × 时间段（最高优先级）

```sql
CREATE INDEX CONCURRENTLY idx_te_user_domain_time
    ON task_events (user_id, domain_id, timestamp DESC)
    INCLUDE (task_level, event_type, success);
```

**为什么这么建：**

- **列顺序**：`user_id`（等值）→ `domain_id`（等值）→ `timestamp`（范围）。B 树复合索引遵循"等值列在前、范围列在后"，范围列后面的列无法再用于索引过滤，所以 `timestamp` 必须放最后。
- **`DESC`**：本查询是取最近时间段的事件，`timestamp DESC` 让"最新优先"类查询（Q1 加 `ORDER BY timestamp DESC`）免排序；PG 的 B 树可双向扫描，`ASC` 查询同样能走这个索引，不影响 Q1 原形态。
- **`INCLUDE`**：把 `task_level / event_type / success` 放进叶子页，使 Q1 变 **Index Only Scan**，省掉回表。这三个字段是 Q1 投影列里除主键外的全部列。
- 代价：约 11 万行 × (3 列键 + 3 列 INCLUDE) ≈ **8-12 MB**；每插入一行多一次 B 树下降与叶子页写入，实测写入延迟通常 **+10%~20%**。

> ⚠️ 若 `task_events` 已有 `(user_id, timestamp)` 索引，Q1 仍需本索引：缺少 `domain_id` 前导列时，`domain_id` 过滤只能在回表后执行，`Rows Removed by Filter` 会很高。两者是否并存见 2.6 的取舍。

**验证：**

```sql
EXPLAIN (ANALYZE, BUFFERS) <Q1 SQL>;   -- 期望：Index Only Scan using idx_te_user_domain_time，无 Sort 节点
```

---

### 2.3 Q2 · `weekly_metrics` 唯一键

```sql
-- 若尚不存在唯一约束，优先用约束（同时表达业务语义 + 建索引）
ALTER TABLE weekly_metrics
    ADD CONSTRAINT uq_wm_user_domain_week UNIQUE (user_id, domain_id, week_no);

-- 若已存在唯一约束，不要再建；若只有普通索引，用 CONCURRENTLY 替换为唯一索引
CREATE UNIQUE INDEX CONCURRENTLY uq_wm_user_domain_week
    ON weekly_metrics (user_id, domain_id, week_no);
```

**为什么：** 该表每用户每领域每周只有一行，唯一约束既是正确性保证（防止重复导入造出双份周指标），又是点查索引。代价可忽略（写入量约为 `task_events` 的 1/7，且只在周末批量写入）。

> 注意：`ADD CONSTRAINT` 会锁表并做全表校验；线上已有数据用 `CREATE UNIQUE INDEX CONCURRENTLY` 更稳，但它失败后索引会留在 `INVALID` 状态，需 `DROP` 后重来。

---

### 2.4 Q3 · 最新坐标系

```sql
CREATE UNIQUE INDEX CONCURRENTLY uq_uc_user_version
    ON user_coordinates (user_id, version DESC);
```

**为什么：** `WHERE user_id = ? ORDER BY version DESC LIMIT 1` 需要"等值 + 有序"的复合索引才能只取一行就停；只有 `(user_id)` 单列索引时，PG 必须先取出该用户所有版本再 `Sort`，版本数增长后线性劣化。`version DESC` 与索引默认升序配合 `LIMIT 1` 等价可用，写 `DESC` 是为了让执行计划更直观。若 schema 无 `version` 列（只有 `created_at`），改用：

```sql
CREATE INDEX CONCURRENTLY idx_uc_user_created
    ON user_coordinates (user_id, created_at DESC);
```

代价：每用户 1-2 行，全表约 1000-2000 行，索引 < 100 KB，**可忽略**。

---

### 2.5 Q4 / Q5 · 聚合类

**Q4（全站斜率分位）：**

```sql
CREATE INDEX CONCURRENTLY idx_wm_domain_week
    ON weekly_metrics (domain_id, week_no)
    INCLUDE (user_id, objective_score);
```

**为什么：** Q4 的 `WHERE domain_id = 'go'` 在全站用户上选择性约 1/50（2%），走索引明显优于全表扫；`INCLUDE (user_id, objective_score)` 让聚合完全在索引内完成（Index Only Scan），避免回表取 `objective_score`。代价：该表仅万级行，索引 < 2 MB，写入约每周一次批量，**代价可忽略**。

> 若实测 Q4 的 `Seq Scan` 已满足 300 ms 阈值，可以不建——避免为一个低频查询增加维护负担。这是"先测再建"的判断点。

**Q5（领域 × level 成功率）：**

```sql
-- 部分索引：只索引有终态结果的事件（约 30% 的行），体积与维护成本都小一个量级
CREATE INDEX CONCURRENTLY idx_te_domain_level_success
    ON task_events (domain_id, task_level)
    INCLUDE (success, objective_score)
    WHERE success IS NOT NULL;
```

**为什么：**

- 列顺序：`domain_id`（等值、选择性 1/50）→ `task_level`（分组键，放进索引可让 `GROUP BY` 走有序扫描免排序）。
- **`WHERE success IS NOT NULL` 是关键**：Q5 只统计终态事件（`task_complete` / `task_abandon`），用部分索引把索引体积从 11 万行压到约 3.5 万行（脚本默认数据中 `task_complete` 约 28% + `task_abandon` 约 3%），**写入放大相应降到 1/3**，且不影响 Q5 的正确性（优化器能识别 `WHERE success IS NOT NULL` 与部分索引谓词匹配）。
- 代价：约为全表索引的 1/3，即 **3-5 MB** + 终态事件写入时的一次 B 树维护。
- ⚠️ 部分索引的前提是**查询里必须写上能推出该谓词的条件**（Q5 已写 `AND success IS NOT NULL`）。若业务 SQL 写成 `WHERE event_type='task_complete'` 而索引谓词是 `success IS NOT NULL`，优化器**不会**用——两者必须对齐。

---

### 2.6 Q6 · 最近 20 条（与 Q1 索引的取舍）

```sql
CREATE INDEX CONCURRENTLY idx_te_user_time
    ON task_events (user_id, timestamp DESC);
```

**为什么不能省：** Q1 的索引前导列是 `(user_id, domain_id, ...)`，Q6 没有 `domain_id` 过滤条件，无法跳过该列做范围扫描——**复合索引的前导列缺失时，后续列无法被有效利用**。所以 Q6 必须独立建索引。

**取舍建议（写入放大敏感时）：**

- 若写入压测（导入 11 万行）耗时可接受，**两个都建**（Q1 是最高频，Q6 是每次启动都走）。
- 若 Q6 实测能接受 20-50 ms，可以只保留 Q1 索引，Q6 退化为对单用户事件（约 112 行）的小规模扫描+排序，量级上并不灾难。
- 反过来若只建 `(user_id, timestamp)`，则 Q1 的 `domain_id` 过滤落到 `Rows Removed by Filter`，**不推荐**。

---

### 2.7 Q7 / Q8 · 不加索引，改用分区与汇总

| 查询 | 不加索引的原因 | 替代方案 |
|---|---|---|
| Q7 按天吞吐 | 查询覆盖全表，`domain_id`/`user_id` 索引无法裁剪；`date_trunc` 表达式索引只在按天过滤时有用，而这里要的是全量分组 | 第 3 节**时间分区** + 查询带时间条件 → 分区裁剪 |
| Q8 领域弃坑率 | `domain_id` 只有 50 个取值，每个领域约 2000+ 行，**选择性过低**，B 树索引回表代价高于顺序扫描，优化器会主动放弃索引 | 第 4 节**物化汇总表**（按领域预聚合），把 11 万行聚合降到 50 行读取 |

> 若确实要加速 Q8 且不想引入汇总表，可用部分索引 `WHERE event_type IN ('task_complete','task_abandon')` 把扫描量压到约 31%，但这属于"用索引当瘦身表"，不如汇总表干净。

---

### 2.8 写入放大的量化与测量

每个新增 B 树索引的代价 = **索引体积 + 每次 INSERT/UPDATE 多一次 B 树下降**。测量方法：

```sql
-- 导入前记录
SELECT pg_size_pretty(pg_total_relation_size('task_events')) AS before_total;
-- 用 \timing 记录导入耗时
\timing on
\COPY task_events (...) FROM 'out/events_copy.tsv' WITH (FORMAT text, DELIMITER E'\t', NULL '\N');
-- 导入后记录：索引体积增量 = 新增索引的净成本
SELECT indexrelname, pg_size_pretty(pg_relation_size(indexrelid))
FROM pg_stat_user_indexes WHERE relname='task_events' ORDER BY pg_relation_size(indexrelid) DESC;
```

经验值（本数据集量级）：

| 索引 | 预估体积（11.2 万行） | 预估写入延迟增量 |
|---|---|---|
| `idx_te_user_domain_time`（含 INCLUDE 3 列） | 8-12 MB | +10%~20% |
| `idx_te_user_time` | 5-8 MB | +8%~15% |
| `idx_te_domain_level_success`（部分索引） | 3-5 MB | +3%~6% |
| `uq_wm_user_domain_week` | < 2 MB | 可忽略 |
| `uq_uc_user_version` | < 0.1 MB | 可忽略 |

**取舍原则：** `task_events` 是写多读少的表（每天每用户 4 条写入，但每次打开 App 都要读），本产品读写比约 1:5 以上，**读优化优先**，上表 5 个索引全部建上后写入总增量仍在 30% 以内，可接受。若后续压测发现导入成为瓶颈，优先砍 `idx_te_user_time`（Q6 可退化），保留 Q1。

---

## 3 · 分区建议（`task_events`）

### 3.1 什么时候该分区：具体阈值

满足**任意一条**即应启动分区改造：

| 阈值 | 数值 | 依据 |
|---|---|---|
| **行数** | 单表 > **5000 万行** | 约 11 万行/千用户/月 的 450 倍；此时索引 B 树层数增加、VACUUM 单次耗时显著上升 |
| **表体积** | 单表（含索引） > **20 GB** | 超过此规模，全表 VACUUM / 重建索引的维护窗口变得难以安排 |
| **索引体积** | 主索引 > **shared_buffers 的 60%** | 索引无法常驻内存 → 点查产生随机 I/O，Q1/Q6 从个位数 ms 劣化到数十 ms。**这是最先到达的一条**，默认 `shared_buffers=128MB` 时主索引约 80 MB（约 100 万行）就会触线 |
| **归档需求** | 需要按时间删除/转移历史数据 | `DELETE` 千万行会产生大量死元组与 WAL；分区下 `DETACH` 是元数据操作，秒级完成 |

**MVP 阶段（11 万 - 100 万行）不需要分区**：单表 + 第 2 节索引即可满足全部阈值。**过早分区的代价是真实的**：planner 对每个分区都要做一次计划，分区数上百后 `Planning Time` 会明显上升（Q2/Q3 这类简单点查会被 planning 拖累）。

### 3.2 按什么分区：**按时间（RANGE，月分区）**

**推荐时间分区，不推荐按领域分区**，理由：

1. **业务访问模式是时间局部的**：4 周实验窗口内，Q1 必带时间范围、Q7 按天聚合，时间分区可直接裁剪掉其余月份。
2. **归档是刚需且按时间定义**：第 4 节的归档策略天然按月/季度切割。
3. **按 `domain_id` 做 LIST 分区的缺点**：50 个分区导致 planner 开销上升；领域热度不均（热门领域分区远大于冷门），无法均衡；新增领域要 `ATTACH` 新分区，是 schema 变更；且 Q1 这类"用户×领域×时间"查询仍需扫描该领域全部分区（领域分区不带时间信息，无法裁剪时间）。
4. **折中**：若 Q8（领域弃坑率）成为瓶颈且必须走明细，可做**二级分区**（RANGE 时间 × LIST 领域），但 50 × N 个子分区会带来 planning 灾难，**MVP 不做**，改走第 4 节物化汇总。

**分区 DDL（声明式，PG 14+）：**

```sql
-- 1) 建分区父表（分区键必须包含在主键/唯一约束内）
CREATE TABLE task_events (
    event_id          uuid        NOT NULL,
    user_id           text        NOT NULL,
    session_id        uuid,
    domain_id         text        NOT NULL,
    task_id           text        NOT NULL,
    task_type         text,
    task_level        smallint,
    event_type        text        NOT NULL,
    evaluator_type    text,
    timestamp         timestamptz NOT NULL,
    duration_seconds  integer,
    completion_rate   numeric(5,4),
    objective_score   numeric(5,2),
    success           boolean,
    PRIMARY KEY (event_id, timestamp)      -- 分区键 timestamp 必须入主键
) PARTITION BY RANGE (timestamp);

-- 2) 按月建子分区（造数数据跨度 2026-08-24 ~ 2026-09-20，覆盖两个月）
CREATE TABLE task_events_2026_08 PARTITION OF task_events
    FOR VALUES FROM ('2026-08-01') TO ('2026-09-01');
CREATE TABLE task_events_2026_09 PARTITION OF task_events
    FOR VALUES FROM ('2026-09-01') TO ('2026-10-01');

-- 3) 默认分区：兜住超出范围的 timestamp，避免插入报错（但要监控，见下）
CREATE TABLE task_events_default PARTITION OF task_events DEFAULT;

-- 4) 子分区上建索引：在父表上建索引会自动传播到所有子分区（推荐，省事且一致）
CREATE INDEX CONCURRENTLY idx_te_user_domain_time
    ON task_events (user_id, domain_id, timestamp DESC)
    INCLUDE (task_level, event_type, success);
-- 已存在的分区会自动带上；新增分区 ATTACH 后需确认索引已传播
```

**分区裁剪验证：** Q7 加上时间条件后，应看到 `Append` 下只挂命中的子分区：

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*) FROM task_events
WHERE timestamp >= '2026-09-01' AND timestamp < '2026-10-01';
-- 期望：Append 下只有 task_events_2026_09；若出现 task_events_default，说明有越界数据
```

**运维提醒：**

- 默认分区一旦有行，后续 `ATTACH` 新分区会因需要校验默认分区而**锁表**；应定期 `SELECT count(*) FROM task_events_default` 并清空（默认分区非空是分区设计的告警信号）。
- 分区键上的 `UPDATE`（改 `timestamp`）会触发跨分区移动，本产品事件为**追加写、不更新**，无此风险。
- 分区创建建议脚本化或用 `pg_partman` 扩展自动滚动建分区 `[待核验:版本与用法以官方文档为准]`。

---

## 4 · 归档策略

### 4.1 阈值：**热数据保留 180 天**

| 数据 | 保留策略 | 依据 |
|---|---|---|
| `task_events` 明细 | 主表保留 **180 天**（约 6 个月），更早的 `DETACH` 归档 | 4 周实验期 + 12 周复盘/对比窗口 + 缓冲；超过 180 天的明细不再进入任何热路径（Q1 最远查到 4 周前，Q8 走汇总表） |
| `weekly_metrics` | **永久保留** | 行数仅 `用户数 × 领域数 × 周数`，是斜率与 5 维指标的唯一载体，体积小、查询热 |
| `user_coordinates` | **永久保留**（含历史版本） | 每用户 1-2 行，需要版本追溯 |
| `weekly_reports` | 永久保留（报告为成品，体积小） | — |

### 4.2 归档操作（不影响在线查询的关键：DETACH 而非 DELETE）

```sql
-- 步骤 1：把到期分区从父表摘下（元数据操作，秒级，不扫数据、不写大量 WAL）
ALTER TABLE task_events DETACH PARTITION task_events_2026_02;

-- 步骤 2：摘下后它变成独立普通表，此时主表查询已不再包含它 —— 在线查询在这一步即已"瘦身"
--        注意：DETACH 前该分区上的数据在查询结果中仍可见，DETACH 瞬间消失，
--        因此务必确认业务不再查询该区间（本产品热路径最远 4 周，安全）

-- 步骤 3：导出归档（任选其一）
--   3a 保留在本库（改名，仍可查，但不再参与主表计划）
ALTER TABLE task_events_2026_02 RENAME TO archive_task_events_2026_02;
--   3b 导出到文件后删除（推荐，真正释放空间）
--       psql -c "\COPY archive_task_events_2026_02 TO 'archive_2026_02.tsv' WITH (FORMAT text, DELIMITER E'\t', NULL '\N')"
--       上传对象存储后：DROP TABLE archive_task_events_2026_02;

-- 步骤 4：确认主表体积回落
SELECT pg_size_pretty(pg_total_relation_size('task_events')) AS after_total;
```

**为什么这样不影响查询：**

- `DETACH` 是元数据操作，只改系统目录，不重写数据，执行时间与分区大小无关；相比 `DELETE FROM task_events WHERE timestamp < ...`（千万行级删除 + 大量死元组 + 长时间锁），对在线查询几乎零影响。
- 主表的 planner 只考虑当前 ATTACH 的子分区，分区数减少后 `Planning Time` 也随之下降。
- 归档前后 Q1/Q6 的执行计划不变（索引形态一致），**只有 Q7 这类全量扫描会变快**——这正是第 5 节要求重跑 Q7 做对照的原因。

### 4.3 归档后的查询连续性

- 若业务需要"查我做过的所有事"（跨归档边界），**不要**去查归档表，改从 `weekly_metrics` 出聚合结果；明细级历史查询另行设计，不进入热路径。
- 归档区间被误查时（例如用户请求 8 个月前的轨迹），返回空结果是可接受行为；若产品不允许，需在第 4.1 节的 180 天上调，**不要用跨库 UNION 兜底**。

---

## 5 · 优化后必做的回归动作

1. 每条 DDL 后**重跑对应查询**，并把前后两行都记进 `docs/slow_query_checklist.md` 第 4 节表格（保留 `run_id` 便于对比）。
2. 建完全部索引后跑一次完整导入计时，确认写入放大在第 2.8 节预估范围内。
3. 跑第 1.2 节的"从未被使用的索引"SQL，确认没有 `idx_scan = 0` 的索引——**建了不用等于纯亏**。
4. 分区改造后重跑 **Q7 / Q8**，前者应变快（裁剪），后者可能微变慢（planning 开销上升），这是预期的权衡，若 Q8 劣化超过 50% 则改为第 4 节汇总表方案。
5. 每次大批量导入后执行 `ANALYZE task_events;`，否则第 2 节所有索引都可能被优化器放弃。

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
#   - docs/index_tuning.md   (rows: 8 条查询对应的索引方案)
# unverified_count: 2
# self_check:
#   frozen_ids_only: true
#   enum_from_spec: true
#   no_absolute_claims: true
#   no_new_concepts: true
#   spec_numbers_unchanged: true
# known_deviations:
#   - 第 1.1 节"现有索引清单"为推定值：C12c 的 schema_notes.md 未随本任务书下发
#     [待核验:需本机用第 1 节开头那条 pg_indexes 查询导出真实清单核对]
#   - 分区阈值（5000 万行 / 20GB / shared_buffers 60%）与归档 180 天为工程经验建议值，
#     非 SPEC 给定数值 [待核验:需按本机实际规模与 SLA 校准]
#   - pg_partman 为外部扩展，仅作提示 [待核验:版本与用法以官方文档为准]
# === END MANIFEST === -->
