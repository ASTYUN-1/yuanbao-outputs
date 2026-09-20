# yuanbao-outputs

「元宝产物」—— 来自 `天赋检测器` 项目的中间产物 / 评测材料合集。

## 这是什么

本仓库收录了「天赋检测器」项目里「元宝」环节产生的设计与评测材料，包括题库、评分函数、指标规范、问卷/报告/任务页 HTML、FAQ 与若干参考数据表（CSV / JSON / YAML / SQL）。

可以把它理解成一个**只读快照**：用于回溯当时的题目设计、评分逻辑、指标口径与实验素材。

## 目录内容

| 类型 | 文件 |
| --- | --- |
| 前端页面 | `01_questionnaire.html` · `02_report.html` · `03_dailytask.html` · `04_domains.html` |
| 说明文档 | `anomaly_rules.md` · `metrics_spec.md` · `pain_tolerance_test.md` · `questionnaire_q10_q18.md` · `tracking_dictionary.md` · `seed_recruit.md` · `schema_notes.md` · `manual_derivation.md` · `faq.md` |
| 数据 / 题库 | `cognitive_test_bank.json` · `expected_results.json` · `manifest_C12b.yaml` |
| 评测素材 | `ideal_coordinates.csv` · `resources.csv` · `tone_guide.csv` · `push_28.csv` |
| 打包文件 | `C01_第1批_linguistic.zip` · `C02_batch1_linguistic_tasks.zip` · `prompts.zip` |
| 代码 / 模式 | `scoring_functions.py` · `schema.sql` |
| 其他 | `Tilt_xxx_移动AI与本地对比.md` · `metrics_spec (1).md` · `ideal_coordinates (1).csv` |

> 带 `(1)` 后缀的文件为同名内容的历史副本，按原样保留。

## 使用建议

- **浏览**: 大部分 Markdown 文件可以直接在 GitHub 上阅读；HTML 文件可以在浏览器中打开预览。
- **引用 JSON / CSV**: 文件结构稳定，可作为后续评测脚本的输入。
- **SQL / Python**: `schema.sql` 和 `scoring_functions.py` 展示了底层数据模型与评分逻辑，可作为参考实现。

## License

随项目一同公开，未单独声明许可；如有二次使用需求请联系作者。
