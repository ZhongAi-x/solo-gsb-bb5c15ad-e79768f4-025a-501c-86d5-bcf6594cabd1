"""单台实体窑点火排程：全部批次均不逾期时的最早整体完工。

针对已保存方案的全部窑次（每窑次为一批），每批给出：
  * 最早可点火分钟 r（从同一排程起点计算，非负整数）；
  * 烧成时长 p（分钟，正整数）；
  * 最迟完成分钟 d（从同一排程起点计算，非负整数）。

单台窑同一时刻只能烧一批（不可并行），批次之间允许空闲；
每批一旦点火便连续烧完（不中断）。求全部批次均不逾期
（完成时刻 <= 最迟完成分钟）时最早的整体完工时刻，
并给出各批次的点火 / 完成分钟与点火顺序。

算法（n = 批次数，不超过 14，与装窑求解器同为位掩码 DP 风格）：

  1. 前向位掩码 DP：dp[mask] 为烧完 mask 全部批次（均不逾期）的最早
     完工时刻，不可行为 None。最后烧批次 j 时，其余批次越早完工越好
     （dp[mask ^ j] 即最早），j 的点火时刻为 max(dp[mask ^ j], r_j)，
     完工不超过 d_j 才可行；dp[mask] 取全部可行 j 的最小完工时刻。
     dp[全集] 即最早整体完工时刻 T*。

  2. 反向位掩码 DP：ls[mask] 为在窗口 [τ, T*] 内烧完 mask 全部批次
     （均不逾期）的最迟可开始时刻 τ，不可行为 None。窗口内首先烧批次 j
     时，j 的点火时刻 s 须满足 s >= r_j、s + p_j <= d_j，且剩余批次能在
     [s + p_j, T*] 内烧完，即 s <= min(d_j, ls[mask ^ j]) - p_j；
     ls[mask] 取全部可行 j 的该上界最大值。由于允许空闲，从更早时刻
     开始总是可行，故「mask 能从时刻 τ 开始烧完」当且仅当 τ <= ls[mask]。

  3. 贪心重建：从排程起点按点火顺序逐批确定。当前时刻 t、剩余批次
     集合 R 时，批次 j 可接在下一个当且仅当
     max(t, r_j) + p_j <= min(d_j, ls[R ^ j])
     （j 自身不逾期，且剩余批次仍能在窗口内烧完）。每步在满足条件的
     批次中取窑次序号最小者；不变式 t <= ls[R] 保证每步必有可取批次，
     所得点火顺序在所有「整体完工时刻 = T*」的排程中，
     按窑次序号序列字典序最小。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


class NoFeasibleFiringOrderError(ValueError):
    """无可行点火顺序：单台窑无法在全部最迟完成分钟内烧完全部批次。"""


@dataclass(frozen=True)
class FiringBatch:
    """一批（一个窑次）的点火约束；分钟均从同一排程起点计算。"""

    kiln_index: int          # 窑次序号（与方案中一致，从 1 开始）
    earliest_start: int      # 最早可点火分钟（非负）
    duration: int            # 烧成时长（分钟，正整数）
    latest_completion: int   # 最迟完成分钟（非负）


@dataclass(frozen=True)
class ScheduledBatch:
    """一批的点火安排：点火 / 完成分钟（从同一排程起点计算）。"""

    kiln_index: int
    start: int
    completion: int


@dataclass(frozen=True)
class FiringSchedule:
    """点火排程结果：最早整体完工时刻与各批安排（按点火顺序）。"""

    makespan: int
    batches: tuple[ScheduledBatch, ...]


def earliest_firing_schedule(batches: Sequence[FiringBatch]) -> FiringSchedule:
    """求全部批次均不逾期时最早整体完工的点火排程。

    单台窑不可并行、允许空闲；分钟均从同一排程起点计算。
    最早整体完工时刻相同的排程并列时，取点火顺序（窑次序号序列）
    字典序最小者；返回批次按点火顺序排列。

    :param batches: 全部批次（1～14 个，窑次序号互不重复）
    :raises NoFeasibleFiringOrderError: 不存在全部批次均不逾期的点火顺序。
    :raises ValueError: 批次为空 / 超过 14 个 / 窑次序号重复 /
        分钟为负 / 烧成时长非正。
    """

    n = len(batches)
    if n == 0:
        raise ValueError("至少需要一个批次")
    if n > 14:
        raise ValueError("批次数量不得超过 14 个")
    if len({b.kiln_index for b in batches}) != n:
        raise ValueError("窑次序号不得重复")
    for b in batches:
        if b.earliest_start < 0 or b.latest_completion < 0:
            raise ValueError("最早可点火分钟与最迟完成分钟均须为非负整数")
        if b.duration < 1:
            raise ValueError("烧成时长须为正整数")

    # 批次按窑次序号升序排列；位 i 对应排序后的第 i 批。
    ordered = sorted(batches, key=lambda b: b.kiln_index)
    r = [b.earliest_start for b in ordered]
    p = [b.duration for b in ordered]
    d = [b.latest_completion for b in ordered]
    size = 1 << n
    full = size - 1

    # ---- 1. 前向 DP：dp[mask] = 烧完 mask（均不逾期）的最早完工时刻 ----
    dp: list[int | None] = [None] * size
    dp[0] = 0
    for mask in range(1, size):
        best: int | None = None
        m = mask
        while m:
            bit = m & -m
            j = bit.bit_length() - 1
            prev = dp[mask ^ bit]
            if prev is not None:
                c = max(prev, r[j]) + p[j]
                if c <= d[j] and (best is None or c < best):
                    best = c
            m ^= bit
        dp[mask] = best

    makespan = dp[full]
    if makespan is None:
        raise NoFeasibleFiringOrderError(
            f"无可行点火顺序：单台窑不可并行，全部 {n} 批无法同时满足各自的"
            "最早可点火分钟与最迟完成分钟约束"
        )

    # ---- 2. 反向 DP：ls[mask] = 窗口 [τ, T*] 内烧完 mask 的最迟开始时刻 ----
    ls: list[int | None] = [None] * size
    ls[0] = makespan
    for mask in range(1, size):
        best = None
        m = mask
        while m:
            bit = m & -m
            j = bit.bit_length() - 1
            rest = ls[mask ^ bit]
            if rest is not None:
                bound = min(d[j], rest) - p[j]
                if r[j] <= bound and (best is None or bound > best):
                    best = bound
            m ^= bit
        ls[mask] = best

    # ---- 3. 贪心重建：点火顺序按窑次序号序列字典序最小 ----
    scheduled: list[ScheduledBatch] = []
    t = 0
    remaining = full
    while remaining:
        for j in range(n):  # 窑次序号升序枚举，首个可取者即字典序最小选择
            bit = 1 << j
            if not remaining & bit:
                continue
            c = max(t, r[j]) + p[j]
            rest = ls[remaining ^ bit]
            if rest is not None and c <= d[j] and c <= rest:
                scheduled.append(
                    ScheduledBatch(
                        kiln_index=ordered[j].kiln_index,
                        start=max(t, r[j]),
                        completion=c,
                    )
                )
                t = c
                remaining ^= bit
                break
        else:  # 不变式 t <= ls[remaining] 保证必有可取批次，理论不可达
            raise AssertionError("点火排程重建失败：当前无批次可接")

    assert t == makespan
    return FiringSchedule(makespan=makespan, batches=tuple(scheduled))
