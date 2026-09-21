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
#   - tools/check_links.py   (rows: 439)
# unverified_count: 0
# self_check:
#   frozen_ids_only: true
#   enum_from_spec: true
#   no_absolute_claims: true
#   no_new_concepts: true
#   spec_numbers_unchanged: true
# known_deviations: []
# === END MANIFEST ===
"""Tilt · H01 · 资源链接存活检查脚本

用途：批量检查 C04 产出的 resources.csv 里的链接是否还活着。

重要背景：resources.csv 的 url_or_location 列绝大多数不是 URL，而是"平台名 · 入口位置"
这类文字描述（契约刻意要求，防编造），同时 40%-60% 条目标了「待核验」。
因此本脚本**不**把所有值当 URL 请求，而是：
  1. 用正则识别真正的 URL（https?://...）
  2. 只对这些 URL 做并发存活检查（urllib.request，HEAD 优先、405/403 回退 GET）
  3. 非 URL 的文字条目只计数，单列为「待人工核」
  4. 输出五类结果：存活 / 失效 / 重定向 / 超时 / 待人工核

依赖：仅 Python 3.10 标准库。
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import socket
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

TASK_ID = "H01"
SPEC_VERSION = "V1.3"
SSOT_CHECKSUM = "TL-SSOT-2026-09-20-A"

RESOURCE_COLUMNS = [
    "domain_id",
    "resource_type",
    "name",
    "url_or_location",
    "why_recommended",
    "source",
    "verify_status",
]

# 真正的 URL 识别：遇到空白、中英文标点、引号即结束
URL_RE = re.compile(r"https?://[^\s<>\"'`)）,，、；;。】]+", re.IGNORECASE)

USER_AGENT = "Mozilla/5.0 (compatible; TiltLinkChecker/1.0; +https://tilt.local)"
READ_BYTES = 2048  # GET 回退时只读少量字节，避免拖垮整批检查

STATUS_ALIVE = "alive"
STATUS_DEAD = "dead"
STATUS_REDIRECT = "redirect"
STATUS_TIMEOUT = "timeout"
STATUS_MANUAL = "manual_review"

STATUS_ORDER = [STATUS_ALIVE, STATUS_DEAD, STATUS_REDIRECT, STATUS_TIMEOUT, STATUS_MANUAL]
STATUS_LABEL = {
    STATUS_ALIVE: "存活",
    STATUS_DEAD: "失效",
    STATUS_REDIRECT: "重定向",
    STATUS_TIMEOUT: "超时",
    STATUS_MANUAL: "待人工核",
}
STATUS_MARK = {
    STATUS_ALIVE: "✓",
    STATUS_DEAD: "✗",
    STATUS_REDIRECT: "→",
    STATUS_TIMEOUT: "⏱",
    STATUS_MANUAL: "?",
}


# --------------------------------------------------------------------------- #
# 解析
# --------------------------------------------------------------------------- #
def read_resources(path: Path):
    """同样处理 UTF-8 BOM 与顶部 manifest 注释块；返回 (header, rows, line_map)。"""
    try:
        raw_lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except OSError as exc:
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
        rows.append(clean)
        line_map.append(kept_line_no[idx] if idx < len(kept_line_no) else kept_line_no[-1])
    return header, rows, line_map


def extract_urls(text):
    return URL_RE.findall(text or "")


# --------------------------------------------------------------------------- #
# 单条 URL 检查（任何异常都必须被吞掉并归类，绝不让整脚本崩）
# --------------------------------------------------------------------------- #
def _open(method, url, timeout):
    request = urllib.request.Request(url, method=method, headers={"User-Agent": USER_AGENT})
    return urllib.request.urlopen(request, timeout=timeout)


def _classify_exception(exc):
    if isinstance(exc, socket.timeout):
        return STATUS_TIMEOUT, f"超时: {exc}"
    reason = getattr(exc, "reason", None)
    if isinstance(reason, socket.timeout) or "timed out" in str(reason).lower():
        return STATUS_TIMEOUT, f"超时: {reason}"
    return STATUS_DEAD, f"{type(exc).__name__}: {exc}"


def check_one_url(url, timeout):
    """返回 dict(status, http_status, final_url, error)。单个 URL 失败不影响整批。"""
    result = {"status": STATUS_DEAD, "http_status": None, "final_url": url, "error": ""}
    try:
        try:
            with _open("HEAD", url, timeout) as resp:
                code = resp.getcode()
                final_url = resp.geturl()
                result.update({"http_status": code, "final_url": final_url})
        except urllib.error.HTTPError as http_exc:
            code = http_exc.code
            # 部分站点不允许 HEAD，回退 GET 再判一次
            if code in (400, 403, 405, 406, 501):
                with _open("GET", url, timeout) as resp:
                    resp.read(READ_BYTES)
                    result.update(
                        {
                            "status": STATUS_ALIVE,
                            "http_status": resp.getcode(),
                            "final_url": resp.geturl(),
                        }
                    )
                    if resp.geturl().rstrip("/") != url.rstrip("/"):
                        result["status"] = STATUS_REDIRECT
                    return result
            result.update({"status": STATUS_DEAD, "http_status": code, "error": f"HTTP {code}"})
            return result
        except (urllib.error.URLError, socket.timeout, OSError) as exc:
            status, message = _classify_exception(exc)
            # HEAD 被拒/连接问题：尝试一次 GET 再定性
            try:
                with _open("GET", url, timeout) as resp:
                    resp.read(READ_BYTES)
                    result.update(
                        {
                            "status": STATUS_ALIVE,
                            "http_status": resp.getcode(),
                            "final_url": resp.geturl(),
                        }
                    )
                    if resp.geturl().rstrip("/") != url.rstrip("/"):
                        result["status"] = STATUS_REDIRECT
                    result["error"] = f"HEAD 失败后 GET 成功（{message}）"
                    return result
            except Exception:
                result.update({"status": status, "error": message})
                return result

        if 200 <= (code or 0) < 300:
            result["status"] = (
                STATUS_REDIRECT if final_url.rstrip("/") != url.rstrip("/") else STATUS_ALIVE
            )
        elif 300 <= (code or 0) < 400:
            result["status"] = STATUS_REDIRECT
        else:
            result["status"] = STATUS_DEAD
            result["error"] = f"HTTP {code}"
        return result
    except Exception as exc:  # 最后兜底：任何未预期异常都记成失败，绝不抛出
        status, message = _classify_exception(exc)
        result.update({"status": status, "error": message})
        return result


# --------------------------------------------------------------------------- #
# 批量检查
# --------------------------------------------------------------------------- #
def build_tasks(rows, line_map, path):
    """一个条目可能含 0~n 个 URL；无 URL 的条目整体记为待人工核。"""
    tasks, manual_items = [], []
    for i, row in enumerate(rows):
        location = row.get("url_or_location", "")
        urls = extract_urls(location)
        base = {
            "domain_id": row.get("domain_id", ""),
            "resource_type": row.get("resource_type", ""),
            "name": row.get("name", ""),
            "url_or_location": location,
            "verify_status": row.get("verify_status", ""),
            "line": line_map[i],
            "file": str(path),
        }
        if not urls:
            item = dict(base)
            item.update(
                {
                    "url": "",
                    "status": STATUS_MANUAL,
                    "http_status": None,
                    "final_url": "",
                    "error": "非 URL 文字描述，需人工核实",
                }
            )
            manual_items.append(item)
            continue
        for url in urls:
            task = dict(base)
            task["url"] = url
            tasks.append(task)
    return tasks, manual_items


def run_checks(tasks, concurrency, timeout):
    results = []
    if not tasks:
        return results
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        future_map = {pool.submit(check_one_url, t["url"], timeout): t for t in tasks}
        for future in as_completed(future_map):
            task = future_map[future]
            try:
                outcome = future.result()
            except Exception as exc:  # 理论上不会到这，仍然兜底
                outcome = {"status": STATUS_DEAD, "http_status": None, "final_url": task["url"], "error": str(exc)}
            item = dict(task)
            item.update(outcome)
            results.append(item)
    results.sort(key=lambda x: (x["line"], x["url"]))
    return results


# --------------------------------------------------------------------------- #
# 输出
# --------------------------------------------------------------------------- #
def item_line(item):
    head = f"{item['domain_id']} · {item['name']}" if item["domain_id"] or item["name"] else "（无名称条目）"
    where = f"第 {item['line']} 行"
    if item["status"] == STATUS_MANUAL:
        return f"  {STATUS_MARK[STATUS_MANUAL]} {where} {head} — {item['url_or_location']}"
    detail = item.get("http_status")
    detail_text = f"HTTP {detail}" if detail else (item.get("error") or "")
    if item["status"] == STATUS_REDIRECT and item.get("final_url") and item["final_url"] != item["url"]:
        detail_text = f"{detail_text} {item['url']} → {item['final_url']}".strip()
    else:
        detail_text = f"{detail_text} {item['url']}".strip()
    return f"  {STATUS_MARK[item['status']]} {where} {head} — {detail_text}"


def render_text_report(items, list_limit):
    counts = {status: 0 for status in STATUS_ORDER}
    buckets = {status: [] for status in STATUS_ORDER}
    for item in items:
        counts[item["status"]] += 1
        buckets[item["status"]].append(item)

    lines = []
    lines.append("=" * 62)
    lines.append(f"资源链接检查报告    条目总数: {len(items)}")
    lines.append(f"SSOT 校验码: {SSOT_CHECKSUM}")
    lines.append("=" * 62)
    for status in STATUS_ORDER:
        lines.append(f"[{STATUS_LABEL[status]}] {counts[status]}")
        shown = buckets[status][:list_limit]
        lines.extend(item_line(i) for i in shown)
        if counts[status] > list_limit:
            lines.append(f"  … 其余 {counts[status] - list_limit} 条已省略（--list-limit 可调）")
    lines.append("-" * 62)
    lines.append(
        "合计："
        + " / ".join(f"{STATUS_LABEL[s]} {counts[s]}" for s in STATUS_ORDER)
    )
    return "\n".join(lines), counts


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="check_links.py",
        description="Tilt 资源链接存活检查脚本（H01）：只校验真 URL，文字描述条目转人工核",
    )
    parser.add_argument("--input", required=True, action="append", help="resources.csv 路径或目录，可多次指定")
    parser.add_argument("--json", dest="json_out", default=None, help="输出机器可读报告路径")
    parser.add_argument("--concurrency", type=int, default=8, help="并发数，默认 8")
    parser.add_argument("--timeout", type=int, default=10, help="单个请求超时秒数，默认 10")
    parser.add_argument("--list-limit", type=int, default=50, help="文本报告每类最多列出条数，默认 50")
    args = parser.parse_args(argv)

    paths = []
    for item in args.input:
        path = Path(item)
        if path.is_dir():
            paths.extend(sorted(path.rglob("*.csv")))
        elif path.is_file():
            paths.append(path)
        else:
            raise SystemExit(f"[ERROR] 输入路径不存在: {path}")
    if not paths:
        raise SystemExit("[ERROR] 输入路径下没有找到任何 .csv 文件")

    all_items = []
    header_warnings = []
    for path in paths:
        header, rows, line_map = read_resources(path)
        if header != RESOURCE_COLUMNS:
            missing = [c for c in RESOURCE_COLUMNS if c not in header]
            unknown = [c for c in header if c not in RESOURCE_COLUMNS]
            header_warnings.append(
                f"[WARN] {path} 表头与契约不符（缺失: {missing or '无'}；多余: {unknown or '无'}）"
            )
        if not rows:
            header_warnings.append(f"[WARN] {path} 无数据行（可能只有 manifest 注释块）")
            continue
        tasks, manual_items = build_tasks(rows, line_map, path)
        checked = run_checks(tasks, args.concurrency, args.timeout)
        all_items.extend(checked)
        all_items.extend(manual_items)

    text, counts = render_text_report(all_items, args.list_limit)
    print(text)
    for warning in header_warnings:
        print(warning)

    if args.json_out:
        payload = {
            "task_id": TASK_ID,
            "spec_version": SPEC_VERSION,
            "ssot_checksum": SSOT_CHECKSUM,
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "concurrency": args.concurrency,
            "timeout": args.timeout,
            "inputs": [str(p) for p in paths],
            "summary": {STATUS_LABEL[s]: counts[s] for s in STATUS_ORDER},
            "counts": counts,
            "items": [
                {
                    "file": i["file"],
                    "line": i["line"],
                    "domain_id": i["domain_id"],
                    "resource_type": i["resource_type"],
                    "name": i["name"],
                    "url_or_location": i["url_or_location"],
                    "url": i["url"],
                    "status": i["status"],
                    "status_cn": STATUS_LABEL[i["status"]],
                    "http_status": i["http_status"],
                    "final_url": i["final_url"],
                    "error": i["error"],
                    "verify_status": i["verify_status"],
                }
                for i in all_items
            ],
        }
        out_path = Path(args.json_out)
        if out_path.parent and not out_path.parent.exists():
            out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"机器可读报告已写入: {out_path}")

    # 失效/超时视为需要处理；待人工核不计入失败（这是契约允许的常态）
    return 1 if (counts[STATUS_DEAD] + counts[STATUS_TIMEOUT]) else 0


if __name__ == "__main__":
    sys.exit(main())


# =========================================================================== #
# 使用示例
# --------------------------------------------------------------------------- #
# 1) 默认参数检查一份资源清单
#    $ python3 tools/check_links.py --input out/resources.csv
#
#    预期输出：
#    ==============================================================
#    资源链接检查报告    条目总数: 42
#    SSOT 校验码: TL-SSOT-2026-09-20-A
#    ==============================================================
#    [存活] 7
#      ✓ 第 3 行  go · 围棋入门教程 — HTTP 200 https://example.com/go
#    [失效] 2
#      ✗ 第 11 行 piano · xxx — HTTP 404 https://example.com/404
#    [重定向] 1
#      → 第 12 行 chess · xxx — HTTP 200 https://a.com → https://a.com/index
#    [超时] 1
#      ⏱ 第 20 行 dance · xxx — 超时: timed out https://slow.example.com
#    [待人工核] 31
#      ? 第 2 行 go · 知乎 · 围棋话题 — 知乎 · 围棋话题
#    --------------------------------------------------------------
#    合计：存活 7 / 失效 2 / 重定向 1 / 超时 1 / 待人工核 31
#    -> 存在失效或超时，退出码 1；否则 0（待人工核不影响退出码）
#
# 2) 调高并发、缩短超时、输出机器可读报告
#    $ python3 tools/check_links.py --input out/resources.csv \
#        --concurrency 16 --timeout 5 --json reports/check_links.json
#
#    终端打印同样的五类报告，并追加：
#    机器可读报告已写入: reports/check_links.json
#    -> JSON 中 items[].status 取值为 alive / dead / redirect / timeout / manual_review
#
# 3) 检查整个目录（如按领域拆分的多份 resources）
#    $ python3 tools/check_links.py --input out/resources_dir --list-limit 100
# =========================================================================== #
