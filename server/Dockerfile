# Use an official Python runtime as a parent image
FROM python:3.12-slim

# Set environment variables
# 1. Prevents Python from writing pyc files to disc
ENV PYTHONDONTWRITEBYTECODE=1
# 2. Prevents Python from buffering stdout and stderr
ENV PYTHONUNBUFFERED=1

# Set the working directory in the container
WORKDIR /app

# System deps for audio/ffmpeg and PostgreSQL client libs
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ffmpeg \
        libpq-dev \
        gcc \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies first (better for layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Create storage directories
RUN mkdir -p /app/storage /app/logs

# Expose the port the app runs on
EXPOSE 8001

# Command to run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
