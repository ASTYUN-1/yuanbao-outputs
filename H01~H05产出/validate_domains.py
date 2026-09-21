#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# === TILT-CONTRACT-MANIFEST ===
# task_id: H01
# spec_version: V1.3
# ssot_checksum: TL-SSOT-2026-09-20-A
# baseline_version: B1.0
# produced_by: Yuanbao
# produced_at: 2026-09-21
# batch: all
# output_files:
#   - tools/validate_domains.py   (rows: 601)
# unverified_count: 0
# self_check:
#   frozen_ids_only: true
#   enum_from_spec: true
#   no_absolute_claims: true
#   no_new_concepts: true
#   spec_numbers_unchanged: true
# known_deviations: []
# === END MANIFEST ===
"""Tilt · H01 · 领域库校验脚本

用途：批量校验 C01 产出的领域库（domains.csv），把"每次人工看一遍"变成"跑一次脚本"。
依赖：仅 Python 3.10 标准库（csv / json / re / argparse / pathlib / collections / datetime）。
退出码：0 = 无 ERROR；1 = 存在 ERROR（可直接接 CI）。

十个检查项（编号与本文件 CHECKS 顺序一致）：
  1 表头完整性与顺序     ERROR
  2 id 唯一性            ERROR
  3 id 在 SSOT 白名单内  ERROR
  4 50 个领域覆盖度      ERROR
  5 冻结数值逐行比对     ERROR
  6 gardner 枚举合规     ERROR
  7 数值字段合法 + 1-5   ERROR
  8 description ≤80 字   ERROR
  9 判定性语言           ERROR
  10 必填列非空          WARN
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, OrderedDict
from datetime import datetime, timezone
from pathlib import Path

TASK_ID = "H01"
SPEC_VERSION = "V1.3"
SSOT_CHECKSUM = "TL-SSOT-2026-09-20-A"

# --------------------------------------------------------------------------- #
# 冻结契约（取自 H01 任务书第 3 节 / 第 6.2 节，不得改动）
# --------------------------------------------------------------------------- #
SSOT_COLUMNS = [
    "id",
    "name",
    "category",
    "gardner_intelligence",
    "startup_difficulty",
    "feedback_speed",
    "mechanism_strength",
]

DOMAIN_COLUMNS = [
    "id",
    "name",
    "category",
    "gardner_intelligence",
    "startup_difficulty",
    "feedback_speed",
    "mechanism_strength",
    "pain_tolerance_required",
    "estimated_cost_per_month",
    "estimated_time_to_proficiency",
    "description",
    "source",
    "verify_status",
]

# 与 SSOT 逐行比对的冻结数值字段（SPEC 已给定，禁止"我认为应该是 3"）
FROZEN_NUMERIC_FIELDS = ["startup_difficulty", "feedback_speed", "mechanism_strength"]
# 必须为合法整数的字段
NUMERIC_INT_FIELDS = [
    "startup_difficulty",
    "feedback_speed",
    "mechanism_strength",
    "pain_tolerance_required",
    "estimated_cost_per_month",
]
# 必填列（空值仅 WARN）
REQUIRED_FIELDS = [
    "id",
    "name",
    "category",
    "gardner_intelligence",
    "startup_difficulty",
    "feedback_speed",
    "mechanism_strength",
    "pain_tolerance_required",
    "description",
]
# 描述类字段：做判定性语言检测
DESCRIPTIVE_FIELDS = ["name", "category", "description"]

GARDNER_ENUM = [
    "linguistic",
    "logical_mathematical",
    "spatial",
    "bodily_kinesthetic",
    "musical",
    "interpersonal",
    "intrapersonal",
    "naturalist",
]

PAIN_TOLERANCE_MIN = 1
PAIN_TOLERANCE_MAX = 5
DESCRIPTION_MAX_LEN = 80
GARDNER_SEPARATOR = ";"

# 判定性语言检测模式（硬约束 6.5 第 4 条，逐条原样实现）
JUDGEMENTAL_PATTERNS = [
    (r"你(一定|肯定)(有|适合|擅长)", "绝对化断言"),
    (r"你(天生|骨子里)", "先天归因"),
    (r"你(不|不太)(适合|擅长)", "否定式判定"),
    (r"你(就是|是)一个?\s*\S*型(人|人格)", "类型标签"),
]
JUDGEMENTAL_COMPILED = [(re.compile(p), tag) for p, tag in JUDGEMENTAL_PATTERNS]

CHECKS = OrderedDict(
    [
        ("header", "1 表头完整性与顺序"),
        ("id_unique", "2 id 唯一性"),
        ("id_whitelist", "3 id 白名单"),
        ("coverage", "4 覆盖度"),
        ("frozen_numbers", "5 冻结数值"),
        ("gardner_enum", "6 gardner 枚举"),
        ("numeric_fields", "7 数值字段"),
        ("description", "8 description"),
        ("judgemental", "9 判定性语言"),
        ("required_empty", "10 必填列非空"),
    ]
)

ERROR = "ERROR"
WARN = "WARN"


# --------------------------------------------------------------------------- #
# 解析（处理两个坑：UTF-8 BOM、文件顶部 manifest 注释块 + 空行）
# --------------------------------------------------------------------------- #
def read_table(path: Path):
    """剥离 `#` 注释块与空行后交给 csv.DictReader，同时保留原始行号。

    返回 (header, rows, line_map)；rows 元素为 {字段名: 去空白后的字符串}。
    """
    try:
        raw_lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except OSError as exc:  # 文件不可读：上层已做存在性检查，这里兜底
        raise SystemExit(f"[ERROR] 无法读取文件 {path}: {exc}")

    kept, kept_line_no = [], []
    for lineno, line in enumerate(raw_lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        kept.append(line)
        kept_line_no.append(lineno)

    if not kept:
        return [], [], []

    reader = csv.DictReader(kept)
    header = list(reader.fieldnames or [])
    rows, line_map = [], []
    for idx, raw_row in enumerate(reader, start=1):
        clean = {}
        for key in header:
            value = raw_row.get(key)
            clean[key] = "" if value is None else str(value).strip()
        extra = raw_row.get(None)
        if extra:
            clean["__extra__"] = ",".join(str(x) for x in extra)
        rows.append(clean)
        line_map.append(kept_line_no[idx] if idx < len(kept_line_no) else kept_line_no[-1])
    return header, rows, line_map


def load_ssot(path: Path):
    """读取 SSOT 白名单，返回 {id: {field: value}}；表头不合规直接退出。"""
    header, rows, _ = read_table(path)
    if not header:
        raise SystemExit(f"[ERROR] SSOT 文件为空或只有注释块: {path}")
    missing = [c for c in SSOT_COLUMNS if c not in header]
    if missing:
        raise SystemExit(
            f"[ERROR] SSOT 表头缺少字段 {missing}；期望表头: {','.join(SSOT_COLUMNS)}"
        )
    ssot = {}
    for row in rows:
        did = row.get("id", "").strip()
        if did:
            ssot[did] = row
    return ssot


# --------------------------------------------------------------------------- #
# 检查项
# --------------------------------------------------------------------------- #
def check_header(header):
    issues = []
    if header != DOMAIN_COLUMNS:
        missing = [c for c in DOMAIN_COLUMNS if c not in header]
        unknown = [c for c in header if c not in DOMAIN_COLUMNS]
        if missing:
            issues.append((ERROR, None, f"表头缺失字段: {', '.join(missing)}"))
        if unknown:
            issues.append((ERROR, None, f"表头出现未知字段: {', '.join(unknown)}"))
        if not missing and not unknown:
            issues.append(
                (
                    ERROR,
                    None,
                    f"表头顺序不符；期望: {','.join(DOMAIN_COLUMNS)} 实际: {','.join(header)}",
                )
            )
    return issues


def check_id_unique(rows, line_map):
    issues = []
    counter = Counter(row.get("id", "") for row in rows if row.get("id", ""))
    for did, count in counter.items():
        if count > 1:
            lines = [str(line_map[i]) for i, r in enumerate(rows) if r.get("id", "") == did]
            issues.append((ERROR, int(lines[0]), f"id 重复: {did}（出现 {count} 次，行 {', '.join(lines)}）"))
    return issues


def check_id_whitelist(rows, line_map, ssot):
    issues = []
    for i, row in enumerate(rows):
        did = row.get("id", "")
        if did and did not in ssot:
            issues.append((ERROR, line_map[i], f"id 越界（不在 SSOT 白名单内）: {did}"))
    return issues


def check_coverage(rows, ssot):
    issues = []
    present = {row.get("id", "") for row in rows}
    missing = [did for did in ssot if did not in present]
    if missing:
        issues.append(
            (ERROR, None, f"缺少 {len(missing)} 个领域: {', '.join(sorted(missing))}")
        )
    return issues


def check_frozen_numbers(rows, line_map, ssot):
    issues = []
    for i, row in enumerate(rows):
        did = row.get("id", "")
        if did not in ssot:
            continue
        for field in FROZEN_NUMERIC_FIELDS:
            expected = str(ssot[did].get(field, "")).strip()
            actual = row.get(field, "")
            if actual != expected:
                issues.append(
                    (
                        ERROR,
                        line_map[i],
                        f"{did}.{field}: SSOT={expected or '空'} 实际={actual or '空'}",
                    )
                )
    return issues


def check_gardner_enum(rows, line_map):
    issues = []
    for i, row in enumerate(rows):
        raw = row.get("gardner_intelligence", "")
        if not raw:
            continue  # 空值交给检查 10
        for value in raw.split(GARDNER_SEPARATOR):
            value = value.strip()
            if not value:
                issues.append(
                    (ERROR, line_map[i], f"{row.get('id', '') or '空 id'}.gardner_intelligence: 存在空的分隔项: {raw!r}")
                )
                continue
            if value not in GARDNER_ENUM:
                issues.append(
                    (
                        ERROR,
                        line_map[i],
                        f"{row.get('id', '') or '空 id'}.gardner_intelligence: 非法枚举值 '{value}'（合法: {', '.join(GARDNER_ENUM)}）",
                    )
                )
    return issues


def check_numeric_fields(rows, line_map):
    issues = []
    for i, row in enumerate(rows):
        did = row.get("id", "") or "空 id"
        for field in NUMERIC_INT_FIELDS:
            raw = row.get(field, "")
            if not raw:
                continue  # 空值交给检查 10
            try:
                value = int(raw)
            except ValueError:
                issues.append((ERROR, line_map[i], f"{did}.{field}: 不是合法整数: {raw!r}"))
                continue
            if field == "pain_tolerance_required" and not (
                PAIN_TOLERANCE_MIN <= value <= PAIN_TOLERANCE_MAX
            ):
                issues.append(
                    (
                        ERROR,
                        line_map[i],
                        f"{did}.pain_tolerance_required: 超出区间 {PAIN_TOLERANCE_MIN}-{PAIN_TOLERANCE_MAX}: {value}",
                    )
                )
        for row_extra in (row.get("__extra__"),):
            if row_extra:
                issues.append((WARN, line_map[i], f"{did}: 字段数多于表头，多余内容: {row_extra}"))
    return issues


def check_description(rows, line_map):
    issues = []
    for i, row in enumerate(rows):
        did = row.get("id", "") or "空 id"
        desc = row.get("description", "")
        if not desc:
            issues.append((ERROR, line_map[i], f"{did}.description 为空"))
            continue
        length = len(desc)
        if length > DESCRIPTION_MAX_LEN:
            issues.append(
                (
                    ERROR,
                    line_map[i],
                    f"{did}.description 过长: {length} 字（上限 {DESCRIPTION_MAX_LEN}）",
                )
            )
    return issues


def check_judgemental(rows, line_map):
    issues = []
    for i, row in enumerate(rows):
        did = row.get("id", "") or "空 id"
        for field in DESCRIPTIVE_FIELDS:
            text = row.get(field, "")
            if not text:
                continue
            for pattern, tag in JUDGEMENTAL_COMPILED:
                hit = pattern.search(text)
                if hit:
                    issues.append(
                        (
                            ERROR,
                            line_map[i],
                            f"{did}.{field}: 判定性语言（{tag}）命中 '{hit.group(0)}'",
                        )
                    )
    return issues


def check_required_empty(rows, line_map):
    issues = []
    for i, row in enumerate(rows):
        did = row.get("id", "") or "空 id"
        empty = [f for f in REQUIRED_FIELDS if not row.get(f, "")]
        if empty:
            issues.append((WARN, line_map[i], f"{did}: 必填列为空: {', '.join(empty)}"))
    return issues


def run_checks(header, rows, line_map, ssot):
    """返回 {check_id: [issue, ...]}，issue = (level, line, message)。"""
    results = OrderedDict()
    results["header"] = check_header(header)
    if header != DOMAIN_COLUMNS:
        # 表头都不对，后续逐字段检查会以大量误报收场：仍继续但只跑与列无关的检查
        for key in CHECKS:
            if key != "header":
                results.setdefault(key, [])
        results["id_unique"] = check_id_unique(rows, line_map)
        results["id_whitelist"] = check_id_whitelist(rows, line_map, ssot)
        results["coverage"] = check_coverage(rows, ssot)
        return results
    results["id_unique"] = check_id_unique(rows, line_map)
    results["id_whitelist"] = check_id_whitelist(rows, line_map, ssot)
    results["coverage"] = check_coverage(rows, ssot)
    results["frozen_numbers"] = check_frozen_numbers(rows, line_map, ssot)
    results["gardner_enum"] = check_gardner_enum(rows, line_map)
    results["numeric_fields"] = check_numeric_fields(rows, line_map)
    results["description"] = check_description(rows, line_map)
    results["judgemental"] = check_judgemental(rows, line_map)
    results["required_empty"] = check_required_empty(rows, line_map)
    return results


# --------------------------------------------------------------------------- #
# 输出
# --------------------------------------------------------------------------- #
def display_width(text):
    return sum(2 if ord(ch) > 127 else 1 for ch in text)


def pad_to(text, width):
    return text + " " * max(0, width - display_width(text))


def render_text_report(input_path, row_count, results):
    lines = []
    lines.append("=" * 62)
    lines.append(f"领域库校验报告    输入: {input_path}")
    lines.append(f"数据行数: {row_count}    SSOT 校验码: {SSOT_CHECKSUM}")
    lines.append("=" * 62)

    total_errors = total_warnings = 0
    for key, name in CHECKS.items():
        issues = results.get(key, [])
        errors = sum(1 for it in issues if it[0] == ERROR)
        warnings = sum(1 for it in issues if it[0] == WARN)
        total_errors += errors
        total_warnings += warnings
        flag = "FAIL" if (errors or warnings) else "PASS"
        lines.append(
            f"[{flag}] {pad_to(name, 20)}错误 {errors} / 警告 {warnings}"
        )
        for level, lineno, message in issues:
            mark = "✗" if level == ERROR else "!"
            where = f"第 {lineno} 行" if lineno else "文件级"
            lines.append(f"  {mark} {where} {message}")
    lines.append("-" * 62)
    lines.append(f"合计：错误 {total_errors} / 警告 {total_warnings}")
    return "\n".join(lines), total_errors, total_warnings


def build_json_report(ssot_path, reports, totals, generated_at):
    return {
        "task_id": TASK_ID,
        "spec_version": SPEC_VERSION,
        "ssot_checksum": SSOT_CHECKSUM,
        "generated_at": generated_at,
        "ssot_file": str(ssot_path),
        "summary": {"errors": totals[0], "warnings": totals[1]},
        "reports": reports,
    }


def collect_input_files(inputs):
    files = []
    for item in inputs:
        path = Path(item)
        if path.is_dir():
            files.extend(sorted(path.rglob("*.csv")))
        elif path.is_file():
            files.append(path)
        else:
            raise SystemExit(f"[ERROR] 输入路径不存在: {path}")
    if not files:
        raise SystemExit("[ERROR] 输入路径下没有找到任何 .csv 文件")
    return files


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="validate_domains.py",
        description="Tilt 领域库校验脚本（H01）：校验 C01 产出的 domains.csv 是否符合冻结契约",
    )
    parser.add_argument("--ssot", required=True, help="SSOT 白名单 CSV 路径（7 列）")
    parser.add_argument(
        "--input",
        required=True,
        action="append",
        help="待校验的目录或 CSV 文件，可多次指定",
    )
    parser.add_argument("--json", dest="json_out", default=None, help="输出机器可读报告路径")
    args = parser.parse_args(argv)

    ssot_path = Path(args.ssot)
    if not ssot_path.is_file():
        raise SystemExit(f"[ERROR] SSOT 文件不存在: {ssot_path}")
    ssot = load_ssot(ssot_path)

    files = collect_input_files(args.input)

    total_errors = total_warnings = 0
    json_reports = []
    text_blocks = []
    for path in files:
        header, rows, line_map = read_table(path)
        if not header:
            text_blocks.append(f"领域库校验报告    输入: {path}\n[FAIL] 文件为空或只有注释块")
            total_errors += 1
            json_reports.append(
                {"input": str(path), "row_count": 0, "summary": {"errors": 1, "warnings": 0}, "checks": []}
            )
            continue
        results = run_checks(header, rows, line_map, ssot)
        text, errors, warnings = render_text_report(path, len(rows), results)
        text_blocks.append(text)
        total_errors += errors
        total_warnings += warnings
        json_reports.append(
            {
                "input": str(path),
                "row_count": len(rows),
                "summary": {"errors": errors, "warnings": warnings},
                "checks": [
                    {
                        "check": key,
                        "name": CHECKS[key],
                        "errors": sum(1 for it in results.get(key, []) if it[0] == ERROR),
                        "warnings": sum(1 for it in results.get(key, []) if it[0] == WARN),
                        "issues": [
                            {"level": it[0], "line": it[1], "message": it[2]}
                            for it in results.get(key, [])
                        ],
                    }
                    for key in CHECKS
                ],
            }
        )

    print("\n\n".join(text_blocks))
    print("-" * 62)
    print(f"全部输入合计：错误 {total_errors} / 警告 {total_warnings}")

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if args.json_out:
        payload = build_json_report(
            ssot_path, json_reports, (total_errors, total_warnings), generated_at
        )
        out_path = Path(args.json_out)
        if out_path.parent and not out_path.parent.exists():
            out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"机器可读报告已写入: {out_path}")

    return 1 if total_errors else 0


if __name__ == "__main__":
    sys.exit(main())


# =========================================================================== #
# 使用示例
# --------------------------------------------------------------------------- #
# 1) 只看人类可读报告
#    $ python3 tools/validate_domains.py --ssot ssot/domains.csv --input out/domains.csv
#
#    预期输出（全部通过）：
#    ==============================================================
#    领域库校验报告    输入: out/domains.csv
#    ==============================================================
#    [PASS] 1 表头完整性与顺序  错误 0 / 警告 0
#    [PASS] 2 id 唯一性         错误 0 / 警告 0
#    ...
#    [PASS] 10 必填列非空       错误 0 / 警告 0
#    --------------------------------------------------------------
#    合计：错误 0 / 警告 0
#    全部输入合计：错误 0 / 警告 0
#    -> 退出码 0
#
# 2) 存在冻结数值被改动时（示例：go.startup_difficulty 被写成 4）
#    $ python3 tools/validate_domains.py --ssot ssot/domains.csv --input out/domains.csv
#
#    [PASS] 1 表头完整性与顺序  错误 0 / 警告 0
#    [FAIL] 5 冻结数值          错误 1 / 警告 0
#      ✗ 第 12 行 go.startup_difficulty: SSOT=2 实际=4
#    --------------------------------------------------------------
#    合计：错误 1 / 警告 0
#    -> 退出码 1（CI 可直接判定失败）
#
# 3) 一次校验多个输入 + 输出机器可读报告
#    $ python3 tools/validate_domains.py \
#        --ssot ssot/domains.csv \
#        --input out/domains.csv --input out/extra_domains.csv \
#        --json reports/validate_domains.json
#
#    终端按输入文件分段打印报告，并在末尾打印：
#    机器可读报告已写入: reports/validate_domains.json
#    -> 有 ERROR 时退出码 1，无 ERROR 时退出码 0
# =========================================================================== #
