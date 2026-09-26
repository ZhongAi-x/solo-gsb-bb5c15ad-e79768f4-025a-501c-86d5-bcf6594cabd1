"""烧成费用分摊：每窑按器物体积比例、受单件收费上限约束分摊费用（分）。

各窑次独立分摊。窑内器物 i 的体积为 v_i、收费上限为 c_i（均为非负 /
正整数，单位分），该窑费用为 C（非负整数分）：

  * 器物 i 的精确份额为 min(c_i, λ·v_i)，λ 取使各器物份额之和恰为 C
    的非负有理数；λ 用 Fraction 精确求解，全程无浮点误差。
  * λ 的几何含义即「水位」：λ 较小时全部器物按 λ·v_i 计费；抬高水位时
    先达到 cap/体积 比值（= c_i/v_i）的器物被上限「饱和」，之后费用只
    在未饱和器物间按体积继续分配。故可按 c_i/v_i 升序逐个饱和器物，
    每步令 λ = 剩余费用 / 未饱和器物总体积，直到 λ 不超过下一器物的
    饱和比值；并列次序不影响结果。
  * 费用超过该窑全部器物上限之和时无解，抛出 InsufficientCapError。

得到精确份额后转为整数分：各件先向下取整（floor），取整产生的剩余分
数量严格少于器物数（每件小数余数在 [0,1) 内，且精确份额合计恰为整数
费用），再按「小数余数降序、器物编号升序」逐一补 1 分。因此每件分摊
为非负整数且不超过上限，每窑合计严格等于请求费用。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction


class InsufficientCapError(ValueError):
    """某窑费用高于该窑全部器物收费上限之和，使份额和为费用的 λ 不存在。"""

    def __init__(self, kiln_index: int, cost: int, cap_sum: int) -> None:
        self.kiln_index = kiln_index
        self.cost = cost
        self.cap_sum = cap_sum
        super().__init__(
            f"窑次 {kiln_index} 的烧成费用 {cost} 分超过该窑器物收费上限之和 "
            f"{cap_sum} 分：上限总和不足，无法按体积比例分摊"
        )


@dataclass(frozen=True)
class CostShare:
    """一件器物在所属窑内的分摊结果。"""

    item_id: str
    volume: int
    cap: int
    share: int
    """最终整数费用（分），满足 0 ≤ share ≤ cap。"""
    exact_share: Fraction
    """取整前的精确份额 min(cap, λ·volume)。"""


@dataclass(frozen=True)
class KilnCostAllocation:
    """一个窑次的分摊结果：器物份额按编号升序。"""

    kiln_index: int
    cost: int
    total_volume: int
    shares: tuple[CostShare, ...]


@dataclass(frozen=True)
class CostAllocation:
    """整份方案的分摊结果：各窑独立分摊，总额等于请求费用合计。"""

    total_cost: int
    kilns: tuple[KilnCostAllocation, ...]


def allocate_kiln_cost(
    kiln_index: int,
    members: Sequence[tuple[str, int]],
    caps: Mapping[str, int],
    cost: int,
) -> KilnCostAllocation:
    """分摊单个窑次的费用。

    :param kiln_index: 窑次序号（从 1 开始，仅用于结果与错误信息）
    :param members: 本窑器物 ``(编号, 体积)`` 序列，非空；体积为正整数
    :param caps: 器物编号 -> 收费上限（分，非负整数），须覆盖本窑全部器物
    :param cost: 该窑烧成费用（分，非负整数）
    :returns: 各器物整数份额（编号升序），合计严格等于 ``cost``
    :raises InsufficientCapError: 费用超过本窑器物上限之和
    """

    members = sorted(members, key=lambda m: m[0])  # 编号升序，输出确定
    total_volume = sum(volume for _, volume in members)
    cap_sum = sum(caps[item_id] for item_id, _ in members)
    if cost > cap_sum:
        raise InsufficientCapError(kiln_index, cost, cap_sum)

    # ---- 1. 水位法精确求 λ：按 cap/体积 升序逐个饱和器物 ----
    # 饱和比值相同时按编号升序处理；λ 恰等于比值时饱和与否份额相同，
    # 故并列次序不影响最终结果。
    order = sorted(
        members,
        key=lambda m: (Fraction(caps[m[0]], m[1]), m[0]),
    )
    remaining = Fraction(cost)
    active_volume = total_volume
    saturated: set[str] = set()
    lam: Fraction | None = None
    for item_id, volume in order:
        candidate = remaining / active_volume
        if candidate < Fraction(caps[item_id], volume):
            lam = candidate
            break
        # candidate >= 饱和比值：该器物被上限截断为 cap，移出未饱和集合
        saturated.add(item_id)
        remaining -= caps[item_id]
        active_volume -= volume
    # cost == cap_sum 时全部器物恰好饱和（lam 仍为 None）；
    # cost < cap_sum 时必有未饱和器物，lam 已在上方求出。

    # ---- 2. 精确份额（Fraction，合计恰为费用） ----
    exact: dict[str, Fraction] = {}
    for item_id, volume in members:
        if item_id in saturated:
            exact[item_id] = Fraction(caps[item_id])
        else:
            assert lam is not None  # 未饱和器物存在时 λ 必已求出
            exact[item_id] = lam * volume
    assert sum(exact.values()) == Fraction(cost)

    # ---- 3. 向下取整 + 剩余分按小数余数降序、编号升序逐一补齐 ----
    floors = {
        item_id: value.numerator // value.denominator
        for item_id, value in exact.items()
    }
    leftover = cost - sum(floors.values())
    assert 0 <= leftover < len(members)  # 每件余数在 [0,1)，合计为整数
    winners = sorted(
        members,
        # floor - exact = -小数余数：升序即余数降序；余数相同按编号升序
        key=lambda m: (floors[m[0]] - exact[m[0]], m[0]),
    )[:leftover]

    shares = dict(floors)
    for item_id, _ in winners:
        shares[item_id] += 1

    return KilnCostAllocation(
        kiln_index=kiln_index,
        cost=cost,
        total_volume=total_volume,
        shares=tuple(
            CostShare(
                item_id=item_id,
                volume=volume,
                cap=caps[item_id],
                share=shares[item_id],
                exact_share=exact[item_id],
            )
            for item_id, volume in members
        ),
    )


def allocate_plan_costs(
    kiln_members: Sequence[tuple[int, Sequence[tuple[str, int]]]],
    caps: Mapping[str, int],
    costs: Mapping[int, int],
) -> CostAllocation:
    """对整份方案逐窑独立分摊。

    :param kiln_members: ``(窑次序号, 本窑器物 (编号, 体积) 序列)`` 序列，
        窑次次序即输出次序；每件器物恰属于一个窑次
    :param caps: 器物编号 -> 收费上限（分），须覆盖全部器物
    :param costs: 窑次序号 -> 烧成费用（分），须覆盖全部窑次
    :returns: 各窑分摊明细与费用合计（等于 ``costs`` 值之和）
    """

    results: list[KilnCostAllocation] = []
    total_cost = 0
    for kiln_index, members in kiln_members:
        cost = costs[kiln_index]
        results.append(allocate_kiln_cost(kiln_index, members, caps, cost))
        total_cost += cost
    return CostAllocation(total_cost=total_cost, kilns=tuple(results))
