#!/usr/bin/env python3
# === TILT-CONTRACT-MANIFEST ===
# task_id: H04
# spec_version: V1.3
# ssot_checksum: TL-SSOT-2026-09-20-A
# baseline_version: B1.0
# produced_by: 元宝 (Yuanbao)
# produced_at: 2026-09-21
# batch: all
# output_files:
#   - consistency_stats.py   (rows: n/a)
# unverified_count: 0
# self_check:
#   frozen_ids_only: true
#   enum_from_spec: false
#   no_absolute_claims: true
#   no_new_concepts: true
#   spec_numbers_unchanged: true
# known_deviations:
#   - enum_from_spec=false：SSOT 3.3/3.4/3.6 未冻结"样本分档"枚举值，脚本默认使用 good/mid/bad
#     （可通过 --tiers 覆盖），未改动任何已冻结枚举。详见 model_eval_plan.md 备注。
# === END MANIFEST ===
"""Tilt H04 · 评分一致性与区分度统计脚本

用途：本机跑完模型打分后，用本脚本计算「一致性 / 区分度 / 防讨好 / 解析成功率 / 延迟 / 综合排名」。

输入：模型 × 样本 × 多次运行的分数 CSV（表头见 docs/model_eval_plan.md 第 5 节）
输出：默认输出人类可读报告到 stdout；加 --json 时把机器可读 JSON 输出到 stdout。

依赖：仅 Python 标准库（csv / statistics / argparse / collections / json / math / sys）
用法：python3 tools/consistency_stats.py --input scores.csv
      python3 tools/consistency_stats.py --input scores.csv --json > report.json
      python3 tools/consistency_stats.py --input scores.csv --json-out out/report.json
      python3 tools/consistency_stats.py --input scores.csv --by-evaluator-type
      python3 tools/consistency_stats.py --input scores.csv --sd-threshold 3 --latency-p95-threshold 3000
所有阈值均可通过命令行覆盖，详见 --help。
"""

import argparse
import csv
import json
import math
import statistics
import sys
import unicodedata
from collections import defaultdict

# ---------------------------------------------------------------------------
# 常量（仅用于数据清洗与展示，不含任何可调阈值）
# ---------------------------------------------------------------------------
REQUIRED_FIELDS = ("model", "sample_id", "sample_tier", "run_index")
SCORE_FIELD = "score"
LATENCY_FIELD = "latency_ms"
PARSE_FIELD = "parse_ok"
SCORE_MIN, SCORE_MAX = 0.0, 100.0
HIST_BINS = 10
DEFAULT_TIERS = "good,mid,bad"

TRUE_SET = ("1", "true", "yes", "y", "t", "ok", "okay")
FALSE_SET = ("0", "false", "no", "n", "f", "fail", "failed")


# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------
def parse_float(value):
    if value is None:
        return None
    value = str(value).strip()
    if value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def parse_bool(value):
    if value is None:
        return None
    value = str(value).strip().lower()
    if value in TRUE_SET:
        return True
    if value in FALSE_SET:
        return False
    return None


def percentile(values, pct):
    """线性插值分位数（等价于 numpy.percentile 默认 linear 口径）。"""
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    k = (len(ordered) - 1) * (pct / 100.0)
    floor_i = int(math.floor(k))
    ceil_i = int(math.ceil(k))
    if floor_i == ceil_i:
        return ordered[floor_i]
    return ordered[floor_i] + (ordered[ceil_i] - ordered[floor_i]) * (k - floor_i)


def safe_mean(values):
    return statistics.mean(values) if values else None


def cohens_d(group_a, group_b):
    """效应量：group_a 相对 group_b 的标准化差异（a 应为更好的档）。"""
    if len(group_a) < 2 or len(group_b) < 2:
        return None
    mean_a, mean_b = statistics.mean(group_a), statistics.mean(group_b)
    var_a, var_b = statistics.variance(group_a), statistics.variance(group_b)
    pooled = ((len(group_a) - 1) * var_a + (len(group_b) - 1) * var_b) / (
        len(group_a) + len(group_b) - 2
    )
    if pooled <= 0:
        return None
    return (mean_a - mean_b) / math.sqrt(pooled)


def lower_better_score(value, threshold):
    """value 越小越好：value=0 得 100 分，value=threshold 得 0 分，线性插值后截断到 [0,100]。"""
    if value is None or threshold is None or threshold <= 0:
        return 0.0
    return max(0.0, min(100.0, 100.0 * (1.0 - value / threshold)))


def higher_better_score(value, threshold):
    """value 越大越好：value=threshold 得 100 分，线性插值后截断到 [0,100]。"""
    if value is None or threshold is None or threshold <= 0:
        return 0.0
    return max(0.0, min(100.0, 100.0 * (value / threshold)))


def band_score(value, worst, ideal):
    """value 落在 [ideal, worst] 区间内线性给分：value<=ideal 得 100，value>=worst 得 0。"""
    if value is None or worst is None or ideal is None or worst <= ideal:
        return 0.0
    return max(0.0, min(100.0, 100.0 * (worst - value) / (worst - ideal)))


def fmt(value, digits=2, dash="n/a"):
    if value is None:
        return dash
    return "{0:.{1}f}".format(value, digits)


# ---------------------------------------------------------------------------
# 读数据
# ---------------------------------------------------------------------------
def read_rows(path):
    """读取 CSV：自动跳过 BOM、跳过以 # 开头的 manifest 注释行。"""
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as handle:
            lines = [line for line in handle if not line.lstrip().startswith("#")]
    except OSError as exc:
        sys.exit("[错误] 无法读取输入文件 {0}: {1}".format(path, exc))

    if not lines:
        sys.exit("[错误] 输入文件 {0} 为空（或全部是注释行）".format(path))

    reader = csv.DictReader(lines)
    header = reader.fieldnames or []
    missing = [name for name in REQUIRED_FIELDS if name not in header]
    if missing:
        sys.exit(
            "[错误] 输入文件缺少必需列: {0}\n必需列: {1}\n实际表头: {2}".format(
                ", ".join(missing), ", ".join(REQUIRED_FIELDS), ", ".join(header)
            )
        )

    rows, invalid = [], []
    for index, raw in enumerate(reader, start=1):
        record = {
            "model": (raw.get("model") or "").strip(),
            "evaluator_type": (raw.get("evaluator_type") or "").strip(),
            "sample_id": (raw.get("sample_id") or "").strip(),
            "tier": (raw.get("sample_tier") or "").strip(),
            "run_index": (raw.get("run_index") or "").strip(),
            "score": parse_float(raw.get(SCORE_FIELD)),
            "latency_ms": parse_float(raw.get(LATENCY_FIELD)),
            "parse_ok": parse_bool(raw.get(PARSE_FIELD)),
        }
        if not record["model"] or not record["sample_id"]:
            invalid.append({"line": index, "reason": "model/sample_id 为空"})
            continue
        if record["score"] is not None and not (SCORE_MIN <= record["score"] <= SCORE_MAX):
            invalid.append(
                {"line": index, "reason": "score 越界({0})".format(record["score"])}
            )
            continue
        rows.append(record)
    return rows, invalid, list(header)


# ---------------------------------------------------------------------------
# 统计
# ---------------------------------------------------------------------------
def build_models(rows, group_by_type=False):
    """按统计单元聚合：默认按 model 聚合；group_by_type=True 时按 (model, evaluator_type) 聚合。"""
    units = defaultdict(lambda: {"samples": defaultdict(list)})
    for row in rows:
        if group_by_type:
            name = "{0}|{1}".format(row["model"], row["evaluator_type"] or "unknown")
        else:
            name = row["model"]
        bucket = units[name]
        key = (row["sample_id"], row["tier"])
        bucket["samples"][key].append(row)
    return units


def sample_stats(run_rows, sd_threshold, range_threshold, cv_threshold):
    scores = [r["score"] for r in run_rows if r["score"] is not None]
    n = len(scores)
    result = {
        "sample_id": run_rows[0]["sample_id"],
        "tier": run_rows[0]["tier"],
        "evaluator_type": run_rows[0]["evaluator_type"],
        "n_runs": len(run_rows),
        "n_scores": n,
        "mean": safe_mean(scores),
        "sd": None,
        "range": None,
        "cv": None,
        "consistent": None,
        "reasons": [],
    }
    if n == 0:
        result["reasons"].append("无有效分数")
        return result
    if n >= 2:
        result["sd"] = statistics.stdev(scores)
        result["range"] = max(scores) - min(scores)
        result["cv"] = result["sd"] / result["mean"] if result["mean"] else None
        reasons = []
        if result["sd"] > sd_threshold:
            reasons.append("sd={0} > {1}".format(fmt(result["sd"]), fmt(sd_threshold)))
        if result["range"] > range_threshold:
            reasons.append(
                "range={0} > {1}".format(fmt(result["range"]), fmt(range_threshold))
            )
        if result["cv"] is not None and result["cv"] > cv_threshold:
            reasons.append("cv={0} > {1}".format(fmt(result["cv"]), fmt(cv_threshold)))
        result["reasons"] = reasons
        result["consistent"] = not reasons
    else:
        result["reasons"].append("仅 1 次有效运行，无法计算一致性")
        result["consistent"] = None
    return result


def histogram(scores):
    bins = [0] * HIST_BINS
    for value in scores:
        idx = int(value // 10)
        if idx < 0:
            idx = 0
        elif idx >= HIST_BINS:
            idx = HIST_BINS - 1
        bins[idx] += 1
    return [
        {
            "bin": "{0}-{1}".format(i * 10, (i + 1) * 10),
            "count": bins[i],
        }
        for i in range(HIST_BINS)
    ]


def analyse_model(name, model_name, evaluator_type, payload, tiers, thresholds, weights):
    samples = [sample_stats(v, thresholds["sd"], thresholds["range"], thresholds["cv"])
               for v in payload["samples"].values()]
    samples.sort(key=lambda s: (s["tier"], s["sample_id"]))

    scored_samples = [s for s in samples if s["n_scores"] >= 2]
    consistency_pass = [s for s in scored_samples if s["consistent"]]
    consistency = {
        "n_samples": len(samples),
        "n_samples_scored": len(scored_samples),
        "pass_rate": (len(consistency_pass) / len(scored_samples)) if scored_samples else None,
        "mean_sd": safe_mean([s["sd"] for s in scored_samples]),
        "max_sd": max([s["sd"] for s in scored_samples]) if scored_samples else None,
        "mean_range": safe_mean([s["range"] for s in scored_samples]),
        "mean_cv": safe_mean([s["cv"] for s in scored_samples if s["cv"] is not None]),
        "failed_samples": [s for s in scored_samples if s["consistent"] is False],
    }

    # ---- 区分度：按档聚合所有有效 run 级分数 ----
    tier_scores = defaultdict(list)
    for run_rows in payload["samples"].values():
        tier = run_rows[0]["tier"]
        tier_scores[tier].extend([r["score"] for r in run_rows if r["score"] is not None])

    present_tiers = [t for t in tiers if tier_scores.get(t)]
    missing_tiers = [t for t in tiers if not tier_scores.get(t)]
    tier_means = {t: safe_mean(tier_scores[t]) for t in present_tiers}
    gaps, gap_pairs = [], []
    for better, worse in zip(present_tiers, present_tiers[1:]):
        gap = tier_means[better] - tier_means[worse]
        gaps.append(gap)
        gap_pairs.append({"pair": "{0}-{1}".format(better, worse), "gap": gap})
    best_tier = present_tiers[0] if present_tiers else None
    worst_tier = present_tiers[-1] if present_tiers else None
    d_value = (
        cohens_d(tier_scores[best_tier], tier_scores[worst_tier])
        if best_tier and worst_tier and best_tier != worst_tier
        else None
    )
    discrimination = {
        "tiers_present": present_tiers,
        "tiers_missing": missing_tiers,
        "tier_means": tier_means,
        "tier_counts": {t: len(tier_scores[t]) for t in present_tiers},
        "gaps": gap_pairs,
        "min_gap": min(gaps) if gaps else None,
        "effect_size_best_worst": d_value,
        "gap_ok": (min(gaps) >= thresholds["tier_gap"]) if gaps else None,
        "effect_ok": (d_value is not None and d_value >= thresholds["effect_size"]),
    }

    # ---- 防讨好：整体分数分布 ----
    all_scores = [s for values in tier_scores.values() for s in values]
    distribution = {
        "n": len(all_scores),
        "min": min(all_scores) if all_scores else None,
        "p25": percentile(all_scores, 25),
        "median": percentile(all_scores, 50),
        "p75": percentile(all_scores, 75),
        "max": max(all_scores) if all_scores else None,
        "histogram": histogram(all_scores),
    }
    sycophancy_flag = (
        distribution["min"] is not None and distribution["min"] > thresholds["min_score"]
    )
    worst_mean = tier_means.get(worst_tier) if worst_tier else None
    anti_sycophancy = {
        "distribution": distribution,
        "worst_tier": worst_tier,
        "worst_tier_mean": worst_mean,
        "suspected_all_high": sycophancy_flag,
        "note": (
            "最低分 {0} 高于告警线 {1}，疑似一律高分（区分不出差产出）".format(
                fmt(distribution["min"]), fmt(thresholds["min_score"])
            )
            if sycophancy_flag
            else ""
        ),
    }

    # ---- 解析成功率 ----
    all_runs = [r for run_rows in payload["samples"].values() for r in run_rows]
    parse_values = [r["parse_ok"] for r in all_runs if r["parse_ok"] is not None]
    parse_ok_count = sum(1 for v in parse_values if v)
    parse_rate = (parse_ok_count / len(parse_values)) if parse_values else None
    parse_failed_samples = sorted(
        {r["sample_id"] for r in all_runs if r["parse_ok"] is False}
    )
    parse = {
        "n_runs_total": len(all_runs),
        "n_runs_with_flag": len(parse_values),
        "n_parse_ok": parse_ok_count,
        "n_parse_fail": len(parse_values) - parse_ok_count,
        "parse_rate": parse_rate,
        "fail_rate": (1 - parse_rate) if parse_rate is not None else None,
        "failed_sample_ids": parse_failed_samples,
        "ok": (parse_rate is not None and parse_rate >= thresholds["parse_rate"]),
    }

    # ---- 延迟 ----
    latencies = [r["latency_ms"] for r in all_runs if r["latency_ms"] is not None]
    latency = {
        "n": len(latencies),
        "p50": percentile(latencies, 50),
        "p95": percentile(latencies, 95),
        "p99": percentile(latencies, 99),
        "mean": safe_mean(latencies),
        "ok": (
            percentile(latencies, 95) is not None
            and percentile(latencies, 95) <= thresholds["latency_p95"]
        ),
    }

    # ---- 一票否决 ----
    veto_reasons = []
    if parse_rate is not None and parse_rate < thresholds["veto_parse_rate"]:
        veto_reasons.append(
            "解析成功率 {0} 低于否决线 {1}".format(fmt(parse_rate), fmt(thresholds["veto_parse_rate"]))
        )
    if discrimination["min_gap"] is not None and discrimination["min_gap"] <= 0:
        veto_reasons.append("出现档间倒挂或档均分无差异（min_gap<=0）")
    if (
        consistency["pass_rate"] is not None
        and consistency["pass_rate"] < thresholds["veto_consistency_pass"]
    ):
        veto_reasons.append(
            "一致性达标率 {0} 低于否决线 {1}".format(
                fmt(consistency["pass_rate"]), fmt(thresholds["veto_consistency_pass"])
            )
        )
    if sycophancy_flag:
        veto_reasons.append(anti_sycophancy["note"])

    # ---- 综合评分 ----
    sub_scores = {
        "consistency": lower_better_score(consistency["mean_sd"], thresholds["sd"]),
        "discrimination": higher_better_score(
            discrimination["min_gap"], thresholds["tier_gap"]
        ),
        "anti_sycophancy": band_score(
            worst_mean, thresholds["bad_mean_max"], thresholds["bad_mean_ideal"]
        ),
        "parse": (parse_rate * 100.0) if parse_rate is not None else 0.0,
        "latency": lower_better_score(latency["p95"], thresholds["latency_p95"]),
    }
    total = sum(sub_scores[key] * weights[key] for key in weights)
    scores = dict(sub_scores)
    scores["total"] = total

    return {
        "unit": name,
        "model": model_name,
        "evaluator_type": evaluator_type,
        "consistency": consistency,
        "discrimination": discrimination,
        "anti_sycophancy": anti_sycophancy,
        "parse": parse,
        "latency": latency,
        "scores": scores,
        "veto": {"vetoed": bool(veto_reasons), "reasons": veto_reasons},
        "samples": samples,
    }


# ---------------------------------------------------------------------------
# 报告
# ---------------------------------------------------------------------------
def display_width(text):
    """终端显示宽度：中文等全角字符按 2 计，保证表格对齐。"""
    width = 0
    for char in str(text):
        width += 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
    return width


def render_table(headers, rows, aligns=None):
    widths = [display_width(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], display_width(cell))
    aligns = aligns or ["<"] * len(headers)

    def line(cells):
        parts = []
        for i, cell in enumerate(cells):
            text = str(cell)
            pad = widths[i] - display_width(text)
            if aligns[i] == ">":
                parts.append(" " * pad + text)
            else:
                parts.append(text + " " * pad)
        return "  ".join(parts)

    out = [line(headers), "  ".join("-" * w for w in widths)]
    for row in rows:
        out.append(line(row))
    return "\n".join(out)


def render_report(results, meta):
    lines = []
    lines.append("=== Tilt 评分一致性统计报告 ===")
    lines.append("输入文件: {0}".format(meta["input"]))
    lines.append(
        "有效数据行: {0}    无效行: {1}    模型数: {2}    样本数: {3}".format(
            meta["n_rows"], meta["n_invalid"], meta["n_models"], meta["n_samples"]
        )
    )
    lines.append("样本分档顺序(好→差): {0}".format(" > ".join(meta["tiers"])))
    lines.append(
        "统计单元: {0}".format("model × evaluator_type" if meta["group_by_evaluator_type"] else "model")
    )
    lines.append(
        "阈值: sd<={sd}  range<={range}  cv<={cv}  min_tier_gap>={tier_gap}  effect_size>={effect_size}".format(
            **meta["thresholds"]
        )
    )
    lines.append(
        "      min_score告警线={min_score}  worst_tier_mean(ideal<={ideal}, 上限={bmax})".format(
            min_score=meta["thresholds"]["min_score"],
            ideal=meta["thresholds"]["bad_mean_ideal"],
            bmax=meta["thresholds"]["bad_mean_max"],
        )
    )
    lines.append(
        "      parse_rate>={pr}  latency_p95<={lp}ms  否决线: parse<{vp} 一致性达标率<{vc}".format(
            pr=meta["thresholds"]["parse_rate"],
            lp=meta["thresholds"]["latency_p95"],
            vp=meta["thresholds"]["veto_parse_rate"],
            vc=meta["thresholds"]["veto_consistency_pass"],
        )
    )
    lines.append(
        "权重: " + "  ".join("{0}={1}".format(k, v) for k, v in meta["weights"].items())
    )
    lines.append("")

    # 1 一致性
    lines.append("[1] 一致性（同一 model+sample 的多次运行波动）")
    rows = []
    for res in results:
        c = res["consistency"]
        rows.append(
            [
                res["unit"],
                c["n_samples"],
                fmt(c["mean_sd"]),
                fmt(c["max_sd"]),
                fmt(c["mean_range"]),
                fmt(c["mean_cv"]),
                "{0}%".format(fmt((c["pass_rate"] or 0) * 100, 1)),
                "PASS" if (c["pass_rate"] or 0) >= 1.0 else "CHECK",
            ]
        )
    lines.append(
        render_table(
            ["model", "samples", "mean_sd", "max_sd", "mean_range", "mean_cv", "达标率", "结论"],
            rows,
            ["<", ">", ">", ">", ">", ">", ">", "<"],
        )
    )
    detail = []
    for res in results:
        for s in res["consistency"]["failed_samples"]:
            detail.append(
                "  - {0} / {1} ({2}): {3}".format(
                    res["unit"], s["sample_id"], s["tier"], "; ".join(s["reasons"])
                )
            )
    if detail:
        lines.append("未达标样本明细:")
        lines.extend(detail)
    else:
        lines.append("未达标样本明细: 无")
    lines.append("")

    # 2 区分度
    lines.append("[2] 区分度（好/中/差三档是否被拉开）")
    tier_headers = ["model"] + list(meta["tiers"]) + ["min_gap", "effect_d", "结论"]
    rows = []
    for res in results:
        d = res["discrimination"]
        row = [res["unit"]]
        for tier in meta["tiers"]:
            row.append(fmt(d["tier_means"].get(tier)))
        row.append(fmt(d["min_gap"]))
        row.append(fmt(d["effect_size_best_worst"]))
        row.append(
            "PASS"
            if (d["gap_ok"] and d["effect_ok"])
            else ("CHECK" if d["gap_ok"] or d["effect_ok"] else "FAIL")
        )
        rows.append(row)
    lines.append(render_table(tier_headers, rows, ["<"] + [">"] * (len(tier_headers) - 1)))
    for res in results:
        if res["discrimination"]["tiers_missing"]:
            lines.append(
                "  - {0}: 缺少分档 {1}，档间差值仅按已有分档计算".format(
                    res["unit"], "/".join(res["discrimination"]["tiers_missing"])
                )
            )
    lines.append("")

    # 3 防讨好
    lines.append("[3] 防讨好（分数分布是否贴着高分区）")
    rows = []
    for res in results:
        dist = res["anti_sycophancy"]["distribution"]
        rows.append(
            [
                res["unit"],
                dist["n"],
                fmt(dist["min"]),
                fmt(dist["p25"]),
                fmt(dist["median"]),
                fmt(dist["p75"]),
                fmt(dist["max"]),
                fmt(res["anti_sycophancy"]["worst_tier_mean"]),
                "告警" if res["anti_sycophancy"]["suspected_all_high"] else "ok",
            ]
        )
    lines.append(
        render_table(
            ["model", "n", "min", "p25", "median", "p75", "max", "worst档均值", "结论"],
            rows,
            ["<", ">", ">", ">", ">", ">", ">", ">", "<"],
        )
    )
    for res in results:
        bins = " ".join(
            "{0}:{1}".format(b["bin"], b["count"])
            for b in res["anti_sycophancy"]["distribution"]["histogram"]
            if b["count"]
        )
        lines.append("  - {0} 直方图: {1}".format(res["unit"], bins))
    lines.append("")

    # 4 解析成功率
    lines.append("[4] 解析成功率（JSON schema 遵循情况）")
    rows = []
    for res in results:
        p = res["parse"]
        rows.append(
            [
                res["unit"],
                p["n_runs_total"],
                p["n_parse_ok"],
                p["n_parse_fail"],
                "{0}%".format(fmt((p["parse_rate"] or 0) * 100, 1)),
                "PASS" if p["ok"] else "FAIL",
            ]
        )
    lines.append(
        render_table(
            ["model", "runs", "parse_ok", "parse_fail", "成功率", "结论"],
            rows,
            ["<", ">", ">", ">", ">", "<"],
        )
    )
    for res in results:
        if res["parse"]["failed_sample_ids"]:
            lines.append(
                "  - {0} 解析失败样本: {1}".format(
                    res["unit"], ", ".join(res["parse"]["failed_sample_ids"])
                )
            )
    lines.append("")

    # 5 延迟
    lines.append("[5] 延迟（ms）")
    rows = []
    for res in results:
        lat = res["latency"]
        rows.append(
            [
                res["unit"],
                lat["n"],
                fmt(lat["p50"], 0),
                fmt(lat["p95"], 0),
                fmt(lat["p99"], 0),
                "PASS" if lat["ok"] else "FAIL",
            ]
        )
    lines.append(
        render_table(
            ["model", "n", "p50", "p95", "p99", "结论"],
            rows,
            ["<", ">", ">", ">", ">", "<"],
        )
    )
    lines.append("")

    # 6 综合排名
    lines.append("[6] 综合排名（加权总分，带一票否决标记）")
    ranking = build_ranking(results)
    rows = []
    for item in ranking:
        res = item["result"]
        rows.append(
            [
                item["rank"],
                res["unit"],
                fmt(res["scores"]["consistency"], 1),
                fmt(res["scores"]["discrimination"], 1),
                fmt(res["scores"]["anti_sycophancy"], 1),
                fmt(res["scores"]["parse"], 1),
                fmt(res["scores"]["latency"], 1),
                fmt(res["scores"]["total"], 1),
                "否决" if res["veto"]["vetoed"] else "可进入人工复核",
            ]
        )
    lines.append(
        render_table(
            ["rank", "model", "一致性", "区分度", "防讨好", "解析", "延迟", "总分", "状态"],
            rows,
            [">", "<", ">", ">", ">", ">", ">", ">", "<"],
        )
    )
    for item in ranking:
        for reason in item["result"]["veto"]["reasons"]:
            lines.append("  - {0} 否决原因: {1}".format(item["result"]["model"], reason))
    lines.append("")
    lines.append("说明: 总分仅用于排序，不替代人工抽检；被否决的模型不应进入 Tilt Layer 3 评估器。")
    return "\n".join(lines)


def build_ranking(results):
    ordered = sorted(results, key=lambda r: (-r["scores"]["total"], r["unit"]))
    return [{"rank": i + 1, "unit": r["unit"], "result": r} for i, r in enumerate(ordered)]


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def build_arg_parser():
    parser = argparse.ArgumentParser(
        prog="consistency_stats.py",
        description="Tilt H04 · 评分一致性与区分度统计（仅依赖标准库）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--input", required=True, help="打分结果 CSV 路径")
    parser.add_argument(
        "--json",
        action="store_true",
        help="把机器可读 JSON 输出到 stdout（此时不再打印人类可读报告）",
    )
    parser.add_argument("--json-out", default=None, help="把机器可读 JSON 写入指定路径")
    parser.add_argument(
        "--by-evaluator-type",
        action="store_true",
        help="按 model × evaluator_type 分组统计（用于检查模型在不同评估器类型上的稳定性）",
    )
    parser.add_argument(
        "--tiers",
        default=DEFAULT_TIERS,
        help="样本分档枚举，英文逗号分隔，按'好→差'顺序排列",
    )

    group = parser.add_argument_group("一致性阈值")
    group.add_argument("--sd-threshold", type=float, default=5.0, help="单次 (model,sample) 组内标准差上限")
    group.add_argument("--range-threshold", type=float, default=10.0, help="组内极差上限")
    group.add_argument("--cv-threshold", type=float, default=0.10, help="组内变异系数上限")

    group = parser.add_argument_group("区分度阈值")
    group.add_argument("--tier-gap-threshold", type=float, default=8.0, help="相邻档均值差下限")
    group.add_argument("--effect-size-threshold", type=float, default=0.80, help="最好档/最差档 Cohen's d 下限")

    group = parser.add_argument_group("防讨好阈值")
    group.add_argument("--min-score-threshold", type=float, default=70.0, help="最低分告警线：最低分高于此值即告警")
    group.add_argument("--bad-mean-max", type=float, default=70.0, help="最差档均值上限（等于此值记 0 分）")
    group.add_argument("--bad-mean-ideal", type=float, default=35.0, help="最差档均值理想值（低于此值记 100 分）")

    group = parser.add_argument_group("工程阈值与否决线")
    group.add_argument("--parse-rate-threshold", type=float, default=0.95, help="解析成功率合格线")
    group.add_argument("--latency-p95-threshold", type=float, default=5000.0, help="P95 延迟上限(ms)")
    group.add_argument("--veto-parse-rate", type=float, default=0.90, help="一票否决：解析成功率下限")
    group.add_argument("--veto-consistency-pass", type=float, default=0.80, help="一票否决：一致性达标率下限")

    group = parser.add_argument_group("综合排名权重（之和须为 1.0）")
    group.add_argument("--weight-consistency", type=float, default=0.30)
    group.add_argument("--weight-discrimination", type=float, default=0.30)
    group.add_argument("--weight-anti-sycophancy", type=float, default=0.15)
    group.add_argument("--weight-parse", type=float, default=0.15)
    group.add_argument("--weight-latency", type=float, default=0.10)
    return parser


def main(argv=None):
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    weights = {
        "consistency": args.weight_consistency,
        "discrimination": args.weight_discrimination,
        "anti_sycophancy": args.weight_anti_sycophancy,
        "parse": args.weight_parse,
        "latency": args.weight_latency,
    }
    weight_sum = sum(weights.values())
    if abs(weight_sum - 1.0) > 1e-6:
        parser.error(
            "权重之和必须为 1.0，当前为 {0}（{1}）".format(
                weight_sum, "  ".join("{0}={1}".format(k, v) for k, v in weights.items())
            )
        )
    if args.bad_mean_max <= args.bad_mean_ideal:
        parser.error("--bad-mean-max 必须大于 --bad-mean-ideal")

    tiers = [t.strip() for t in args.tiers.split(",") if t.strip()]
    if len(tiers) < 2:
        parser.error("--tiers 至少需要 2 个分档")

    thresholds = {
        "sd": args.sd_threshold,
        "range": args.range_threshold,
        "cv": args.cv_threshold,
        "tier_gap": args.tier_gap_threshold,
        "effect_size": args.effect_size_threshold,
        "min_score": args.min_score_threshold,
        "bad_mean_max": args.bad_mean_max,
        "bad_mean_ideal": args.bad_mean_ideal,
        "parse_rate": args.parse_rate_threshold,
        "latency_p95": args.latency_p95_threshold,
        "veto_parse_rate": args.veto_parse_rate,
        "veto_consistency_pass": args.veto_consistency_pass,
    }

    rows, invalid, header = read_rows(args.input)
    if not rows:
        sys.exit("[错误] 输入文件 {0} 中没有有效数据行".format(args.input))

    units = build_models(rows, args.by_evaluator_type)
    results = []
    for name in sorted(units):
        payload = units[name]
        first_row = next(iter(payload["samples"].values()))[0]
        results.append(
            analyse_model(
                name,
                first_row["model"],
                first_row["evaluator_type"],
                payload,
                tiers,
                thresholds,
                weights,
            )
        )

    meta = {
        "input": args.input,
        "n_rows": len(rows),
        "n_invalid": len(invalid),
        "n_models": len(results),
        "n_samples": sum(len(u["samples"]) for u in units.values()),
        "group_by_evaluator_type": bool(args.by_evaluator_type),
        "tiers": tiers,
        "thresholds": thresholds,
        "weights": weights,
        "header": header,
    }

    payload = {
        "meta": meta,
        "invalid_rows": invalid,
        "ranking": [
            {
                "rank": item["rank"],
                "unit": item["unit"],
                "total": item["result"]["scores"]["total"],
                "vetoed": item["result"]["veto"]["vetoed"],
                "veto_reasons": item["result"]["veto"]["reasons"],
            }
            for item in build_ranking(results)
        ],
        "models": {
            res["unit"]: {k: v for k, v in res.items() if k != "model"} for res in results
        },
    }

    if args.json_out:
        try:
            with open(args.json_out, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
        except OSError as exc:
            sys.exit("[错误] 无法写入 JSON 文件 {0}: {1}".format(args.json_out, exc))
        print(render_report(results, meta))
        print("\nJSON 已写入: {0}".format(args.json_out))
        return 0

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    print(render_report(results, meta))
    return 0


if __name__ == "__main__":
    sys.exit(main())
