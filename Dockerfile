# Use a lightweight Python image
FROM python:3.11-slim-bookworm

# Install system dependencies
# ffmpeg is crucial for music functionality
# git is often needed for installing dependencies from git repositories
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    ffmpeg \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first to leverage Docker cache
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Command to run the bot
CMD ["python", "main.py"]
