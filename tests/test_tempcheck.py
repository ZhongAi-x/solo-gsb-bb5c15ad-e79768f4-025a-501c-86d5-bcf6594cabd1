"""tempcheck 单元测试：固定用例 + 随机用例候选端点暴力枚举交叉验证。"""

import os
import random
import sys
from fractions import Fraction

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.tempcheck import format_fraction, longest_qualified_period  # noqa: E402


def _brute_force(samples, low, high, min_hold, max_interval):
    """候选端点枚举：最长合格时段的端点必为采样时刻或温区边界穿越时刻。

    返回 (start, end, duration, meets)，与 longest_qualified_period 同构。
    """
    n = len(samples)
    cands = {Fraction(t) for t, _ in samples}
    for i in range(n - 1):
        t0, temp0 = samples[i]
        t1, temp1 = samples[i + 1]
        if t1 - t0 > max_interval or temp0 == temp1:
            continue
        slope = temp1 - temp0
        for target in (low, high):
            t = Fraction(t0) + Fraction(target - temp0) * (t1 - t0) / slope
            if Fraction(t0) <= t <= Fraction(t1):
                cands.add(t)
    pts = sorted(cands)

    def temp_at(t):
        """时刻 t 的插值温度；落在断开段或采样范围外时为 None。"""
        for i in range(n - 1):
            t0, temp0 = samples[i]
            t1, temp1 = samples[i + 1]
            if t1 - t0 > max_interval:
                continue
            if Fraction(t0) <= t <= Fraction(t1):
                return Fraction(temp0) + Fraction(temp1 - temp0) * (t - t0) / (
                    t1 - t0
                )
        return None

    best = None  # (start, end)；等长不替换 -> 保留开始最早
    for ai, a in enumerate(pts):
        for b in pts[ai + 1:]:
            ok = True
            for i in range(len(pts) - 1):
                if pts[i] >= a and pts[i + 1] <= b:
                    mid = (pts[i] + pts[i + 1]) / 2
                    temp = temp_at(mid)
                    if temp is None or not (low <= temp <= high):
                        ok = False
                        break
            if ok and (best is None or b - a > best[1] - best[0]):
                best = (a, b)
    if best is None:
        return None, None, Fraction(0), Fraction(0) >= min_hold
    duration = best[1] - best[0]
    return best[0], best[1], duration, duration >= min_hold


def test_constant_in_zone_whole_span():
    # 恒温且在温区内：首末采样点之间整段合格，不外推
    r = longest_qualified_period([(0, 100), (10, 100)], 50, 150, 5, 10)
    assert (r.start, r.end, r.duration) == (0, 10, 10)
    assert r.meets_requirement is True
    # 首末采样点之外不外推：时段不超出 [3, 7]
    r = longest_qualified_period([(3, 100), (7, 100)], 50, 150, 5, 10)
    assert (r.start, r.end, r.duration) == (3, 7, 4)
    assert r.meets_requirement is False  # 4 < 5


def test_linear_crossing_exact_fraction():
    # 0 秒 0 度 -> 3 秒 100 度，温区 [25, 75]：
    # 穿越时刻 3/4 与 9/4，时长 3/2（约分分数）
    r = longest_qualified_period([(0, 0), (3, 100)], 25, 75, 1, 10)
    assert r.start == Fraction(3, 4)
    assert r.end == Fraction(9, 4)
    assert r.duration == Fraction(3, 2)
    assert r.meets_requirement is True
    # 最低保温 2 秒则不达标
    r = longest_qualified_period([(0, 0), (3, 100)], 25, 75, 2, 10)
    assert r.meets_requirement is False


def test_cooling_segment_symmetric():
    # 降温段：先进入上界、后越出下界
    r = longest_qualified_period([(0, 100), (4, 0)], 25, 75, 1, 10)
    assert r.start == Fraction(1, 1)  # 100 -> 75 用 1 秒
    assert r.end == Fraction(3, 1)    # 100 -> 25 用 3 秒
    assert r.duration == 2


def test_gap_breaks_period():
    # 间隔 15 > 上限 10：曲线断开，两段各 10 秒，等长取开始最早
    samples = [(0, 100), (10, 100), (25, 100), (35, 100)]
    r = longest_qualified_period(samples, 50, 150, 1, 10)
    assert (r.start, r.end, r.duration) == (0, 10, 10)
    # 间隔恰好等于上限不断开：合并为 [0, 15]
    r = longest_qualified_period([(0, 100), (15, 100)], 50, 150, 1, 15)
    assert (r.start, r.end, r.duration) == (0, 15, 15)


def test_merge_across_sample_point():
    # 温度在采样点处保持合格：相邻段端点相接，合并为同一时段
    r = longest_qualified_period(
        [(0, 100), (10, 150), (20, 100)], 100, 200, 20, 10
    )
    assert (r.start, r.end, r.duration) == (0, 20, 20)
    assert r.meets_requirement is True


def test_peak_above_zone_splits_runs():
    # 温区 [150, 220]：峰顶越出上界，曲线被切成多段合格时段
    samples = [
        (0, 160), (20, 200), (35, 240), (50, 200), (65, 180),
        (95, 190), (115, 210),
    ]
    r = longest_qualified_period(samples, 150, 220, 25, 20)
    assert r.start == 0
    assert r.end == Fraction(55, 2)  # 20 + 20*15/40
    assert r.duration == Fraction(55, 2)
    assert r.meets_requirement is True
    # t=65~95 间隔 30 > 20 断开；末段 [95, 115] 独立成段（20 秒，非最长）


def test_single_point_touch_is_zero_duration():
    # 仅在单点触及温区边界：无正时长，起止为空、时长 0
    r = longest_qualified_period([(0, 0), (10, 100), (20, 0)], 100, 100, 1, 20)
    assert r.start is None and r.end is None
    assert r.duration == 0
    assert r.meets_requirement is False


def test_no_qualified_period():
    # 全程低于温区
    r = longest_qualified_period([(0, 10), (10, 20)], 100, 200, 1, 20)
    assert r.start is None and r.end is None
    assert r.duration == 0
    assert r.meets_requirement is False
    # 单个采样点：无插值段，同样无正时长
    r = longest_qualified_period([(5, 100)], 100, 200, 1, 20)
    assert r.start is None and r.end is None
    assert r.duration == 0


def test_meets_requirement_boundary():
    # 时长恰好等于最低保温秒数即达标
    r = longest_qualified_period([(0, 100), (30, 100)], 50, 150, 30, 40)
    assert r.duration == 30
    assert r.meets_requirement is True


def test_format_fraction():
    assert format_fraction(Fraction(4, 1)) == "4/1"
    assert format_fraction(Fraction(6, 4)) == "3/2"  # 约分
    assert format_fraction(Fraction(0)) == "0/1"
    assert format_fraction(Fraction(-1, 2)) == "-1/2"
    assert format_fraction(None) is None


def test_random_brute_force():
    # 随机小规模用例：与候选端点暴力枚举交叉验证
    rng = random.Random(20260925)
    for trial in range(400):
        n = rng.randint(1, 8)
        t = rng.randint(0, 5)
        samples = []
        for _ in range(n):
            t += rng.randint(1, 12)
            samples.append((t, rng.randint(0, 300)))
        low = rng.randint(0, 200)
        high = low + rng.randint(0, 150)
        max_interval = rng.randint(2, 15)
        min_hold = rng.randint(1, 30)

        r = longest_qualified_period(samples, low, high, min_hold, max_interval)
        got = (r.start, r.end, r.duration, r.meets_requirement)
        exp = _brute_force(samples, low, high, min_hold, max_interval)
        assert got == exp, (
            f"trial {trial}: {got} != {exp}, samples={samples}, "
            f"zone=[{low},{high}], min_hold={min_hold}, max_interval={max_interval}"
        )
        # 基本不变式：无正时长 <=> 起止为空且时长为 0
        if r.start is None:
            assert r.end is None and r.duration == 0
        else:
            assert r.end > r.start and r.duration == r.end - r.start


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n全部 {len(fns)} 个测试通过")
