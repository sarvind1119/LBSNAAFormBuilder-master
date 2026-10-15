FROM python:3.10-slim

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    poppler-utils \
    libgl1 \
    libglib2.0-0 \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code
COPY app.py .
COPY database.py .
COPY validation_engine.py .
COPY celebrity_detection.py .
COPY model_manager.py .
COPY storage.py .
COPY email_service.py .
COPY wsgi.py .

# Templates and static files
COPY templates/ ./templates/
COPY static/ ./static/

# Pre-trained models
COPY models/ ./models/

# Celebrity reference images
COPY celebrity_reference/ ./celebrity_reference/

# Create directories
RUN mkdir -p temp_uploads data data/uploads

EXPOSE 5000

ENV FLASK_APP=app.py
ENV PYTHONUNBUFFERED=1
ENV DATA_DIR=/app/data

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:5000/health || exit 1

# Production server (Flask's built-in server is for local development only).
# One worker so models are loaded once and the in-memory rate limiter stays consistent.
# 16 threads keep light requests responsive; heavy validations are capped in app.py
# (VALIDATION_CONCURRENCY, default 3).
CMD exec gunicorn -w 1 --threads 16 --timeout 180 -b 0.0.0.0:${PORT:-5000} wsgi:app
