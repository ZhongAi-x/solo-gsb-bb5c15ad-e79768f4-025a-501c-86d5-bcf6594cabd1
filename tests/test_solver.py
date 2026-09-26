"""solver 单元测试：固定用例 + 小规模暴力枚举交叉验证。"""

import random
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.solver import (  # noqa: E402
    CapacityExceededError,
    TargetUnreachableError,
    Ware,
    append_items,
    cancel_items_and_repack,
    compare_kiln_assignments,
    min_capacity_for_target,
    select_within_kiln_limit,
    solve,
)


def _feasible(items_by_id, group, capacity, forbidden_pairs=()):
    total = sum(items_by_id[i].volume for i in group)
    if total > capacity:
        return False
    lo = max(items_by_id[i].temp_low for i in group)
    hi = min(items_by_id[i].temp_high for i in group)
    if lo > hi:
        return False
    for a, b in forbidden_pairs:
        if a in group and b in group:
            return False
    return True


def _brute_force(items, capacity, forbidden_pairs=()):
    """枚举所有集合划分，返回 (最少窑次, 字典序最小方案)。"""
    ids = sorted(i.item_id for i in items)
    by_id = {i.item_id: i for i in items}
    best = None  # (窑次数, 方案元组)

    def partitions(s, groups):
        nonlocal best
        if not s:
            plan = tuple(sorted(tuple(sorted(g)) for g in groups))
            k = len(plan)
            if best is None or (k, plan) < (best[0], best[1]):
                best = (k, plan)
            return
        elem = s[0]
        rest = s[1:]
        # elem 放入已有某一组
        for gi in range(len(groups)):
            ng = groups[gi] | {elem}
            if _feasible(by_id, ng, capacity, forbidden_pairs):
                new_groups = groups[:gi] + [ng] + groups[gi + 1:]
                partitions(rest, new_groups)
        # elem 单开一组
        if _feasible(by_id, {elem}, capacity, forbidden_pairs):
            partitions(rest, groups + [{elem}])

    partitions(ids, [])
    return best


def _run(items, capacity):
    kilns = solve(items, capacity)
    plan = tuple(k.item_ids for k in kilns)
    return len(kilns), plan


def test_overcapacity_single_item():
    items = [Ware("a", 11, 100, 200)]
    try:
        solve(items, 10)
        assert False, "应抛出 CapacityExceededError"
    except CapacityExceededError:
        pass


def test_basic_capacity_split():
    # 每件 6，容量 10 -> 必须 3 窑
    items = [Ware(str(i), 6, 100, 200) for i in range(1, 4)]
    k, plan = _run(items, 10)
    assert k == 3
    assert plan == (("1",), ("2",), ("3",))


def test_temperature_intersection():
    # 1: [100,120] 2: [130,140] 3: [110,130]，容量任意
    # 1 与 2 不可同窑；1+3=[110,120] 可同窑(温度110)，2+3=[130,130](温度130)
    # 两种 2 窑方案：(1,3)(2) 与 (1)(2,3)；("1",) 是 ("1","3") 的前缀，
    # 字典序更小，故整体字典序最小方案为 [1] + [2,3]。
    items = [Ware("1", 1, 100, 120), Ware("2", 1, 130, 140), Ware("3", 1, 110, 130)]
    kilns = solve(items, 100)
    assert len(kilns) == 2
    assert kilns[0].item_ids == ("1",)
    assert kilns[0].firing_temp == 100
    assert kilns[1].item_ids == ("2", "3")
    assert kilns[1].firing_temp == 130


def test_firing_temp_is_intersection_lower_bound():
    items = [Ware("a", 1, 100, 300), Ware("b", 1, 150, 250), Ware("c", 1, 200, 400)]
    kilns = solve(items, 100)
    assert len(kilns) == 1
    assert kilns[0].firing_temp == 200  # max(100,150,200)
    assert kilns[0].total_volume == 3


def test_lex_tiebreak_example():
    # 构造窑次相同时的字典序选择：
    # 四件器物，每件体积 6，容量 10 -> 只能两两？不行，6+6>10 -> 每窑一件
    items = [Ware("b", 6, 1, 2), Ware("a", 6, 1, 2), Ware("c", 6, 1, 2)]
    k, plan = _run(items, 10)
    assert k == 3
    # 输入乱序，输出仍按编号升序、窑次按序列排序
    assert plan == (("a",), ("b",), ("c",))


def test_lex_tiebreak_pairing():
    # 容量 10，每件 5，温度全兼容 => 2 窑，两两组合。
    # 可能最优方案 (1,2)(3,4) / (1,3)(2,4) / (1,4)(2,3)，字典序最小为 (1,2)(3,4)
    items = [Ware(str(i), 5, 100, 200) for i in range(1, 5)]
    k, plan = _run(items, 10)
    assert k == 2
    assert plan == (("1", "2"), ("3", "4"))


def test_random_brute_force():
    rng = random.Random(42)
    for trial in range(300):
        n = rng.randint(1, 7)
        ids = [f"id{i}" for i in range(n)]
        capacity = rng.randint(5, 15)
        items = []
        for i in range(n):
            vol = rng.randint(1, 8)
            lo = rng.randint(900, 1000)
            hi = lo + rng.randint(0, 100)
            items.append(Ware(ids[i], vol, lo, hi))
        if any(it.volume > capacity for it in items):
            try:
                solve(items, capacity)
                assert False, f"trial {trial}: 应抛出 CapacityExceededError"
            except CapacityExceededError:
                continue
        got_k, got_plan = _run(items, capacity)
        exp_k, exp_plan = _brute_force(items, capacity)
        assert got_k == exp_k, f"trial {trial}: {got_k} != {exp_k}, {items}"
        assert got_plan == exp_plan, (
            f"trial {trial}: {got_plan} != {exp_plan}, items={items}, cap={capacity}"
        )


def test_n14_performance_and_correctness():
    # n=14 全兼容、容量只够单件 -> 14 窑，确保性能可接受
    items = [Ware(f"i{i:02d}", 5, 1000, 1000) for i in range(14)]
    import time

    t0 = time.time()
    k, plan = _run(items, 9)
    elapsed = time.time() - t0
    assert k == 14
    assert elapsed < 5.0, f"n=14 耗时 {elapsed:.2f}s"

    # 全部可同窑 -> 1 窑，烧成温度取交集下界
    items2 = [Ware(f"i{i:02d}", 1, 1000 + i, 2000) for i in range(14)]
    kilns = solve(items2, 1000)
    assert len(kilns) == 1
    assert kilns[0].firing_temp == 1013
    assert kilns[0].total_volume == 14


# ---------------------------------------------------------------------------
# 釉色隔离 solve(items, capacity, separation_pairs)
# ---------------------------------------------------------------------------


def test_glaze_separation_forces_more_kilns():
    # 每件 5、容量 10、温区全兼容，4 件无互斥时 2 窑 (1,2)(3,4)。
    items = [Ware(str(i), 5, 100, 200) for i in range(1, 5)]
    kilns = solve(items, 10)
    assert len(kilns) == 2
    # 1 与 2 互斥后，4 件两两容量可行的 2 窑划分中
    # (1,3)(2,4) 与 (1,4)(2,3) 字典序更小者为 (1,3)(2,4)。
    kilns = solve(items, 10, [["1", "2"]])
    assert len(kilns) == 2
    assert [k.item_ids for k in kilns] == [("1", "3"), ("2", "4")]
    # 三件两两互斥 -> 3 窑；器物 4 无互斥，并入序列字典序最小可行位置：
    # ("1") 是 ("1","4") 的前缀，故 4 最终落入末窑 -> ("1")("2")("3","4")。
    kilns = solve(items, 10, [["1", "2"], ["1", "3"], ["2", "3"]])
    assert len(kilns) == 3
    assert [k.item_ids for k in kilns] == [("1",), ("2",), ("3", "4")]
    # 全部两两互斥 -> 每件单独成窑
    pairs = [(a, b) for a, b in __import__("itertools").combinations(
        [str(i) for i in range(1, 5)], 2
    )]
    kilns = solve(items, 10, pairs)
    assert len(kilns) == 4
    assert [k.item_ids for k in kilns] == [("1",), ("2",), ("3",), ("4",)]


def test_glaze_separation_keeps_temp_and_capacity_rules():
    # 互斥与温区规则叠加：p4 温区不兼容本就单独成窑；
    # 互斥 (p1,p3) 与 (p2,p3) 迫使 p3 单独一窑，p1、p2 温区有交集但
    # 体积 5+6 > 10 亦不可同窑 -> 4 窑。
    items = [
        Ware("p1", 5, 100, 200),
        Ware("p2", 6, 120, 220),
        Ware("p3", 4, 150, 300),
        Ware("p4", 5, 1000, 1100),
    ]
    kilns = solve(items, 10, [["p1", "p3"], ["p2", "p3"]])
    assert len(kilns) == 4
    assert [k.item_ids for k in kilns] == [
        ("p1",), ("p2",), ("p3",), ("p4",)
    ]
    assert [k.firing_temp for k in kilns] == [100, 120, 150, 1000]
    assert [k.total_volume for k in kilns] == [5, 6, 4, 5]

    # 仅互斥 (p2,p3)：不增加窑次，原 (p1)(p2,p3)(p4) 改为
    # 字典序最小的 (p1,p3)(p2)(p4)。
    kilns = solve(items, 10, [["p3", "p2"]])
    assert len(kilns) == 3
    assert [k.item_ids for k in kilns] == [("p1", "p3"), ("p2",), ("p4",)]
    assert kilns[0].firing_temp == 150 and kilns[0].total_volume == 9


def test_glaze_separation_pair_order_is_unordered():
    # 互斥对为无序关系：(a,b) 与 (b,a) 语义相同，且与器物传入顺序无关。
    items = [
        Ware("b", 5, 100, 200),
        Ware("a", 5, 100, 200),
        Ware("c", 5, 100, 200),
        Ware("d", 5, 100, 200),
    ]
    r1 = solve(items, 10, [["a", "b"]])
    r2 = solve(items, 10, [["b", "a"]])
    assert [k.item_ids for k in r1] == [k.item_ids for k in r2]
    assert [k.item_ids for k in r1] == [("a", "c"), ("b", "d")]


def test_glaze_separation_invalid_pairs():
    items = [Ware("a", 1, 100, 200), Ware("b", 1, 100, 200)]
    # 两端编号相同
    for bad in ([["a", "a"]], [[" a ", "a"]]):
        try:
            solve(items, 10, bad)
            assert False, f"{bad}: 应抛出 ValueError"
        except ValueError:
            pass
    # 重复（含顺序相反）
    for bad in ([["a", "b"], ["a", "b"]], [["a", "b"], ["b", "a"]]):
        try:
            solve(items, 10, bad)
            assert False, f"{bad}: 应抛出 ValueError"
        except ValueError:
            pass
    # 编号不属于器物列表
    try:
        solve(items, 10, [["a", "x"]])
        assert False, "应抛出 ValueError"
    except ValueError:
        pass


def test_glaze_separation_none_or_empty_pairs_matches_solve():
    # separation_pairs=None 与空列表时，结果必须与原 solve 完全一致
    items = [Ware(str(i), 6, 100, 200) for i in range(1, 4)]
    base = [k.item_ids for k in solve(items, 10)]
    assert [k.item_ids for k in solve(items, 10, None)] == base
    assert [k.item_ids for k in solve(items, 10, [])] == base
    assert base == [("1",), ("2",), ("3",)]


def test_glaze_separation_random_brute_force():
    # 随机小规模用例：互斥约束下的最少窑次与整体字典序方案同暴力枚举交叉验证
    import itertools

    rng = random.Random(2026)
    for trial in range(400):
        n = rng.randint(1, 7)
        items = []
        for i in range(n):
            vol = rng.randint(1, 8)
            lo = rng.randint(900, 1000)
            hi = lo + rng.randint(0, 100)
            items.append(Ware(f"id{i}", vol, lo, hi))
        capacity = rng.randint(max(it.volume for it in items), 18)
        ids = sorted(it.item_id for it in items)
        all_pairs = list(itertools.combinations(ids, 2))
        rng.shuffle(all_pairs)
        pairs = [list(p) for p in all_pairs[: rng.randint(0, len(all_pairs))]]

        kilns = solve(items, capacity, pairs)
        exp_k, exp_plan = _brute_force(items, capacity, pairs)
        assert len(kilns) == exp_k, f"trial {trial}: {len(kilns)} != {exp_k}"
        got_plan = tuple(k.item_ids for k in kilns)
        assert got_plan == exp_plan, (
            f"trial {trial}: {got_plan} != {exp_plan}, pairs={pairs}"
        )
        # 每条互斥对在结果中都必须分属不同窑
        groups = [set(k.item_ids) for k in kilns]
        for a, b in pairs:
            assert not any(a in g and b in g for g in groups), (
                f"trial {trial}: 互斥对 {a},{b} 同窑"
            )


def test_glaze_separation_performance_n14():
    # n=14 且全部两两互斥 -> 14 窑，耗时与无互斥求解同量级
    import itertools
    import time

    items = [Ware(f"i{i:02d}", 1, 1000, 1000) for i in range(14)]
    pairs = list(itertools.combinations([w.item_id for w in items], 2))
    t0 = time.time()
    kilns = solve(items, 9, pairs)
    elapsed = time.time() - t0
    assert elapsed < 5.0, f"全互斥 n=14 耗时 {elapsed:.2f}s"
    assert len(kilns) == 14


def test_min_capacity_basic():
    # 三件各 6、温度全兼容：3 窑需容量 6，2 窑需 12，1 窑需 18
    items = [Ware(str(i), 6, 100, 200) for i in range(1, 4)]
    cap, kilns = min_capacity_for_target(items, 3)
    assert cap == 6 and len(kilns) == 3
    cap, kilns = min_capacity_for_target(items, 2)
    assert cap == 12 and len(kilns) == 2
    # ("1",) 是 ("1","2") 的前缀，字典序更小，故首窑只装 "1"
    assert [k.item_ids for k in kilns] == [("1",), ("2", "3")]
    cap, kilns = min_capacity_for_target(items, 1)
    assert cap == 18 and len(kilns) == 1
    assert kilns[0].item_ids == ("1", "2", "3")
    assert kilns[0].firing_temp == 100
    assert kilns[0].total_volume == 18


def test_min_capacity_target_equals_item_count():
    # 目标 = 器物数时，最大单件体积即可（每件一窑）
    items = [Ware("a", 5, 100, 200), Ware("b", 9, 100, 200)]
    cap, kilns = min_capacity_for_target(items, 2)
    assert cap == 9 and len(kilns) == 2


def test_min_capacity_unreachable():
    # 温度区间互不兼容：任何容量下 1 与 2 都不可同窑
    items = [Ware("1", 3, 100, 120), Ware("2", 4, 130, 140)]
    try:
        min_capacity_for_target(items, 1)
        assert False, "应抛出 TargetUnreachableError"
    except TargetUnreachableError:
        pass
    # 目标 2 可达：最小容量为最大单件体积
    cap, kilns = min_capacity_for_target(items, 2)
    assert cap == 4 and len(kilns) == 2


def test_min_capacity_invalid_target():
    items = [Ware("a", 5, 100, 200)]
    try:
        min_capacity_for_target(items, 0)
        assert False, "应抛出 ValueError"
    except ValueError:
        pass


def test_min_capacity_matches_linear_scan():
    # 随机小规模用例：与 [最大单件, 总体积] 全范围线性扫描交叉验证，
    # 同时校验返回方案与 solve 在该容量下的字典序最小方案一致
    rng = random.Random(7)
    for trial in range(200):
        n = rng.randint(1, 7)
        items = []
        for i in range(n):
            vol = rng.randint(1, 8)
            lo = rng.randint(900, 1000)
            hi = lo + rng.randint(0, 100)
            items.append(Ware(f"id{i}", vol, lo, hi))
        max_vol = max(it.volume for it in items)
        total = sum(it.volume for it in items)
        counts = {cap: len(solve(items, cap)) for cap in range(max_vol, total + 1)}
        for target in range(1, n + 1):
            feasible = [c for c, k in counts.items() if k <= target]
            if not feasible:
                try:
                    min_capacity_for_target(items, target)
                    assert False, f"trial {trial}: 应抛出 TargetUnreachableError"
                except TargetUnreachableError:
                    continue
            exp_cap = min(feasible)
            got_cap, kilns = min_capacity_for_target(items, target)
            assert got_cap == exp_cap, (
                f"trial {trial} target {target}: {got_cap} != {exp_cap}"
            )
            assert len(kilns) == counts[got_cap] <= target
            exp_kilns = solve(items, exp_cap)
            assert [k.item_ids for k in kilns] == [k.item_ids for k in exp_kilns]


# ---------------------------------------------------------------------------
# 限窑次接单 select_within_kiln_limit
# ---------------------------------------------------------------------------


def _brute_force_production_limit(items, capacity, max_kilns):
    """枚举全部 2^n 个子集，返回择优保留的编号元组（与接口相同的三级排序）。"""
    ordered = sorted(items, key=lambda it: it.item_id)
    by_id = {it.item_id: it for it in items}
    best = None  # (件数, 总体积)，并列时取编号升序列表字典序最小者
    for mask in range(1, 1 << len(ordered)):
        members = tuple(it.item_id for j, it in enumerate(ordered) if (mask >> j) & 1)
        if len(solve([by_id[i] for i in members], capacity)) > max_kilns:
            continue
        total = sum(by_id[i].volume for i in members)
        if (
            best is None
            or (len(members), total) > (best[0], best[1])
            or ((len(members), total) == (best[0], best[1]) and members < best[2])
        ):
            best = (len(members), total, members)
    return best[2]


def test_production_limit_basic_count():
    # 每件 6、容量 10 -> 每窑至多 1 件；上限 2 窑 -> 保留 2 件，
    # 件数与总体积均并列，取编号升序列表字典序最小者 ("1","2")。
    items = [Ware(str(i), 6, 100, 200) for i in range(1, 4)]
    result = select_within_kiln_limit(items, 10, 2)
    assert result.kept_item_ids == ("1", "2")
    assert result.delayed_item_ids == ("3",)
    assert len(result.kilns) == 2
    assert [k.item_ids for k in result.kilns] == [("1",), ("2",)]


def test_production_limit_one_kiln():
    # 温度互不兼容：1 与 2 不可同窑，1 窑内只能保留温度区间最大者。
    items = [
        Ware("1", 3, 100, 120),
        Ware("2", 4, 130, 140),
        Ware("3", 2, 110, 125),
    ]
    result = select_within_kiln_limit(items, 100, 1)
    assert result.kept_item_ids == ("1", "3")
    assert result.delayed_item_ids == ("2",)
    assert len(result.kilns) == 1
    assert result.kilns[0].item_ids == ("1", "3")
    assert result.kilns[0].firing_temp == 110
    assert result.kilns[0].total_volume == 5


def test_production_limit_volume_tiebreak():
    # 容量 10、上限 1 窑：体积 7/6/5 两两之和均超容，每件只能单独成窑，
    # 件数同为 1 时保留总体积最大者 -> "1"(7)。
    items = [
        Ware("1", 7, 100, 200),
        Ware("2", 6, 100, 200),
        Ware("3", 5, 100, 200),
    ]
    result = select_within_kiln_limit(items, 10, 1)
    assert result.kept_item_ids == ("1",)
    assert result.delayed_item_ids == ("2", "3")


def test_production_limit_id_tiebreak_standard_lex():
    # 标准字符串字典序：("10",) < ("2",)，故上限 1 窑、件数与体积并列时
    # 保留 "10" 而非 "2"。
    items = [
        Ware("2", 6, 100, 200),
        Ware("10", 6, 100, 200),
        Ware("3", 6, 100, 200),
    ]
    result = select_within_kiln_limit(items, 10, 1)
    assert result.kept_item_ids == ("10",)
    assert result.delayed_item_ids == ("2", "3")


def test_production_limit_actual_kilns_may_be_fewer():
    # 上限 3 窑但保留器物可全部装入 2 窑时，实际装窑取最少窑次。
    items = [Ware(str(i), 6, 100, 200) for i in range(1, 4)]
    result = select_within_kiln_limit(items, 10, 3)
    assert result.kept_item_ids == ("1", "2", "3")
    assert result.delayed_item_ids == ()
    assert len(result.kilns) == 3

    # 同样 3 件、容量 12（两两可同窑）、上限 3 窑 -> 全部保留且实际 2 窑
    items = [Ware(str(i), 6, 100, 200) for i in range(1, 4)]
    result = select_within_kiln_limit(items, 12, 3)
    assert result.kept_item_ids == ("1", "2", "3")
    assert len(result.kilns) == 2


def test_production_limit_max_equals_item_count_keeps_all():
    items = [
        Ware("a", 3, 100, 120),
        Ware("b", 5, 130, 140),
    ]
    result = select_within_kiln_limit(items, 100, 2)
    assert result.kept_item_ids == ("a", "b")
    assert result.delayed_item_ids == ()
    assert len(result.kilns) == 2


def test_production_limit_invalid_max_kilns():
    items = [Ware("a", 5, 100, 200)]
    try:
        select_within_kiln_limit(items, 10, 0)
        assert False, "应抛出 ValueError"
    except ValueError:
        pass


def test_production_limit_oversized_item_still_errors():
    # 原方案保存时单件不会超容，此处保持 solver 语义一致：超容即报错。
    items = [Ware("a", 11, 100, 200)]
    try:
        select_within_kiln_limit(items, 10, 1)
        assert False, "应抛出 CapacityExceededError"
    except CapacityExceededError:
        pass


def test_production_limit_random_brute_force():
    # 随机小规模用例：保留集合与装窑明细同时交叉验证暴力枚举 / solve。
    rng = random.Random(99)
    for trial in range(300):
        n = rng.randint(1, 7)
        items = []
        for i in range(n):
            vol = rng.randint(1, 8)
            lo = rng.randint(900, 1000)
            hi = lo + rng.randint(0, 100)
            items.append(Ware(f"id{i}", vol, lo, hi))
        capacity = rng.randint(max(it.volume for it in items), 20)
        max_kilns = rng.randint(1, n)

        result = select_within_kiln_limit(items, capacity, max_kilns)
        exp_kept = _brute_force_production_limit(items, capacity, max_kilns)
        assert result.kept_item_ids == exp_kept, (
            f"trial {trial}: kept {result.kept_item_ids} != {exp_kept}, "
            f"items={items}, cap={capacity}, max_kilns={max_kilns}"
        )
        # 延期列表 = 全量编号 - 保留编号，均升序
        all_ids = tuple(sorted(it.item_id for it in items))
        kept_set = set(exp_kept)
        assert result.delayed_item_ids == tuple(i for i in all_ids if i not in kept_set)
        # 装窑明细与 solve 在保留子集上的结果一致（最少窑次 + 字典序）
        by_id = {it.item_id: it for it in items}
        exp_kilns = solve([by_id[i] for i in exp_kept], capacity)
        assert len(exp_kilns) <= max_kilns
        assert [k.item_ids for k in result.kilns] == [k.item_ids for k in exp_kilns]
        assert [k.total_volume for k in result.kilns] == [
            k.total_volume for k in exp_kilns
        ]
        assert [k.firing_temp for k in result.kilns] == [
            k.firing_temp for k in exp_kilns
        ]


# ---------------------------------------------------------------------------
# 方案对比 compare_kiln_assignments
# ---------------------------------------------------------------------------


def _brute_force_compare(source_kilns, target_kilns):
    """枚举全部一对一配对，返回 (配对序列, 留窑的共同器物集合)。

    配对序列按来源序号升序；最优解并列时取序列字典序最小者（与接口一致）。
    """
    from itertools import combinations, permutations

    m, k = len(source_kilns), len(target_kilns)
    pair_count = min(m, k)
    src_of = {x: i + 1 for i, kiln in enumerate(source_kilns) for x in kiln}
    tgt_of = {x: j + 1 for j, kiln in enumerate(target_kilns) for x in kiln}
    common = set(src_of) & set(tgt_of)

    best = None  # (留窑数取负, 配对序列, 留窑集合)
    for srcs in combinations(range(1, m + 1), pair_count):
        for tgts in permutations(range(1, k + 1), pair_count):
            pairs = tuple(zip(srcs, tgts))
            pair_map = dict(pairs)
            stayed = {
                x for x in common if pair_map.get(src_of[x]) == tgt_of[x]
            }
            key = (-len(stayed), pairs)
            if best is None or key < best[:2]:
                best = (key[0], pairs, stayed)
    return best[1], best[2]


def _check_compare_result(result, source_kilns, target_kilns):
    """校验对比结果与暴力枚举一致，且各编号列表升序、划分完备。"""
    src_ids = {x for kiln in source_kilns for x in kiln}
    tgt_ids = {x for kiln in target_kilns for x in kiln}
    common = src_ids & tgt_ids

    exp_pairs, exp_stayed = _brute_force_compare(source_kilns, target_kilns)
    assert result.pairs == exp_pairs, (
        f"pairs {result.pairs} != {exp_pairs}, "
        f"source={source_kilns}, target={target_kilns}"
    )
    # 配对数取两边窑次数较小值，来源序号升序且互不重复、目标序号互不重复
    assert len(result.pairs) == min(len(source_kilns), len(target_kilns))
    assert [s for s, _ in result.pairs] == sorted(s for s, _ in result.pairs)
    assert len({t for _, t in result.pairs}) == len(result.pairs)

    assert set(result.stayed_item_ids) == exp_stayed
    assert list(result.stayed_item_ids) == sorted(result.stayed_item_ids)
    # 换窑 = 共同器物 - 留窑；未落在配对窑内也算换窑
    assert set(result.moved_item_ids) == common - exp_stayed
    assert list(result.moved_item_ids) == sorted(result.moved_item_ids)
    # 单方独有编号
    assert set(result.only_in_source_item_ids) == src_ids - tgt_ids
    assert list(result.only_in_source_item_ids) == sorted(
        result.only_in_source_item_ids
    )
    assert set(result.only_in_target_item_ids) == tgt_ids - src_ids
    assert list(result.only_in_target_item_ids) == sorted(
        result.only_in_target_item_ids
    )


def test_compare_basic():
    # 来源 [a b] [c]，目标 [a] [b c]：唯一最优配对 (1,1)(2,2)，b 换窑
    result = compare_kiln_assignments([["a", "b"], ["c"]], [["a"], ["b", "c"]])
    assert result.pairs == ((1, 1), (2, 2))
    assert result.stayed_item_ids == ("a", "c")
    assert result.moved_item_ids == ("b",)
    assert result.only_in_source_item_ids == ()
    assert result.only_in_target_item_ids == ()


def test_compare_tiebreak_lex_by_source():
    # 来源 3 窑、目标 2 窑：(1,1)(3,2) 与 (2,1)(3,2) 留窑数同为 2，
    # 配对序列字典序最小者为 (1,1)(3,2)。
    result = compare_kiln_assignments(
        [["a"], ["b"], ["c"]], [["a", "b"], ["c"]]
    )
    assert result.pairs == ((1, 1), (3, 2))
    assert result.stayed_item_ids == ("a", "c")
    assert result.moved_item_ids == ("b",)


def test_compare_unpaired_kiln_counts_as_moved():
    # 目标仅 1 窑：配对 (1,1) 后 b 所在来源窑 2 未配对，未落在配对窑内算换窑
    result = compare_kiln_assignments([["a"], ["b"]], [["a", "b"]])
    assert result.pairs == ((1, 1),)
    assert result.stayed_item_ids == ("a",)
    assert result.moved_item_ids == ("b",)


def test_compare_no_common_items():
    # 无共同器物：留窑数恒为 0，字典序最小配对为 (1,1)
    result = compare_kiln_assignments([["x", "y"]], [["p", "q"], ["r"]])
    assert result.pairs == ((1, 1),)
    assert result.stayed_item_ids == ()
    assert result.moved_item_ids == ()
    assert result.only_in_source_item_ids == ("x", "y")
    assert result.only_in_target_item_ids == ("p", "q", "r")


def test_compare_identical_plans():
    # 同一方案对比：恒等配对，全部留窑
    kilns = [["a", "b"], ["c"]]
    result = compare_kiln_assignments(kilns, kilns)
    assert result.pairs == ((1, 1), (2, 2))
    assert result.stayed_item_ids == ("a", "b", "c")
    assert result.moved_item_ids == ()


def test_compare_standard_lex_order_of_ids():
    # 编号列表按标准字符串字典序升序（"10" < "2"）
    result = compare_kiln_assignments(
        [["2"], ["10"], ["3"]], [["2"], ["10"], ["3"]]
    )
    assert result.stayed_item_ids == ("10", "2", "3")


def test_compare_empty_kilns_rejected():
    try:
        compare_kiln_assignments([], [["a"]])
        assert False, "应抛出 ValueError"
    except ValueError:
        pass


def test_compare_random_brute_force():
    # 随机小规模用例：配对序列与全部编号列表同暴力枚举交叉验证
    rng = random.Random(2024)
    for trial in range(150):
        pool = [f"id{i}" for i in range(rng.randint(1, 6))]

        def random_plan():
            items = [x for x in pool if rng.random() < 0.7] or [
                pool[rng.randrange(len(pool))]
            ]
            rng.shuffle(items)
            kilns = [[] for _ in range(rng.randint(1, min(4, len(items))))]
            for x in items:
                kilns[rng.randrange(len(kilns))].append(x)
            return [sorted(kk) for kk in kilns if kk]

        source_kilns = random_plan()
        target_kilns = random_plan()
        result = compare_kiln_assignments(source_kilns, target_kilns)
        _check_compare_result(result, source_kilns, target_kilns)


# ---------------------------------------------------------------------------
# 追加器物 append_items
# ---------------------------------------------------------------------------


def _brute_force_append(original_kilns, new_items, capacity):
    """枚举每件新器物的去向（某一原窑或追加窑），返回 (新增窑次数, 方案元组)。

    方案元组 = 原窑次序的合并编号元组 + 追加窑字典序最小方案（复用
    _brute_force），与接口的整体字典序规则一致。
    """
    from itertools import product

    ids = sorted(w.item_id for w in new_items)
    by_id = {w.item_id: w for w in new_items}
    m = len(original_kilns)
    orig_sorted = [sorted(w.item_id for w in kiln) for kiln in original_kilns]
    orig_vol = [sum(w.volume for w in kiln) for kiln in original_kilns]
    orig_lo = [max(w.temp_low for w in kiln) for kiln in original_kilns]
    orig_hi = [min(w.temp_high for w in kiln) for kiln in original_kilns]

    def fits(j, members):
        vol = orig_vol[j] + sum(by_id[i].volume for i in members)
        if vol > capacity:
            return False
        lo = max([orig_lo[j]] + [by_id[i].temp_low for i in members])
        hi = min([orig_hi[j]] + [by_id[i].temp_high for i in members])
        return lo <= hi

    best = None  # (新增窑次数, 方案元组)
    for assignment in product(range(m + 1), repeat=len(ids)):
        in_kiln = [[] for _ in range(m)]
        appended = []
        for item_id, dest in zip(ids, assignment):
            if dest < m:
                in_kiln[dest].append(item_id)
            else:
                appended.append(item_id)
        if any(not fits(j, in_kiln[j]) for j in range(m)):
            continue
        if appended:
            add_count, add_plan = _brute_force(
                [by_id[i] for i in appended], capacity
            )
        else:
            add_count, add_plan = 0, ()
        plan = tuple(
            tuple(sorted(orig_sorted[j] + in_kiln[j])) for j in range(m)
        ) + add_plan
        key = (add_count, plan)
        if best is None or key < best:
            best = key
    return best


def _check_append_result(kilns, original_kilns, new_items, capacity):
    """校验结果的基本性质：原窑为前缀、原器物归属不变、各窑约束与温度正确。"""
    m = len(original_kilns)
    assert len(kilns) >= m
    all_wares = {w.item_id: w for kiln in original_kilns for w in kiln}
    all_wares.update({w.item_id: w for w in new_items})
    for j, kiln_wares in enumerate(original_kilns):
        assert {w.item_id for w in kiln_wares} <= set(kilns[j].item_ids)
    for k in kilns:
        assert list(k.item_ids) == sorted(k.item_ids)
        assert k.total_volume == sum(all_wares[i].volume for i in k.item_ids)
        assert k.total_volume <= capacity
        assert k.firing_temp == max(all_wares[i].temp_low for i in k.item_ids)
        assert k.firing_temp <= min(all_wares[i].temp_high for i in k.item_ids)


def test_append_items_fills_original_kiln():
    # p5 可填入窑 1（容量与温区交集均满足）-> 0 追加窑，烧成温度随之更新
    original = [
        [Ware("p1", 5, 100, 200)],
        [Ware("p2", 6, 120, 220), Ware("p3", 4, 150, 300)],
        [Ware("p4", 5, 1000, 1100)],
    ]
    kilns = append_items(original, [Ware("p5", 4, 150, 260)], 10)
    assert [k.item_ids for k in kilns] == [("p1", "p5"), ("p2", "p3"), ("p4",)]
    assert kilns[0].total_volume == 9
    assert kilns[0].firing_temp == 150  # max(100, 150)
    assert kilns[1].firing_temp == 150
    assert kilns[2].firing_temp == 1000


def test_append_items_appended_kiln():
    # 新器物填不进任何原窑 -> 追加 1 窑，置于原窑之后
    original = [[Ware("p1", 9, 100, 200)]]
    kilns = append_items(original, [Ware("p5", 5, 100, 200)], 10)
    assert [k.item_ids for k in kilns] == [("p1",), ("p5",)]
    assert kilns[1].total_volume == 5
    assert kilns[1].firing_temp == 100


def test_append_items_appended_kilns_share():
    # 两件新器物均填不进原窑，但彼此可同窑 -> 只追加 1 窑
    original = [[Ware("x", 6, 100, 200)]]
    new = [Ware("a", 5, 100, 200), Ware("b", 5, 100, 200)]
    kilns = append_items(original, new, 10)
    assert [k.item_ids for k in kilns] == [("x",), ("a", "b")]
    assert kilns[1].total_volume == 10


def test_append_items_prefers_fewer_appended_over_lex():
    # 新增窑次最少优先于字典序：填入原窑使追加窑为 0
    original = [[Ware("x", 5, 100, 200)]]
    kilns = append_items(original, [Ware("a", 5, 100, 200)], 10)
    assert [k.item_ids for k in kilns] == [("a", "x")]


def test_append_items_lex_tiebreak():
    # 追加 1 窑的三种方案并列：("a","b")("c") < ("b",)("a","c") < ("b","c")("a")
    original = [[Ware("b", 5, 100, 200)]]
    new = [Ware("a", 5, 100, 200), Ware("c", 5, 100, 200)]
    kilns = append_items(original, new, 10)
    assert [k.item_ids for k in kilns] == [("a", "b"), ("c",)]


def test_append_items_temperature_intersection():
    # a 与 x 温区相交可同窑（烧成温度升为 140）；b 与 x 温区不相交 -> 追加
    original = [[Ware("x", 1, 100, 150)]]
    new = [Ware("a", 1, 140, 200), Ware("b", 1, 160, 200)]
    kilns = append_items(original, new, 10)
    assert [k.item_ids for k in kilns] == [("a", "x"), ("b",)]
    assert kilns[0].firing_temp == 140
    assert kilns[1].firing_temp == 160


def test_append_items_multiple_into_same_kiln():
    # 同一原窑可填入多件新器物，按合并后的整体判定容量与温区
    original = [[Ware("x", 2, 100, 300)]]
    new = [Ware("a", 3, 120, 200), Ware("b", 4, 150, 250)]
    kilns = append_items(original, new, 10)
    assert [k.item_ids for k in kilns] == [("a", "b", "x")]
    assert kilns[0].total_volume == 9
    assert kilns[0].firing_temp == 150


def test_append_items_oversized():
    try:
        append_items([[Ware("x", 5, 100, 200)]], [Ware("a", 11, 100, 200)], 10)
        assert False, "应抛出 CapacityExceededError"
    except CapacityExceededError:
        pass


def test_append_items_empty_rejected():
    try:
        append_items([[Ware("x", 5, 100, 200)]], [], 10)
        assert False, "应抛出 ValueError"
    except ValueError:
        pass


def test_append_items_count_limit():
    # 原 13 件（13 窑）+ 新 2 件 = 15 件 -> 超限；+ 新 1 件 = 14 件可行
    original = [[Ware(f"o{i:02d}", 1, 100, 200)] for i in range(13)]
    try:
        append_items(
            original,
            [Ware("n1", 1, 100, 200), Ware("n2", 1, 100, 200)],
            100,
        )
        assert False, "应抛出 ValueError"
    except ValueError:
        pass
    kilns = append_items(original, [Ware("n1", 1, 100, 200)], 100)
    assert len(kilns) == 13
    # "n1" < "o00"，填入首窑使整体字典序最小
    assert kilns[0].item_ids == ("n1", "o00")


def test_append_items_performance_n14():
    # 原 1 件 + 新 13 件（合并 14 件），全兼容 -> 全部填入原窑，0 追加窑
    import time

    original = [[Ware("o0", 1, 1000, 2000)]]
    new = [Ware(f"n{i:02d}", 1, 1000 + i, 2000) for i in range(13)]
    t0 = time.time()
    kilns = append_items(original, new, 100)
    elapsed = time.time() - t0
    assert elapsed < 5.0, f"合并 14 件耗时 {elapsed:.2f}s"
    assert len(kilns) == 1
    assert kilns[0].total_volume == 14
    assert kilns[0].firing_temp == 1012


def test_append_items_random_brute_force():
    # 随机小规模用例：新增窑次数与整体方案同暴力枚举交叉验证
    rng = random.Random(2025)
    for trial in range(200):
        n_orig = rng.randint(1, 4)
        n_new = rng.randint(1, 4)
        capacity = rng.randint(6, 12)
        orig_items = []
        for i in range(n_orig):
            vol = rng.randint(1, 6)
            lo = rng.randint(900, 1000)
            hi = lo + rng.randint(0, 100)
            orig_items.append(Ware(f"o{i}", vol, lo, hi))
        new_items = []
        for i in range(n_new):
            vol = rng.randint(1, 6)
            lo = rng.randint(900, 1000)
            hi = lo + rng.randint(0, 100)
            new_items.append(Ware(f"n{i}", vol, lo, hi))

        by_id = {w.item_id: w for w in orig_items}
        original_kilns = [
            [by_id[i] for i in k.item_ids] for k in solve(orig_items, capacity)
        ]

        kilns = append_items(original_kilns, new_items, capacity)
        got = (
            len(kilns) - len(original_kilns),
            tuple(k.item_ids for k in kilns),
        )
        exp = _brute_force_append(original_kilns, new_items, capacity)
        assert got == exp, (
            f"trial {trial}: {got} != {exp}, "
            f"original={original_kilns}, new={new_items}, cap={capacity}"
        )
        _check_append_result(kilns, original_kilns, new_items, capacity)


# ---------------------------------------------------------------------------
# 取消器物 cancel_items_and_repack
# ---------------------------------------------------------------------------


def _brute_force_cancel(items, capacity, original_kilns, cancel_ids):
    """枚举剩余器物的全部 K 窑划分，K 为最少窑次，返回
    (最少窑次, 最大留窑数, 最优方案元组)，次目标并列取整体字典序最小，
    配对并列沿用 compare_kiln_assignments 的配对字典序规则。"""
    by_id = {it.item_id: it for it in items}
    cancel = set(cancel_ids)
    rem = sorted(i for i in by_id if i not in cancel)
    rem_wares = [by_id[i] for i in rem]
    min_k = len(solve(rem_wares, capacity))
    best = None  # (-留窑数, 方案元组)

    def fits(members):
        vol = sum(by_id[i].volume for i in members)
        lo = max(by_id[i].temp_low for i in members)
        hi = min(by_id[i].temp_high for i in members)
        return vol <= capacity and lo <= hi

    def rec(s, groups):
        nonlocal best
        if not s:
            if len(groups) != min_k:
                return
            plan = tuple(sorted(tuple(sorted(g)) for g in groups))
            # 与接口相同：完整原窑列表（含被腾空的窑）做一对一最优配对
            stayed = len(
                compare_kiln_assignments(original_kilns, list(plan)).stayed_item_ids
            )
            key = (-stayed, plan)
            if best is None or key < best[0]:
                best = (key, stayed)
            return

        elem = s[0]
        rest = s[1:]
        for gi in range(len(groups)):
            ng = groups[gi] | {elem}
            if fits(ng):
                rec(rest, groups[:gi] + [ng] + groups[gi + 1:])
        if fits({elem}):
            rec(rest, groups + [{elem}])

    rec(rem, [])
    assert best is not None
    return min_k, best[1], best[0][1]


def _check_cancel_result(result, items, capacity, original_kilns, cancel_ids):
    """校验取消重排结果的基本性质。"""
    by_id = {it.item_id: it for it in items}
    cancel = set(cancel_ids)
    remaining = sorted(i for i in by_id if i not in cancel)

    # 划分完备：新窑恰覆盖全部剩余器物，各窑可行且窑内编号升序
    grouped = [x for k in result.kilns for x in k.item_ids]
    assert sorted(grouped) == remaining
    assert len(grouped) == len(set(grouped))
    for k in result.kilns:
        assert list(k.item_ids) == sorted(k.item_ids)
        assert k.total_volume == sum(by_id[i].volume for i in k.item_ids)
        assert k.total_volume <= capacity
        assert k.firing_temp == max(by_id[i].temp_low for i in k.item_ids)
        assert k.firing_temp <= min(by_id[i].temp_high for i in k.item_ids)

    # 取消编号升序；留窑 + 换窑恰好划分剩余器物
    assert list(result.canceled_item_ids) == sorted(result.canceled_item_ids)
    assert set(result.canceled_item_ids) == cancel
    assert set(result.stayed_item_ids).isdisjoint(result.moved_item_ids)
    assert set(result.stayed_item_ids) | set(result.moved_item_ids) == set(remaining)
    assert result.max_stayed_count == len(result.stayed_item_ids)

    # 对外配对与留窑 / 换窑编号必须与 compare 规则完全一致
    cmp = compare_kiln_assignments(
        original_kilns, [list(k.item_ids) for k in result.kilns]
    )
    assert result.pairs == cmp.pairs
    assert result.stayed_item_ids == cmp.stayed_item_ids
    assert result.moved_item_ids == cmp.moved_item_ids


def test_cancel_items_no_reschedule_needed():
    # 原方案 3 窑，取消后每件仍单独成窑：最优配对为恒等配对，全部留窑。
    items = [Ware(str(i), 6, 100, 200) for i in range(1, 4)]
    original = [["1"], ["2"], ["3"]]
    result = cancel_items_and_repack(items, 10, original, ["2"])
    assert [k.item_ids for k in result.kilns] == [("1",), ("3",)]
    assert result.canceled_item_ids == ("2",)
    assert result.stayed_item_ids == ("1", "3")
    assert result.moved_item_ids == ()
    assert result.pairs == ((1, 1), (3, 2))
    _check_cancel_result(result, items, 10, original, ["2"])


def test_cancel_items_compact_fewer_kilns():
    # 原方案 [p1] [p2,p3] [p4](高温)；取消 p4 后 p1/p2/p3 可在容量 15 下
    # 一窑烧成，最少窑次从 3 降为 1；与原窑配对取共同器物最多者 (2,1)。
    items = [
        Ware("p1", 5, 100, 200),
        Ware("p2", 6, 120, 220),
        Ware("p3", 4, 150, 300),
        Ware("p4", 5, 1000, 1100),
    ]
    original = [["p1"], ["p2", "p3"], ["p4"]]
    result = cancel_items_and_repack(items, 15, original, ["p4"])
    assert len(result.kilns) == 1
    assert result.kilns[0].item_ids == ("p1", "p2", "p3")
    assert result.kilns[0].total_volume == 15
    assert result.kilns[0].firing_temp == 150
    # 新窑含 p2,p3，与原窑 2 配对留窑 2 件，优于与原窑 1 配对的 1 件
    assert result.pairs == ((2, 1),)
    assert result.stayed_item_ids == ("p2", "p3")
    assert result.moved_item_ids == ("p1",)
    _check_cancel_result(result, items, 15, original, ["p4"])


def test_cancel_items_stayed_beats_lex_within_min_kilns():
    # 容量 6：原方案 [a,b] [c,d]（各 6）。取消后剩余 3 件最少需 2 窑：
    # 拆法 (a)(b,c,d) 不可行（体积 9 > 6），可行拆法中
    # (a,b)(c,d去掉?)… 构造为原窑 [a,b][c,d]，取消 d -> 剩 a,b,c，
    # 可行 2 窑划分：(a,b)(c) 留窑 3，(a)(b,c) 与 (a,c)(b) 各留窑 1。
    items = [
        Ware("a", 3, 100, 200),
        Ware("b", 3, 100, 200),
        Ware("c", 3, 100, 200),
        Ware("d", 3, 100, 200),
    ]
    original = [["a", "b"], ["c", "d"]]
    result = cancel_items_and_repack(items, 6, original, ["d"])
    assert len(result.kilns) == 2
    # 整体字典序更小的 (a)(b,c) 只留 1 件，须让位于留窑 3 件的 (a,b)(c)
    assert [k.item_ids for k in result.kilns] == [("a", "b"), ("c",)]
    assert result.max_stayed_count == 3
    assert result.stayed_item_ids == ("a", "b", "c")
    assert result.moved_item_ids == ()
    assert result.pairs == ((1, 1), (2, 2))
    _check_cancel_result(result, items, 6, original, ["d"])


def test_cancel_items_pairing_lex_tiebreak():
    # 构造「最大留窑数相同、最优配对不唯一」的并列：
    # 原方案 [a] [b] [c]（容量 3，每件 3，温度全兼容），取消 z 后…
    # 直接取 3 件器物取消其中 0 件不允许，故用 4 件取消 1：
    # 原方案（容量 3）[a] [b] [c] [d]，取消 d 后剩 a,b,c 仍需 3 窑（单件），
    # 无并列。改容量 6：原 [a,b] [c] [d]，取消 d 后剩 a,b,c，最少 2 窑，
    # 可行划分 (a,b)(c) 与 (a)(b,c)：
    #   方案 (a,b)(c)：配对 (1,1)(2,2) 留窑 3；
    #   方案 (a)(b,c)：配对 (1,1)(2,2) 留窑 1（(2,1)(3,2) 也是 1）。
    # 留窑数不同，无并列。真正并列需要各窑器物错配后仍同分：
    items = [
        Ware("a", 3, 100, 200),
        Ware("b", 3, 100, 200),
        Ware("c", 3, 100, 200),
    ]
    # 容量 6 原方案 [a] [b,c]，取消后剩 a,b（取消 c）：
    # 最少 1 窑 (a,b)，与原窑 1/2 配对均留窑 1，配对并列取
    # 字典序最小 (1,1)，故 a 留窑、b 换窑。
    original = [["a"], ["b", "c"]]
    result = cancel_items_and_repack(items, 6, original, ["c"])
    assert len(result.kilns) == 1
    assert result.kilns[0].item_ids == ("a", "b")
    assert result.max_stayed_count == 1
    assert result.pairs == ((1, 1),)
    assert result.stayed_item_ids == ("a",)
    assert result.moved_item_ids == ("b",)
    _check_cancel_result(result, items, 6, original, ["c"])


def test_cancel_items_empty_original_kiln_counts_unpaired():
    # 取消某窑的全部器物后该窑被腾空：腾空窑不参与配对，原在其中者不存在，
    # 其余器物若换窑仍按规则统计。
    items = [
        Ware("h", 5, 1000, 1100),
        Ware("x", 6, 100, 200),
        Ware("y", 6, 100, 200),
    ]
    original = [["h"], ["x"], ["y"]]
    result = cancel_items_and_repack(items, 10, original, ["h"])
    assert len(result.kilns) == 2
    assert [k.item_ids for k in result.kilns] == [("x",), ("y",)]
    # 原窑 1 腾空；剩 2 窑与新窑配 2 对，字典序最小为 (2,1)(3,2)
    assert result.pairs == ((2, 1), (3, 2))
    assert result.stayed_item_ids == ("x", "y")
    assert result.moved_item_ids == ()
    _check_cancel_result(result, items, 10, original, ["h"])


def test_cancel_items_invalid():
    items = [Ware("a", 1, 100, 200), Ware("b", 1, 100, 200)]
    original = [["a"], ["b"]]
    for bad in ([], ["a", "a"], ["z"], ["a", "b"]):
        try:
            cancel_items_and_repack(items, 10, original, bad)
            assert False, f"{bad}: 应抛出 ValueError"
        except ValueError:
            pass


def test_cancel_items_random_brute_force():
    # 随机小规模用例：最少窑次、最大留窑数、整体字典序方案全部交叉验证
    rng = random.Random(31337)
    for trial in range(400):
        n = rng.randint(2, 7)
        items = []
        for i in range(n):
            vol = rng.randint(1, 7)
            lo = rng.randint(100, 140)
            hi = lo + rng.randint(0, 40)
            items.append(Ware(f"i{i}", vol, lo, hi))
        capacity = rng.randint(max(it.volume for it in items), 18)
        original = [list(k.item_ids) for k in solve(items, capacity)]
        cancel = rng.sample(
            sorted(it.item_id for it in items), rng.randint(1, n - 1)
        )

        result = cancel_items_and_repack(items, capacity, original, cancel)
        exp_k, exp_stayed, exp_plan = _brute_force_cancel(
            items, capacity, original, cancel
        )
        got_plan = tuple(k.item_ids for k in result.kilns)
        assert len(result.kilns) == exp_k, (
            f"trial {trial}: kilns {len(result.kilns)} != {exp_k}"
        )
        assert result.max_stayed_count == exp_stayed, (
            f"trial {trial}: stayed {result.max_stayed_count} != {exp_stayed}, "
            f"items={items}, cap={capacity}, cancel={cancel}, "
            f"original={original}, got={got_plan}"
        )
        assert got_plan == exp_plan, (
            f"trial {trial}: {got_plan} != {exp_plan}, "
            f"items={items}, cap={capacity}, cancel={cancel}, original={original}"
        )
        _check_cancel_result(result, items, capacity, original, cancel)


def test_cancel_items_performance_n14():
    # 取消 1 件、容量 4（剩余 13 件最少 4 窑）的较紧场景，控制在数秒内
    import time

    items = [Ware(f"i{i:02d}", 1, 100, 200) for i in range(14)]
    original = [list(k.item_ids) for k in solve(items, 4)]
    t0 = time.time()
    result = cancel_items_and_repack(items, 4, original, ["i00"])
    elapsed = time.time() - t0
    assert elapsed < 10.0, f"取消重排耗时 {elapsed:.2f}s"
    assert len(result.kilns) == 4
    assert result.max_stayed_count == 13


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n全部 {len(fns)} 个测试通过")