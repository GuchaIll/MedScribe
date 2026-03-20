FROM python:3.11-slim

WORKDIR /app

# System dependencies for psycopg2, WeasyPrint, and OpenCV
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    libgomp1 \
    libglib2.0-0 \
    libgl1 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libfontconfig1 \
    libcairo2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-xlib-2.0-0 \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.docker.txt .
RUN pip install --no-cache-dir -r requirements.docker.txt

COPY . .

EXPOSE 3001

# Default: run migrations then start with hot-reload.
# Production: override CMD with ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "3001", "--workers", "2"]
CMD ["sh", "-c", "alembic upgrade head && uvicorn main:app --reload --host 0.0.0.0 --port 3001"]
