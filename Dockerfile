# Use an official lightweight Python image
FROM python:3.12-slim

# Prevent Python from writing .pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

# geopandas requires libgdal system libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgdal-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source (excludes files listed in .dockerignore)
COPY . .

# Cloud Run defaults to port 8080
EXPOSE 8080

# Run with Gunicorn; single worker + threads suits Cloud Run's per-instance concurrency model
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 app:app
