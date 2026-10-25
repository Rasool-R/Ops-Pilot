FROM python:3.11-slim AS base

# Prevent Python from writing .pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Create a non-root system group and user for container hardening
RUN groupadd --system --gid 10001 opspilot && \
    useradd --system --uid 10001 --gid opspilot --create-home opspilot

# Copy dependency definition first to leverage Docker layer caching
COPY pyproject.toml README.md ./
COPY app ./app

# Install production dependencies
RUN pip install --upgrade pip && \
    pip install . && \
    chown -R opspilot:opspilot /app

# Switch to non-root user
USER opspilot

EXPOSE 8000

# Container-level health check probing the FastAPI liveness endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=3)" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]