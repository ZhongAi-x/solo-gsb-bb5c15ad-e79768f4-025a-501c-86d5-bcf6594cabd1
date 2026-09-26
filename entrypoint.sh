#!/bin/sh
# 容器启动入口：
# 1. 安装 / 校验依赖（镜像已预装，此处幂等执行以满足“启动时安装依赖”）
# 2. 初始化数据库（建表，幂等）
# 3. 启动 API 服务
set -e

echo "[entrypoint] 安装/校验 Python 依赖..."
pip install --no-cache-dir -r requirements.txt

echo "[entrypoint] 初始化数据库 (${KILN_DB_PATH:-/data/kiln.db})..."
python -c "from app.database import init_db; init_db(); print('[entrypoint] 数据库就绪')"

HOST="${UVICORN_HOST:-0.0.0.0}"
PORT="${UVICORN_PORT:-8000}"
echo "[entrypoint] 启动 uvicorn: ${HOST}:${PORT}"
exec uvicorn app.main:app --host "${HOST}" --port "${PORT}"
