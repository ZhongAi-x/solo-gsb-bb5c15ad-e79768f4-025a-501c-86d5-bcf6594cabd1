"""shelf_placement 单元测试：固定用例 + 小规模独立枚举交叉验证。

暴力参考实现不使用被测模块的后缀位掩码 DP，而是枚举层位分配的全部
n! 个排列，逐一检查实际温度闭区间约束后，按「最小温差最大 →
器物编号升序所配层位编号序列字典序最小」择优，与 DP + 贪心重建相互独立。
"""

import os
import random
import sys
from itertools import permutations

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.shelf_placement import (  # noqa: E402
    NoFeasibleShelfPlacementError,
    Shelf,
    place_shelves,
)
from app.solver import Ware  # noqa: E402


def _margin(temp, low, high):
    if not (low <= temp <= high):
        return None
    return min(temp - low, high - temp)


def _brute_place(firing_temp, items, shelves):
    """枚举全部排列的参考实现；返回 (最优最小温差, 按器物升序的层位序列) 或 None。"""

    its = sorted(items, key=lambda it: it.item_id)
    ss = sorted(shelves, key=lambda s: s.shelf_id)
    best = None  # (min_margin, shelf_id_tuple)
    for perm in permutations(range(len(ss))):
        margins = []
        for i, j in enumerate(perm):
            m = _margin(
                firing_temp + ss[j].temp_offset,
                its[i].temp_low,
                its[i].temp_high,
            )
            if m is None:
                break
            margins.append(m)
        else:
            margin = min(margins)
            seq = tuple(ss[j].shelf_id for j in perm)
            # 先最小温差最大；并列取器物升序所配层位编号序列字典序最小
            if best is None or (margin, ) > (best[0], ) or (
                margin == best[0] and seq < best[1]
            ):
                best = (margin, seq)
    return best


def _check_against_brute(firing_temp, items, shelves):
    result = place_shelves(firing_temp, items, shelves)
    expected = _brute_place(firing_temp, items, shelves)
    assert expected is not None, "暴力枚举认为可行，但 place_shelves 未返回结果"

    best_margin, expected_shelves = expected
    assert result.min_temp_gap == best_margin
    got = [x.item_id for x in result.items]
    assert got == sorted(x.item_id for x in items)  # 逐件结果按器物编号升序
    assert [x.shelf_id for x in result.items] == list(expected_shelves)

    # 单件不变式：实际温度 = firing_temp + 偏移，温差与闭区间一致
    shelf_by_id = {s.shelf_id: s for s in shelves}
    for x in result.items:
        item = next(it for it in items if it.item_id == x.item_id)
        assert x.actual_temp == firing_temp + shelf_by_id[x.shelf_id].temp_offset
        assert item.temp_low <= x.actual_temp <= item.temp_high
        assert x.min_temp_gap == _margin(
            x.actual_temp, item.temp_low, item.temp_high
        )
    assert min(x.min_temp_gap for x in result.items) == result.min_temp_gap
    # 一一分配：层位编号互不相同且恰好覆盖请求层位
    assert sorted(x.shelf_id for x in result.items) == sorted(
        s.shelf_id for s in shelves
    )
    return result


def test_basic_optimal_pair():
    # firing_temp=150：p2 区间 120~220、p3 区间 150~300
    # 层位 A(0) 温差分别为 min(30,70)=30、0；层位 B(20) 温差为 50、20
    # p2-B(50) + p3-A(0) 的最小温差 0；p2-A(30) + p3-B(20) 的最小温差 20
    items = [
        Ware("p2", 6, 120, 220),
        Ware("p3", 4, 150, 300),
    ]
    shelves = [Shelf("A", 0), Shelf("B", 20)]
    r = _check_against_brute(150, items, shelves)
    assert r.min_temp_gap == 20
    assert [(x.item_id, x.shelf_id, x.actual_temp) for x in r.items] == [
        ("p2", "A", 150),
        ("p3", "B", 170),
    ]


def test_single_item_single_shelf():
    r = place_shelves(100, [Ware("p1", 5, 90, 120)], [Shelf("s1", 10)])
    assert r.min_temp_gap == 10
    assert r.items[0].actual_temp == 110
    assert r.items[0].min_temp_gap == 10


def test_boundary_temp_gap_zero_is_feasible():
    # 实际温度恰在边界：闭区间可行，温差为 0
    r = place_shelves(
        100, [Ware("p1", 1, 100, 100)], [Shelf("s1", 0)]
    )
    assert r.min_temp_gap == 0
    assert r.items[0].actual_temp == 100


def test_negative_offset():
    # firing_temp=150，偏移可为负：p2 区间 120~220
    r = place_shelves(
        150,
        [Ware("p2", 6, 120, 220)],
        [Shelf("s1", -30)],
    )
    assert r.items[0].actual_temp == 120
    assert r.min_temp_gap == 0


def test_tie_break_lexicographic_shelf_sequence():
    # 器物区间完全相同 [100,110]，firing_temp=100；两个层位温差相同（0、5），
    # 两种分配最小温差均为 0；取器物升序所配层位编号序列字典序最小者
    items = [
        Ware("a", 1, 100, 110),
        Ware("b", 1, 100, 110),
    ]
    shelves = [Shelf("s1", 0), Shelf("s2", 5)]
    r = _check_against_brute(100, items, shelves)
    assert [x.shelf_id for x in r.items] == ["s1", "s2"]

    # 非对称并列：最优值为 0 且 a 必须配高温层位、b 任意 -> 取 b 的最小编号层位
    shelves = [Shelf("s1", 0), Shelf("s2", 5), Shelf("s3", 10)]
    items = [
        Ware("a", 1, 105, 110),  # 仅 s2/s3 可行
        Ware("b", 1, 100, 110),
        Ware("c", 1, 100, 110),
    ]
    # 最优：a-s3(5), b-s1(0), c-s2(5) -> 最小温差 0；
    # 另一方案 a-s2(0), b-s1(0), c-s3(5) 最小温差也是 0。
    # 器物序列 (a,b,c) 对应层位序列比较 ("s2","s1","s3") < ("s3","s1","s2")。
    r = _check_against_brute(100, items, shelves)
    assert r.min_temp_gap == 0
    assert [x.shelf_id for x in r.items] == ["s2", "s1", "s3"]


def test_no_feasible_assignment():
    # 每件器物都有可行层位，但完美匹配不存在（p2/p3 均只能入同一层位）
    items = [
        Ware("p2", 6, 120, 220),
        Ware("p3", 4, 150, 300),
    ]
    shelves = [Shelf("A", 0), Shelf("B", 200)]
    # firing_temp=150: A->150（两件均可行），B->350（均不可行）
    try:
        place_shelves(150, items, shelves, kiln_index=2)
    except NoFeasibleShelfPlacementError as exc:
        assert "窑次 2" in str(exc)
    else:
        raise AssertionError("应抛出 NoFeasibleShelfPlacementError")

    assert _brute_place(150, items, shelves) is None


def test_item_unfit_for_any_shelf():
    items = [
        Ware("p1", 1, 100, 110),
        Ware("p2", 1, 200, 210),
    ]
    shelves = [Shelf("A", 0), Shelf("B", 5)]
    # firing_temp=100：100/105 对 p2 全部不可行，错误信息列出该器物
    try:
        place_shelves(100, items, shelves, kiln_index=1)
    except NoFeasibleShelfPlacementError as exc:
        assert "p2" in str(exc)
    else:
        raise AssertionError("应抛出 NoFeasibleShelfPlacementError")


def test_count_mismatch_and_duplicate_shelf():
    items = [Ware("a", 1, 100, 110)]
    try:
        place_shelves(100, items, [Shelf("s1", 0), Shelf("s2", 0)])
    except ValueError as exc:
        assert "层位数量必须与该窑器物数相同" in str(exc)
    else:
        raise AssertionError("层位数量不符应抛出 ValueError")

    items = [
        Ware("a", 1, 100, 110),
        Ware("b", 1, 100, 110),
    ]
    try:
        place_shelves(100, items, [Shelf("s1", 0), Shelf("s1", 5)])
    except ValueError as exc:
        assert "层位编号必须唯一" in str(exc)
    else:
        raise AssertionError("层位编号重复应抛出 ValueError")


def test_random_cross_validation():
    rng = random.Random(20260926)
    trials = 400
    for trial in range(trials):
        n = rng.randint(1, 6)
        firing_temp = rng.randint(80, 120)
        items = []
        for i in range(n):
            low = firing_temp + rng.randint(-30, 10)
            high = low + rng.randint(0, 40)
            items.append(Ware(f"i{i:02d}", rng.randint(1, 9), low, high))
        shelves = [
            Shelf(f"s{j:02d}", rng.randint(-40, 50)) for j in range(n)
        ]
        expected = _brute_place(firing_temp, items, shelves)
        if expected is None:
            try:
                place_shelves(firing_temp, items, shelves)
            except NoFeasibleShelfPlacementError:
                continue
            raise AssertionError(f"trial {trial}: 暴力枚举认为无解，但求解返回了安排")
        _check_against_brute(firing_temp, items, shelves)


def test_performance_n14():
    import time

    firing_temp = 100
    items = [Ware(f"i{i:02d}", 1, 90, 130) for i in range(14)]
    shelves = [Shelf(f"s{i:02d}", i) for i in range(14)]
    t0 = time.time()
    r = place_shelves(firing_temp, items, shelves)
    elapsed = time.time() - t0
    assert elapsed < 5.0, f"n=14 耗时 {elapsed:.2f}s"
    # 器物 i 配层位 i：实际温度 100+i，温差 min(10+i, 30-i)
    # 最优匹配最大化瓶颈（按温差矩阵单调，i 配 i 最优）
    assert len(r.items) == 14
    assert r.min_temp_gap == min(min(10 + i, 30 - i) for i in range(14))
    assert r.min_temp_gap == 10  # i=0 时 min(10,30)=10 为瓶颈


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n全部 {len(fns)} 个测试通过")
