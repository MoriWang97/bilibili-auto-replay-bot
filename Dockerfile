# ── Stage 1: Build ──────────────────────────────────────────
FROM python:3.11-slim as builder

WORKDIR /app

# 安装构建依赖
RUN pip install --no-cache-dir pip --upgrade

# 复制依赖文件
COPY pyproject.toml .

# 安装依赖到指定目录
RUN pip install --no-cache-dir --target=/app/deps .

# ── Stage 2: Runtime ────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

# 创建非 root 用户
RUN useradd --create-home --shell /bin/bash botuser

# 复制依赖
COPY --from=builder /app/deps /app/deps

# 复制源代码
COPY src/ ./src/
COPY run.py .
COPY config/config.example.yaml ./config/

# 设置 Python 路径
ENV PYTHONPATH="/app/deps:/app"
ENV PYTHONUNBUFFERED=1

# 切换到非 root 用户
USER botuser

# 启动命令
CMD ["python", "run.py"]
