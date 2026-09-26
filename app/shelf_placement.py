"""窑内层位安排：器物与层位一一分配，最大化到温区边界的最小温差。

针对某一窑次（烧成温度 firing_temp = 该窑器物温区交集下界）与一组层位：
  * 层位 s 带唯一编号与整数温度偏移 off_s，器物 i 入位后的实际温度为
    t = firing_temp + off_s；
  * 仅当实际温度落入器物 i 的原温度闭区间 [temp_low_i, temp_high_i] 时
    该入位可行，此时到最近温区边界的温差为
    margin(i, s) = min(t - temp_low_i, temp_high_i - t)（非负整数）。

求器物与层位的一一分配（完美匹配，二者数量相同），使全部器物温差的
最小值最大；最优值并列时，按器物编号升序排列所配层位编号，取该层位
编号序列字典序最小者（标准字符串字典序，与全项目编号排序一致）。

算法（n ≤ 14，器物 / 层位均按编号升序排列，位 j 对应第 j 个层位）：

  1. 温差矩阵 w[i][j]：不可行记 -1，否则记器物 i 入层位 j 的温差；
     同时把「w[i][j] 不低于阈值 D」的可行层位预存为邻接位掩码。
  2. 阈值完美匹配 DP——给定阈值 D，can[mask] 表示层位集合 mask 能否恰好
     匹配给按编号升序的前 popcount(mask) 件器物：器物 k 可接在 mask 的
     匹配末尾当且仅当它在 mask 内有一个阈值可行层位 j 且 can[mask\\j]
     为真；can[全集] 即该阈值下是否存在完美匹配。
  3. 最优阈值 D*：候选温差（矩阵中的非负值，含 0）按升序排列；阈值图的
     完美匹配可行性对阈值单调（D 下降只会增加可行边），故在候选列表上
     **二分查找**存在完美匹配的最大阈值；一个可行候选都没有时无完整
     可行分配。
  4. 贪心重建字典序最小序列：器物按编号升序逐件确定，每步在层位编号
     升序枚举中取首个满足「剩余器物在 w ≥ D* 的阈值图上仍可完美匹配」
     的层位（后缀可匹配表与 can 同为位掩码 DP），所得层位编号序列即在
     全部最优分配中字典序最小者。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .solver import Ware

# 不可行状态标记（温差恒为非负整数，-1 专用于表示无可行入位）
_INFEASIBLE = -1


class NoFeasibleShelfPlacementError(ValueError):
    """器物与层位间不存在使每件实际温度均落入原温度闭区间的完整一一分配。"""


@dataclass(frozen=True)
class Shelf:
    """一个层位：唯一编号与整数温度偏移。"""

    shelf_id: str
    temp_offset: int


@dataclass(frozen=True)
class ShelfPlacementItem:
    """一件器物的入位结果。"""

    item_id: str
    shelf_id: str
    actual_temp: int
    min_temp_gap: int


@dataclass(frozen=True)
class ShelfPlacement:
    """整窑层位安排：逐件入位结果（按器物编号升序）与全局最小温差。"""

    min_temp_gap: int
    items: tuple[ShelfPlacementItem, ...]


def _adjacency_bits(w: Sequence[Sequence[int]], n: int, d: int) -> list[int]:
    """adj[i]：器物 i 在阈值 d 下可行层位的位掩码（w[i][j] >= d）。"""

    adj = [0] * n
    for i in range(n):
        wi = w[i]
        bits = 0
        for j in range(n):
            if wi[j] >= d:
                bits |= 1 << j
        adj[i] = bits
    return adj


def _has_perfect_matching(adj: Sequence[int], n: int) -> bool:
    """阈值邻接（adj[i] 为器物 i 的可行层位位掩码）下是否存在完美匹配。

    can[mask] 为真当且仅当层位集合 mask 能恰好匹配给按编号升序的前
    popcount(mask) 件器物：最后一件器物 k 取 mask 内任一阈值可行层位 j，
    且其余层位能匹配前 k 件器物。
    """

    size = 1 << n
    can = bytearray(size)
    can[0] = 1
    for mask in range(1, size):
        k = mask.bit_count() - 1  # 第 k 件器物（0 起）是该前缀中最后待配的一件
        choices = adj[k] & mask
        while choices:
            bit = choices & -choices
            if can[mask ^ bit]:
                can[mask] = 1
                break
            choices ^= bit
    return bool(can[size - 1])


def _suffix_match_table(adj: Sequence[int], n: int) -> list[bytearray]:
    """后缀可完美匹配表：suffix[k][mask] 为真当且仅当器物 k..n-1 能恰好
    匹配到层位集合 mask。供贪心重建逐件判定剩余可配性。"""

    size = 1 << n
    suffix = [bytearray(size) for _ in range(n + 1)]
    suffix[n][0] = 1
    for k in range(n - 1, -1, -1):
        row = suffix[k]
        nxt = suffix[k + 1]
        ak = adj[k]
        for mask in range(1, size):
            choices = ak & mask
            if not choices:
                continue
            sub = choices
            while sub:
                bit = sub & -sub
                if nxt[mask ^ bit]:
                    row[mask] = 1
                    break
                sub ^= bit
    return suffix


def place_shelves(
    firing_temp: int,
    items: Sequence[Ware],
    shelves: Sequence[Shelf],
    kiln_index: int = 1,
) -> ShelfPlacement:
    """求器物与层位一一分配，最大化到温区边界的最小温差。

    器物按编号字典序升序、层位按编号字典序升序排列后做位掩码 DP；
    最优值并列时取「器物编号升序所配层位编号序列」字典序最小者。

    :param firing_temp: 该窑烧成温度（方案保存的温区交集下界）
    :param items: 该窑全部器物（含原温度闭区间）
    :param shelves: 层位列表，数量必须与器物数相同，编号互不相同
    :param kiln_index: 窑次序号（从 1 开始，仅用于结果与错误信息）
    :raises NoFeasibleShelfPlacementError: 不存在完整可行的一一分配。
    :raises ValueError: 器物为空 / 超过 14 件 / 层位数量不符 / 层位编号重复。
    """

    n = len(items)
    if n == 0:
        raise ValueError("至少需要一件器物")
    if n > 14:
        raise ValueError("器物数量不得超过 14 件")
    if len(shelves) != n:
        raise ValueError(
            f"层位数量必须与该窑器物数相同: 器物 {n} 件，层位 {len(shelves)} 个"
        )

    ordered_items = sorted(items, key=lambda it: it.item_id)
    ordered_shelves = sorted(shelves, key=lambda s: s.shelf_id)
    shelf_ids = [s.shelf_id for s in ordered_shelves]
    if len(set(shelf_ids)) != n:
        raise ValueError("层位编号必须唯一")

    # ---- 1. 温差矩阵 w[i][j]（不可行为 -1） ----
    w = [[_INFEASIBLE] * n for _ in range(n)]
    for i, item in enumerate(ordered_items):
        for j, shelf in enumerate(ordered_shelves):
            actual = firing_temp + shelf.temp_offset
            if item.temp_low <= actual <= item.temp_high:
                w[i][j] = min(
                    actual - item.temp_low,
                    item.temp_high - actual,
                )

    # ---- 2+3. 最优阈值 D*：候选温差升序，阈值可行性单调，二分查找 ----
    candidates = sorted(
        {w[i][j] for i in range(n) for j in range(n) if w[i][j] >= 0}
    )
    optimum: int | None = None
    lo, hi = 0, len(candidates) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        d = candidates[mid]
        if _has_perfect_matching(_adjacency_bits(w, n, d), n):
            optimum = d
            lo = mid + 1
        else:
            hi = mid - 1

    if optimum is None:
        stranded = [
            ordered_items[i].item_id
            for i in range(n)
            if all(m < 0 for m in w[i])
        ]
        detail = ""
        if stranded:
            detail = "；以下器物对全部层位均不可行: " + ", ".join(stranded)
        raise NoFeasibleShelfPlacementError(
            f"窑次 {kiln_index} 不存在完整可行的层位分配: {n} 件器物与 {n} 个层位"
            "无法一一配对，使每件器物入位后的实际温度（该窑烧成温度 "
            f"{firing_temp} 加层位温度偏移）均落入其原温度闭区间{detail}"
        )

    # ---- 4. 贪心重建：每层取编号最小、且剩余仍可在阈值 D* 下完美匹配者 ----
    adj = _adjacency_bits(w, n, optimum)
    suffix = _suffix_match_table(adj, n)
    assignments: list[ShelfPlacementItem] = []
    mask = (1 << n) - 1
    for i, item in enumerate(ordered_items):
        chosen = -1
        choices = adj[i] & mask
        for j in range(n):  # 层位编号升序枚举，首个可扩展最优解者即字典序最小
            bit = 1 << j
            if (choices & bit) and suffix[i + 1][mask ^ bit]:
                chosen = j
                break
        if chosen < 0:  # 阈值 D* 已被验证存在完美匹配，重建必能找到（理论不可达）
            raise AssertionError("层位安排重建失败：当前器物无层位可取")
        shelf = ordered_shelves[chosen]
        actual = firing_temp + shelf.temp_offset
        assignments.append(
            ShelfPlacementItem(
                item_id=item.item_id,
                shelf_id=shelf.shelf_id,
                actual_temp=actual,
                min_temp_gap=w[i][chosen],
            )
        )
        mask ^= 1 << chosen

    assert mask == 0
    return ShelfPlacement(min_temp_gap=optimum, items=tuple(assignments))
