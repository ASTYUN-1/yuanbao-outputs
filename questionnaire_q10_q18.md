# Tilt · 坐标系问卷 Q10-Q18（价值取向 / 风险态度 / 抽象层级）

> 本文件补齐 SPEC 12.2 六维坐标问卷的后 9 道题，与前 9 题（Q1-Q9）共同构成 18 题完整问卷。
> 计分实现见 `docs/scoring_functions.py`。

## 通用约定

| 项 | 约定 |
|---|---|
| 选项标注 | `（枚举值 ±1）`，枚举值取自冻结清单 3.4，一律英文 snake_case |
| 索引 | 下表"顺序即计分索引"决定传入计分函数的整数值（0 起） |
| 反向题 | 选中项 **-1**（题干为"你最讨厌"这类否定式提问） |
| 测谎题 | 正向 +1，且与本维度内另一道同义题共同参与一致性加权（`×1.5`） |
| "我不知道" | 每题最后一个选项，**该题整题不计分**，不进入归一化分母；三题全部选它时走函数兜底返回值；按 SPEC 12.7，同时应降低该维度的 `confidence` |
| 文案调性 | 一律引导性、口语化，禁止判定性结论，判断权交回用户本人 |

---

## Q10-Q12 · 价值取向（`value_orientation`）

选项枚举顺序即计分索引：

| 索引 | 枚举值 | 中文 |
|---|---|---|
| 0 | `creation` | 创造 |
| 1 | `helping` | 帮助 |
| 2 | `influence` | 影响 |
| 3 | `money` | 赚钱 |
| 4 | `aesthetics` | 美感 |

**Q10：**
> 最让你有成就感的是：

- A. 创造一个新东西（creation +1）
- B. 帮别人解决一个问题（helping +1）
- C. 影响很多人的想法（influence +1）
- D. 赚到很多钱（money +1）
- E. 做出美的东西（aesthetics +1）
- F. 我不知道（不计分）

**Q11：**
> 如果只能选一种工作，你会选：

- A. 设计师/创作者（creation +1）
- B. 老师/医生（helping +1）
- C. 领导/管理者（influence +1）
- D. 投资人/商人（money +1）
- E. 艺术家（aesthetics +1）
- F. 我不知道（不计分）

**Q12（反向题）：**
> 你最讨厌：

- A. 重复劳动，一点创造都没有（creation -1）
- B. 别人有困难，我帮不上忙（helping -1）
- C. 说什么都没人听（influence -1）
- D. 钱不够用（money -1）
- E. 东西做得丑（aesthetics -1）
- F. 我不知道（不计分）

---

## Q13-Q15 · 风险态度（`risk_attitude`）

选项枚举顺序即计分索引：

| 索引 | 枚举值 | 中文 |
|---|---|---|
| 0 | `conservative` | 保守 |
| 1 | `neutral` | 中性 |
| 2 | `aggressive` | 激进 |

**Q13：**
> 面对一个不确定的机会，你会：

- A. 等别人试过再说（conservative +1）
- B. 收集信息再决定（neutral +1）
- C. 直接上手试（aggressive +1）
- D. 我不知道（不计分）

**Q14：**
> 你怎么看失败：

- A. 失败挺可怕的（conservative +1）
- B. 失败是学习的成本（neutral +1）
- C. 失败越多越好（aggressive +1）
- D. 我不知道（不计分）

**Q15（测谎题，重复 Q13 不同表述）：**
> 回报很高但可能血本无归，你的第一反应是：

- A. 算了，太冒险（conservative +1）
- B. 先算清楚再决定（neutral +1）
- C. 干就完了（aggressive +1）
- D. 我不知道（不计分）

---

## Q16-Q18 · 抽象层级（`abstraction_level`）

选项枚举顺序即计分索引：

| 索引 | 枚举值 | 中文 |
|---|---|---|
| 0 | `theory` | 理论 |
| 1 | `application` | 应用 |
| 2 | `operation` | 操作 |

**Q16：**
> 你更喜欢研究：

- A. "为什么"（theory +1）
- B. "怎么做"（application +1）
- C. "做出来"（operation +1）
- D. 我不知道（不计分）

**Q17：**
> 让你兴奋的话题是：

- A. 宇宙和哲学（theory +1）
- B. 商业和工程（application +1）
- C. 运动和手工（operation +1）
- D. 我不知道（不计分）

**Q18（测谎题，重复 Q16 不同表述）：**
> 拿到一个没见过的东西，你的第一反应是：

- A. 先搞懂它的原理（theory +1）
- B. 想想能拿来干嘛（application +1）
- C. 直接拆开上手玩（operation +1）
- D. 我不知道（不计分）

---

## 备注

1. SPEC 12.2 的 Q18 原文为「请重复选择 Q1 的答案」（挂在认知风格上），与本任务 6.1 的 Q16-Q18 → `abstraction_level` 分工冲突；本产出按本任务执行，Q18 改为抽象层级测谎题，需产品确认后回填 SPEC。
2. SPEC 12.2 的 Q15 原文为「你愿意为高回报冒多大风险？」，为满足 6.3「每维须含 1 道反向题或测谎题」，改为 Q13 的同义反复测谎题，原语义由 Q13 承接。
3. SPEC 12.2 原文用中文标注选项（如"视觉 +1"），本产出按硬约束 9 统一改为 3.4 英文枚举值。
4. "我不知道"的计分口径 SPEC 未定义，本产出定为「整题跳过、不进分母」，三题全跳过走兜底值并降低 `confidence`。

```yaml
# === TILT-CONTRACT-MANIFEST ===
# task_id: C06
# spec_version: V1.3
# ssot_checksum: TL-SSOT-2026-09-20-A
# baseline_version: B1.0
# produced_by: yuanbao
# produced_at: 2026-09-20
# batch: all
# output_files:
#   - docs/questionnaire_q10_q18.md   (rows: 9)
#   - docs/scoring_functions.py   (rows: 294)
# unverified_count: 0
# self_check:
#   frozen_ids_only: true
#   enum_from_spec: true
#   no_absolute_claims: true
#   no_new_concepts: true
#   spec_numbers_unchanged: true
# known_deviations:
#   - SPEC 12.2 Q18 原为"重复 Q1 答案"（认知风格测谎题），本任务 6.1 要求 Q16-Q18 归属 abstraction_level，故改为抽象层级测谎题（重复 Q16 不同表述），待产品确认
#   - SPEC 12.2 Q15 原为"你愿意为高回报冒多大风险？"，为满足 6.3 每维含 1 道反向题/测谎题，改为 Q13 同义反复测谎题
#   - 选项加分标注由 SPEC 原文的中文（视觉/创造）统一改为 3.4 英文枚举值（creation/aesthetics），遵守硬约束 9
#   - "我不知道"计分口径 SPEC 未定义，本产出定为整题跳过（传 None）、不进分母；三题全跳过走兜底返回值并降低 confidence
# === END MANIFEST ===
```
