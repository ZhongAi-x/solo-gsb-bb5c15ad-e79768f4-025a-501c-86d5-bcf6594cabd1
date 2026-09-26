"""inspection 单元测试：固定用例 + 小规模独立枚举交叉验证。

暴力参考实现不使用被测模块的位掩码递推，而是用 itertools.combinations
枚举全部器物组合，逐一检查预算与窑次覆盖后，按「风险分总和最大 →
总耗时最小 → 抽中编号升序列表字典序最小」择优，与子集递推相互独立。
"""

import os
import random
import sys
from itertools import combinations

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.inspection import (  # noqa: E402
    InspectionItem,
    NoFeasibleInspectionSampleError,
    select_inspection_sample,
)


def _brute_sample(kiln_item_ids, params, budget):
    """枚举全部组合的参考实现；返回最优抽中编号元组（升序）或 None。

    params: {item_id: (risk_score, inspect_minutes)}
    """
    ids = sorted(params)
    k = len(kiln_item_ids)
    best = None  # ((-风险分, 总耗时, 编号元组), 编号元组)
    for r in range(1, len(ids) + 1):
        for combo in combinations(ids, r):
            minutes = sum(params[i][1] for i in combo)
            if minutes > budget:
                continue
            picked = set(combo)
            if any(
                not any(i in picked for i in kiln_ids)
                for kiln_ids in kiln_item_ids
            ):
                continue
            risk = sum(params[i][0] for i in combo)
            key = (-risk, minutes, combo)
            if best is None or key < best[0]:
                best = (key, combo)
    return None if best is None else best[1]


def _check_against_brute(kiln_item_ids, items, budget):
    params = {it.item_id: (it.risk_score, it.inspect_minutes) for it in items}
    expected = _brute_sample(kiln_item_ids, params, budget)
    assert expected is not None, "暴力枚举认为可行，但 select_inspection_sample 未返回结果"

    result = select_inspection_sample(kiln_item_ids, items, budget)
    assert result.sampled_item_ids == expected
    assert result.total_risk_score == sum(params[i][0] for i in expected)
    assert result.total_inspect_minutes == sum(params[i][1] for i in expected)
    assert result.total_inspect_minutes <= budget

    # 覆盖不变式：每个窑次至少抽中一件，且各窑明细与抽中编号一致
    sampled = set(result.sampled_item_ids)
    assert len(result.kilns) == len(kiln_item_ids)
    for idx, (kiln_out, kiln_ids) in enumerate(
        zip(result.kilns, kiln_item_ids), start=1
    ):
        assert kiln_out.kiln_index == idx
        assert kiln_out.sampled_item_ids == tuple(
            sorted(i for i in kiln_ids if i in sampled)
        )
        assert len(kiln_out.sampled_item_ids) >= 1
    assert sorted(i for k in result.kilns for i in k.sampled_item_ids) == sorted(
        sampled
    )
    return result


def test_basic_budget_forces_choice():
    # 窑 1 [p1]、窑 2 [p2,p3]、窑 3 [p4]；最低覆盖耗时 10+3+8 = 21
    kilns = [["p1"], ["p2", "p3"], ["p4"]]
    items = [
        InspectionItem("p1", 5, 10),
        InspectionItem("p2", 9, 7),
        InspectionItem("p3", 4, 3),
        InspectionItem("p4", 6, 8),
    ]
    # 预算 21：只能取各窑最低耗时器物
    r = _check_against_brute(kilns, items, 21)
    assert r.sampled_item_ids == ("p1", "p3", "p4")
    assert r.total_risk_score == 15
    assert r.total_inspect_minutes == 21

    # 预算 25：p1+p2+p4 = 25 分钟、风险 20，优于 p1+p3+p4 的风险 15
    r = _check_against_brute(kilns, items, 25)
    assert r.sampled_item_ids == ("p1", "p2", "p4")
    assert r.total_risk_score == 20
    assert r.total_inspect_minutes == 25


def test_tie_break_min_minutes_then_lexicographic():
    # 风险分相同 -> 取总耗时更小者
    kilns = [["a"], ["b"]]
    items = [
        InspectionItem("a", 5, 4),
        InspectionItem("b", 5, 9),
    ]
    r = _check_against_brute(kilns, items, 100)
    assert r.sampled_item_ids == ("a", "b")
    assert r.total_inspect_minutes == 13

    # 风险分与耗时都相同 -> 取抽中编号升序列表字典序最小者
    kilns = [["a", "b"], ["c"]]
    items = [
        InspectionItem("a", 5, 4),
        InspectionItem("b", 5, 4),
        InspectionItem("c", 1, 1),
    ]
    r = _check_against_brute(kilns, items, 5)
    assert r.sampled_item_ids == ("a", "c")
    assert r.total_risk_score == 6
    assert r.total_inspect_minutes == 5


def test_zero_risk_scores_pick_min_minutes():
    # 全部风险分为 0（非负允许）：风险并列后取总耗时最小
    kilns = [["a", "b"], ["c", "d"]]
    items = [
        InspectionItem("a", 0, 6),
        InspectionItem("b", 0, 2),
        InspectionItem("c", 0, 5),
        InspectionItem("d", 0, 3),
    ]
    r = _check_against_brute(kilns, items, 100)
    assert r.sampled_item_ids == ("b", "d")
    assert r.total_risk_score == 0
    assert r.total_inspect_minutes == 5


def test_no_feasible_coverage():
    # 最低覆盖耗时 10+3+8 = 21，预算 20 无可行覆盖
    kilns = [["p1"], ["p2", "p3"], ["p4"]]
    items = [
        InspectionItem("p1", 5, 10),
        InspectionItem("p2", 9, 7),
        InspectionItem("p3", 4, 3),
        InspectionItem("p4", 6, 8),
    ]
    try:
        select_inspection_sample(kilns, items, 20)
    except NoFeasibleInspectionSampleError as exc:
        assert "21" in str(exc)
        assert "20" in str(exc)
    else:
        raise AssertionError("应抛出 NoFeasibleInspectionSampleError")

    assert _brute_sample(kilns, {i.item_id: (i.risk_score, i.inspect_minutes) for i in items}, 20) is None

    # 预算为 0 恒不可行（每窑至少一件、每件至少 1 分钟）
    try:
        select_inspection_sample([["p1"]], [InspectionItem("p1", 0, 1)], 0)
    except NoFeasibleInspectionSampleError:
        pass
    else:
        raise AssertionError("预算 0 应抛出 NoFeasibleInspectionSampleError")


def test_single_kiln_picks_best_item_within_budget():
    kilns = [["a", "b", "c"]]
    items = [
        InspectionItem("a", 3, 5),
        InspectionItem("b", 8, 6),
        InspectionItem("c", 8, 4),
    ]
    # 预算 6：b、c 风险并列 8，取耗时更小的 c
    r = _check_against_brute(kilns, items, 6)
    assert r.sampled_item_ids == ("c",)
    assert r.total_risk_score == 8


def test_validation_errors():
    kilns = [["a"], ["b"]]
    items = [InspectionItem("a", 1, 1), InspectionItem("b", 1, 1)]

    # 重复编号
    try:
        select_inspection_sample(
            kilns, [InspectionItem("a", 1, 1), InspectionItem("a", 2, 2)], 10
        )
    except ValueError as exc:
        assert "不得重复" in str(exc)
    else:
        raise AssertionError("重复编号应抛出 ValueError")

    # 不属于原方案的编号
    try:
        select_inspection_sample(
            kilns, [InspectionItem("a", 1, 1), InspectionItem("x", 1, 1)], 10
        )
    except ValueError as exc:
        assert "不属于原方案" in str(exc)
    else:
        raise AssertionError("未知编号应抛出 ValueError")

    # 缺少编号
    try:
        select_inspection_sample(kilns, [InspectionItem("a", 1, 1)], 10)
    except ValueError as exc:
        assert "缺少编号" in str(exc)
    else:
        raise AssertionError("缺少编号应抛出 ValueError")

    # 负风险分 / 非正分钟数 / 负预算
    for bad in (
        lambda: select_inspection_sample(
            kilns, [InspectionItem("a", -1, 1), InspectionItem("b", 1, 1)], 10
        ),
        lambda: select_inspection_sample(
            kilns, [InspectionItem("a", 1, 0), InspectionItem("b", 1, 1)], 10
        ),
        lambda: select_inspection_sample(kilns, items, -1),
    ):
        try:
            bad()
        except ValueError:
            pass
        else:
            raise AssertionError("非法参数应抛出 ValueError")


def test_random_cross_validation():
    rng = random.Random(20260926)
    trials = 400
    for trial in range(trials):
        n = rng.randint(1, 8)
        ids = [f"i{i:02d}" for i in range(n)]
        # 随机划分窑次：每件器物随机归入一个窑，打乱后按窑分组
        assignment = [rng.randint(0, n - 1) for _ in range(n)]
        kilns = [
            sorted(ids[i] for i in range(n) if assignment[i] == k)
            for k in range(n)
        ]
        kilns = [kiln for kiln in kilns if kiln]
        params = {
            i: (rng.randint(0, 20), rng.randint(1, 15)) for i in ids
        }
        items = [InspectionItem(i, params[i][0], params[i][1]) for i in ids]
        min_required = sum(
            min(params[i][1] for i in kiln) for kiln in kilns
        )
        budget = rng.randint(0, min_required + 30)

        expected = _brute_sample(kilns, params, budget)
        if expected is None:
            try:
                select_inspection_sample(kilns, items, budget)
            except NoFeasibleInspectionSampleError:
                continue
            raise AssertionError(
                f"trial {trial}: 暴力枚举认为无解，但求解返回了抽样"
            )
        _check_against_brute(kilns, items, budget)


def test_performance_n14():
    import time

    ids = [f"i{i:02d}" for i in range(14)]
    kilns = [[i] for i in ids]  # 14 个窑次，每窑一件
    items = [
        InspectionItem(i, (idx * 7) % 13, (idx * 5) % 11 + 1)
        for idx, i in enumerate(ids)
    ]
    budget = sum(it.inspect_minutes for it in items)
    t0 = time.time()
    r = select_inspection_sample(kilns, items, budget)
    elapsed = time.time() - t0
    assert elapsed < 5.0, f"n=14 耗时 {elapsed:.2f}s"
    assert r.sampled_item_ids == tuple(ids)
    assert r.total_inspect_minutes == budget


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n全部 {len(fns)} 个测试通过")
