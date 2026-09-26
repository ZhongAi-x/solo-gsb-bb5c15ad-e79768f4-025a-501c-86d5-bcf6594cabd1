"""SQLite 持久化层。

表 plans：
  id          TEXT PRIMARY KEY  (uuid4 hex)
  capacity    TEXT              (单窑容量的十进制文本，支持任意大小的正整数)
  item_count  INTEGER
  kiln_count  INTEGER
  payload     TEXT              (完整方案的 JSON，含器物与窑次明细)
  created_at  TEXT              (UTC ISO 8601)

容量存储兼容性：早期版本 capacity 列为 SQLite INTEGER（有符号 64 位），
无法保存超过 9223372036854775807 的单窑容量。init_db() 在启动时检测旧表，
并在**单个事务**内将其重建为 capacity TEXT（容量以十进制文本存放），
既有方案全部保留；升级失败或中断会整体回滚，磁盘上不会留下半迁移表；
重复启动幂等。读取一律以 payload JSON 为准，API 返回的 capacity 仍是
JSON 整数，调用方无需感知存储格式。
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

DB_PATH = os.environ.get("KILN_DB_PATH", "/data/kiln.db")

# 迁移期间使用的临时表名；迁移事务提交后即改名为 plans。
_MIGRATION_TMP_TABLE = "plans_capacity_migration"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS plans (
    id          TEXT PRIMARY KEY,
    capacity    TEXT NOT NULL,
    item_count  INTEGER NOT NULL,
    kiln_count  INTEGER NOT NULL,
    payload     TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
"""


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _capacity_column_type(conn: sqlite3.Connection) -> str | None:
    """返回 plans.capacity 的声明类型（大写）；列或表不存在时返回 None。"""

    row = conn.execute(
        "SELECT type FROM pragma_table_info('plans') WHERE name = 'capacity'"
    ).fetchone()
    return row[0].upper() if row else None


def _migrate_capacity_to_text(conn: sqlite3.Connection) -> None:
    """把旧表（capacity 为 INTEGER）重建为 capacity TEXT（十进制文本）。

    全部语句包在一个显式事务中：中途失败或进程崩溃都会整体回滚
    （连接以自动提交模式打开，事务边界显式控制），磁盘上始终只有
    迁移前或迁移后的完整 plans 表，不会残留半迁移表。
    """

    try:
        conn.execute("BEGIN")
        # 防御性清理：正常流程不会残留临时表（崩溃时事务整体回滚），
        # 此处兜底以保证迁移可重入。
        conn.execute(f"DROP TABLE IF EXISTS {_MIGRATION_TMP_TABLE}")
        conn.execute(
            f"""
            CREATE TABLE {_MIGRATION_TMP_TABLE} (
                id          TEXT PRIMARY KEY,
                capacity    TEXT NOT NULL,
                item_count  INTEGER NOT NULL,
                kiln_count  INTEGER NOT NULL,
                payload     TEXT NOT NULL,
                created_at  TEXT NOT NULL
            )
            """
        )
        # 旧容量为有符号 64 位 INTEGER，CAST 成文本即其十进制表示。
        conn.execute(
            f"""
            INSERT INTO {_MIGRATION_TMP_TABLE}
                (id, capacity, item_count, kiln_count, payload, created_at)
            SELECT id, CAST(capacity AS TEXT), item_count, kiln_count,
                   payload, created_at
            FROM plans
            """
        )
        conn.execute("DROP TABLE plans")
        conn.execute(f"ALTER TABLE {_MIGRATION_TMP_TABLE} RENAME TO plans")
        conn.execute("COMMIT")
    except BaseException:
        # COMMIT 失败时事务可能已被 SQLite 自动结束，忽略随后的回滚错误。
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise


def init_db() -> None:
    """初始化数据库（幂等），容器启动时调用。

    - 无 plans 表：直接按新结构建表（capacity 为十进制文本）；
    - 旧表（capacity 非 TEXT）：单事务重建为 TEXT 容量，既有方案全部保留；
    - 已是新结构：直接返回。
    """

    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    # isolation_level=None：自动提交，DDL/DML 的事务边界完全由本模块
    # 显式控制，避免迁移事务被隐式提交拆开。
    conn = sqlite3.connect(DB_PATH, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        table_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'plans'"
        ).fetchone()
        if table_exists is None:
            conn.execute(_SCHEMA)
            return

        if _capacity_column_type(conn) != "TEXT":
            _migrate_capacity_to_text(conn)
    finally:
        conn.close()


def save_plan(plan: dict) -> None:
    """保存方案。plan 必须含 id/capacity/item_count/kiln_count/created_at。

    capacity 以十进制文本落库，以支持超过 SQLite 有符号 64 位上限的容量；
    完整方案（含 JSON 整数容量）同时存于 payload。
    """

    with connect() as conn:
        conn.execute(
            """
            INSERT INTO plans (id, capacity, item_count, kiln_count, payload, created_at)
            VALUES (:id, :capacity, :item_count, :kiln_count, :payload, :created_at)
            """,
            {
                "id": plan["id"],
                "capacity": str(plan["capacity"]),
                "item_count": plan["item_count"],
                "kiln_count": plan["kiln_count"],
                "payload": json.dumps(plan, ensure_ascii=False),
                "created_at": plan["created_at"],
            },
        )


def get_plan(plan_id: str) -> dict | None:
    """按 ID 读取方案，不存在返回 None。"""

    with connect() as conn:
        row = conn.execute(
            "SELECT payload FROM plans WHERE id = ?", (plan_id,)
        ).fetchone()
    return json.loads(row["payload"]) if row else None
