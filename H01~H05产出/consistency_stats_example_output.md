# consistency_stats.py · 最小示例的预期输出

本文件由脚本在 `tools/example_scores.csv` 上**实际运行**生成，用于本机逐行比对、确认脚本本身没被改坏。
若本机输出与本文不一致，先检查 Python 版本（本脚本在 Python 3.8+ 上跑通）与 CSV 是否被改动。

## 命令 1 · 默认报告

```bash
python3 tools/consistency_stats.py --input tools/example_scores.csv
```

```
=== Tilt 评分一致性统计报告 ===
输入文件: tools/example_scores.csv
有效数据行: 18    无效行: 0    模型数: 3    样本数: 6
样本分档顺序(好→差): good > mid > bad
统计单元: model
阈值: sd<=5.0  range<=10.0  cv<=0.1  min_tier_gap>=8.0  effect_size>=0.8
      min_score告警线=70.0  worst_tier_mean(ideal<=35.0, 上限=70.0)
      parse_rate>=0.95  latency_p95<=5000.0ms  否决线: parse<0.9 一致性达标率<0.8
权重: consistency=0.3  discrimination=0.3  anti_sycophancy=0.15  parse=0.15  latency=0.1

[1] 一致性（同一 model+sample 的多次运行波动）
model      samples  mean_sd  max_sd  mean_range  mean_cv  达标率  结论 
---------  -------  -------  ------  ----------  -------  ------  -----
ds_demo          2     1.00    1.41        1.50     0.02  100.0%  PASS 
glm_demo         2     1.00    1.00        2.00     0.02  100.0%  PASS 
qwen_demo        2     3.50    6.00        7.00     0.04   50.0%  CHECK
未达标样本明细:
  - qwen_demo / llm_writing_good_001 (good): sd=6.00 > 5.00; range=12.00 > 10.00

[2] 区分度（好/中/差三档是否被拉开）
model       good  mid    bad  min_gap  effect_d  结论
---------  -----  ---  -----  -------  --------  ----
ds_demo    85.33  n/a  40.00    45.33     48.08  PASS
glm_demo   89.00  n/a  43.00    46.00     46.00  PASS
qwen_demo  89.00  n/a  75.00    14.00      3.25  PASS
  - ds_demo: 缺少分档 mid，档间差值仅按已有分档计算
  - glm_demo: 缺少分档 mid，档间差值仅按已有分档计算
  - qwen_demo: 缺少分档 mid，档间差值仅按已有分档计算

[3] 防讨好（分数分布是否贴着高分区）
model      n    min    p25  median    p75    max  worst档均值  结论
---------  -  -----  -----  ------  -----  -----  -----------  ----
ds_demo    5  39.00  41.00   85.00  85.00  86.00        40.00  ok  
glm_demo   6  42.00  43.25   66.00  88.75  90.00        43.00  ok  
qwen_demo  6  74.00  75.25   79.50  87.50  95.00        75.00  告警
  - ds_demo 直方图: 30-40:1 40-50:1 80-90:3
  - glm_demo 直方图: 40-50:3 80-90:2 90-100:1
  - qwen_demo 直方图: 70-80:3 80-90:2 90-100:1

[4] 解析成功率（JSON schema 遵循情况）
model      runs  parse_ok  parse_fail  成功率  结论
---------  ----  --------  ----------  ------  ----
ds_demo       6         5           1   83.3%  FAIL
glm_demo      6         6           0  100.0%  PASS
qwen_demo     6         6           0  100.0%  PASS
  - ds_demo 解析失败样本: llm_writing_bad_001

[5] 延迟（ms）
model      n   p50   p95   p99  结论
---------  -  ----  ----  ----  ----
ds_demo    6  4450  9175  9435  FAIL
glm_demo   6  1245  1298  1300  PASS
qwen_demo  6   855   902   908  PASS

[6] 综合排名（加权总分，带一票否决标记）
rank  model      一致性  区分度  防讨好   解析  延迟  总分  状态          
----  ---------  ------  ------  ------  -----  ----  ----  --------------
   1  glm_demo     80.0   100.0    77.1  100.0  74.0  88.0  可进入人工复核
   2  ds_demo      80.1   100.0    85.7   83.3   0.0  79.4  否决          
   3  qwen_demo    30.0   100.0     0.0  100.0  82.0  62.2  否决          
  - ds_demo 否决原因: 解析成功率 0.83 低于否决线 0.90
  - qwen_demo 否决原因: 一致性达标率 0.50 低于否决线 0.80
  - qwen_demo 否决原因: 最低分 74.00 高于告警线 70.00，疑似一律高分（区分不出差产出）

说明: 总分仅用于排序，不替代人工抽检；被否决的模型不应进入 Tilt Layer 3 评估器。

```

## 命令 2 · 按 evaluator_type 分组

```bash
python3 tools/consistency_stats.py --input tools/example_scores.csv --by-evaluator-type
```

```
=== Tilt 评分一致性统计报告 ===
输入文件: tools/example_scores.csv
有效数据行: 18    无效行: 0    模型数: 3    样本数: 6
样本分档顺序(好→差): good > mid > bad
统计单元: model × evaluator_type
阈值: sd<=5.0  range<=10.0  cv<=0.1  min_tier_gap>=8.0  effect_size>=0.8
      min_score告警线=70.0  worst_tier_mean(ideal<=35.0, 上限=70.0)
      parse_rate>=0.95  latency_p95<=5000.0ms  否决线: parse<0.9 一致性达标率<0.8
权重: consistency=0.3  discrimination=0.3  anti_sycophancy=0.15  parse=0.15  latency=0.1

[1] 一致性（同一 model+sample 的多次运行波动）
model                  samples  mean_sd  max_sd  mean_range  mean_cv  达标率  结论 
---------------------  -------  -------  ------  ----------  -------  ------  -----
ds_demo|llm_writing          2     1.00    1.41        1.50     0.02  100.0%  PASS 
glm_demo|llm_writing         2     1.00    1.00        2.00     0.02  100.0%  PASS 
qwen_demo|llm_writing        2     3.50    6.00        7.00     0.04   50.0%  CHECK
未达标样本明细:
  - qwen_demo|llm_writing / llm_writing_good_001 (good): sd=6.00 > 5.00; range=12.00 > 10.00

[2] 区分度（好/中/差三档是否被拉开）
model                   good  mid    bad  min_gap  effect_d  结论
---------------------  -----  ---  -----  -------  --------  ----
ds_demo|llm_writing    85.33  n/a  40.00    45.33     48.08  PASS
glm_demo|llm_writing   89.00  n/a  43.00    46.00     46.00  PASS
qwen_demo|llm_writing  89.00  n/a  75.00    14.00      3.25  PASS
  - ds_demo|llm_writing: 缺少分档 mid，档间差值仅按已有分档计算
  - glm_demo|llm_writing: 缺少分档 mid，档间差值仅按已有分档计算
  - qwen_demo|llm_writing: 缺少分档 mid，档间差值仅按已有分档计算

[3] 防讨好（分数分布是否贴着高分区）
model                  n    min    p25  median    p75    max  worst档均值  结论
---------------------  -  -----  -----  ------  -----  -----  -----------  ----
ds_demo|llm_writing    5  39.00  41.00   85.00  85.00  86.00        40.00  ok  
glm_demo|llm_writing   6  42.00  43.25   66.00  88.75  90.00        43.00  ok  
qwen_demo|llm_writing  6  74.00  75.25   79.50  87.50  95.00        75.00  告警
  - ds_demo|llm_writing 直方图: 30-40:1 40-50:1 80-90:3
  - glm_demo|llm_writing 直方图: 40-50:3 80-90:2 90-100:1
  - qwen_demo|llm_writing 直方图: 70-80:3 80-90:2 90-100:1

[4] 解析成功率（JSON schema 遵循情况）
model                  runs  parse_ok  parse_fail  成功率  结论
---------------------  ----  --------  ----------  ------  ----
ds_demo|llm_writing       6         5           1   83.3%  FAIL
glm_demo|llm_writing      6         6           0  100.0%  PASS
qwen_demo|llm_writing     6         6           0  100.0%  PASS
  - ds_demo|llm_writing 解析失败样本: llm_writing_bad_001

[5] 延迟（ms）
model                  n   p50   p95   p99  结论
---------------------  -  ----  ----  ----  ----
ds_demo|llm_writing    6  4450  9175  9435  FAIL
glm_demo|llm_writing   6  1245  1298  1300  PASS
qwen_demo|llm_writing  6   855   902   908  PASS

[6] 综合排名（加权总分，带一票否决标记）
rank  model                  一致性  区分度  防讨好   解析  延迟  总分  状态          
----  ---------------------  ------  ------  ------  -----  ----  ----  --------------
   1  glm_demo|llm_writing     80.0   100.0    77.1  100.0  74.0  88.0  可进入人工复核
   2  ds_demo|llm_writing      80.1   100.0    85.7   83.3   0.0  79.4  否决          
   3  qwen_demo|llm_writing    30.0   100.0     0.0  100.0  82.0  62.2  否决          
  - ds_demo 否决原因: 解析成功率 0.83 低于否决线 0.90
  - qwen_demo 否决原因: 一致性达标率 0.50 低于否决线 0.80
  - qwen_demo 否决原因: 最低分 74.00 高于告警线 70.00，疑似一律高分（区分不出差产出）

说明: 总分仅用于排序，不替代人工抽检；被否决的模型不应进入 Tilt Layer 3 评估器。

```

## 命令 3 · 机器可读 JSON（前 40 行示意）

```bash
python3 tools/consistency_stats.py --input tools/example_scores.csv --json
```

```
{
  "meta": {
    "input": "tools/example_scores.csv",
    "n_rows": 18,
    "n_invalid": 0,
    "n_models": 3,
    "n_samples": 6,
    "group_by_evaluator_type": false,
    "tiers": [
      "good",
      "mid",
      "bad"
    ],
    "thresholds": {
      "sd": 5.0,
      "range": 10.0,
      "cv": 0.1,
      "tier_gap": 8.0,
      "effect_size": 0.8,
      "min_score": 70.0,
      "bad_mean_max": 70.0,
      "bad_mean_ideal": 35.0,
      "parse_rate": 0.95,
      "latency_p95": 5000.0,
      "veto_parse_rate": 0.9,
      "veto_consistency_pass": 0.8
    },
    "weights": {
      "consistency": 0.3,
      "discrimination": 0.3,
      "anti_sycophancy": 0.15,
      "parse": 0.15,
      "latency": 0.1
    },
    "header": [
      "model",
      "evaluator_type",
      "sample_id",
      "sample_tier",
      "run_index",
...
```

完整 JSON 的关键字段（用于断言）：

- `meta.n_rows` = 18，`meta.n_invalid` = 0，`meta.n_models` = 3，`meta.n_samples` = 6
- `ranking` = `[{"rank":1,"unit":"glm_demo","total":87.98,"vetoed":false}, {"rank":2,"unit":"ds_demo","total":79.38,"vetoed":true}, {"rank":3,"unit":"qwen_demo","total":62.2,"vetoed":true}]`
- `models.ds_demo.parse.parse_rate` = 0.8333…（触发解析率否决）
- `models.qwen_demo.anti_sycophancy.suspected_all_high` = true（最低分 74 > 70）
- `models.qwen_demo.consistency.pass_rate` = 0.5（触发一致性否决）
- `models.glm_demo.veto.vetoed` = false

## 命令 4 · 阈值覆盖（收紧 sd 与 P95 延迟）

```bash
python3 tools/consistency_stats.py --input tools/example_scores.csv --sd-threshold 3 --latency-p95-threshold 3000
```

```
=== Tilt 评分一致性统计报告 ===
输入文件: tools/example_scores.csv
有效数据行: 18    无效行: 0    模型数: 3    样本数: 6
样本分档顺序(好→差): good > mid > bad
统计单元: model
阈值: sd<=3.0  range<=10.0  cv<=0.1  min_tier_gap>=8.0  effect_size>=0.8
      min_score告警线=70.0  worst_tier_mean(ideal<=35.0, 上限=70.0)
      parse_rate>=0.95  latency_p95<=3000.0ms  否决线: parse<0.9 一致性达标率<0.8
权重: consistency=0.3  discrimination=0.3  anti_sycophancy=0.15  parse=0.15  latency=0.1

[1] 一致性（同一 model+sample 的多次运行波动）
model      samples  mean_sd  max_sd  mean_range  mean_cv  达标率  结论 
---------  -------  -------  ------  ----------  -------  ------  -----
ds_demo          2     1.00    1.41        1.50     0.02  100.0%  PASS 
glm_demo         2     1.00    1.00        2.00     0.02  100.0%  PASS 
qwen_demo        2     3.50    6.00        7.00     0.04   50.0%  CHECK
未达标样本明细:
  - qwen_demo / llm_writing_good_001 (good): sd=6.00 > 3.00; range=12.00 > 10.00


```

## 命令 5 · 权重校验（预期报错退出码 2）

```bash
python3 tools/consistency_stats.py --input tools/example_scores.csv --weight-consistency 0.5
```

预期 stderr 末行：

```
consistency_stats.py: error: 权重之和必须为 1.0，当前为 1.2000000000000002（consistency=0.5  discrimination=0.3  anti_sycophancy=0.15  parse=0.15  latency=0.1）
```

---

# === TILT-CONTRACT-MANIFEST ===
# task_id: H04
# spec_version: V1.3
# ssot_checksum: TL-SSOT-2026-09-20-A
# baseline_version: B1.0
# produced_by: 元宝 (Yuanbao)
# produced_at: 2026-09-21
# batch: all
# output_files:
#   - consistency_stats_example_output.md   (rows: n/a)
# unverified_count: 0
# self_check:
#   frozen_ids_only: true
#   enum_from_spec: false
#   no_absolute_claims: true
#   no_new_concepts: true
#   spec_numbers_unchanged: true
# known_deviations:
#   - enum_from_spec=false：示例 CSV 中 sample_tier 取值 good/bad 不在 SSOT 冻结枚举内（SSOT 未定义该枚举）。
# === END MANIFEST ===
