"""成品质检抽样：总分钟预算内每个窑次至少抽中一件，最大化风险分总和。

针对已保存方案的全部器物（每件带非负风险分与正整数检验分钟数）与总分钟
预算，选出一份抽样集合，要求：

  * 总耗时（抽中器物检验分钟数之和）不超过总分钟预算；
  * 每个窑次至少抽中一件器物。

在所有可行集合中按以下优先级择优：
  1. 风险分总和最大；
  2. 总耗时最小；
  3. 抽中编号升序列表字典序最小（标准字符串字典序，前缀视为更小）。

各窑器物互不相交，故任何可行集合的耗时不低于「每窑各抽一件最低耗时器物」
的耗时之和，而每窑各取一件最低耗时器物即达到该下界——预算低于此和时
无可行集合，抛出 NoFeasibleInspectionSampleError。

算法（n ≤ 14，器物按编号升序排列，位 i 对应第 i 件）：
  枚举全部 2^n 个器物子集，用「去掉最低位 + 一件」递推每个子集的总耗时、
  风险分总和与窑次覆盖位掩码；扫描全部子集，在「覆盖集满全部窑次且
  总耗时不超过预算」的子集中按上述三级键取最优。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


class NoFeasibleInspectionSampleError(ValueError):
    """总分钟预算内不存在覆盖全部窑次的抽样集合。"""


@dataclass(frozen=True)
class InspectionItem:
    """一件器物的质检参数：非负风险分与正整数检验分钟数。"""

    item_id: str
    risk_score: int
    inspect_minutes: int


@dataclass(frozen=True)
class KilnInspection:
    """一个窑次的抽样覆盖明细：抽中编号按升序。"""

    kiln_index: int
    sampled_item_ids: tuple[str, ...]


@dataclass(frozen=True)
class InspectionSample:
    """抽样结果：抽中编号（升序）、各窑覆盖明细、总风险分与总耗时。"""

    sampled_item_ids: tuple[str, ...]
    total_risk_score: int
    total_inspect_minutes: int
    kilns: tuple[KilnInspection, ...]


def select_inspection_sample(
    kiln_item_ids: Sequence[Sequence[str]],
    items: Sequence[InspectionItem],
    budget_minutes: int,
) -> InspectionSample:
    """在总分钟预算内选出覆盖全部窑次的最优抽样集合。

    择优优先级：风险分总和最大 → 总耗时最小 → 抽中编号升序列表
    字典序最小。

    :param kiln_item_ids: 方案各窑的器物编号（窑次序号从 1 开始，与列表顺序一致）
    :param items: 全部器物的质检参数（编号须恰好覆盖各窑器物，不重复）
    :param budget_minutes: 总分钟预算（非负整数）
    :raises NoFeasibleInspectionSampleError: 预算内不存在覆盖全部窑次的抽样集合。
    :raises ValueError: 窑次列表为空 / 编号未恰好覆盖各窑器物或有重复 /
        风险分、检验分钟数或预算非法。
    """

    if not kiln_item_ids:
        raise ValueError("方案至少包含一个窑次")
    if budget_minutes < 0:
        raise ValueError("总分钟预算不得为负")

    kiln_of: dict[str, int] = {}
    for idx, kiln_ids in enumerate(kiln_item_ids):
        if not kiln_ids:
            raise ValueError(f"窑次 {idx + 1} 不含任何器物")
        for item_id in kiln_ids:
            kiln_of[item_id] = idx  # 窑次序号（0 起）

    n = len(kiln_of)
    if n > 14:
        raise ValueError("器物数量不得超过 14 件")

    param_by_id: dict[str, InspectionItem] = {}
    for it in items:
        if it.item_id in param_by_id:
            raise ValueError(f"器物编号不得重复: {it.item_id}")
        if it.risk_score < 0:
            raise ValueError(f"器物 {it.item_id} 的风险分不得为负")
        if it.inspect_minutes < 1:
            raise ValueError(f"器物 {it.item_id} 的检验分钟数必须为正整数")
        param_by_id[it.item_id] = it

    unknown = sorted(set(param_by_id) - set(kiln_of))
    if unknown:
        raise ValueError("以下器物编号不属于原方案: " + ", ".join(unknown))
    missing = sorted(set(kiln_of) - set(param_by_id))
    if missing:
        raise ValueError(
            "质检参数必须覆盖原方案全部器物，缺少编号: " + ", ".join(missing)
        )

    # 器物按编号字典序升序排列；位 i 对应排序后的第 i 件。
    ids = sorted(kiln_of)
    k = len(kiln_item_ids)
    full_kilns = (1 << k) - 1
    minutes_of = [param_by_id[i].inspect_minutes for i in ids]
    risk_of = [param_by_id[i].risk_score for i in ids]
    kiln_bit = [1 << kiln_of[i] for i in ids]

    # ---- 枚举全部子集：递推总耗时、风险分总和与窑次覆盖位掩码 ----
    size = 1 << n
    sum_minutes = [0] * size
    sum_risk = [0] * size
    cover = [0] * size
    for mask in range(1, size):
        bit = mask & -mask  # 最低位
        i = bit.bit_length() - 1
        prev = mask ^ bit
        sum_minutes[mask] = sum_minutes[prev] + minutes_of[i]
        sum_risk[mask] = sum_risk[prev] + risk_of[i]
        cover[mask] = cover[prev] | kiln_bit[i]

    # ---- 在覆盖全部窑次且不超预算的子集中按三级键择优 ----
    best_risk = -1
    best_minutes = 0
    best_tuple: tuple[str, ...] | None = None
    for mask in range(1, size):
        if cover[mask] != full_kilns or sum_minutes[mask] > budget_minutes:
            continue
        risk = sum_risk[mask]
        minutes = sum_minutes[mask]
        if best_tuple is not None and (
            risk < best_risk or (risk == best_risk and minutes > best_minutes)
        ):
            continue
        members = tuple(ids[i] for i in range(n) if (mask >> i) & 1)
        if (
            best_tuple is not None
            and risk == best_risk
            and minutes == best_minutes
            and members >= best_tuple
        ):
            continue
        best_risk = risk
        best_minutes = minutes
        best_tuple = members

    if best_tuple is None:
        # 各窑最低单件耗时之和即覆盖全部窑次所需的最小耗时（下界可达）。
        min_required = sum(
            min(param_by_id[i].inspect_minutes for i in kiln_ids)
            for kiln_ids in kiln_item_ids
        )
        raise NoFeasibleInspectionSampleError(
            f"总分钟预算 {budget_minutes} 内不存在覆盖全部 {k} 个窑次的抽样方案: "
            f"每个窑次至少抽中一件所需最低耗时为 {min_required} 分钟"
        )

    sampled_set = set(best_tuple)
    kilns_out = tuple(
        KilnInspection(
            kiln_index=idx,
            sampled_item_ids=tuple(
                sorted(i for i in kiln_ids if i in sampled_set)
            ),
        )
        for idx, kiln_ids in enumerate(kiln_item_ids, start=1)
    )

    return InspectionSample(
        sampled_item_ids=best_tuple,
        total_risk_score=best_risk,
        total_inspect_minutes=best_minutes,
        kilns=kilns_out,
    )
