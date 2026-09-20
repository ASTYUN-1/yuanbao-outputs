-- === TILT-CONTRACT-MANIFEST ===
-- task_id: C12c
-- spec_version: V1.3
-- ssot_checksum: TL-SSOT-2026-09-20-A
-- baseline_version: B1.0
-- produced_by: 元宝 (Yuanbao)
-- produced_at: 2026-09-20
-- batch: all
-- output_files:
--   - db/schema.sql   (rows: 5 tables)
--   - db/schema_notes.md   (rows: 273)
-- unverified_count: 0
-- self_check:
--   frozen_ids_only: true
--   enum_from_spec: true
--   no_absolute_claims: true
--   no_new_concepts: true
--   spec_numbers_unchanged: true
-- known_deviations:
--   - weekly_reports / weekly_metrics 增加 week_number BETWEEN 1 AND 4 与 weekly_reports UNIQUE(user_id, week_number)：SPEC 未定义，按 3.9「单周期 4 周」假设；若后续支持多周期，唯一键需扩为 (user_id, cycle_no, week_number)
--   - task_events.task_variant 承载 3.7 的 task_type 枚举（standard|disaccharide）：列名沿用 SPEC 原文未重命名
-- === END MANIFEST ===

-- =====================================================================
-- Tilt · db/schema.sql
-- 环境：PostgreSQL 14+（纯 PG 方言，不含任何 MySQL 语法）
-- 内容：合并 SPEC 4.5（users / task_events / weekly_reports）
--       与 SPEC 12.3（user_coordinates / weekly_metrics）共 5 张表，
--       按 6.2 要求补齐外键、唯一约束、NOT NULL / DEFAULT / CHECK。
-- 表顺序：父表 users 在前，四张子表在后。
-- 字段命名：全部沿用 SPEC 原文，未重命名、未增删改字段名。
-- 执行：psql -v ON_ERROR_STOP=1 -d tilt -f db/schema.sql
-- 索引与分区设计说明见 db/schema_notes.md
-- =====================================================================

BEGIN;

-- ---------------------------------------------------------------------
-- 1. users（父表，SPEC 4.5）
-- ---------------------------------------------------------------------
CREATE TABLE users (
    id              UUID PRIMARY KEY,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    age_range       VARCHAR(20),
    user_state      VARCHAR(20),
    coordinate      JSONB,
    cognitive_radar JSONB,
    grit_score      INT,
    current_domains TEXT[],
    metadata        JSONB,
    CONSTRAINT users_grit_score_range CHECK (
        grit_score IS NULL OR (grit_score >= 0 AND grit_score <= 100)
    ),
    CONSTRAINT users_current_domains_known CHECK (
        current_domains IS NULL
        OR current_domains <@ ARRAY[
            'writing_general','translation','podcasting','teaching','debating',
            'script_writing','blogging','go','chess','programming',
            'math_olympiad','strategy_games','cryptography','bridge','photography',
            'ui_design','modeling_3d','architecture_design','video_editing','animation',
            'painting','running','fitness','yoga','martial_arts',
            'dance','climbing','badminton','piano','guitar',
            'composition','singing','djing','sales','counseling',
            'negotiation','mediation','coaching','recruiting','philosophy',
            'psychology','meditation','reading','biography_writing','cooking',
            'gardening','astronomy','biology','pet_training','meteorology'
        ]::TEXT[]
    )
);

COMMENT ON TABLE users IS '用户主表；coordinate/cognitive_radar 为 6 维自我坐标系的快照，metadata 放不进固定列的扩展属性';
COMMENT ON COLUMN users.coordinate IS '6 维坐标系（cognitive_style/energy_source/feedback_speed/value_orientation/risk_attitude/abstraction_level）的当前快照 JSONB';
COMMENT ON COLUMN users.current_domains IS '用户筛选后正在进行 4 周试验的 3-5 个领域 ID，取自 3.1 冻结表';
COMMENT ON COLUMN users.grit_score IS '0-100 整数，SPEC 给定口径，禁止改写区间';

CREATE INDEX idx_users_created_at ON users (created_at);

-- ---------------------------------------------------------------------
-- 2. task_events（SPEC 4.5，最热写入路径）
-- ---------------------------------------------------------------------
CREATE TABLE task_events (
    id               BIGSERIAL PRIMARY KEY,
    user_id          UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    event_type       VARCHAR(50) NOT NULL,
    domain           VARCHAR(50) NOT NULL,
    task_id          VARCHAR(50) NOT NULL,
    task_level       INT NOT NULL,
    task_variant     VARCHAR(20),
    timestamp        TIMESTAMP NOT NULL,
    duration_seconds INT,
    pause_count      INT,
    pause_durations  INT[],
    completion_rate  DECIMAL(4,3),
    retry_count      INT,
    objective_score  DECIMAL(5,2),
    success          BOOLEAN,
    raw_data         JSONB,
    created_at       TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT task_events_event_type_enum CHECK (
        event_type IN (
            'task_start','task_complete','task_abandon','task_retry','task_pause','task_resume',
            'session_start','session_end','domain_switch','task_share','report_view','settings_change'
        )
    ),
    CONSTRAINT task_events_domain_known CHECK (
        domain IN (
            'writing_general','translation','podcasting','teaching','debating',
            'script_writing','blogging','go','chess','programming',
            'math_olympiad','strategy_games','cryptography','bridge','photography',
            'ui_design','modeling_3d','architecture_design','video_editing','animation',
            'painting','running','fitness','yoga','martial_arts',
            'dance','climbing','badminton','piano','guitar',
            'composition','singing','djing','sales','counseling',
            'negotiation','mediation','coaching','recruiting','philosophy',
            'psychology','meditation','reading','biography_writing','cooking',
            'gardening','astronomy','biology','pet_training','meteorology'
        )
    ),
    CONSTRAINT task_events_task_id_format CHECK (
        task_id ~ '^[a-z][a-z0-9_]*_L(10|[1-9])_[0-9]{3}$'
    ),
    CONSTRAINT task_events_task_level_range CHECK (task_level BETWEEN 1 AND 10),
    CONSTRAINT task_events_task_variant_enum CHECK (
        task_variant IS NULL OR task_variant IN ('standard','disaccharide')
    ),
    CONSTRAINT task_events_duration_nonneg CHECK (duration_seconds IS NULL OR duration_seconds >= 0),
    CONSTRAINT task_events_pause_count_nonneg CHECK (pause_count IS NULL OR pause_count >= 0),
    CONSTRAINT task_events_retry_count_nonneg CHECK (retry_count IS NULL OR retry_count >= 0),
    CONSTRAINT task_events_completion_rate_range CHECK (
        completion_rate IS NULL OR (completion_rate >= 0 AND completion_rate <= 1)
    )
);

COMMENT ON TABLE task_events IS '行为埋点流水表，4 周试验期客观指标的唯一数据来源；timestamp 为事件发生时刻，created_at 为入库时刻';
COMMENT ON COLUMN task_events.domain IS '领域 ID，取自 3.1 冻结表（列名沿用 SPEC 的 domain，不改成 domain_id）';
COMMENT ON COLUMN task_events.task_id IS '{domain_id}_L{level}_{三位序号}，如 go_L3_001';
COMMENT ON COLUMN task_events.task_variant IS '承载 3.7 的 task_type 枚举 standard|disaccharide';
COMMENT ON COLUMN task_events.raw_data IS '评估器原始输出（katago/stockfish/llm_* 等 10 类 evaluator_type 的返回体）';

-- 最热路径：某用户 × 某领域 × 某时间段（SPEC 原文索引，定义保持不变）
CREATE INDEX idx_user_domain_time ON task_events (user_id, domain, timestamp);
-- 跨领域时间线：某用户全部事件按时间倒序（会话回放 / 斜率重算）
CREATE INDEX idx_task_events_user_time ON task_events (user_id, timestamp DESC);
-- 跨用户统计：某领域全部事件按时间（领域级难度校准、分位计算）
CREATE INDEX idx_task_events_domain_time ON task_events (domain, timestamp);
-- 任务级聚合：某任务被多少用户做过、成功率与重试分布
CREATE INDEX idx_task_events_task_time ON task_events (domain, task_id, timestamp);

-- ---------------------------------------------------------------------
-- 3. weekly_reports（SPEC 4.5）
-- ---------------------------------------------------------------------
CREATE TABLE weekly_reports (
    id               BIGSERIAL PRIMARY KEY,
    user_id          UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    week_number      INT NOT NULL,
    start_date       DATE NOT NULL,
    end_date         DATE NOT NULL,
    domain_metrics   JSONB,
    objective_levels JSONB,
    objective_slopes JSONB,
    radar_chart      JSONB,
    summary          TEXT,
    generated_at     TIMESTAMP NOT NULL DEFAULT NOW(),
    created_at       TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT weekly_reports_user_week_unique UNIQUE (user_id, week_number),
    CONSTRAINT weekly_reports_week_range CHECK (week_number BETWEEN 1 AND 4),
    CONSTRAINT weekly_reports_date_order CHECK (end_date >= start_date)
);

COMMENT ON TABLE weekly_reports IS '4 周试验的周报；generated_at 为报告生成时刻，created_at 为落库时刻（两者默认同源）';
COMMENT ON COLUMN weekly_reports.objective_slopes IS '各领域进步斜率，产品最终输出物，只做呈现不做判定';
COMMENT ON COLUMN weekly_reports.summary IS '面向用户的中文文案，必须引导性、禁止判定性（硬约束 5）';

CREATE INDEX idx_weekly_reports_generated_at ON weekly_reports (generated_at);

-- ---------------------------------------------------------------------
-- 4. user_coordinates（SPEC 12.3）
-- ---------------------------------------------------------------------
CREATE TABLE user_coordinates (
    id                 BIGSERIAL PRIMARY KEY,
    user_id            UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    cognitive_style    DECIMAL(4,3)[],
    energy_source      DECIMAL(4,3)[],
    feedback_speed     DECIMAL(4,3),
    value_orientation  DECIMAL(4,3)[],
    risk_attitude      DECIMAL(4,3),
    abstraction_level  DECIMAL(4,3),
    confidence         DECIMAL(3,2),
    version            VARCHAR(10) NOT NULL,
    raw_answers        JSONB,
    created_at         TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT user_coordinates_user_version_unique UNIQUE (user_id, version),
    CONSTRAINT user_coordinates_confidence_range CHECK (
        confidence IS NULL OR (confidence >= 0 AND confidence <= 1)
    ),
    CONSTRAINT user_coordinates_feedback_speed_range CHECK (
        feedback_speed IS NULL OR (feedback_speed >= 0 AND feedback_speed <= 1)
    ),
    CONSTRAINT user_coordinates_risk_attitude_range CHECK (
        risk_attitude IS NULL OR (risk_attitude >= 0 AND risk_attitude <= 1)
    ),
    CONSTRAINT user_coordinates_abstraction_level_range CHECK (
        abstraction_level IS NULL OR (abstraction_level >= 0 AND abstraction_level <= 1)
    ),
    CONSTRAINT user_coordinates_cognitive_style_range CHECK (
        cognitive_style IS NULL OR (0 <= ALL(cognitive_style) AND 1 >= ALL(cognitive_style))
    ),
    CONSTRAINT user_coordinates_energy_source_range CHECK (
        energy_source IS NULL OR (0 <= ALL(energy_source) AND 1 >= ALL(energy_source))
    ),
    CONSTRAINT user_coordinates_value_orientation_range CHECK (
        value_orientation IS NULL OR (0 <= ALL(value_orientation) AND 1 >= ALL(value_orientation))
    )
);

COMMENT ON TABLE user_coordinates IS '18 题坐标系的历史版本表；users.coordinate 为当前快照，本表保留每次重测的版本';
COMMENT ON COLUMN user_coordinates.version IS '坐标系版本，与 user_id 组成唯一键；按 6.2 要求补齐 UNIQUE';
COMMENT ON COLUMN user_coordinates.feedback_speed IS 'SPEC 12.3 为标量（当前实现），3.4 该维度为 short|long 两档，见 schema_notes.md 第 6 节说明';
COMMENT ON COLUMN user_coordinates.risk_attitude IS 'SPEC 12.3 为标量（当前实现），3.4 该维度为 conservative|neutral|aggressive 三档，见 schema_notes.md 第 6 节说明';
COMMENT ON COLUMN user_coordinates.raw_answers IS '18 题原始作答，便于重算与审计';

-- 取最新坐标系：某用户按 created_at 倒序取第一条
CREATE INDEX idx_user_coordinates_user_created ON user_coordinates (user_id, created_at DESC);

-- ---------------------------------------------------------------------
-- 5. weekly_metrics（SPEC 12.3；user_id 外键按 6.2 要求补齐）
-- ---------------------------------------------------------------------
CREATE TABLE weekly_metrics (
    id                     BIGSERIAL PRIMARY KEY,
    user_id                UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    domain_id              VARCHAR(50) NOT NULL,
    week_number            INT NOT NULL,
    objective_level        DECIMAL(3,1),
    bounce_back            DECIMAL(3,1),
    repetition             DECIMAL(3,1),
    detail_sensitivity     DECIMAL(3,1),
    proactive_optimization DECIMAL(3,1),
    pain_tolerance         DECIMAL(3,1),
    task_count             INT,
    success_rate           DECIMAL(4,3),
    created_at             TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT weekly_metrics_user_domain_week_unique UNIQUE (user_id, domain_id, week_number),
    CONSTRAINT weekly_metrics_week_range CHECK (week_number BETWEEN 1 AND 4),
    CONSTRAINT weekly_metrics_domain_known CHECK (
        domain_id IN (
            'writing_general','translation','podcasting','teaching','debating',
            'script_writing','blogging','go','chess','programming',
            'math_olympiad','strategy_games','cryptography','bridge','photography',
            'ui_design','modeling_3d','architecture_design','video_editing','animation',
            'painting','running','fitness','yoga','martial_arts',
            'dance','climbing','badminton','piano','guitar',
            'composition','singing','djing','sales','counseling',
            'negotiation','mediation','coaching','recruiting','philosophy',
            'psychology','meditation','reading','biography_writing','cooking',
            'gardening','astronomy','biology','pet_training','meteorology'
        )
    ),
    CONSTRAINT weekly_metrics_task_count_nonneg CHECK (task_count IS NULL OR task_count >= 0),
    CONSTRAINT weekly_metrics_success_rate_range CHECK (
        success_rate IS NULL OR (success_rate >= 0 AND success_rate <= 1)
    )
);

COMMENT ON TABLE weekly_metrics IS '每用户 × 每领域 × 每周的客观水平与 5 维客观指标（3.5 固定字段名）';
COMMENT ON COLUMN weekly_metrics.objective_level IS '客观水平，与 5 维指标一起用于计算进步斜率';

-- 某用户某周跨领域对比（唯一键为 (user_id, domain_id, week_number)，需单独建 (user_id, week_number) 前缀）
CREATE INDEX idx_weekly_metrics_user_week ON weekly_metrics (user_id, week_number);
-- 全站某领域某周分布（跨用户分位计算），INCLUDE 让分位聚合走 index-only scan
CREATE INDEX idx_weekly_metrics_domain_week ON weekly_metrics (domain_id, week_number) INCLUDE (objective_level);

COMMIT;
