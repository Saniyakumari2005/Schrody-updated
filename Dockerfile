# ---- Dockerfile for Schrody Discord Bot ----
FROM python:3.12-slim AS base

# Prevent Python from writing .pyc files / buffering stdout (important for log visibility in k8s)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps needed to build a couple of the pinned wheels (pandas/PyNaCl) on slim images
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libffi-dev \
        procps \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first so Docker can cache this layer between builds
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the source
COPY . .

# Run as a non-root user (best practice for containers in k8s)
RUN useradd --create-home --uid 10001 botuser \
    && chown -R botuser:botuser /app
USER botuser

# The bot doesn't serve HTTP; this is just a self-check the entrypoint can use
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import sys; sys.exit(0)"

CMD ["python", "bot.py"]
