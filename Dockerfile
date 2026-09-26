FROM python:3.12-slim

# 容器启动时安装依赖：依赖预装于镜像，entrypoint 再做一次幂等安装保证可用性
WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY entrypoint.sh ./entrypoint.sh
RUN chmod +x ./entrypoint.sh \
    && mkdir -p /data

# SQLite 数据库文件路径（可通过 compose / 环境变量覆盖）
ENV KILN_DB_PATH=/data/kiln.db \
    UVICORN_HOST=0.0.0.0 \
    UVICORN_PORT=8000

EXPOSE 8000

ENTRYPOINT ["./entrypoint.sh"]
