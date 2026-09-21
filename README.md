# yuanbao-outputs

「元宝产物」—— 来自 `天赋检测器` 项目的中间产物 / 评测材料合集。

## 这是什么

本仓库收录了「天赋检测器」项目里「元宝」环节产生的设计与评测材料，包括题库、评分函数、指标规范、问卷/报告/任务页 HTML、FAQ 与若干参考数据表（CSV / JSON / YAML / SQL），以及「第二批补做」环节的用户事件流与领域素材。

可以把它理解成一个**只读快照**：用于回溯当时的题目设计、评分逻辑、指标口径与实验素材。

## 目录内容

### 根目录

| 类型 | 文件 |
| --- | --- |
| 前端页面 | `01_questionnaire.html` · `02_report.html` · `03_dailytask.html` · `04_domains.html` |
| 说明文档 | `anomaly_rules.md` · `pain_tolerance_test.md` · `questionnaire_q10_q18.md` · `tracking_dictionary.md` · `seed_recruit.md` · `schema_notes.md` · `manual_derivation.md` · `faq.md` |
| 数据 / 题库 | `cognitive_test_bank.json` · `expected_results.json` |
| 评测素材 | `resources.csv` · `tone_guide.csv` · `push_28.csv` |
| 打包文件 | `C01_第1批_linguistic.zip` · `C02_batch1_linguistic_tasks.zip` · `prompts.zip` |
| 代码 / 模式 | `scoring_functions.py` · `schema.sql` |
| 其他 | `metrics_spec.md` · `ideal_coordinates.csv` |

### 子目录

- `第二批补做内容/` —— 「元宝」环节第二阶段的补做/验证素材，共 28 个文件：
  - 5 名用户的领域元数据清单 `manifest_C12b_user_001~005.yaml`
  - 5 名用户的做题事件流 `events_user_001~005.jsonl`
  - 各智能域的任务库/元数据：`C01_*_领域元数据.zip`、`C02_*_任务库.zip`、`C03_*_去糖任务库.zip` 等
  - 域名数据集 `domains.zip` / `domains (1).zip` / `domains_batch5.zip` / `domains_batch6.zip`
  - 批次任务包 `tasks_batch4.zip` / `tasks_batch8.zip`

## 使用建议

- **浏览**: 大部分 Markdown 文件可以直接在 GitHub 上阅读；HTML 文件可以在浏览器中打开预览。
- **引用 JSON / CSV**: 文件结构稳定，可作为后续评测脚本的输入。
- **SQL / Python**: `schema.sql` 和 `scoring_functions.py` 展示了底层数据模型与评分逻辑，可作为参考实现。
- **第二批数据**: 子目录里的 yaml/jsonl 是按用户维度的领域元数据 + 事件流，可用于复盘某位用户在该批次的做题轨迹；zip 包可作为题库/任务包复现源。

## License

随项目一同公开，未单独声明许可；如有二次使用需求请联系作者。
