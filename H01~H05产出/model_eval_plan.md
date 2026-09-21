# Tilt · 国产模型选型评测方案（Layer 3 LLM 评估器）

> 补齐 SPEC 10.4 遗留的「国产 AI 模型选型」问题（原任务 C22）。
> 云端交付「评测方案 + 统计脚本」，真实打分在本机执行（需要密钥与网络）。

## 0 · 适用范围与前置约束

- 第 3.3 节的 10 个 `evaluator_type` 中，**只有 5 个会调用大模型**：
  `llm_writing` / `llm_image` / `llm_video` / `llm_audio` / `llm_dialogue`。
  其余 5 个（`katago` / `stockfish` / `auto_test` / `data_tracking` / `knowledge_test`）由规则、棋类引擎或题库打分，
  **不纳入本次模型选型**；但它们的分数同样可以用 `tools/consistency_stats.py` 做一致性统计。
- 本方案不调用任何 API、不包含任何联网代码；脚本仅依赖 Python 标准库。
- 本方案不产出"哪个模型最好"的结论，只产出可复现的测量方法与决策表格。最终选择权在本机实测结果与人工复核（SPEC 11.4）。
- 下表所有价格与上下文长度均为 **2026-09-21 核查快照**。近 30 天内 GLM、DeepSeek、Qwen 均公开调整过价格或版本，
  执行前必须以厂商官方价格页复核，**本表不作为长期事实源**。

---

## 1 · 候选模型清单（10 个）

单价单位统一为「元 / 百万 tokens」，口径为**缓存未命中输入 / 输出**（另有缓存命中价时单列）。

| # | 厂商 / 平台 | 候选模型（Model ID） | 输入模态 | 上下文长度 | 单价（输入 / 输出） | 核查来源与日期 | 入选理由 |
|---|---|---|---|---|---|---|---|
| 1 | 智谱 BigModel | `glm-5.3-flash` | 图片、视频、文件、文本 | 1M | 0.8 / 2.8（缓存命中 0.23） | 智谱《API 定价》官方文档，2026-09-21 | 原生多模态低价档，是唯一能直接"看图 / 看片打分"的便宜选项，覆盖 `llm_image` / `llm_video` |
| 2 | 智谱 BigModel | `glm-5.3` | 文本 | 1M | 8 / 28（缓存命中 2） | 智谱《API 定价》官方文档，2026-09-21 | 旗舰文本档，用于测"花 10 倍价格是否换来更稳的分数" |
| 3 | 深度求索 | `deepseek-flash`（DeepSeek-V4.1-Flash） | 文本、图像 | 1M（最大输出 384K） | 闲时 1 / 4，高峰 2 / 8（闲时缓存命中 0.02） | DeepSeek 官方《Models & Pricing》，2026-09-20；人民币口径见 2026-09-17 中信证券研报与每经报道 | 成本基线，1800 次批量调用的主力候选；并发上限 2500，适合并行跑 |
| 4 | 深度求索 | `deepseek-v4-pro`（DeepSeek-V4-Pro-0813） | 文本 | 1M（最大输出 384K） | 官方美元价 $0.66 / $1.98（闲时）；人民币口径 [待核验:官方页以美元标价，人民币数字仅见二手汇总 4.5 / 13.5] | DeepSeek 官方《Models & Pricing》，2026-09-20 | 旗舰对照项，判断"贵 4 倍是否换来更稳的分数" |
| 5 | 阿里云百炼 | `qwen3.8-flash` | 文本、图片、视频 | 262,144 原生，官方规格页另标注默认 1,000,000 [待核验:两处口径不一致，以调用时平台返回为准] | 0.8 / 2.7（缓存命中 0.1） | 阿里云 2026-08-27 调价公告（证券时报转载）+ 百炼模型文档 | 与 `glm-5.3-flash` 同价区间的第二家，用于厂商互备（避免单厂商故障） |
| 6 | 腾讯云 / 混元 | `hy4-preview` | 文本 | 1M（最大输出 64K [待核验:最大输出值仅见第三方汇总]） | 6 / 18（缓存命中 0.3） | 腾讯云《模型价格》官方文档 + 中证网 2026-08-28 报道 | 中文语境与国内合规链路；缓存命中价 0.3 元对"长 prompt 反复调用"很划算 |
| 7 | 月之暗面 | `kimi-k3` | 文本 | 1,048,576 | 缓存命中 2 / 缓存未命中 20 / 输出 100 | Kimi 开放平台《模型推理价格说明》官方页，2026-09-21 | 长上下文上限对照；本清单最贵，用于判断"最贵是否等于最稳" |
| 8 | MiniMax | `MiniMax-M3` | 文本、图片、视频 | 1M | [待核验:仅第三方汇总给出 $0.30 / $1.20（输入 ≤512K）与 $0.60 / $2.40（>512K），未核对官方价格页] | 第三方汇总页，核查日 2026-07-18 | 长上下文 + 多模态候选，价格需实测前先复核 |
| 9 | 百度千帆 | `ernie-5.1` | 文本 | 128K | ≤32K：4 / 18；32K–128K：6 / 22 | 百度智能云千帆《价格》官方文档，2026-09-21 | 中文写作类评估的对照项；上下文最短，长样本需截断后再送评 |
| 10 | 火山引擎 | `doubao-seed-2-1-pro-260915` | 文本、图片、视频 | 1024k（260628 版为 256k） | 6 / 30（缓存命中 1.2；批量推理 3 / 15） | 火山方舟模型详情页官方页，2026-09-21 | 候选池里唯一同时给到 1024k 上下文与多模态输入的旗舰档 |

**备选池（本轮不评测，仅在主表某模型被否决时替补，不占 10 个名额）**

- `qwen3.8-max`：国内价 12 / 36（隐式缓存命中 1.5）[待核验:仅见媒体报道，未在百炼价格页直接核对]
- `glm-5.3-flashx`：与 `glm-5.3-flash` 同权重、1M 上下文、定价 2 / 7（2026-09-18 上线），官方称推理速度 5 倍 [待核验:200 tokens/s 为官方自报值，第三方实测落在 17–80 tokens/s，需实测确认]
- `doubao-seed-evolving`：周级迭代、价格同 2.1-pro（6 / 30）[待核验:周级迭代意味着打分基线可能每周漂移，与"一致性"要求存在冲突，需连续多周复测]

**候选池的硬性排除条件（任一命中即不进入评测）**：上下文长度 < 32K；不支持 JSON / 结构化输出；不提供中国大陆可调用的官方 API 端点。

---

## 2 · 评测维度与合格线

| # | 维度 | 测什么 | 打分方法（可直接照做） | 合格线建议 | 脚本位置 |
|---|---|---|---|---|---|
| 1 | **一致性** | 同一份产出跑 3 次，分数波动有多大 | 每个 `(model, sample)` 组内算标准差 sd、极差 range、变异系数 `cv = sd / mean`；再算模型级"达标样本占比" | `sd ≤ 5.0`、`range ≤ 10.0`、`cv ≤ 0.10`；模型级达标率 ≥ 80%（低于此值一票否决） | 报告 `[1]` |
| 2 | **区分度** | 好 / 中 / 差三档能否被拉开 | 算各档均值、相邻档均值差 `gap`、最好档与最差档的 Cohen's d | 相邻档 `gap ≥ 8.0`；`Cohen's d ≥ 0.80`；出现 `gap ≤ 0`（档间倒挂）直接否决 | 报告 `[2]` |
| 3 | **防讨好** | 是否一律给高分 | 看全样本分数分布：min / P25 / 中位数 / P75 / max + 10 分一档的直方图；并单看最差档均值 | `min ≤ 70`（`min > 70` 即告警并否决）；最差档均值理想 ≤ 35、上限 70 | 报告 `[3]` |
| 4 | **指令遵循** | 是否严格按 JSON schema 输出 | `parse_ok` 字段统计成功率，并记录失败样本 ID | 成功率 ≥ 95%；低于 90% 一票否决 | 报告 `[4]` |
| 5 | **中文能力** | 对中文产出的评价是否合理（脚本不覆盖，人工做） | 每个 `evaluator_type` 抽 15 份（好 / 中 / 差各 5），2 名中文母语评审独立判断"模型给出的 `reason` 是否与该产出实际相符"，判"可采纳 / 不可采纳" | 可采纳率 ≥ 80%；两名评审简单一致率 ≥ 75%（分歧样本由第三人裁定） | 无，本机人工记录 |
| 6 | **成本** | 单次调用价格 × 调用量 | 单次成本 =（输入单价 × `input_tokens` + 输出单价 × `output_tokens`）÷ 1,000,000；月成本 = 单次成本 × 日均调用量 × 30 | 以"单用户 4 周 LLM 评估总成本 ≤ X 元"为准，X [待核验:SPEC 未给出成本上限，需产品方确认后填入] | 需本机用单价表 × `input_tokens` / `output_tokens` 自行计算 |
| 7 | **延迟** | 单次响应耗时 | 记录 `latency_ms`，算 P50 / P95 / P99 | `P95 ≤ 5000 ms`；`llm_dialogue` 这类可能阻塞交互的建议收到 `P95 ≤ 3000 ms`（可用 `--latency-p95-threshold 3000` 单独跑） | 报告 `[5]` |
| 8 | **跨类型稳定性**（补充项） | 同一个模型在 5 种 `llm_*` 评估器上是否都稳 | 用 `--by-evaluator-type` 按 `model × evaluator_type` 分组重跑第 1–4 项，取**最差那个类型**作为该模型的成绩 | 每个 `evaluator_type` 都必须各自满足第 1、2、4 项的合格线（不允许"只 writing 稳、audio 崩"） | 报告 `[1]~[4]`（加 `--by-evaluator-type`） |

> **为什么补第 8 项**：Tilt 的 Layer 3 会让同一个模型同时给写作、图像、视频、音频、对话打分。
> 一个模型平均分很稳，但如果它在 `llm_audio` 上 sd=12，音频类领域的 4 周斜率就是噪声。
> 单看总体均值会掩盖这种"偏科"，所以把"最差类型"而不是"平均类型"作为成绩。

---

## 3 · 测试集设计

### 3.1 覆盖的 `evaluator_type`

只覆盖 LLM 类的 5 个：`llm_writing`、`llm_image`、`llm_video`、`llm_audio`、`llm_dialogue`。

### 3.2 样本量与结构

| 项 | 数值 |
|---|---|
| 每个 `evaluator_type` 的样本数 | 12 份（好 4 / 中 4 / 差 4） |
| `evaluator_type` 数 | 5 |
| 样本总数 | **60 份** |
| 每份跑几次 | **3 次**（`run_index` = 1 / 2 / 3） |
| 每个模型的调用次数 | 60 × 3 = 180 次 |
| 10 个模型的总调用次数 | **1800 次**（另按 5% 预留重试，实际按 1900 次申请额度） |

### 3.3 样本从哪些领域取（领域 ID 严格取自 SSOT 3.1）

| `evaluator_type` | 取样本的领域（各 3 份） |
|---|---|
| `llm_writing` | `writing_general`、`blogging`、`biography_writing`、`script_writing` |
| `llm_image` | `photography`、`painting`、`ui_design`、`modeling_3d` |
| `llm_video` | `video_editing`、`animation` |
| `llm_audio` | `singing`、`composition`、`podcasting`、`djing` |
| `llm_dialogue` | `debating`、`coaching`、`negotiation`、`counseling` |

每个 `evaluator_type` 共 12 份，按 3.4 的分档流程切成 4 / 4 / 4，**不预先按领域指定档位**。

### 3.4 分档方法（可执行）

1. 写一份 5 条锚点的 rubric：完成度 / 准确性 / 表达质量 / 创意 / 与任务 Level 的匹配度，每条 0–20 分，合计 0–100。
2. 3 名评审对全部 60 份独立打分（不看模型分数）。
3. 每份取 3 人打分的**中位数**作为人工基准分。
4. 在同一个 `evaluator_type` 内按人工基准分降序排列：**前 4 份 = `good`，中 4 份 = `mid`，后 4 份 = `bad`**。
5. 门槛校验：相邻档的基准分中位数差必须 ≥ 15 分；不满足就补样本或重新标注，直到满足。
6. 3 名评审之间的打分一致性留档（可用 Kendall 协同系数，要求 ≥ 0.6），用于说明分档本身可信。

### 3.5 样本 ID 命名

`{evaluator_type}_{tier}_{三位序号}`，例如 `llm_writing_good_001`、`llm_audio_bad_003`。
`tier` 取值 `good` / `mid` / `bad`（说明见文末备注）。

### 3.6 调用参数（必须固定，否则一致性无从谈起）

- `temperature = 0`；厂商不支持时取该平台的最小值。
- 同一 `evaluator_type` 用**同一份 prompt 模板 + 同一份 JSON schema**，版本号写进 `prompt_version` 列。
- 输出 schema 固定两个字段：`score`（0–100 整数）与 `reason`（不超过 80 字）。
- 3 次运行在同一小时内完成，避免撞上模型静默更新。
- 单次失败最多重试 2 次；仍失败则 `parse_ok=false` 且 `score` **留空**（**禁止填 0**，否则会污染均值与区分度）。

---

## 4 · 执行步骤（本机）

**第 0 步 · 准备**
1. 开通第 1 节 10 个模型的 API Key，写入环境变量（如 `DEEPSEEK_API_KEY`、`GLM_API_KEY`），**不写进任何代码或提交物**。
2. 建一张 `model_registry.csv`：`model,base_url,model_id,input_price_per_mtok,output_price_per_mtok,prompt_version,checked_at`。
3. 复核第 1 节所有标了 `[待核验]` 的规格，把实测值回填，填不上的从候选池里剔除。

**第 1 步 · 固化 prompt**
4. 为 5 个 `evaluator_type` 各写一份 prompt 模板 + JSON schema，版本号统一 `pv1`。
5. 用 3 份样本做冒烟测试：要求 3/3 都能解析出 `score` 与 `reason`。解析不过的模型先修 prompt，不要把问题带进正式跑。

**第 2 步 · 建测试集**
6. 按 3.3 收集 60 份产出（真实用户产出需脱敏），落 `samples.csv`：`sample_id,evaluator_type,domain_id,sample_tier,artifact_path`。
7. 按 3.4 完成人工分档与门槛校验。

**第 3 步 · 跑打分**
8. 按下面的伪代码执行（真实调用代码在本机写，本节不含任何联网代码）：

```
for model in model_registry:
    for sample in samples:                    # 60 份
        for run_index in 1..3:
            t0 = now()
            resp = call(model, prompt[sample.evaluator_type], sample.artifact)   # 本机实现
            latency_ms = now() - t0
            ok, score = try_parse_json(resp)  # 严格按 schema 解析，失败则 score 留空
            append_row(scores.csv, model, sample, run_index, score, latency_ms, ok, resp)
            sleep(2s)                         # 避开限流
```

9. 每跑完一个模型就立刻跑一次统计脚本，发现该模型解析率崩了就停跑，省下额度。

**第 4 步 · 落盘**
10. 结果写入 `scores.csv`，编码 **UTF-8 with BOM**，表头见第 5 节。
11. `raw_response` 原样保存（换行替换成 `\n` 字面量），便于回溯"为什么这次解析失败"。

**第 5 步 · 统计**
12. 总体跑：`python3 tools/consistency_stats.py --input scores.csv`
13. 分类型跑：`python3 tools/consistency_stats.py --input scores.csv --by-evaluator-type`
14. 两类结果都存 JSON：`--json-out reports/stats_{日期}.json`，便于与下一轮复测对比。

**第 6 步 · 人工抽检**
15. 按第 2 节第 5 项做中文能力抽检，结果记 `results_manual.csv`：`model,evaluator_type,sample_id,reviewer,acceptable,note`。

**第 7 步 · 成本估算**
16. 用 `scores.csv` 的 `input_tokens` / `output_tokens` × `model_registry.csv` 的单价，算出每个模型跑完 1800 次的实际成本，以及折算到单用户 4 周的成本。

**第 8 步 · 出决策表并选定**
17. 按第 6 节填写决策表，选出**主选 1 个 + 备选 1 个**（备选必须来自不同厂商）。

**第 9 步 · 灰度复测**
18. 上线后连续 2 周每周重跑一次脚本，确认 sd 与解析率不退化；退化则切备选。

---

## 5 · 结果记录表模板（本机填数据用）

**必需列（脚本依赖，顺序固定）**

```
model,evaluator_type,sample_id,sample_tier,run_index,score,latency_ms,parse_ok,raw_response
```

**推荐补上的可选列（用于成本估算与回溯，脚本不强制）**

```
model,evaluator_type,sample_id,sample_tier,run_index,score,latency_ms,parse_ok,input_tokens,output_tokens,prompt_version,model_version,timestamp,raw_response
```

**字段说明与填写要求**

| 字段 | 类型 | 说明 |
|---|---|---|
| `model` | 字符串 | 填厂商 Model ID，如 `glm-5.3-flash`；同一次评测内不得重名 |
| `evaluator_type` | 枚举 | 取 SSOT 3.3 的 10 个值之一，如 `llm_writing` |
| `sample_id` | 字符串 | 见 3.5 命名规范 |
| `sample_tier` | 枚举 | `good` / `mid` / `bad`（见文末备注） |
| `run_index` | 整数 | 1 / 2 / 3 |
| `score` | 浮点数或空 | 模型给出的 0–100 分；**解析失败必须留空，不得填 0** |
| `latency_ms` | 整数 | 发起请求到收到完整响应的耗时 |
| `parse_ok` | `true` / `false` | 是否严格解析出 schema 要求的 `score` + `reason` |
| `input_tokens` | 整数（可选） | 用于成本估算 |
| `output_tokens` | 整数（可选） | 用于成本估算 |
| `prompt_version` | 字符串（可选） | 如 `pv1`；换 prompt 后必须换版本号，否则跨版本数据不可比 |
| `model_version` | 字符串（可选） | 厂商返回的模型版本，用于事后定位"哪天静默更新了" |
| `timestamp` | ISO 8601（可选） | 形如 `2026-09-19T10:30:00Z` |
| `raw_response` | 字符串（可选） | 原始返回；**换行必须先替换成 `\n` 字面量**，字段内不得出现未转义换行 |

**格式要求**：UTF-8 with BOM；逗号分隔；文本字段双引号包裹；字段内双引号写成两个双引号；一行一条记录；文件顶部可放 `#` 开头的 manifest 注释块（脚本会自动跳过）。

---

## 6 · 决策方法

### 6.1 一票否决（命中任一即出局，不看总分）

| 否决项 | 条件 | 为什么 |
|---|---|---|
| 解析成功率 | `< 0.90` | 解析不过意味着这次打分直接丢，工程上无法接受 |
| 区分度 | 相邻档均分差 `≤ 0`（档间倒挂或完全无差异） | 分不出好坏，评估层没有意义 |
| 一致性达标率 | `< 0.80` | 同一份产出 3 次分数乱跳，斜率就是噪声 |
| 防讨好 | 全样本最低分 `> 70` | 差产出也拿 70+，用户看不到"哪个方向 4 周斜率平缓"（违反产品三原则第 1 条） |

### 6.2 加权打分表（默认权重，可用命令行改）

| 子项 | 权重 | 计分公式 |
|---|---|---|
| 一致性 | 0.30 | `100 × (1 − 平均 sd ÷ sd 阈值)`，截断到 [0, 100] |
| 区分度 | 0.30 | `100 × (最小档间差 ÷ 档间差阈值)`，截断到 [0, 100] |
| 防讨好 | 0.15 | `100 × (70 − 最差档均值) ÷ (70 − 35)`，截断到 [0, 100] |
| 解析成功率 | 0.15 | `解析成功率 × 100` |
| 延迟 | 0.10 | `100 × (1 − P95 ÷ P95 阈值)`，截断到 [0, 100] |

权重之和必须为 1.0（脚本会校验）。命令行：`--weight-consistency` / `--weight-discrimination` / `--weight-anti-sycophancy` / `--weight-parse` / `--weight-latency`。

### 6.3 决策模板（本机填）

| 模型 | 是否否决 | 否决原因 | 总分 | 分类型最差成绩（`--by-evaluator-type`） | 单用户 4 周成本估算 | 中文抽检可采纳率 | 结论 |
|---|---|---|---|---|---|---|---|
| `glm-5.3-flash` | 否 | — | 88.0 | `llm_audio` 一致性达标率 0.75 | ¥X | 86% | 主选 |
| `deepseek-flash` | 是 | 解析成功率 0.83 | 79.4 | — | ¥Y | — | 淘汰 |
| … | | | | | | | |

**选择规则**

1. 在未被否决的模型里，取总分最高者为**主选**。
2. 取总分次高、且**厂商与主选不同**者为**备选**（避免同一厂商同时故障或同时调价）。
3. 若全部被否决：先把 prompt 收紧（缩短输出、加 few-shot 锚点、强制只输出 JSON），再跑一轮；仍不行，则考虑"多模型打分取中位数"的兜底方案 —— 这属于新增机制，**需产品方确认后再落地，不在本方案内擅自决定**。
4. 总分只用于排序，**不替代第 2 节第 5 项的人工抽检**；人工抽检不通过的模型不得入选。

---

## 7 · 脚本用法与最小示例

**文件**：`tools/consistency_stats.py`（仅依赖标准库：`csv` / `statistics` / `argparse` / `collections` / `json` / `math` / `sys` / `unicodedata`）

**最小示例 CSV**：`tools/example_scores.csv`（3 个模型 × 2 个样本 × 3 次运行 = 18 行，含 BOM 与 manifest 注释块）

**验证命令**

```bash
python3 tools/consistency_stats.py --input tools/example_scores.csv
python3 tools/consistency_stats.py --input tools/example_scores.csv --by-evaluator-type
python3 tools/consistency_stats.py --input tools/example_scores.csv --json
python3 tools/consistency_stats.py --input tools/example_scores.csv --sd-threshold 3 --latency-p95-threshold 3000
```

**预期输出**：见 `docs/consistency_stats_example_output.md`（该文件由本脚本实际运行生成，可直接逐行比对，
用于确认脚本本身没被改坏；数字对不上即说明环境或数据有问题）。

**示例数据的设计意图**：`glm_demo` 是"稳且能拉开档次"的样子；`qwen_demo` 模拟讨好型（最低分 74，触发防讨好告警 + 一致性否决）；
`ds_demo` 模拟工程问题（1 次解析失败 + P95 延迟 9175ms，触发解析率否决）。

**常用阈值覆盖参数**（全部可通过命令行改，脚本内不当常量用）

```
--sd-threshold --range-threshold --cv-threshold
--tier-gap-threshold --effect-size-threshold
--min-score-threshold --bad-mean-max --bad-mean-ideal
--parse-rate-threshold --latency-p95-threshold
--veto-parse-rate --veto-consistency-pass
--weight-consistency --weight-discrimination --weight-anti-sycophancy --weight-parse --weight-latency
--tiers good,mid,bad        # 分档枚举可改
--by-evaluator-type         # 按 model × evaluator_type 分组
--json / --json-out PATH    # 机器可读输出
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
#   - model_eval_plan.md   (rows: n/a)
# unverified_count: 8
# self_check:
#   frozen_ids_only: true
#   enum_from_spec: false
#   no_absolute_claims: true
#   no_new_concepts: true
#   spec_numbers_unchanged: true
# known_deviations:
#   - enum_from_spec=false：SSOT 3.3/3.4/3.6 未冻结"样本分档"枚举值，本文档与脚本使用 good/mid/bad
#     （脚本可用 --tiers 覆盖），未改动任何已冻结枚举。
# === END MANIFEST ===

## 备注

1. `sample_tier` 的取值（`good`/`mid`/`bad`）不在 SSOT 冻结清单里，是我为可执行起见选的；如其他任务已定别的写法，请统一后我改脚本默认值（`--tiers` 已留口子），这会影响跨任务 CSV 拼接。
2. 第 8 节要求"代码 / CSV / Markdown 均放文件顶部"，第 4.5 节要求"Markdown 放文件最末尾"，两处冲突；本 Markdown 按 4.5 放末尾，`.py` 与 `.csv` 按 4.5 放顶部。
3. 第 2 节第 6 项的"单用户 4 周成本上限 X" SPEC 里没有，需要产品方给数；在拿到之前成本维度只能做排序不能做否决。
4. `enum_from_spec` 如实填 false（原因见 known_deviations），不是漏填。
5. 未调用任何 API，脚本不含联网代码；示例 CSV 的分数是为演示阈值触发而构造的示意数据，不是真实模型打分结果。
