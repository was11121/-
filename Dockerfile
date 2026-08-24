# Remedy - Linux 生产镜像
# 架构: gunicorn + Flask；集中库走 PostgreSQL（compose 提供），本地可用 SQLite。
# 默认不安装 torch/transformers（镜像小）；需要 BERT 人格时:
#   docker build --build-arg WITH_AI=1 .
FROM python:3.12-slim

# 需要 BERT 人格（torch，镜像很大）时构建传 --build-arg WITH_AI=1
ARG WITH_AI=0

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MYAGENT_DATA_DIR=/data

WORKDIR /app

# 系统依赖：curl(健康检查/诊断)、openssh-client(联网 SSH 中转兜底)、
# tzdata(合法时区)
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates openssh-client tzdata \
    && rm -rf /var/lib/apt/lists/*

# 依赖层（利用 Docker 缓存）
COPY requirements-docker.txt ./
COPY requirements.txt ./
RUN --mount=type=cache,target=/root/.cache/pip \
    if [ "${WITH_AI:-0}" = "1" ]; then \
        pip install -r requirements.txt; \
    else \
        pip install -r requirements-docker.txt && \
        echo "PERSONALITY_DISABLE_BERT=1" > /etc/profile.d/myagent.sh; \
    fi

# 应用代码
COPY . .

RUN mkdir -p /data && useradd -r -u 10001 appuser && chown -R appuser:appuser /app /data
USER appuser

EXPOSE 8091

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8091/health || exit 1

CMD ["gunicorn", "--bind", "0.0.0.0:8091", "--workers", "2", "--threads", "4", "--timeout", "120", "app:app"]