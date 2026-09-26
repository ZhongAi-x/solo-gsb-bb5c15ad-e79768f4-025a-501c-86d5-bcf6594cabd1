"""cost_allocation 单元测试：固定用例 + 小规模独立枚举交叉验证。

暴力参考实现不使用被测模块的「水位法」，而是枚举全部 2^n 个饱和器物
子集，按区间条件反解 λ（Fraction），与逐饱和水位法相互独立。
"""

import os
import random
import sys
from fractions import Fraction
from itertools import combinations

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.cost_allocation import (  # noqa: E402
    InsufficientCapError,
    allocate_kiln_cost,
    allocate_plan_costs,
)


def _brute_exact_shares(members, caps, cost):
    """枚举饱和集合 S 反解 λ：S 内份额取 cap、其余取 λ·v，返回精确分数字典。"""

    ids = [m[0] for m in members]
    if cost == sum(caps[i] for i in ids):
        return {i: Fraction(caps[i]) for i in ids}

    solutions = []
    n = len(ids)
    for r in range(n + 1):
        for sat in combinations(range(n), r):
            sat_set = set(sat)
            sum_cap = sum(caps[ids[i]] for i in sat_set)
            vol_rest = sum(members[i][1] for i in range(n) if i not in sat_set)
            if vol_rest == 0:
                continue
            lam = Fraction(cost - sum_cap, vol_rest)
            if lam < 0:
                continue
            ok = True
            for i, (item_id, volume) in enumerate(members):
                share = lam * volume
                if i in sat_set:
                    if share < caps[item_id]:
                        ok = False
                        break
                else:
                    if share > caps[item_id]:
                        ok = False
                        break
            if ok:
                solutions.append(
                    {
                        ids[i]: (
                            Fraction(caps[ids[i]])
                            if i in sat_set
                            else lam * members[i][1]
                        )
                        for i in range(n)
                    }
                )
    assert solutions, f"枚举未找到 λ: members={members}, caps={caps}, cost={cost}"
    first = solutions[0]
    for other in solutions[1:]:
        assert other == first  # λ 恰等于饱和比值时不同 S 给出的份额必须一致
    return first


def _brute_integer_shares(members, caps, cost):
    """精确份额向下取整，剩余分按余数降序、编号升序补齐。"""

    exact = _brute_exact_shares(members, caps, cost)
    floors = {i: exact[i].numerator // exact[i].denominator for i in exact}
    leftover = cost - sum(floors.values())
    winners = sorted(
        exact,
        key=lambda i: (floors[i] - exact[i], i),
    )[:leftover]
    shares = dict(floors)
    for i in winners:
        shares[i] += 1
    return shares, exact


def _check_invariants(result, members, caps, cost):
    ids = sorted(i for i, _ in members)
    assert [s.item_id for s in result.shares] == ids
    assert result.cost == cost
    assert result.total_volume == sum(v for _, v in members)
    got = {s.item_id: s.share for s in result.shares}
    assert sum(got.values()) == cost  # 每窑合计严格等于请求费用
    for item_id, _ in members:
        assert 0 <= got[item_id] <= caps[item_id]  # 非负且不超过上限
    for s in result.shares:
        # 整数份额只可能是精确份额的 floor 或 floor+1（补齐时）
        assert Fraction(s.share) - 1 < s.exact_share < Fraction(s.share) + 1
        assert s.exact_share >= 0


def test_proportional_split_no_cap():
    # 体积 1:2:3，无上限约束；100 分下精确份额 100/6、200/6、300/6
    members = [("a", 1), ("b", 2), ("c", 3)]
    caps = {"a": 10_000, "b": 10_000, "c": 10_000}
    r = allocate_kiln_cost(1, members, caps, 100)
    assert [s.share for s in r.shares] == [17, 33, 50]
    # 余数最大的 a（余 4/6）先补 1；c 余数为 0
    assert sum(s.share for s in r.shares) == 100

    r = allocate_kiln_cost(1, members, caps, 101)
    # 精确 101/6、202/6、303/6 → floor 16,33,50；余数 a=5/6 > b=4/6 > c=3/6
    assert [s.share for s in r.shares] == [17, 34, 50]


def test_remainder_tie_by_id():
    members = [("p1", 1), ("p2", 1)]
    caps = {"p1": 10_000, "p2": 10_000}
    r = allocate_kiln_cost(2, members, caps, 1)
    # 精确各 1/2，余数相同：编号升序，p1 补齐
    assert [s.share for s in r.shares] == [1, 0]
    assert r.kiln_index == 2


def test_cap_binding():
    # a 上限 5，b 不受限；10 分：λ=5，a 饱和取 5、b 取 5
    members = [("a", 1), ("b", 1)]
    caps = {"a": 5, "b": 10_000}
    r = allocate_kiln_cost(1, members, caps, 10)
    assert [s.share for s in r.shares] == [5, 5]
    assert r.shares[0].exact_share == Fraction(5)
    assert r.shares[1].exact_share == Fraction(5)


def test_cap_binding_with_remainder_order():
    # a 体积 1 上限 10（饱和比值 10），b 体积 2、c 体积 3 不受限。
    # 费用 61：a 饱和取 10，剩余 51 在体积 5 上分配 λ=51/5：
    # b=102/5（20.4），c=153/5（30.6）→ floor 10/20/30，余数 c(.6)>b(.4)
    members = [("a", 1), ("b", 2), ("c", 3)]
    caps = {"a": 10, "b": 10_000, "c": 10_000}
    r = allocate_kiln_cost(1, members, caps, 61)
    assert [s.share for s in r.shares] == [10, 20, 31]
    assert sum(s.share for s in r.shares) == 61


def test_insufficient_cap_raises():
    members = [("a", 1), ("b", 1)]
    caps = {"a": 1, "b": 1}
    try:
        allocate_kiln_cost(3, members, caps, 3)
    except InsufficientCapError as exc:
        assert exc.kiln_index == 3
        assert exc.cost == 3
        assert exc.cap_sum == 2
    else:  # pragma: no cover
        raise AssertionError("应当抛出 InsufficientCapError")


def test_zero_cost():
    members = [("a", 2), ("b", 3), ("c", 4)]
    caps = {"a": 0, "b": 100, "c": 0}
    r = allocate_kiln_cost(1, members, caps, 0)
    assert [s.share for s in r.shares] == [0, 0, 0]
    assert all(s.exact_share == 0 for s in r.shares)


def test_cost_equals_cap_sum():
    members = [("a", 2), ("b", 3), ("c", 4)]
    caps = {"a": 7, "b": 1, "c": 13}
    cost = sum(caps.values())
    r = allocate_kiln_cost(1, members, caps, cost)
    assert {s.item_id: s.share for s in r.shares} == caps
    assert sum(s.share for s in r.shares) == cost


def test_plan_level_total():
    kilns = [
        (1, [("a", 1), ("b", 2)]),
        (2, [("c", 3)]),
    ]
    caps = {"a": 100, "b": 100, "c": 5}
    costs = {1: 30, 2: 5}
    result = allocate_plan_costs(kilns, caps, costs)
    assert result.total_cost == 35
    assert [k.kiln_index for k in result.kilns] == [1, 2]
    assert sum(s.share for k in result.kilns for s in k.shares) == 35
    # 窑 2 单件：费用全额落在该件
    assert result.kilns[1].shares[0].share == 5


def test_random_against_brute_force():
    rng = random.Random(20260925)
    for trial in range(4000):
        n = rng.randint(1, 6)
        members = [(f"i{i}", rng.randint(1, 8)) for i in range(n)]
        caps = {i: rng.randint(0, 30) for i, _ in members}
        cap_sum = sum(caps.values())
        cost = rng.randint(0, cap_sum)

        result = allocate_kiln_cost(1, members, caps, cost)
        exp_shares, exp_exact = _brute_integer_shares(members, caps, cost)
        for s in result.shares:
            assert s.share == exp_shares[s.item_id], (
                f"trial {trial}: {s.item_id} share {s.share} != "
                f"{exp_shares[s.item_id]}, members={members}, caps={caps}, "
                f"cost={cost}"
            )
            assert s.exact_share == exp_exact[s.item_id]
        _check_invariants(result, members, caps, cost)

    # 费用超过上限之和必报错
    members = [("x", 1), ("y", 2)]
    caps = {"x": 4, "y": 4}
    for cost in (9, 100):
        try:
            allocate_kiln_cost(1, members, caps, cost)
        except InsufficientCapError:
            pass
        else:  # pragma: no cover
            raise AssertionError(f"cost={cost} 应当抛出 InsufficientCapError")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n全部 {len(fns)} 个测试通过")
