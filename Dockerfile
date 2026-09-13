# syntax=docker/dockerfile:1.7

# Use a lightweight Python image
FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Optional build arguments for custom mirrors if Debian/PyPI servers are slow
ARG APT_MIRROR=""
ARG PIP_INDEX_URL=""

# Install system dependencies
# Includes retry logic and automatic fallback to Fastly CDN mirror if default deb.debian.org is slow/down
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    set -e; \
    echo 'Acquire::Retries "3";' > /etc/apt/apt.conf.d/80retries; \
    echo 'Acquire::http::Timeout "20";' >> /etc/apt/apt.conf.d/80retries; \
    if [ -n "$APT_MIRROR" ]; then \
        sed -i "s|deb.debian.org|$APT_MIRROR|g" /etc/apt/sources.list.d/debian.sources 2>/dev/null || true; \
        sed -i "s|deb.debian.org|$APT_MIRROR|g" /etc/apt/sources.list 2>/dev/null || true; \
    fi; \
    if ! apt-get update; then \
        echo "Default Debian repository failed or slow, switching to Fastly CDN mirror..."; \
        sed -i 's|deb.debian.org|cdn-fastly.deb.debian.org|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || true; \
        sed -i 's|deb.debian.org|cdn-fastly.deb.debian.org|g' /etc/apt/sources.list 2>/dev/null || true; \
        apt-get update; \
    fi; \
    apt-get install -y --no-install-recommends \
        ffmpeg \
        git \
        build-essential

# Set working directory
WORKDIR /app

# Copy requirements first to leverage Docker cache
COPY requirements.txt .

# Install Python dependencies
RUN --mount=type=cache,target=/root/.cache/pip \
    if [ -n "$PIP_INDEX_URL" ]; then \
        pip install --index-url "$PIP_INDEX_URL" -r requirements.txt; \
    else \
        pip install -r requirements.txt; \
    fi

# Copy the rest of the application
COPY . .

# Expose the data volume
VOLUME ["/app/data"]

# Set default data directory
ENV DATA_DIR=/app/data

# Command to run the bot
CMD ["python", "main.py"]
