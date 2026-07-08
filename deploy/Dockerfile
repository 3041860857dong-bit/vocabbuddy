# syntax=docker/dockerfile:1
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    VOCABBUDDY_ENV=production

WORKDIR /app

# 优先安装依赖，利用层缓存（依赖变动频率远低于代码）
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# 复制后端与前端静态资源。
# ⚠️ 不要把 .env 打进镜像！密钥请在运行时通过环境变量或挂载卷注入。
COPY backend/ ./backend/
COPY static/  ./static/

# 以非 root 用户运行，降低被入侵后的影响面
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# 生产用多 worker；可通过环境变量 UVICORN_WORKERS 调整（默认 4）
CMD ["sh", "-c", "python -m uvicorn backend.app:app --host 0.0.0.0 --port 8000 --workers ${UVICORN_WORKERS:-4}"]
