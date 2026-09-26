"""database 持久化测试：超大容量存取、旧表迁移的原子性与幂等性。

无需第三方依赖，直接运行：python3 tests/test_database.py
"""

import json
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_TMP = tempfile.mkdtemp(prefix="kiln-db-test-")

from app import database  # noqa: E402

INT64_MAX = 2**63 - 1
HUGE = 10**30  # 远超 SQLite 有符号 64 位整数上限


def _use_fresh_db(name: str) -> str:
    database.DB_PATH = os.path.join(_TMP, name)
    return database.DB_PATH


def _raw_column_type(db_path: str, table: str, column: str) -> str:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(
            f"SELECT type FROM pragma_table_info('{table}') WHERE name = ?",
            (column,),
        ).fetchone()[0].upper()
    finally:
        conn.close()


def _raw_row(db_path: str, plan_id: str) -> tuple[str, str]:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(
            "SELECT capacity, payload FROM plans WHERE id = ?", (plan_id,)
        ).fetchone()
    finally:
        conn.close()


def _make_plan(plan_id: str, capacity: int, created_at: str = "2026-09-26T00:00:00+00:00") -> dict:
    return {
        "id": plan_id,
        "capacity": capacity,
        "item_count": 1,
        "kiln_count": 1,
        "items": [
            {"item_id": "p1", "volume": 5, "temp_low": 100, "temp_high": 200},
        ],
        "kilns": [
            {"index": 1, "item_ids": ["p1"], "total_volume": 5, "firing_temp": 100},
        ],
        "created_at": created_at,
    }


def test_fresh_db_stores_capacity_as_text():
    db_path = _use_fresh_db("fresh.db")
    database.init_db()
    assert _raw_column_type(db_path, "plans", "capacity") == "TEXT"

    database.save_plan(_make_plan("a", HUGE))
    raw_capacity, raw_payload = _raw_row(db_path, "a")
    assert raw_capacity == str(HUGE)
    assert json.loads(raw_payload)["capacity"] == HUGE

    plan = database.get_plan("a")
    assert plan["capacity"] == HUGE
    assert isinstance(plan["capacity"], int)
    print("ok: 新库 capacity 为 TEXT，超大容量存取后读回仍为整数")


def test_int64_boundary_capacities():
    _use_fresh_db("boundary.db")
    database.init_db()
    for i, capacity in enumerate((INT64_MAX, INT64_MAX + 1, INT64_MAX + 12345)):
        plan_id = f"b{i}"
        database.save_plan(_make_plan(plan_id, capacity))
        assert database.get_plan(plan_id)["capacity"] == capacity
    print("ok: 64 位边界及超大容量均可正确保存与读回")


def test_legacy_table_migrated_and_preserved():
    db_path = _use_fresh_db("legacy.db")
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE plans (
            id TEXT PRIMARY KEY,
            capacity INTEGER NOT NULL,
            item_count INTEGER NOT NULL,
            kiln_count INTEGER NOT NULL,
            payload TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    old_plan_small = _make_plan("old-small", 10)
    old_plan_boundary = _make_plan("old-boundary", INT64_MAX)
    for plan in (old_plan_small, old_plan_boundary):
        conn.execute(
            "INSERT INTO plans (id, capacity, item_count, kiln_count, payload, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                plan["id"],
                plan["capacity"],
                plan["item_count"],
                plan["kiln_count"],
                json.dumps(plan, ensure_ascii=False),
                plan["created_at"],
            ),
        )
    conn.commit()
    conn.close()

    assert _raw_column_type(db_path, "plans", "capacity") == "INTEGER"

    database.init_db()

    # 表结构升级为 TEXT，两条既有方案及其余字段全部保留。
    assert _raw_column_type(db_path, "plans", "capacity") == "TEXT"
    assert _raw_row(db_path, "old-small")[0] == "10"
    assert _raw_row(db_path, "old-boundary")[0] == str(INT64_MAX)
    assert database.get_plan("old-small") == old_plan_small
    assert database.get_plan("old-boundary") == old_plan_boundary

    # 迁移后的表可继续写入超大容量。
    database.save_plan(_make_plan("new-huge", HUGE))
    assert database.get_plan("new-huge")["capacity"] == HUGE
    print("ok: 旧 INTEGER 表单事务迁移为 TEXT，既有方案保留且可写超大容量")


def test_init_db_idempotent():
    fresh_path = _use_fresh_db("idempotent.db")
    # 全新库连续初始化
    database.init_db()
    database.init_db()
    database.save_plan(_make_plan("h", HUGE))

    # 旧库迁移后连续再启动，数据与结构不变
    legacy_path = _use_fresh_db("idempotent-legacy.db")
    conn = sqlite3.connect(legacy_path)
    conn.execute(
        "CREATE TABLE plans (id TEXT PRIMARY KEY, capacity INTEGER NOT NULL,"
        " item_count INTEGER NOT NULL, kiln_count INTEGER NOT NULL,"
        " payload TEXT NOT NULL, created_at TEXT NOT NULL)"
    )
    plan = _make_plan("keep", 42)
    conn.execute(
        "INSERT INTO plans VALUES (?, ?, ?, ?, ?, ?)",
        (
            plan["id"],
            plan["capacity"],
            plan["item_count"],
            plan["kiln_count"],
            json.dumps(plan, ensure_ascii=False),
            plan["created_at"],
        ),
    )
    conn.commit()
    conn.close()

    for _ in range(3):
        database.init_db()
        assert _raw_column_type(legacy_path, "plans", "capacity") == "TEXT"
        assert database.get_plan("keep") == plan

    database.DB_PATH = fresh_path
    assert _raw_column_type(fresh_path, "plans", "capacity") == "TEXT"
    assert database.get_plan("h")["capacity"] == HUGE
    print("ok: 重复启动幂等，迁移只执行一次")


def test_failed_migration_rolls_back():
    db_path = _use_fresh_db("rollback.db")
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE plans (id TEXT PRIMARY KEY, capacity INTEGER NOT NULL,"
        " item_count INTEGER NOT NULL, kiln_count INTEGER NOT NULL,"
        " payload TEXT NOT NULL, created_at TEXT NOT NULL)"
    )
    plan = _make_plan("immutable", 7)
    conn.execute(
        "INSERT INTO plans VALUES (?, ?, ?, ?, ?, ?)",
        (
            plan["id"],
            plan["capacity"],
            plan["item_count"],
            plan["kiln_count"],
            json.dumps(plan, ensure_ascii=False),
            plan["created_at"],
        ),
    )
    # 临时表名被视图占用，迁移第一步 DROP TABLE 即失败。
    conn.execute(f"CREATE VIEW {database._MIGRATION_TMP_TABLE} AS SELECT 1")
    conn.commit()
    conn.close()

    try:
        database.init_db()
    except sqlite3.OperationalError:
        pass
    else:
        raise AssertionError("迁移失败时应抛出异常")

    # 事务整体回滚：旧表、旧行、旧列类型与视图都保持原状，无残留临时表。
    assert _raw_column_type(db_path, "plans", "capacity") == "INTEGER"
    assert database.get_plan("immutable") == plan
    check = sqlite3.connect(db_path)
    try:
        assert check.execute(
            "SELECT name FROM sqlite_master WHERE name = ?",
            (database._MIGRATION_TMP_TABLE,),
        ).fetchone()[0] == database._MIGRATION_TMP_TABLE
        assert check.execute(
            "SELECT type FROM sqlite_master WHERE name = 'plans'"
        ).fetchone()[0] == "table"
    finally:
        check.close()

    # 排除故障后再次启动，迁移顺利完成。
    conn = sqlite3.connect(db_path)
    conn.execute(f"DROP VIEW {database._MIGRATION_TMP_TABLE}")
    conn.commit()
    conn.close()
    database.init_db()
    assert _raw_column_type(db_path, "plans", "capacity") == "TEXT"
    assert database.get_plan("immutable") == plan
    print("ok: 迁移失败整体回滚不留半迁移表，排除故障后重试成功")


def test_api_save_paths_keep_huge_capacity():
    # 路由级用例需要 fastapi / pydantic；与其它测试一致，缺少依赖时跳过。
    try:
        from app.main import (
            append_plan_items,
            cancel_plan_items,
            create_plan,
            read_plan,
        )
        from app.schemas import AppendItemsIn, CancelItemsIn, PlanCreate
    except ImportError:  # pragma: no cover - 容器与 CI 环境始终装有依赖
        print("skip: 未安装 fastapi / pydantic，跳过路由级用例")
        return

    _use_fresh_db("api.db")
    database.init_db()

    created = create_plan(
        PlanCreate(
            capacity=HUGE,
            items=[
                {"item_id": "p1", "volume": 5, "temp_low": 100, "temp_high": 200},
                {"item_id": "p2", "volume": 6, "temp_low": 120, "temp_high": 220},
            ],
        )
    )
    assert created.capacity == HUGE
    assert read_plan(created.id).capacity == HUGE

    appended = append_plan_items(
        created.id,
        AppendItemsIn(
            items=[
                {"item_id": "p3", "volume": 4, "temp_low": 150, "temp_high": 300},
            ]
        ),
    )
    assert appended.capacity == HUGE
    assert read_plan(appended.id).capacity == HUGE

    canceled = cancel_plan_items(
        appended.id, CancelItemsIn(item_ids=["p3"])
    )
    assert canceled.new_plan.capacity == HUGE
    assert read_plan(canceled.new_plan_id).capacity == HUGE

    # 原方案未被改写。
    assert read_plan(created.id).item_count == 2
    print("ok: 创建 / 追加另存 / 取消另存三条路径均持久化并返回超大容量")


if __name__ == "__main__":
    test_fresh_db_stores_capacity_as_text()
    test_int64_boundary_capacities()
    test_legacy_table_migrated_and_preserved()
    test_init_db_idempotent()
    test_failed_migration_rolls_back()
    test_api_save_paths_keep_huge_capacity()
    print("全部 database 测试通过")
