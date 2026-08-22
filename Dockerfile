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

# Download NLTK data during build
RUN python -c "import nltk; [nltk.download(r, quiet=True) for r in ['punkt', 'punkt_tab', 'vader_lexicon', 'stopwords']]"

# Copy project
COPY . .

# Change ownership to a non-root user (Hugging Face Spaces requirement)
RUN useradd -m -u 1000 user
USER user

# Expose port
EXPOSE 7860

# Run gunicorn on port 7860
CMD ["gunicorn", "-b", "0.0.0.0:7860", "-w", "2", "app:app"]
