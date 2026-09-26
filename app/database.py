"""SQLite 持久化层。

表 plans：
  id          TEXT PRIMARY KEY  (uuid4 hex)
  capacity    TEXT              (单窑容量的十进制文本，支持超出有符号 64 位的正整数)
  item_count  INTEGER
  kiln_count  INTEGER
  payload     TEXT              (完整方案的 JSON，含器物与窑次明细；capacity 在其中保持 JSON 整数)
  created_at  TEXT              (UTC ISO 8601)

历史版本的 capacity 列为 INTEGER（SQLite 有符号 64 位），容量超过上限时
落库阶段抛出 OverflowError。init_db 在启动时以单个事务把旧表迁移为
TEXT 十进制文本存储（保留全部既有方案），迁移失败整体回滚、重复启动幂等。
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

DB_PATH = os.environ.get("KILN_DB_PATH", "/data/kiln.db")

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

# 旧表（capacity INTEGER）→ 新表（capacity TEXT）的事务迁移语句序列。
# 借用临时表整体重建：SQLite 无法直接修改列类型。
_CAPACITY_MIGRATION = (
    """
    CREATE TABLE plans_capacity_migration (
        id          TEXT PRIMARY KEY,
        capacity    TEXT NOT NULL,
        item_count  INTEGER NOT NULL,
        kiln_count  INTEGER NOT NULL,
        payload     TEXT NOT NULL,
        created_at  TEXT NOT NULL
    )
    """,
    """
    INSERT INTO plans_capacity_migration
        (id, capacity, item_count, kiln_count, payload, created_at)
    SELECT id, CAST(capacity AS TEXT), item_count, kiln_count, payload, created_at
    FROM plans
    """,
    "DROP TABLE plans",
    "ALTER TABLE plans_capacity_migration RENAME TO plans",
)


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


def _capacity_declared_type(conn: sqlite3.Connection) -> str | None:
    """返回 plans.capacity 的声明类型（大写）；表或列不存在时返回 None。"""

    for row in conn.execute("PRAGMA table_info(plans)").fetchall():
        if row["name"] == "capacity":
            return (row["type"] or "").upper()
    return None


def init_db() -> None:
    """创建表并按需迁移容量列（幂等），容器启动时调用。

    若既有 plans 表的 capacity 列仍为旧版 INTEGER，则在单个事务内重建为
    TEXT 十进制文本表并拷贝全部既有方案：任一步失败或进程中断都会整体
    回滚，不会留下半迁移表；已为 TEXT 时直接跳过，重复启动幂等。
    """

    with connect() as conn:
        conn.execute(_SCHEMA)
        if _capacity_declared_type(conn) == "TEXT":
            return
        conn.execute("BEGIN IMMEDIATE")
        try:
            for statement in _CAPACITY_MIGRATION:
                conn.execute(statement)
        except BaseException:
            conn.rollback()
            raise
        conn.commit()


def save_plan(plan: dict) -> None:
    """保存方案。plan 必须含 id/capacity/item_count/kiln_count/created_at。

    capacity 以十进制文本落库，不受 SQLite INTEGER 的 64 位上限约束；
    完整方案（含原始整数容量）同时存入 payload JSON，读取时原样返回。
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
    """按 ID 读取方案，不存在返回 None。

    返回 payload JSON 的原样解析结果，capacity 保持保存时的 JSON 整数。
    """

    with connect() as conn:
        row = conn.execute(
            "SELECT payload FROM plans WHERE id = ?", (plan_id,)
        ).fetchone()
    return json.loads(row["payload"]) if row else None
