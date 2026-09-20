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
#   - "我不知道"计分口径 SPEC 未定义，本产出定为整题跳过（传 None）、不进分母；三题全跳过走兜底返回值并降低 confidence
#   - 全 0 兜底：多维维度沿用 score_cognitive_style 的 [0.0] * n；单维维度返回 0.0（未沿用 score_energy_source 的均匀分布写法）
# === END MANIFEST ===

"""Tilt 自我坐标系问卷 Q10-Q18 计分函数。

覆盖三个维度：

- ``score_value_orientation``  Q10-Q12  价值取向（5 维向量）
- ``score_risk_attitude``      Q13-Q15  风险态度（单维标量）
- ``score_abstraction_level``  Q16-Q18  抽象层级（单维标量）

入参约定：
    每题传入选项索引（0 起，见 questionnaire_q10_q18.md 的"顺序即计分索引"表）；
    用户选择"我不知道"时传入 ``None``，该题整题跳过，不计分、不进入归一化分母。

出参约定：
    多维维度返回归一化向量，分量落在 -1 ~ +1，归一化方式与 SPEC 12.2
    ``score_cognitive_style`` 一致（``s / sum(abs(s))``）；
    单维维度返回标量 -1 ~ +1（分值语义见各函数 docstring）。

注意：所有返回值仅表示"坐标系的相对偏向"，不构成"你适合某领域/某职业"的结论，
最终判断权属于用户本人。
"""

from typing import List, Optional, Sequence

# 选项索引常量（顺序与冻结清单 3.4 的枚举顺序一致）
CREATION, HELPING, INFLUENCE, MONEY, AESTHETICS = 0, 1, 2, 3, 4
CONSERVATIVE, NEUTRAL, AGGRESSIVE = 0, 1, 2
THEORY, APPLICATION, OPERATION = 0, 1, 2

# "我不知道"选项的统一取值
UNKNOWN: Optional[int] = None

# 测谎题一致性加权系数（沿用 SPEC 12.2 Q4==Q6 时权重 ×1.5 的写法）
LIE_DETECT_WEIGHT = 1.5


def _normalize(scores: Sequence[float], fallback: List[float]) -> List[float]:
    """把原始加总向量归一化到 -1 ~ +1（与 SPEC 12.2 score_cognitive_style 一致）。

    归一化公式为 ``s / sum(abs(s))``。当所有分量为 0（用户全选"我不知道"，
    或正负相抵）时返回 ``fallback`` 兜底值。

    Args:
        scores: 原始加总向量。
        fallback: 全 0 时的兜底返回值，长度需与 ``scores`` 一致。

    Returns:
        归一化后的向量，分量落在 -1 ~ +1。
    """
    total = sum(abs(s) for s in scores)
    if total == 0:
        return list(fallback)
    return [s / total for s in scores]


def _weighted_mean(
    answers: Sequence[Optional[int]],
    to_value,
    lie_a: Optional[int],
    lie_b: Optional[int],
    lie_index: int,
) -> float:
    """按权重求加权均值，用于单维三分维度的计分。

    Args:
        answers: 三道题的答案索引，``None`` 表示"我不知道"。
        to_value: 索引 -> 分值 的映射函数。
        lie_a: 测谎题组的第一个答案。
        lie_b: 测谎题组的第二个答案（同义反复题）。
        lie_index: 一致性成立时需要加权（×1.5）的那道题在 ``answers`` 中的下标。

    Returns:
        加权均值，落在 -1 ~ +1。三题全部跳过时返回 0.0。
    """
    raw: List[float] = [0.0] * len(answers)
    weights: List[float] = [0.0] * len(answers)

    for i, ans in enumerate(answers):
        if ans is None:
            continue
        raw[i] = to_value(ans)
        weights[i] = 1.0

    # 测谎题一致性加权：两道同义题答案一致，该题权重 ×1.5
    if lie_a is not None and lie_b is not None and lie_a == lie_b:
        if weights[lie_index] > 0:
            weights[lie_index] = LIE_DETECT_WEIGHT

    total_weight = sum(weights)
    if total_weight == 0:
        return 0.0
    return sum(raw[i] * weights[i] for i in range(len(answers))) / total_weight


def score_value_orientation(
    q10: Optional[int],
    q11: Optional[int],
    q12: Optional[int],
) -> List[float]:
    """计算价值取向维度得分（Q10-Q12），返回 5 维向量。

    向量顺序与冻结清单 3.4 一致：
    ``[creation, helping, influence, money, aesthetics]``（创造 / 帮助 / 影响 / 赚钱 / 美感）。

    计分规则：
        - Q10、Q11 为正向题，选中项 +1
        - Q12 为反向题（题干"你最讨厌"），选中项 -1
        - 传 ``None``（用户选"我不知道"）的题整题跳过，不计分、不进入归一化分母

    归一化：``s / sum(abs(s))``，分量落在 -1 ~ +1。
    兜底：三题全部跳过或正负相抵为 0 时，返回 ``[0.0, 0.0, 0.0, 0.0, 0.0]``
    （沿用 SPEC 12.2 ``score_cognitive_style`` 的兜底写法）。

    Args:
        q10: Q10 答案索引（0-4），"我不知道"传 ``None``。
        q11: Q11 答案索引（0-4），"我不知道"传 ``None``。
        q12: Q12 答案索引（0-4），"我不知道"传 ``None``。

    Returns:
        长度为 5 的归一化向量。

    Examples:
        >>> score_value_orientation(0, 0, 4)
        [0.6666666666666666, 0.0, 0.0, 0.0, -0.3333333333333333]
    """
    scores = [0.0, 0.0, 0.0, 0.0, 0.0]

    if q10 is not None:
        scores[q10] += 1
    if q11 is not None:
        scores[q11] += 1
    if q12 is not None:
        scores[q12] -= 1  # 反向题

    return _normalize(scores, [0.0, 0.0, 0.0, 0.0, 0.0])


def score_risk_attitude(
    q13: Optional[int],
    q14: Optional[int],
    q15: Optional[int],
) -> float:
    """计算风险态度维度得分（Q13-Q15），返回单维标量。

    本维度是**单维三分**（``conservative`` / ``neutral`` / ``aggressive``），
    因此**返回标量而非数组**：

        -1.0 = 最保守，0.0 = 中性（或无法区分），+1.0 = 最激进

    与 SPEC 12.2 ``Coordinate.riskAttitude`` 的 "-1（保守）到 +1（激进）" 一致。

    取值映射：``conservative(0) -> -1.0``，``neutral(1) -> 0.0``，``aggressive(2) -> +1.0``。
    测谎题：Q15 是 Q13 的同义反复表述，``q13 == q15`` 时 Q13 权重 ×1.5
    （沿用 SPEC 12.2 Q4==Q6 的加权写法）。
    兜底：三题全部跳过时返回 ``0.0``（中性，且该维度 ``confidence`` 应降低）。

    Args:
        q13: Q13 答案索引（0-2），"我不知道"传 ``None``。
        q14: Q14 答案索引（0-2），"我不知道"传 ``None``。
        q15: Q15 答案索引（0-2），"我不知道"传 ``None``。

    Returns:
        -1.0 ~ +1.0 的标量。

    Examples:
        >>> score_risk_attitude(0, 1, 0)
        -0.7142857142857143
    """

    def to_value(index: int) -> float:
        return float(index) - 1.0  # 保守 -1 / 中性 0 / 激进 +1

    return _weighted_mean((q13, q14, q15), to_value, lie_a=q13, lie_b=q15, lie_index=0)


def score_abstraction_level(
    q16: Optional[int],
    q17: Optional[int],
    q18: Optional[int],
) -> float:
    """计算抽象层级维度得分（Q16-Q18），返回单维标量。

    本维度是**单维三分**（``theory`` / ``application`` / ``operation``），
    因此**返回标量而非数组**：

        +1.0 = 偏理论，0.0 = 偏应用（或无法区分），-1.0 = 偏操作

    与 SPEC 12.2 ``Coordinate.abstractionLevel`` 的 "-1（操作）到 +1（理论）" 一致。

    取值映射：``theory(0) -> +1.0``，``application(1) -> 0.0``，``operation(2) -> -1.0``。
    测谎题：Q18 是 Q16 的同义反复表述，``q16 == q18`` 时 Q16 权重 ×1.5
    （沿用 SPEC 12.2 Q4==Q6 的加权写法）。
    兜底：三题全部跳过（或得分为 0）时返回 ``0.0``，表示"偏应用 / 无法区分"，
    且该维度 ``confidence`` 应降低。

    Args:
        q16: Q16 答案索引（0-2），"我不知道"传 ``None``。
        q17: Q17 答案索引（0-2），"我不知道"传 ``None``。
        q18: Q18 答案索引（0-2），"我不知道"传 ``None``。

    Returns:
        -1.0 ~ +1.0 的标量。

    Examples:
        >>> score_abstraction_level(0, 2, 0)
        0.42857142857142855
    """

    def to_value(index: int) -> float:
        return 1.0 - float(index)  # 理论 +1 / 应用 0 / 操作 -1

    return _weighted_mean((q16, q17, q18), to_value, lie_a=q16, lie_b=q18, lie_index=0)


# ---------------------------------------------------------------------------
# 手算验证示例（每个函数给定输入 -> 期望输出）
# ---------------------------------------------------------------------------
def _run_examples() -> None:
    """打印三个函数的手算验证示例，可直接 `python scoring_functions.py` 运行。"""

    # --- score_value_orientation ---
    # 输入：Q10=A(creation,0) Q11=A(creation,0) Q12=E(aesthetics,4)
    # 手算：[+1,0,0,0,0] + [+1,0,0,0,0] + [0,0,0,0,-1] = [2,0,0,0,-1]
    #       sum(|s|) = 3 -> [2/3, 0, 0, 0, -1/3]
    print("score_value_orientation(0, 0, 4) =", score_value_orientation(0, 0, 4))
    print("  期望: [0.6666666666666666, 0.0, 0.0, 0.0, -0.3333333333333333]")

    # 输入：三题全选"我不知道"
    print("score_value_orientation(None, None, None) =", score_value_orientation(None, None, None))
    print("  期望: [0.0, 0.0, 0.0, 0.0, 0.0]")

    # --- score_risk_attitude ---
    # 输入：Q13=A(conservative,0 -> -1.0) Q14=B(neutral,1 -> 0.0) Q15=A(conservative,0 -> -1.0)
    # 测谎：q13 == q15 -> Q13 权重 1.5，其余各 1.0，总权重 3.5
    # 手算：(1.5*(-1.0) + 1.0*0.0 + 1.0*(-1.0)) / 3.5 = -2.5 / 3.5 = -0.7142857...
    print("score_risk_attitude(0, 1, 0) =", score_risk_attitude(0, 1, 0))
    print("  期望: -0.7142857142857143")

    # 输入：Q13=C(aggressive) Q15=C(aggressive)，测谎一致，全部激进
    # 手算：(1.5*1.0 + 1.0*1.0 + 1.0*1.0) / 3.5 = 1.0（上界）
    print("score_risk_attitude(2, 2, 2) =", score_risk_attitude(2, 2, 2))
    print("  期望: 1.0")

    # --- score_abstraction_level ---
    # 输入：Q16=A(theory,0 -> +1.0) Q17=C(operation,2 -> -1.0) Q18=A(theory,0 -> +1.0)
    # 测谎：q16 == q18 -> Q16 权重 1.5，其余各 1.0，总权重 3.5
    # 手算：(1.5*1.0 + 1.0*(-1.0) + 1.0*1.0) / 3.5 = 1.5 / 3.5 = 0.4285714...
    print("score_abstraction_level(0, 2, 0) =", score_abstraction_level(0, 2, 0))
    print("  期望: 0.42857142857142855")

    # 输入：Q16=B(application) Q18=C(operation)，测谎不一致，不加权，总权重 3.0
    # 手算：(1.0*0.0 + 1.0*0.0 + 1.0*(-1.0)) / 3.0 = -0.3333333...
    print("score_abstraction_level(1, 1, 2) =", score_abstraction_level(1, 1, 2))
    print("  期望: -0.3333333333333333")


if __name__ == "__main__":
    _run_examples()

# ---------------------------------------------------------------------------
# 备注
# 1. SPEC 12.2 的 Q18 原文为「请重复选择 Q1 的答案」（认知风格测谎题），与本任务 6.1
#    的 Q16-Q18 -> abstraction_level 分工冲突，本产出按本任务执行，需产品确认后回填 SPEC。
# 2. SPEC 12.2 的 Q15 原文为「你愿意为高回报冒多大风险？」，为满足 6.3 每维含 1 道反向题
#    或测谎题，改为 Q13 的同义反复测谎题，原语义由 Q13 承接。
# 3. 全 0 兜底存在两种 SPEC 写法（cognitive_style 的全 0 / energy_source 的均匀分布），
#    本产出多维维度统一沿用 cognitive_style 的全 0 写法。
# 4. "我不知道"的计分口径 SPEC 未定义，本产出定为整题跳过、不进分母；上层仍应按
#    SPEC 12.7 降低该维度 confidence。
# ---------------------------------------------------------------------------
