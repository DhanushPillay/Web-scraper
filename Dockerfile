FROM python:3.12-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
# Hugging Face default port
ENV PORT=7860
# Required by Flask/Werkzeug in production
ENV FLASK_ENV=production

# Set work directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Change ownership to a non-root user (Hugging Face Spaces requirement)
RUN useradd -m -u 1000 user && chown -R user:user /app
USER user

EXPOSE 7860

# RENDER=true enables the free-tier memory guard (skips per-article og:image
# fan-out in /api/scrape, which OOMs a 512MB container).
ENV PYTHONPATH=/app/src
ENV RENDER=true
# 300s: an SSE scrape holds a worker for the whole stream, so gunicorn's 30s
# default would kill it mid-scrape and silently discard the run.
CMD ["gunicorn", "-b", "0.0.0.0:7860", "-w", "2", "--timeout", "300", "src.app:app"]
