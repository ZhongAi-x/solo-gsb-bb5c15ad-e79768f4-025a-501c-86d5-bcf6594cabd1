"""窑次温控核验：按分段线性插值精确求解合格温区内的最长连续时段。

输入为按时间严格递增的温度采样（整数秒、整数温度）、合格温区闭区间
[temp_low, temp_high]（该窑器物温区交集）、正整数最低连续保温秒数与
正整数最大采样间隔。相邻采样点之间温度按线性变化；相邻采样间隔超过
上限时曲线在该段断开（段内不计入），且不在首末采样点之外外推。

全部中间量使用 Fraction 精确计算：对每个未断开的采样段，温度关于时间
为线性（单调）函数，落在闭区间内的时刻集合是一个闭区间，端点为采样
时刻或温度恰好等于温区边界的穿越时刻（有理数）。相邻段在采样点处
端点相接即合并为同一连续时段；取时长最长者，等长取开始最早；
无正时长时段时起止为 None、时长为 0。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction


@dataclass(frozen=True)
class TemperatureCheckResult:
    """最长合格时段。

    start / end 为起止时刻（秒，精确分数）；无正时长时段时均为 None，
    duration 为 0。meets_requirement 表示 duration 是否达到最低连续保温秒数。
    """

    start: Fraction | None
    end: Fraction | None
    duration: Fraction
    meets_requirement: bool


def longest_qualified_period(
    samples: Sequence[tuple[int, int]],
    temp_low: int,
    temp_high: int,
    min_hold_seconds: int,
    max_interval_seconds: int,
) -> TemperatureCheckResult:
    """求温度落在合格温区闭区间内的最长连续时段。

    :param samples: (时刻秒, 温度) 序列，时刻严格递增（至少 1 个采样点）
    :param temp_low: 合格温区下界（该窑器物温区交集下界）
    :param temp_high: 合格温区上界（交集上界），须 temp_low <= temp_high
    :param min_hold_seconds: 最低连续保温秒数（正整数）
    :param max_interval_seconds: 最大采样间隔秒数（正整数）；相邻采样间隔
        超过该值时曲线在该处断开，断开段不计入
    :returns: 最长合格时段；等长取开始最早，无正时长时起止为 None、时长 0
    """

    # ---- 1. 逐段求落在温区内的正时长闭区间（精确分数端点） ----
    intervals: list[tuple[Fraction, Fraction]] = []
    for (t0, temp0), (t1, temp1) in zip(samples, samples[1:]):
        span = t1 - t0
        if span > max_interval_seconds:
            continue  # 采样间隔超限：该段断开，不计入
        slope = temp1 - temp0
        if slope == 0:
            if temp_low <= temp0 <= temp_high:
                intervals.append((Fraction(t0), Fraction(t1)))
            continue

        def _t_at(target: int) -> Fraction:
            # 段内温度线性变化，温度等于 target 的时刻（精确分数）
            return Fraction(t0) + Fraction(target - temp0) * span / slope

        if slope > 0:  # 升温：先进入下界，后越出上界
            enter, leave = _t_at(temp_low), _t_at(temp_high)
        else:  # 降温：先进入上界，后越出下界
            enter, leave = _t_at(temp_high), _t_at(temp_low)
        start = max(Fraction(t0), enter)
        end = min(Fraction(t1), leave)
        if start < end:  # 仅保留正时长段（单点接触时长为 0，不计）
            intervals.append((start, end))

    # ---- 2. 相邻段在采样点处端点相接则合并为同一连续时段 ----
    merged: list[list[Fraction]] = []
    for start, end in intervals:
        if merged and merged[-1][1] == start:
            merged[-1][1] = end
        else:
            merged.append([start, end])

    # ---- 3. 取时长最长者；等长不替换，保留开始最早 ----
    best: tuple[Fraction, Fraction] | None = None
    for start, end in merged:
        if best is None or end - start > best[1] - best[0]:
            best = (start, end)

    if best is None:
        return TemperatureCheckResult(
            start=None,
            end=None,
            duration=Fraction(0),
            meets_requirement=Fraction(0) >= min_hold_seconds,
        )
    duration = best[1] - best[0]
    return TemperatureCheckResult(
        start=best[0],
        end=best[1],
        duration=duration,
        meets_requirement=duration >= min_hold_seconds,
    )


def format_fraction(value: Fraction | None) -> str | None:
    """把精确分数格式化为约分分数字符串 p/q（分母恒正）；None 原样返回。"""

    if value is None:
        return None
    return f"{value.numerator}/{value.denominator}"
