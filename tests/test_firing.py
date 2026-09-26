"""firing 单元测试：固定用例 + 小规模全排列暴力枚举交叉验证。"""

import random
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.firing import (  # noqa: E402
    FiringBatch,
    NoFeasibleFiringOrderError,
    earliest_firing_schedule,
)


def _brute_force(batches):
    """枚举全部点火排列，返回 (最早整体完工时刻, 字典序最小顺序, 各批安排)。

    固定排列下逐批尽量早点火即该排列的最优排程（完成时刻逐批最小，
    若该排列存在不逾期排程，此排程必不逾期）；在所有不逾期排列中取
    完工时刻最小者，并列取窑次序号序列字典序最小。无可行排列返回 None。
    """
    from itertools import permutations

    ordered = sorted(batches, key=lambda b: b.kiln_index)
    best = None  # ((完工时刻, 顺序元组), {窑次序号: (点火, 完成)})
    for perm in permutations(ordered):
        t = 0
        schedule = {}
        feasible = True
        for b in perm:
            s = max(t, b.earliest_start)
            c = s + b.duration
            if c > b.latest_completion:
                feasible = False
                break
            schedule[b.kiln_index] = (s, c)
            t = c
        if not feasible:
            continue
        key = (t, tuple(b.kiln_index for b in perm))
        if best is None or key < best[0]:
            best = (key, schedule)
    if best is None:
        return None
    (makespan, order), schedule = best
    return makespan, order, schedule


def _check_schedule(schedule, batches):
    """校验排程结果的基本性质：覆盖完备、不并行、约束满足、不逾期。"""
    by_index = {b.kiln_index: b for b in batches}
    assert len(schedule.batches) == len(batches)
    assert {b.kiln_index for b in schedule.batches} == set(by_index)
    t = 0
    for b in schedule.batches:
        c = by_index[b.kiln_index]
        assert b.start == max(t, c.earliest_start)  # 尽量早点火（允许空闲）
        assert b.start >= c.earliest_start
        assert b.completion == b.start + c.duration
        assert b.completion <= c.latest_completion
        assert b.start >= t  # 单台窑不可并行
        t = b.completion
    assert schedule.makespan == t


def test_basic_no_idle():
    # 三批均可从 0 点火、互不冲突：按窑次序号顺烧，无空闲
    batches = [
        FiringBatch(1, 0, 120, 400),
        FiringBatch(2, 0, 150, 400),
        FiringBatch(3, 0, 90, 480),
    ]
    schedule = earliest_firing_schedule(batches)
    assert schedule.makespan == 360
    assert [b.kiln_index for b in schedule.batches] == [1, 2, 3]
    assert [(b.start, b.completion) for b in schedule.batches] == [
        (0, 120),
        (120, 270),
        (270, 360),
    ]
    _check_schedule(schedule, batches)


def test_deadline_forces_reorder_and_idle():
    # 批次 2 须落在 [150, 300]：批次 3 先烧（[0,120]），空闲 30 分钟后
    # 批次 2 在 150 点火，批次 1 最后 -> 唯一最优顺序 (3, 2, 1)，完工 390
    batches = [
        FiringBatch(1, 0, 90, 480),
        FiringBatch(2, 150, 150, 300),
        FiringBatch(3, 0, 120, 400),
    ]
    schedule = earliest_firing_schedule(batches)
    assert schedule.makespan == 390
    assert [b.kiln_index for b in schedule.batches] == [3, 2, 1]
    assert [(b.start, b.completion) for b in schedule.batches] == [
        (0, 120),
        (150, 300),
        (300, 390),
    ]
    _check_schedule(schedule, batches)


def test_earliest_start_delays_first_batch():
    # 全部批次最早可点火均在未来：排程起点后先空闲
    batches = [FiringBatch(1, 100, 30, 200), FiringBatch(2, 50, 40, 300)]
    schedule = earliest_firing_schedule(batches)
    assert schedule.makespan == 130
    assert [b.kiln_index for b in schedule.batches] == [2, 1]
    assert [(b.start, b.completion) for b in schedule.batches] == [(50, 90), (100, 130)]
    _check_schedule(schedule, batches)


def test_lex_tiebreak():
    # 两批约束完全相同：两种顺序同为最优，取窑次序号序列字典序最小者
    batches = [FiringBatch(2, 0, 10, 100), FiringBatch(1, 0, 10, 100)]
    schedule = earliest_firing_schedule(batches)
    assert schedule.makespan == 20
    assert [b.kiln_index for b in schedule.batches] == [1, 2]
    _check_schedule(schedule, batches)


def test_infeasible_single_batch():
    # 单批自身约束矛盾：最早可点火 + 烧成时长 > 最迟完成
    try:
        earliest_firing_schedule([FiringBatch(1, 10, 20, 25)])
        assert False, "应抛出 NoFeasibleFiringOrderError"
    except NoFeasibleFiringOrderError:
        pass


def test_infeasible_conflicting_batches():
    # 两批均须独占 [0, 100] 窗口：不可并行必然逾期其一
    batches = [
        FiringBatch(1, 0, 100, 100),
        FiringBatch(2, 0, 100, 100),
    ]
    try:
        earliest_firing_schedule(batches)
        assert False, "应抛出 NoFeasibleFiringOrderError"
    except NoFeasibleFiringOrderError:
        pass


def test_invalid_input():
    good = FiringBatch(1, 0, 10, 100)
    # 空列表 / 超过 14 批 / 窑次序号重复
    for bad in (
        [],
        [FiringBatch(i, 0, 10, 100) for i in range(1, 16)],
        [good, FiringBatch(1, 0, 5, 50)],
    ):
        try:
            earliest_firing_schedule(bad)
            assert False, f"{bad}: 应抛出 ValueError"
        except ValueError:
            pass
    # 分钟为负 / 烧成时长非正
    for bad in (
        [FiringBatch(1, -1, 10, 100)],
        [FiringBatch(1, 0, 10, -5)],
        [FiringBatch(1, 0, 0, 100)],
    ):
        try:
            earliest_firing_schedule(bad)
            assert False, f"{bad}: 应抛出 ValueError"
        except ValueError:
            pass


def test_random_brute_force():
    # 随机小规模用例：最早完工时刻、点火顺序与各批点火/完成分钟
    # 全部同全排列暴力枚举交叉验证
    rng = random.Random(2026)
    for trial in range(400):
        n = rng.randint(1, 7)
        batches = []
        for i in range(1, n + 1):
            r = rng.randint(0, 30)
            p = rng.randint(1, 20)
            d = rng.randint(0, 80)
            batches.append(FiringBatch(i, r, p, d))
        rng.shuffle(batches)  # 传入顺序不影响结果

        exp = _brute_force(batches)
        if exp is None:
            try:
                earliest_firing_schedule(batches)
                assert False, f"trial {trial}: 应抛出 NoFeasibleFiringOrderError"
            except NoFeasibleFiringOrderError:
                continue
        exp_makespan, exp_order, exp_schedule = exp
        schedule = earliest_firing_schedule(batches)
        assert schedule.makespan == exp_makespan, (
            f"trial {trial}: makespan {schedule.makespan} != {exp_makespan}, "
            f"batches={batches}"
        )
        got_order = tuple(b.kiln_index for b in schedule.batches)
        assert got_order == exp_order, (
            f"trial {trial}: order {got_order} != {exp_order}, batches={batches}"
        )
        for b in schedule.batches:
            assert (b.start, b.completion) == exp_schedule[b.kiln_index], (
                f"trial {trial}: kiln {b.kiln_index} "
                f"{(b.start, b.completion)} != {exp_schedule[b.kiln_index]}"
            )
        _check_schedule(schedule, batches)


def test_performance_n14():
    # n=14 全兼容：完工时刻下界即时长之和，耗时控制在数秒内
    import time

    batches = [FiringBatch(i, 0, 5, 1000) for i in range(1, 15)]
    t0 = time.time()
    schedule = earliest_firing_schedule(batches)
    elapsed = time.time() - t0
    assert schedule.makespan == 70
    assert [b.kiln_index for b in schedule.batches] == list(range(1, 15))
    assert elapsed < 5.0, f"n=14 耗时 {elapsed:.2f}s"

    # n=14 且全部互相冲突（窗口相同、时长之和恰等于窗长）：唯一顺序可行
    tight = [FiringBatch(i, 0, 10, 140) for i in range(1, 15)]
    schedule = earliest_firing_schedule(tight)
    assert schedule.makespan == 140
    _check_schedule(schedule, tight)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n全部 {len(fns)} 个测试通过")
