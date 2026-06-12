# Helios Core — backend image
FROM python:3.12-slim

# Keep Python lean and predictable in containers
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps: build tools for argon2-cffi / psycopg, and curl for healthchecks
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first for better layer caching
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# App code (in development this is overridden by the bind mount in compose)
COPY . .

EXPOSE 8000

# Default command (overridden by docker-compose for --reload in dev)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
