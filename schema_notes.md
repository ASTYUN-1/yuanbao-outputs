# Tilt · `db/schema_notes.md`

> 配套文件：`db/schema.sql`（PostgreSQL 14+，5 张表 + 11 个索引/唯一键）
> 本文说明：索引与查询的对应关系、分区策略、JSONB 取舍、删除与保留设计、对 SPEC 的修正及理由。

---

## 1. 索引清单（每条索引 ↔ 一个具体查询）

### 1.1 `users`

| 索引 | 对应查询 | 为什么 |
|---|---|---|
| `idx_users_created_at (created_at)` | 按注册时间做 cohort 统计；30 天清除任务按批次扫描账号 | `users` 是低写入表（注册/更新稀疏），索引成本可忽略；`id` 已有主键索引，用户维度点查不需要额外索引 |

### 1.2 `task_events`（最热写入路径）

| 索引 | 对应查询 | 为什么 |
|---|---|---|
| `idx_user_domain_time (user_id, domain, timestamp)` | **最热路径**：某用户 × 某领域 × 某时间段的全部事件（周指标计算、斜率重算、会话还原） | SPEC 原文索引，定义一字未改。列序为「两列等值 + 一列范围」，符合最左前缀，`timestamp` 放最后可直接做范围扫描并顺序输出 |
| `idx_task_events_user_time (user_id, timestamp DESC)` | 某用户**跨领域**时间线：日报、活跃度、用户级事件回放 | 上面的索引以 `domain` 为第二列，查询不带 `domain` 时用不上，必须单独建。`DESC` 让"最近 N 条"免排序 |
| `idx_task_events_domain_time (domain, timestamp)` | 某领域跨用户统计：领域难度校准、参与热度、评估器整体表现 | 跨用户聚合只按领域与时间过滤，需要以 `domain` 为前缀 |
| `idx_task_events_task_time (domain, task_id, timestamp)` | 单任务级聚合：某任务的尝试次数、成功率、重试分布（任务质量迭代） | `task_id` 已含 domain 前缀（`{domain_id}_L{level}_{序号}`），但按 `(domain, task_id)` 建索引可让"某领域全部任务"也走索引扫描 |

**写入成本提示（重要取舍）：** 每条 `task_events` INSERT 需维护 4 个 B-tree。若压测显示写入成为瓶颈，保留优先级为
`idx_user_domain_time` > `idx_task_events_user_time` > `idx_task_events_domain_time` > `idx_task_events_task_time`；
后两条对应的都是分析型查询，可降级为离线批处理（T+1 抽数到分析库）后再删除。
另可选：`event_type` 漏斗分析（start→complete 转化率）需要 `(event_type, timestamp)`，当前**未建**，因为该查询低频且跨用户全表扫描，建议放在分析库，不要拖累在线写入。

### 1.3 `weekly_reports`

| 索引 | 对应查询 | 为什么 |
|---|---|---|
| `weekly_reports_user_week_unique UNIQUE (user_id, week_number)` | 某用户第 N 周的报告（周报页渲染） | 唯一键同时承担查询索引，无需另建 `(user_id)` 索引 |
| `idx_weekly_reports_generated_at (generated_at)` | 运维/统计：按生成时间扫描、清理过期报告 | 报告表每用户每周最多 1 行，量级小，成本可忽略 |

### 1.4 `user_coordinates`

| 索引 | 对应查询 | 为什么 |
|---|---|---|
| `user_coordinates_user_version_unique UNIQUE (user_id, version)` | 按版本取坐标系：`WHERE user_id=$1 AND version=$2` | 6.2 要求补齐；同时防止同一版本被重复写入产生脏数据 |
| `idx_user_coordinates_user_created (user_id, created_at DESC)` | **取最新坐标系**：`WHERE user_id=$1 ORDER BY created_at DESC LIMIT 1` | 取"最新"必须用 `created_at`，**不能用 `version` 排序**：`version` 是 `VARCHAR(10)`，字典序下 `'v10' < 'v2'`，排序会取错 |

### 1.5 `weekly_metrics`

| 索引 | 对应查询 | 为什么 |
|---|---|---|
| `weekly_metrics_user_domain_week_unique UNIQUE (user_id, domain_id, week_number)` | 某用户 × 某领域 × 某周的指标：写入即 upsert、读取即唯一键点查 | SPEC 原文唯一键，已补齐 `user_id` 外键；在线路径的绝对主查询 |
| `idx_weekly_metrics_user_week (user_id, week_number)` | 某用户某周**跨 3-5 个领域**的对比（周报渲染、斜率排序） | 唯一键的列序是 `(user_id, domain_id, week_number)`，跳过 `domain_id` 时无法用于此查询，必须补前缀索引 |
| `idx_weekly_metrics_domain_week (domain_id, week_number) INCLUDE (objective_level)` | 全站某领域某周的客观水平分布 → 分位计算 | `INCLUDE` 让 `percentile_cont` 聚合走 index-only scan，避免回表扫全表 |

---

## 2. 四类必须覆盖的查询模式（示例 SQL + 命中索引）

**Q1 · 某用户在某领域某时间段的所有事件（最热路径）**

```sql
SELECT event_type, task_id, task_level, timestamp, duration_seconds,
       completion_rate, retry_count, objective_score, success
FROM   task_events
WHERE  user_id = $1
  AND  domain  = 'go'
  AND  timestamp >= $2
  AND  timestamp <  $3
ORDER  BY timestamp;
-- 命中 idx_user_domain_time（等值+等值+范围，索引内已有序，无 Sort 节点）
```

**Q2 · 某用户某周的指标（唯一键查询 / upsert）**

```sql
-- 读取
SELECT * FROM weekly_metrics
WHERE user_id = $1 AND domain_id = 'go' AND week_number = 2;
-- 命中 weekly_metrics_user_domain_week_unique

-- 写入（重算幂等）
INSERT INTO weekly_metrics (user_id, domain_id, week_number, objective_level, bounce_back,
                            repetition, detail_sensitivity, proactive_optimization,
                            pain_tolerance, task_count, success_rate)
VALUES ($1,'go',2,$2,$3,$4,$5,$6,$7,$8,$9)
ON CONFLICT (user_id, domain_id, week_number) DO UPDATE
SET objective_level = EXCLUDED.objective_level, created_at = NOW();
```

**Q3 · 某用户的最新坐标系**

```sql
SELECT * FROM user_coordinates
WHERE user_id = $1
ORDER BY created_at DESC
LIMIT 1;
-- 命中 idx_user_coordinates_user_created，LIMIT 1 直接取索引首行

-- 按版本取（历史版本回溯）
SELECT * FROM user_coordinates WHERE user_id = $1 AND version = $2;
-- 命中 user_coordinates_user_version_unique
```

**Q4 · 全站某领域的斜率分布（跨用户分位计算）**

```sql
-- 水平分布：某领域第 4 周的中位数/分位
SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY objective_level) AS p50
FROM   weekly_metrics
WHERE  domain_id = 'go' AND week_number = 4;
-- 命中 idx_weekly_metrics_domain_week（index-only scan）

-- 斜率分布：第 4 周相对第 1 周的进步斜率（跨用户）
SELECT user_id,
       MAX(objective_level) FILTER (WHERE week_number = 4)
     - MAX(objective_level) FILTER (WHERE week_number = 1) AS slope
FROM   weekly_metrics
WHERE  domain_id = 'go' AND week_number IN (1, 4)
GROUP  BY user_id
HAVING COUNT(*) = 2;
-- 命中同一索引；HAVING COUNT(*)=2 排除只做了 1 周、无法算斜率的用户
```

---

## 3. 分区建议：`task_events`

**结论：MVP 阶段不分区**，保持单表 + 上文 4 个索引；达到阈值后按 `timestamp` 做 **RANGE 月分区**。

**数据量阈值（工程量级估算，非 SPEC 给定值，上线前用真实埋点密度复核）**

| 触发条件 | 阈值 |
|---|---|
| 单表行数 | > 5000 万行 |
| 单表体积（含索引） | > 30 GB |
| 持续写入峰值 | > 500 行/秒 |

**量级换算：** 单用户每天约产生 20-40 条事件（`session_start/end` + 若干 `task_*`）。
1 万 DAU ≈ 900 万行/月 → 约 5-6 个月触及阈值；10 万 DAU ≈ 9000 万行/月 → 上线即应分区。

**为什么按时间 RANGE、不按 `user_id` HASH**

1. 查询几乎都带时间范围（周指标按周重算、斜率按 4 周窗口算），月分区让"第 N 周"只扫 1 个分区；HASH 对时间范围查询完全无效。
2. 过期数据可整体 `DETACH PARTITION` 后归档/删除，与第 5 节的保留策略直接配合；HASH 只能逐行删。
3. 索引体积随分区变小，单个分区的索引更可能常驻内存。

**改造代价与注意事项**

- 分区后**主键必须包含分区键**：`PRIMARY KEY (id, timestamp)`（`BIGSERIAL` 序列仍保证全局唯一，但 PG 要求 PK 含分区键）。
- `UNIQUE` 约束必须含分区键；`task_events` 无唯一键，不受影响。
- 分区表作为子表引用 `users(id)` 的外键、以及 `ON DELETE CASCADE`，在 PostgreSQL 12+ 均支持。
- 必须预建分区（建议 `pg_partman` 或每月定时任务），**缺分区会导致 INSERT 直接报错**，这是分区方案最常见的线上事故。

**参考 DDL（达到阈值后再执行，本脚本未包含）**

```sql
-- 1) 新建分区父表（结构沿用现有表）
CREATE TABLE task_events_p (LIKE task_events INCLUDING ALL) PARTITION BY RANGE (timestamp);
-- 注意：LIKE INCLUDING ALL 会带入 PRIMARY KEY (id)，需在分区父表上改为 (id, timestamp)

-- 2) 按月建分区
CREATE TABLE task_events_2026_10 PARTITION OF task_events_p
    FOR VALUES FROM ('2026-10-01') TO ('2026-11-01');

-- 3) 数据迁移 + 改名（维护窗口内完成）
--    INSERT INTO task_events_p SELECT * FROM task_events;
--    ALTER TABLE task_events RENAME TO task_events_old;
--    ALTER TABLE task_events_p RENAME TO task_events;
```

---

## 4. JSONB 字段说明

### 4.1 用了 JSONB 的列

| 表 | 列 | 内容 |
|---|---|---|
| `users` | `coordinate` | 6 维自我坐标系当前快照 |
| `users` | `cognitive_radar` | 雷达图渲染数据 |
| `users` | `metadata` | 未进入固定列的扩展属性 |
| `task_events` | `raw_data` | 评估器原始输出（10 类 `evaluator_type`，结构各异） |
| `weekly_reports` | `domain_metrics` / `objective_levels` / `objective_slopes` / `radar_chart` | 3-5 个领域的指标、水平、斜率与雷达数据 |
| `user_coordinates` | `raw_answers` | 18 题原始作答 |

### 4.2 为什么不拆成列

1. **领域集合是动态的**：用户并行投入的 3-5 个领域因人而异，拆列会得到一张稀疏宽表；改为行存储则需要新增"领域指标明细表"，但 6.4.3 明确禁止引入 SPEC 之外的业务表。
2. **评估器输出会演进**：`katago`（胜率/目差）、`stockfish`（eval）、`llm_*`（评分卡/评语）结构各不相同，且版本迭代频繁；拆列意味着评估器每次升级都要 DDL。
3. **访问模式是整块读写**：这些字段一次写入、整体读出用于渲染/重算，SQL 层不需要按 JSON 内部 key 做过滤、排序或聚合 —— 没有关系化的收益。

热字段（`domain`、`task_level`、`event_type`、`success`、`timestamp`）已提升为独立列，正是为了让高频过滤走普通列 + B-tree，避免 JSONB 解析。

### 4.3 查询时要注意

- **无 schema 保证**：JSONB 不校验结构，应用层必须做版本兼容与缺省处理。建议在 JSON **值内部**带 `schema_version` 字段（写在值里，不新增列），便于灰度期兼容旧格式。
- **勿在 WHERE 里高频过滤 JSONB**：如需按键查询，用 `CREATE INDEX ... USING GIN (raw_data jsonb_path_ops)`；默认**不建**（写入放大明显），仅在排障时临时创建。
- **更新是整值重写**：JSONB 的局部更新会重写整个值并放大 WAL。`raw_data` / `raw_answers` 应按"一次写入、不再修改"使用，重算结果写到 `weekly_metrics` 等关系列。
- **数值精度**：JSONB 的 number 按 `numeric` 存储，序列化/反序列化时注意浮点与精度丢失，尤其是斜率这类小数。
- **键顺序不保留**：JSONB 会规范化（去重、重排键），不要依赖键顺序做差异比较。

---

## 5. 数据保留与删除（SPEC 8.3：用户删除账号后 30 天内清除）

### 5.1 设计：两阶段硬删除 + 外键级联

脚本中四张子表的外键均配置为 `ON DELETE CASCADE`，删除链路为：
`users` → `task_events` / `weekly_reports` / `user_coordinates` / `weekly_metrics`。

| 阶段 | 动作 |
|---|---|
| T0（用户申请） | 应用层置 `users.user_state` 为已注销状态（**沿用 SPEC 已有列，不新增列/表**），吊销登录凭证，停止一切采集、推荐与周报生成；此阶段数据仍在，支持撤回 |
| T0+30 天 | 执行 `DELETE FROM users WHERE id = $1;`，四张子表级联清除，含 `raw_data` / `raw_answers` 行为明细 |

### 5.2 为什么不用软删除

SPEC 8.3 要求"清除"而非"隐藏"。软删除会让 PII 与行为明细长期留存，且每个查询都要补 `WHERE deleted_at IS NULL`，漏一处即造成已注销用户的数据泄露 —— 与本产品的行为数据敏感度不匹配。

### 5.3 注意事项

- **分区后的删除**：`task_events` 分区后级联仍是逐行删除，大规模清理建议按 `user_id` 批量删除，或直接 `DETACH` + 删除已过保留期的整月分区。
- **删除凭证**：合规回执需要的"删除时间、删除范围"应在独立的审计/日志系统留存（只存 `user_id` 哈希与时间戳，**不得含行为数据**），不进业务库 —— 6.4.3 禁止新增业务表。
- **备份残留**：RPO 内的备份与快照仍包含该用户数据，删除操作需要在恢复流程中重放，否则恢复后会"复活"已删数据。
- **分析库/数仓**：若后续把 `task_events` 抽到分析库，删除请求必须同步下发，且分析库不得保留可反推个人的明细。

---

## 6. 对 SPEC 的修正与决策说明

| # | 位置 | 处理 | 理由 |
|---|---|---|---|
| 1 | `weekly_metrics.user_id` | 补齐外键 `REFERENCES users(id) ON DELETE CASCADE` + `NOT NULL` | 6.2 明确要求；指标脱离用户无意义，且删除链路必须覆盖此表 |
| 2 | 四张子表的 `user_id` | 均补 `NOT NULL` | 埋点、报告、坐标系、指标都必须归属到具体用户；`weekly_reports` / `weekly_metrics` 原文未声明，按 6.2 第 3 条补齐 |
| 3 | `user_coordinates` | 补 `UNIQUE (user_id, version)`，且 `version` 改 `NOT NULL` | 唯一键含 NULL 会失效（NULL 互不相等），`version` 可空则唯一约束形同虚设 |
| 4 | `weekly_reports` | 补 `UNIQUE (user_id, week_number)` + `week_number BETWEEN 1 AND 4` | 按 3.9「单周期 4 周」假设；已在 manifest `known_deviations` 声明。**若后续支持多周期，唯一键需扩为 `(user_id, cycle_no, week_number)`** |
| 5 | `feedback_speed` / `risk_attitude` / `abstraction_level` | **保持 SPEC 的标量类型，未改为数组** | 字段名与类型是算法层契约（6.4.1），改类型会让已对接的写入/读取代码全部返工。标量语义 = "该维度轴上的位置"（0 = short / conservative / theory，1 = long / aggressive / operation），MVP 够用。**代价**：丢失逐选项分布，三档的 `risk_attitude` 无法区分"两端各半"与"全部居中"。若算法层确认需要分布，迁移方案为 `ALTER ... TYPE DECIMAL(4,3)[]`，需同步算法层并回填历史数据 |
| 6 | `task_events.domain` vs `weekly_metrics.domain_id` | 列名**均未改**，保持 SPEC 原文 | 两表对同一语义用了不同列名，是 SPEC 的历史不一致；按 6.4.1 严禁重命名。JOIN 时写 `task_events.domain = weekly_metrics.domain_id` |
| 7 | `task_events.task_variant` | 加 `CHECK IN ('standard','disaccharide')` | 承载 3.7 的 `task_type` 枚举；列名沿用 SPEC 原文，未改名为 `task_type` |
| 8 | `task_level` | `CHECK BETWEEN 1 AND 10` | 3.7 定义 level 范围 1-10（MVP 只用 L1-L5）；未把上限锁到 5，避免 V1.0 开 L6-L10 时改 DDL |
| 9 | `users.id` | 未加 `DEFAULT` | SPEC 未定义生成方式；PG13+ 可用内置 `gen_random_uuid()`，由应用层生成还是数据库生成需工程确认后补 |
| 10 | `users.user_state` / `age_range` | **未加枚举 CHECK** | 冻结清单（第 3 节）未给这两个字段的枚举值，不臆造（硬约束 1/2） |
| 11 | `objective_score`（5,2）、5 维指标与 `objective_level`（3,1） | **未加区间 CHECK** | SPEC 未定义刻度（0-10 还是 0-100），擅自加区间会锁死算法口径；待算法层确认刻度后补，并同步校验 `DECIMAL(3,1)` 的 99.9 上限是否够用 |
| 12 | `task_events` 的 50 值枚举 CHECK | 已加，但可降级 | 每次 INSERT 都要对 50 个元素求值。若压测显示写入瓶颈，优先改为应用层校验（领域 ID 由服务端生成，本就可信），或在产品确认后引入领域字典表 + 外键（6.4.3 当前禁止新增业务表） |

---

## 备注

- 本文档第 5 节在任务书中缺失（编号由第 4 节直接跳到第 6 节），未影响本任务执行，仅作记录。
- 第 3 节分区阈值为工程量级估算，非 SPEC 给定数据；上线前请用真实埋点密度复核。
- 我的建议（不进正式产出）：① `feedback_speed` / `risk_attitude` / `abstraction_level` 长期应统一为数组以保留逐选项分布；② 若支持多周期试验，`weekly_reports` / `weekly_metrics` 需引入周期标识并扩展唯一键。
- 待确认：5 维客观指标与 `objective_score` / `objective_level` 的刻度区间，确认后我可补 CHECK 约束。

<!-- === TILT-CONTRACT-MANIFEST ===
task_id: C12c
spec_version: V1.3
ssot_checksum: TL-SSOT-2026-09-20-A
baseline_version: B1.0
produced_by: 元宝 (Yuanbao)
produced_at: 2026-09-20
batch: all
output_files:
  - db/schema.sql   (rows: 5 tables)
  - db/schema_notes.md   (rows: 273)
unverified_count: 0
self_check:
  frozen_ids_only: true
  enum_from_spec: true
  no_absolute_claims: true
  no_new_concepts: true
  spec_numbers_unchanged: true
known_deviations:
  - weekly_reports / weekly_metrics 增加 week_number BETWEEN 1 AND 4 与 weekly_reports UNIQUE(user_id, week_number)：SPEC 未定义，按 3.9「单周期 4 周」假设；若后续支持多周期，唯一键需扩为 (user_id, cycle_no, week_number)
  - task_events.task_variant 承载 3.7 的 task_type 枚举（standard|disaccharide）：列名沿用 SPEC 原文未重命名
=== END MANIFEST === -->
