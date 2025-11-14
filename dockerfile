# --- Base image ---
FROM python:3.11-slim AS base

# System deps (build, SSL, tzdata)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

# --- App user ---
RUN useradd -ms /bin/bash appuser

WORKDIR /app

# --- Install Python deps early (better layer cache) ---
COPY requirement.txt /app/requirement.txt
RUN pip install --upgrade pip && pip install -r /app/requirement.txt

# --- Copy source ---
COPY . /app

# Ensure runtime dirs exist
RUN mkdir -p /app/logs /app/backups /app/business && chown -R appuser:appuser /app

USER appuser

EXPOSE 10000

# --- Start ---
CMD ["gunicorn", "-c", "gunicorn.conf.py", "app:create_app()"]
