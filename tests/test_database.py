"""database 持久化层测试：容量十进制文本存储与旧表事务迁移。

覆盖：
  * 新库建表后 plans.capacity 列为 TEXT；
  * 超出 SQLite 有符号 64 位上限的容量可保存、并按原 JSON 整数读回；
  * 旧版 INTEGER 表在 init_db 中以事务迁移为 TEXT，既有方案完整保留；
  * 迁移失败整体回滚、不留半迁移表，重复 init_db 幂等。
"""

import json
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import database  # noqa: E402

INT64_MAX = 2**63 - 1
HUGE_CAPACITY = 2**63  # 超出 SQLite 有符号 64 位上限
HUGER_CAPACITY = 10**30

_OLD_SCHEMA = """
CREATE TABLE plans (
    id          TEXT PRIMARY KEY,
    capacity    INTEGER NOT NULL,
    item_count  INTEGER NOT NULL,
    kiln_count  INTEGER NOT NULL,
    payload     TEXT NOT NULL,
    created_at  TEXT NOT NULL
)
"""


def _make_plan(plan_id, capacity):
    return {
        "id": plan_id,
        "capacity": capacity,
        "item_count": 2,
        "kiln_count": 1,
        "items": [
            {"item_id": "p1", "volume": 5, "temp_low": 100, "temp_high": 200},
            {"item_id": "p2", "volume": 6, "temp_low": 120, "temp_high": 220},
        ],
        "kilns": [
            {"index": 1, "item_ids": ["p1", "p2"], "total_volume": 11, "firing_temp": 120}
        ],
        "created_at": "2026-09-26T00:00:00+00:00",
    }


def _use_tmp_db():
    """把 database.DB_PATH 指向一个新的临时文件，返回路径。"""

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)  # 由 connect() 按需创建，模拟全新数据库
    database.DB_PATH = path
    return path


def _capacity_column(path):
    conn = sqlite3.connect(path)
    try:
        return {
            row[1]: row[2].upper() for row in conn.execute("PRAGMA table_info(plans)")
        }["capacity"]
    finally:
        conn.close()


def _table_names(path):
    conn = sqlite3.connect(path)
    try:
        return {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    finally:
        conn.close()


def _create_legacy_db(path, plans):
    """按旧版 INTEGER 结构建库并插入既有方案，返回各方案的 payload 文本。"""

    payloads = {}
    conn = sqlite3.connect(path)
    try:
        conn.execute(_OLD_SCHEMA)
        for plan in plans:
            payload = json.dumps(plan, ensure_ascii=False)
            conn.execute(
                "INSERT INTO plans (id, capacity, item_count, kiln_count, payload, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    plan["id"],
                    plan["capacity"],
                    plan["item_count"],
                    plan["kiln_count"],
                    payload,
                    plan["created_at"],
                ),
            )
            payloads[plan["id"]] = payload
        conn.commit()
    finally:
        conn.close()
    return payloads


def test_fresh_schema_uses_text_capacity():
    path = _use_tmp_db()
    database.init_db()
    assert _capacity_column(path) == "TEXT"
    assert _table_names(path) == {"plans"}


def test_save_and_get_huge_capacity():
    _use_tmp_db()
    database.init_db()
    for capacity in (1, INT64_MAX, HUGE_CAPACITY, HUGER_CAPACITY):
        plan = _make_plan(f"plan-{capacity}", capacity)
        database.save_plan(plan)
        loaded = database.get_plan(plan["id"])
        assert loaded is not None
        assert loaded["capacity"] == capacity
        assert isinstance(loaded["capacity"], int)
        assert loaded == plan
    assert database.get_plan("no-such-plan") is None


def test_capacity_stored_as_decimal_text():
    path = _use_tmp_db()
    database.init_db()
    database.save_plan(_make_plan("p-huge", HUGE_CAPACITY))
    conn = sqlite3.connect(path)
    try:
        value, storage = conn.execute(
            "SELECT capacity, typeof(capacity) FROM plans WHERE id = 'p-huge'"
        ).fetchone()
    finally:
        conn.close()
    assert storage == "text"
    assert value == str(HUGE_CAPACITY)


def test_migration_preserves_existing_plans():
    path = _use_tmp_db()
    plans = [_make_plan("legacy-1", 10), _make_plan("legacy-2", INT64_MAX)]
    payloads = _create_legacy_db(path, plans)
    assert _capacity_column(path) == "INTEGER"

    database.init_db()

    assert _capacity_column(path) == "TEXT"
    assert _table_names(path) == {"plans"}
    conn = sqlite3.connect(path)
    try:
        rows = dict(
            conn.execute("SELECT id, capacity FROM plans").fetchall()
        )
    finally:
        conn.close()
    assert rows == {"legacy-1": "10", "legacy-2": str(INT64_MAX)}

    # 既有方案的 payload 逐字节保留，读取时 capacity 仍为 JSON 整数
    for plan in plans:
        loaded = database.get_plan(plan["id"])
        assert loaded == plan
        assert isinstance(loaded["capacity"], int)
        assert json.dumps(loaded, ensure_ascii=False) == payloads[plan["id"]]

    # 迁移后仍可保存超大容量新方案
    database.save_plan(_make_plan("after-migration", HUGER_CAPACITY))
    assert database.get_plan("after-migration")["capacity"] == HUGER_CAPACITY


def test_init_db_idempotent():
    path = _use_tmp_db()
    plans = [_make_plan("legacy", 42)]
    _create_legacy_db(path, plans)
    for _ in range(3):
        database.init_db()
        assert _capacity_column(path) == "TEXT"
        assert database.get_plan("legacy")["capacity"] == 42
    # 全新库上重复初始化同样幂等
    _use_tmp_db()
    for _ in range(2):
        database.init_db()


def test_failed_migration_rolls_back():
    path = _use_tmp_db()
    plans = [_make_plan("legacy", 7)]
    _create_legacy_db(path, plans)
    # 注入故障：迁移临时表名被占用，CREATE TABLE 必然失败
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE plans_capacity_migration (stub TEXT)")
    conn.commit()
    conn.close()

    try:
        database.init_db()
    except sqlite3.OperationalError:
        pass
    else:
        raise AssertionError("迁移应当失败并抛出 OperationalError")

    # 不留半迁移表：旧表结构与原数据原样保留
    assert _capacity_column(path) == "INTEGER"
    assert _table_names(path) == {"plans", "plans_capacity_migration"}
    conn = sqlite3.connect(path)
    try:
        row = conn.execute(
            "SELECT capacity, payload FROM plans WHERE id = 'legacy'"
        ).fetchone()
    finally:
        conn.close()
    assert row[0] == 7
    assert json.loads(row[1])["capacity"] == 7

    # 排除故障后重试，迁移正常完成（失败可重入）
    conn = sqlite3.connect(path)
    conn.execute("DROP TABLE plans_capacity_migration")
    conn.commit()
    conn.close()
    database.init_db()
    assert _capacity_column(path) == "TEXT"
    assert _table_names(path) == {"plans"}
    assert database.get_plan("legacy")["capacity"] == 7


if __name__ == "__main__":
    test_fresh_schema_uses_text_capacity()
    test_save_and_get_huge_capacity()
    test_capacity_stored_as_decimal_text()
    test_migration_preserves_existing_plans()
    test_init_db_idempotent()
    test_failed_migration_rolls_back()
    print("test_database: all tests passed")
