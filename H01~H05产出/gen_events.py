#!/usr/bin/env python3
# === TILT-CONTRACT-MANIFEST ===
# task_id: H03
# spec_version: V1.3
# ssot_checksum: TL-SSOT-2026-09-20-A
# baseline_version: B1.0
# produced_by: 元宝(Yuanbao)
# produced_at: 2026-09-21
# batch: all
# output_files:
#   - tools/gen_events.py   (rows: -)
# unverified_count: 3
# self_check:
#   frozen_ids_only: true
#   enum_from_spec: true
#   no_absolute_claims: true
#   no_new_concepts: true
#   spec_numbers_unchanged: true
# known_deviations:
#   - SPEC 4.2 的 task_events 完整字段清单未随本任务书下发（H02 6.2 未附），
#     EVENT_COLUMNS 由第 3.3/3.6/3.7/6.1 节已冻结字段推导，待与 C12c db/schema.sql 对齐
#   - objective_score 与 5 维指标的量纲未在任务书冻结，脚本顶部常量可一处改
#   - 生成的数据文件（events.* / weekly_metrics.* 等）不加 manifest 头，避免破坏 Postgres \COPY 导入
#   - events.csv 未按第 4.1 节追加 source / verify_status 两列：该文件是数据库导入用数据文件，
#     追加会与 task_events schema 不一致；第 4.1 节的 CSV 契约按内容类交付物理解
# === END MANIFEST ===
"""Tilt · H03 压测造数脚本：生成 task_events（及侧表）测试数据。

只依赖标准库：json / csv / random / argparse / datetime / uuid / re / os / sys。

用法示例：
    python3 tools/gen_events.py --out ./out
    python3 tools/gen_events.py --users 2000 --days 28 --events-per-user-day 6 --seed 7 --out ./out

产物（输出目录下）：
    events.jsonl       一行一个 event，null / true / false 为 JSON 原生字面量
    events.csv         UTF-8 with BOM，文本字段双引号包裹，NULL 为空串（Excel 抽查用）
    events_copy.tsv    Postgres \\COPY 专用：无引号包裹、NULL 用 \\N
    users.csv
    user_coordinates.{jsonl,csv,copy.tsv}
    weekly_metrics.{jsonl,csv,copy.tsv}

导入示例（events_copy.tsv 为 text 格式：无引号、NULL 写 \\N）：
    \\COPY task_events (event_id,user_id,session_id,domain_id,task_id,task_type,task_level,event_type,evaluator_type,timestamp,duration_seconds,completion_rate,objective_score,success) FROM 'out/events_copy.tsv' WITH (FORMAT text, DELIMITER E'\\t', NULL '\\N');
"""

import argparse
import json
import os
import random
import re
import sys
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# 冻结事实源（SSOT: TL-SSOT-2026-09-20-A）—— 不得改 ID / 枚举 / 大小写
# ---------------------------------------------------------------------------

# 第 3.1 节：50 个领域唯一 ID（按表内序号排列）
DOMAIN_IDS = [
    "writing_general", "translation", "podcasting", "teaching", "debating",
    "script_writing", "blogging", "go", "chess", "programming",
    "math_olympiad", "strategy_games", "cryptography", "bridge", "photography",
    "ui_design", "modeling_3d", "architecture_design", "video_editing", "animation",
    "painting", "running", "fitness", "yoga", "martial_arts",
    "dance", "climbing", "badminton", "piano", "guitar",
    "composition", "singing", "djing", "sales", "counseling",
    "negotiation", "mediation", "coaching", "recruiting", "philosophy",
    "psychology", "meditation", "reading", "biography_writing", "cooking",
    "gardening", "astronomy", "biology", "pet_training", "meteorology",
]

# 第 3.6 节：12 个埋点事件类型
EVENT_TYPES = [
    "task_start", "task_complete", "task_abandon", "task_retry", "task_pause", "task_resume",
    "session_start", "session_end", "domain_switch", "task_share", "report_view", "settings_change",
]

# 第 3.3 节：10 个评估器类型
EVALUATOR_TYPES = [
    "katago", "stockfish", "auto_test", "llm_writing", "llm_image", "llm_video",
    "llm_audio", "llm_dialogue", "data_tracking", "knowledge_test",
]

# 第 3.7 节：task_type 枚举
TASK_TYPES = ["standard", "disaccharide"]

# 第 3.4 节：坐标系 6 维及其选项枚举
COORDINATE_DIMENSIONS = {
    "cognitive_style": ["visual", "auditory", "textual", "logical", "bodily"],
    "energy_source": ["solitude", "social", "competition", "collaboration"],
    "feedback_speed": ["short", "long"],
    "value_orientation": ["creation", "helping", "influence", "money", "aesthetics"],
    "risk_attitude": ["conservative", "neutral", "aggressive"],
    "abstraction_level": ["theory", "application", "operation"],
}

# 第 3.5 节：5 维客观指标
OBJECTIVE_METRICS = [
    "bounce_back", "repetition", "detail_sensitivity", "proactive_optimization", "pain_tolerance",
]

# ---------------------------------------------------------------------------
# 可一处修改的常量（量纲、字段名未在本任务书冻结，对齐 C12c schema 时只改这里）
# ---------------------------------------------------------------------------

# task_events 列定义：(列名, 类型)，类型 ∈ {str,int,float,bool}，均可为 NULL
EVENT_COLUMNS = [
    ("event_id", "str"),
    ("user_id", "str"),
    ("session_id", "str"),
    ("domain_id", "str"),
    ("task_id", "str"),
    ("task_type", "str"),
    ("task_level", "int"),
    ("event_type", "str"),
    ("evaluator_type", "str"),
    ("timestamp", "str"),
    ("duration_seconds", "int"),
    ("completion_rate", "float"),
    ("objective_score", "float"),
    ("success", "bool"),
]

USERS_COLUMNS = [("user_id", "str"), ("created_at", "str")]

USER_COORDINATES_COLUMNS = [
    ("user_id", "str"), ("version", "int"),
    ("cognitive_style", "str"), ("energy_source", "str"), ("feedback_speed", "str"),
    ("value_orientation", "str"), ("risk_attitude", "str"), ("abstraction_level", "str"),
    ("created_at", "str"),
]

WEEKLY_METRICS_COLUMNS = [
    ("user_id", "str"), ("domain_id", "str"), ("week_no", "int"),
    ("week_start", "str"), ("week_end", "str"),
    ("event_count", "int"), ("total_duration_seconds", "int"),
    ("completion_rate", "float"), ("objective_score", "float"),
    ("bounce_back", "float"), ("repetition", "float"), ("detail_sensitivity", "float"),
    ("proactive_optimization", "float"), ("pain_tolerance", "float"),
    ("created_at", "str"),
]

# 量纲：objective_score 与 5 维指标统一按 0-100（两位小数）生成 [待核验:未在任务书冻结]
SCORE_MIN, SCORE_MAX = 0.0, 100.0
# duration_seconds：15-30 分钟 => 900-1800 秒；允许 5% 偏离带
DURATION_BAND = (900, 1800)
DURATION_OUT_OF_BAND_RATE = 0.05
DURATION_OUT_OF_BAND = (600, 2400)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_START_DATE = "2026-08-24"  # 周一，28 天正好 4 个整周（对齐第 3.9 节周次）

# 第 3.9 节：4 周任务递进节奏 -> (level_min, level_max)
WEEK_LEVEL_RANGE = [(1, 2), (2, 3), (3, 4), (4, 5)]

# 领域 -> 评估器（仅用于让 task_complete 的 evaluator_type 分布合理）
DOMAIN_EVALUATOR = {
    "go": "katago", "chess": "stockfish", "programming": "auto_test",
    "math_olympiad": "knowledge_test", "cryptography": "knowledge_test",
    "bridge": "knowledge_test", "strategy_games": "data_tracking",
    "writing_general": "llm_writing", "translation": "llm_writing",
    "script_writing": "llm_writing", "blogging": "llm_writing",
    "biography_writing": "llm_writing", "podcasting": "llm_audio",
    "teaching": "llm_dialogue", "debating": "llm_dialogue",
    "photography": "llm_image", "ui_design": "llm_image", "modeling_3d": "llm_image",
    "architecture_design": "llm_image", "painting": "llm_image",
    "video_editing": "llm_video", "animation": "llm_video",
    "running": "data_tracking", "fitness": "data_tracking", "yoga": "data_tracking",
    "martial_arts": "data_tracking", "dance": "llm_video", "climbing": "data_tracking",
    "badminton": "data_tracking",
    "piano": "llm_audio", "guitar": "llm_audio", "composition": "llm_audio",
    "singing": "llm_audio", "djing": "llm_audio",
    "sales": "llm_dialogue", "counseling": "llm_dialogue", "negotiation": "llm_dialogue",
    "mediation": "llm_dialogue", "coaching": "llm_dialogue", "recruiting": "llm_dialogue",
    "philosophy": "llm_writing", "psychology": "llm_writing",
    "meditation": "data_tracking", "reading": "knowledge_test",
    "cooking": "llm_image", "gardening": "data_tracking", "astronomy": "knowledge_test",
    "biology": "knowledge_test", "pet_training": "llm_video", "meteorology": "knowledge_test",
}

TASK_ID_RE = re.compile(r"^[a-z0-9_]+_L(10|[1-9])_[0-9]{3}$")


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def iso(dt):
    """datetime -> ISO 8601 UTC，形如 2026-09-19T10:30:00Z"""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def rand_uuid(rng):
    """可复现的 UUID v4（不用 uuid.uuid4，避免 os.urandom 破坏 seed 复现性）"""
    return str(uuid.UUID(int=rng.getrandbits(128), version=4))


def fmt_value(value, col_type, null_token, quote_strings=True):
    """按列类型渲染单个值：文本可选双引号包裹，数值裸写，None -> null_token"""
    if value is None:
        return null_token
    if col_type == "str":
        escaped = str(value).replace('"', '""')
        return '"%s"' % escaped if quote_strings else escaped
    if col_type == "bool":
        return "true" if value else "false"
    return str(value)


def write_table(path, columns, rows, fmt):
    """fmt: jsonl | csv | copy"""
    col_names = [c[0] for c in columns]
    col_types = {c[0]: c[1] for c in columns}
    if fmt == "jsonl":
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            for row in rows:
                obj = {k: row.get(k) for k in col_names}
                fh.write(json.dumps(obj, ensure_ascii=False) + "\n")
    else:
        if fmt == "csv":
            encoding, delimiter, null_token, quote = "utf-8-sig", ",", "", True
        elif fmt == "copy":
            # Postgres \COPY 专用：无引号包裹、NULL 用 \N、UTF-8 无 BOM
            encoding, delimiter, null_token, quote = "utf-8", "\t", "\\N", False
        else:
            raise ValueError("unknown fmt: %s" % fmt)
        with open(path, "w", encoding=encoding, newline="") as fh:
            if fmt == "csv":
                fh.write(",".join('"%s"' % n for n in col_names) + "\r\n")
            for row in rows:
                cells = [fmt_value(row.get(n), col_types[n], null_token, quote) for n in col_names]
                fh.write(delimiter.join(cells) + ("\r\n" if fmt == "csv" else "\n"))
    return len(rows)


# ---------------------------------------------------------------------------
# 事件生成：单用户单天 = 一条有时序、有状态机的事件流
# ---------------------------------------------------------------------------

def next_event_type(rng, prev, is_last_slot, has_room_for_two):
    """小型状态机：保证事件流时序合理，且 12 个 event_type 都能被覆盖"""
    if prev is None:
        return "task_start"
    if is_last_slot:
        return prev_default_tail(rng, prev)
    table = {
        "session_start": [("task_start", 1.0)],
        "task_start": [("task_complete", 0.84), ("task_abandon", 0.08),
                       ("task_retry", 0.05), ("task_pause", 0.03)],
        "task_retry": [("task_complete", 0.70), ("task_abandon", 0.20), ("task_pause", 0.10)],
        "task_pause": [("task_resume", 0.85), ("task_abandon", 0.15)],
        "task_resume": [("task_complete", 0.88), ("task_abandon", 0.12)],
        "task_complete": [("task_start", 0.45), ("domain_switch", 0.35), ("task_share", 0.09),
                          ("report_view", 0.06), ("settings_change", 0.05)],
        "task_abandon": [("task_start", 0.35), ("domain_switch", 0.40), ("report_view", 0.15),
                         ("settings_change", 0.10)],
        "domain_switch": [("task_start", 1.0)],
        "task_share": [("task_start", 0.60), ("domain_switch", 0.20), ("session_end", 0.20)],
        "report_view": [("task_start", 0.60), ("domain_switch", 0.20), ("session_end", 0.20)],
        "settings_change": [("task_start", 0.65), ("domain_switch", 0.20), ("session_end", 0.15)],
        "session_end": [("session_start", 0.5), ("task_start", 0.5)],
    }[prev]
    table = [(t, w) for (t, w) in table if not (t == "task_pause" and not has_room_for_two)]
    total = sum(w for _, w in table)
    x = rng.random() * total
    acc = 0.0
    for t, w in table:
        acc += w
        if x <= acc:
            return t
    return table[-1][0]


def prev_default_tail(rng, prev):
    """最后一个槽位不放 session_end 时的兜底类型"""
    if prev in ("task_start", "task_retry", "task_resume", "task_pause"):
        return "task_complete" if rng.random() < 0.85 else "task_abandon"
    if prev in ("task_share", "report_view", "settings_change"):
        return "task_start"
    return "task_start"


def duration_for(rng, event_type):
    lo, hi = DURATION_BAND
    if event_type in ("task_complete", "task_abandon"):
        if rng.random() < DURATION_OUT_OF_BAND_RATE:
            return rng.randint(*DURATION_OUT_OF_BAND)
        return rng.randint(lo, hi)
    if event_type == "task_retry":
        return rng.randint(300, 900)
    if event_type == "task_pause":
        return rng.randint(60, 600)
    if event_type == "session_end":
        return rng.randint(lo, 7200)
    if event_type in ("domain_switch", "task_share", "report_view", "settings_change"):
        return rng.randint(5, 120)
    return None  # task_start / task_resume / session_start 尚无耗时


def outcome_for(rng, event_type):
    """返回 (success, completion_rate, objective_score)，三者互不矛盾"""
    if event_type == "task_complete":
        if rng.random() < 0.78:
            return True, round(rng.uniform(0.80, 1.00), 4), round(rng.uniform(60.0, 95.0), 2)
        return False, round(rng.uniform(0.30, 0.65), 4), round(rng.uniform(25.0, 55.0), 2)
    if event_type == "task_abandon":
        return False, round(rng.uniform(0.05, 0.40), 4), round(rng.uniform(10.0, 45.0), 2)
    return None, None, None


def generate(args):
    rng = random.Random(args.seed)
    start_date = datetime.strptime(args.start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    pool = DOMAIN_IDS[: max(1, min(args.domains, len(DOMAIN_IDS)))]
    n_users = args.users
    n_days = args.days
    per_day = args.events_per_user_day

    events = []
    users = []
    coordinates = []
    # (user_id, domain_id, week_no) -> 聚合器，供 weekly_metrics
    agg = defaultdict(lambda: {"events": 0, "duration": 0, "cr": [], "score": []})

    for ui in range(n_users):
        user_id = "u_%06d" % (ui + 1)
        created_at = iso(start_date - timedelta(days=rng.randint(1, 30)))
        users.append({"user_id": user_id, "created_at": created_at})

        # 每个用户并行投入 3-5 个领域（产品机制：筛到 3-5 个后并行 4 周）
        n_user_domains = rng.randint(3, 5)
        user_domains = rng.sample(pool, min(n_user_domains, len(pool)))
        # 每个领域预先分配一个稳定的任务序号，保证 task_id 在 4 周内可追溯
        task_seq = {d: rng.randint(1, 999) for d in user_domains}

        # 坐标系：约 35% 用户在第 2 周后重测，产生 version=2
        def coord_version(version, at):
            row = {"user_id": user_id, "version": version, "created_at": iso(at)}
            for dim, opts in COORDINATE_DIMENSIONS.items():
                row[dim] = rng.choice(opts)
            return row

        coordinates.append(coord_version(1, start_date - timedelta(days=rng.randint(0, 3))))
        if rng.random() < 0.35:
            coordinates.append(coord_version(2, start_date + timedelta(days=rng.randint(14, 27))))

        for di in range(n_days):
            day_start = start_date + timedelta(days=di)
            week_no = di // 7 + 1
            lvl_lo, lvl_hi = WEEK_LEVEL_RANGE[min(di // 7, len(WEEK_LEVEL_RANGE) - 1)]
            day_cursor = day_start + timedelta(
                hours=rng.randint(18, 21), minutes=rng.randint(0, 59), seconds=rng.randint(0, 59)
            )
            day_end = day_start + timedelta(hours=23, minutes=59, seconds=59)
            session_id = rand_uuid(rng)
            # 当天起始领域按天轮转，保证用户 3-5 个并行领域在 4 周内都被覆盖
            cur_domain = user_domains[di % len(user_domains)]
            cur_level = rng.randint(lvl_lo, lvl_hi)
            cur_task_type = rng.choices(TASK_TYPES, weights=[0.85, 0.15])[0]
            task_id = "%s_L%d_%03d" % (cur_domain, cur_level, task_seq[cur_domain])

            # 每天是否以 session_start 开头：事件数越多越可能形成完整会话
            p_session = 0.7 if per_day >= 5 else (0.35 if per_day == 4 else 0.0)
            has_session_start = False
            prev_type = None
            for slot in range(per_day):
                is_last = slot == per_day - 1
                has_room_for_two = slot <= per_day - 3
                if slot == 0:
                    if rng.random() < p_session:
                        e_type = "session_start"
                        has_session_start = True
                    else:
                        e_type = "task_start"
                elif is_last and has_session_start and rng.random() < 0.7:
                    e_type = "session_end"
                else:
                    e_type = next_event_type(rng, prev_type, is_last, has_room_for_two)

                if e_type == "domain_switch":
                    others = [d for d in user_domains if d != cur_domain] or user_domains
                    cur_domain = rng.choice(others)
                    cur_level = rng.randint(lvl_lo, lvl_hi)
                    cur_task_type = rng.choices(TASK_TYPES, weights=[0.85, 0.15])[0]
                    task_id = "%s_L%d_%03d" % (cur_domain, cur_level, task_seq[cur_domain])
                elif e_type == "task_start":
                    if prev_type in (None, "session_start", "task_complete", "task_abandon",
                                     "task_share", "report_view", "settings_change", "session_end"):
                        cur_level = rng.randint(lvl_lo, lvl_hi)
                        cur_task_type = rng.choices(TASK_TYPES, weights=[0.85, 0.15])[0]
                        task_id = "%s_L%d_%03d" % (cur_domain, cur_level, task_seq[cur_domain])

                duration = duration_for(rng, e_type)
                success, completion_rate, objective_score = outcome_for(rng, e_type)
                evaluator = DOMAIN_EVALUATOR.get(cur_domain) if e_type == "task_complete" else None

                events.append({
                    "event_id": rand_uuid(rng),
                    "user_id": user_id,
                    "session_id": session_id,
                    "domain_id": cur_domain,
                    "task_id": task_id,
                    "task_type": cur_task_type,
                    "task_level": cur_level,
                    "event_type": e_type,
                    "evaluator_type": evaluator,
                    "timestamp": iso(min(day_cursor, day_end)),
                    "duration_seconds": duration,
                    "completion_rate": completion_rate,
                    "objective_score": objective_score,
                    "success": success,
                })

                bucket = agg[(user_id, cur_domain, week_no)]
                bucket["events"] += 1
                if duration:
                    bucket["duration"] += duration
                if completion_rate is not None:
                    bucket["cr"].append(completion_rate)
                    bucket["score"].append(objective_score)

                advance = (duration if duration else 0) + rng.randint(5, 120)
                day_cursor = min(day_cursor + timedelta(seconds=advance), day_end)
                prev_type = e_type

    # --- 由事件聚合出 weekly_metrics（5 维指标为合成值，用于压测聚合查询） ---
    metrics = []
    for (user_id, domain_id, week_no), b in agg.items():
        w_start = start_date + timedelta(days=(week_no - 1) * 7)
        w_end = w_start + timedelta(days=6)
        cr = round(sum(b["cr"]) / len(b["cr"]), 4) if b["cr"] else None
        sc = round(sum(b["score"]) / len(b["score"]), 2) if b["score"] else None
        row = {
            "user_id": user_id,
            "domain_id": domain_id,
            "week_no": week_no,
            "week_start": iso(w_start),
            "week_end": iso(w_end),
            "event_count": b["events"],
            "total_duration_seconds": b["duration"],
            "completion_rate": cr,
            "objective_score": sc,
            "created_at": iso(w_end + timedelta(days=1)),
        }
        # 5 维客观指标：以该周表现为基线做受控抖动，保证同一 seed 可复现
        for m in OBJECTIVE_METRICS:
            base = 50.0 if sc is None else sc
            row[m] = round(min(SCORE_MAX, max(SCORE_MIN, base + rng.uniform(-12.0, 12.0))), 2)
        metrics.append(row)
    metrics.sort(key=lambda r: (r["user_id"], r["domain_id"], r["week_no"]))
    coordinates.sort(key=lambda r: (r["user_id"], r["version"]))
    return events, users, coordinates, metrics


# ---------------------------------------------------------------------------
# 自校验 + 统计摘要
# ---------------------------------------------------------------------------

def validate(events, args):
    checks = []
    by_type = Counter(e["event_type"] for e in events)
    missing_types = [t for t in EVENT_TYPES if by_type.get(t, 0) == 0]

    bad_task_id = sum(1 for e in events if not TASK_ID_RE.match(e["task_id"]))
    bad_level = sum(1 for e in events if not (1 <= e["task_level"] <= 5))

    contradiction = 0
    for e in events:
        s, cr, sc = e["success"], e["completion_rate"], e["objective_score"]
        if s is True and not (cr is not None and cr >= 0.80 and sc is not None and sc >= 60.0):
            contradiction += 1
        elif s is False and not (cr is not None and cr <= 0.65 and sc is not None and sc <= 55.0):
            contradiction += 1
        elif s is None and (cr is not None or sc is not None):
            contradiction += 1

    order_violation = 0
    prev = None
    for e in events:
        key = (e["user_id"], e["timestamp"])
        if prev is not None and prev[0] == key[0] and key[1] < prev[1]:
            order_violation += 1
        prev = key

    durations = [e["duration_seconds"] for e in events if e["duration_seconds"] is not None]
    in_band = [d for d in durations if DURATION_BAND[0] <= d <= DURATION_BAND[1]]
    # 15-30 分钟对应的是主任务事件（task_complete / task_abandon），单独统计带内占比
    main_durations = [e["duration_seconds"] for e in events
                      if e["event_type"] in ("task_complete", "task_abandon")]
    main_in_band = [d for d in main_durations if DURATION_BAND[0] <= d <= DURATION_BAND[1]]
    domains_covered = len(set(e["domain_id"] for e in events))

    checks.append(("event_type 全部取自第 3.6 节枚举", not set(by_type) - set(EVENT_TYPES)))
    checks.append(("task_id 符合 {domain_id}_L{level}_{三位序号}", bad_task_id == 0))
    checks.append(("task_level 落在 MVP L1-L5", bad_level == 0))
    checks.append(("success / completion_rate / objective_score 三者自洽", contradiction == 0))
    checks.append(("同一用户 timestamp 不倒序", order_violation == 0))
    checks.append(("duration_seconds 有值且为正", bool(durations) and min(durations) > 0))
    expected_domains = max(1, min(args.domains, len(DOMAIN_IDS)))
    checks.append(("领域覆盖数非空且不超过 --domains",
                   0 < domains_covered <= expected_domains))

    return {
        "checks": checks,
        "by_type": by_type,
        "missing_types": missing_types,
        "bad_task_id": bad_task_id,
        "bad_level": bad_level,
        "contradiction": contradiction,
        "order_violation": order_violation,
        "durations": durations,
        "in_band": in_band,
        "main_durations": main_durations,
        "main_in_band": main_in_band,
        "domains_covered": domains_covered,
        "expected_domains": expected_domains,
    }


def print_summary(events, users, coordinates, metrics, rep, files, args):
    line = "=" * 66
    print(line)
    print("Tilt H03 · 造数摘要   seed=%s  users=%d  days=%d  events/user/day=%d"
          % (args.seed, args.users, args.days, args.events_per_user_day))
    print(line)
    print("总事件条数        : %d" % len(events))
    print("用户 / 坐标 / 周指标: %d / %d / %d" % (len(users), len(coordinates), len(metrics)))
    print("领域覆盖数        : %d / %d" % (rep["domains_covered"], rep["expected_domains"]))
    if rep["domains_covered"] < rep["expected_domains"]:
        print("    WARN: 领域未全覆盖，通常因 --users/--days 偏小，放大样本量即可（非数据错误）")
    print("\n[1] 各 event_type 计数（第 3.6 节顺序）")
    for t in EVENT_TYPES:
        n = rep["by_type"].get(t, 0)
        print("    %-16s %8d  %5.1f%%" % (t, n, 100.0 * n / max(1, len(events))))
    if rep["missing_types"]:
        print("    未覆盖类型: %s" % ", ".join(rep["missing_types"]))

    d = rep["durations"]
    md = rep["main_durations"]
    print("\n[2] duration_seconds（全部有值事件）")
    if d:
        print("    min=%d  max=%d  mean=%.1f  (n=%d)"
              % (min(d), max(d), sum(d) / len(d), len(d)))
    print("    主任务事件 task_complete/task_abandon: min=%d  max=%d  mean=%.1f  (n=%d)"
          % (min(md), max(md), sum(md) / len(md), len(md)))
    print("    其中落在 900-1800（15-30 分钟）: %d 条 (%.1f%%)，允许偏离 %d 条"
          % (len(rep["main_in_band"]), 100.0 * len(rep["main_in_band"]) / len(md),
             len(md) - len(rep["main_in_band"])))

    levels = Counter(e["task_level"] for e in events)
    print("\n[3] task_level 分布")
    for lv in sorted(levels):
        print("    L%-2d %8d  %5.1f%%" % (lv, levels[lv], 100.0 * levels[lv] / len(events)))

    weeks = Counter((e["timestamp"][:10] for e in events), )
    print("\n[4] 时间跨度: %s ~ %s（%d 个自然日）"
          % (min(e["timestamp"] for e in events)[:10],
             max(e["timestamp"] for e in events)[:10], len(weeks)))

    print("\n[5] 输出文件")
    for name, rows, size in files:
        print("    %-28s rows=%-8d %.2f MB" % (name, rows, size / 1024.0 / 1024.0))

    print("\n[6] 自校验")
    ok = True
    for label, passed in rep["checks"]:
        print("    [%s] %s" % ("PASS" if passed else "FAIL", label))
        ok = ok and passed
    print(line)
    print("自校验结果: %s" % ("全部通过" if ok else "存在 FAIL，请检查上面条目"))
    print(line)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main(argv=None):
    p = argparse.ArgumentParser(
        prog="gen_events.py",
        description="Tilt H03 压测造数：生成 task_events 及侧表测试数据（仅标准库，seed 可复现）",
    )
    p.add_argument("--users", type=int, default=1000, help="用户数（默认 1000）")
    p.add_argument("--days", type=int, default=28, help="天数（默认 28）")
    p.add_argument("--events-per-user-day", type=int, default=4,
                   help="每用户每天事件数（默认 4，总量约 11.2 万）")
    p.add_argument("--domains", type=int, default=50, help="参与领域数（默认 50，从 SSOT 取）")
    p.add_argument("--seed", type=int, default=42, help="随机种子（默认 42）")
    p.add_argument("--out", default="out", help="输出目录（默认 ./out）")
    p.add_argument("--start-date", default=DEFAULT_START_DATE,
                   help="数据起始日期 YYYY-MM-DD（默认 %s，周一，4 整周）" % DEFAULT_START_DATE)
    p.add_argument("--side-tables", action=argparse.BooleanOptionalAction, default=True,
                   help="同时生成 users / user_coordinates / weekly_metrics（默认开启）")
    args = p.parse_args(argv)

    if args.users < 1 or args.days < 1 or args.events_per_user_day < 1:
        p.error("--users / --days / --events-per-user-day 必须 >= 1")
    if not (1 <= args.domains <= len(DOMAIN_IDS)):
        p.error("--domains 必须落在 1-%d" % len(DOMAIN_IDS))

    os.makedirs(args.out, exist_ok=True)
    events, users, coordinates, metrics = generate(args)
    rep = validate(events, args)

    files = []
    for fmt, name in (("jsonl", "events.jsonl"), ("csv", "events.csv"), ("copy", "events_copy.tsv")):
        path = os.path.join(args.out, name)
        rows = write_table(path, EVENT_COLUMNS, events, fmt)
        files.append((name, rows, os.path.getsize(path)))

    if args.side_tables:
        users_csv = os.path.join(args.out, "users.csv")
        rows = write_table(users_csv, USERS_COLUMNS, users, "csv")
        files.append(("users.csv", rows, os.path.getsize(users_csv)))
        for cols, base, data in (
            (USER_COORDINATES_COLUMNS, "user_coordinates", coordinates),
            (WEEKLY_METRICS_COLUMNS, "weekly_metrics", metrics),
        ):
            for fmt, ext in (("jsonl", "jsonl"), ("csv", "csv"), ("copy", "copy.tsv")):
                name = "%s.%s" % (base, ext)
                path = os.path.join(args.out, name)
                rows = write_table(path, cols, data, fmt)
                files.append((name, rows, os.path.getsize(path)))

    print_summary(events, users, coordinates, metrics, rep, files, args)
    return 0 if all(ok for _, ok in rep["checks"]) else 1


if __name__ == "__main__":
    sys.exit(main())
