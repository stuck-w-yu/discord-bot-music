# syntax=docker/dockerfile:1.7

# Use a lightweight Python image
FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies
# ffmpeg is crucial for music functionality
# git is often needed for installing dependencies from git repositories
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && \
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
    pip install -r requirements.txt

# Copy the rest of the application
COPY . .

# Expose the data volume
VOLUME ["/app/data"]

# Set default data directory
ENV DATA_DIR=/app/data

# Command to run the bot
CMD ["python", "main.py"]
