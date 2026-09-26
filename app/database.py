"""SQLite 持久化层。

表 plans：
  id          TEXT PRIMARY KEY  (uuid4 hex)
  capacity    INTEGER
  item_count  INTEGER
  kiln_count  INTEGER
  payload     TEXT              (完整方案的 JSON，含器物与窑次明细)
  created_at  TEXT              (UTC ISO 8601)
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
    capacity    INTEGER NOT NULL,
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


def init_db() -> None:
    """创建表（幂等），容器启动时调用。"""

    with connect() as conn:
        conn.execute(_SCHEMA)


def save_plan(plan: dict) -> None:
    """保存方案。plan 必须含 id/capacity/item_count/kiln_count/created_at。"""

    with connect() as conn:
        conn.execute(
            """
            INSERT INTO plans (id, capacity, item_count, kiln_count, payload, created_at)
            VALUES (:id, :capacity, :item_count, :kiln_count, :payload, :created_at)
            """,
            {
                "id": plan["id"],
                "capacity": plan["capacity"],
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
