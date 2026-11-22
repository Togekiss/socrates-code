# Use Python 3.12 slim image (Debian 12 Bookworm)
FROM python:3.12-slim-bookworm

# Install required system tools (DCE/.NET retired; native Python httpx extractor used)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy the requirements file and install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
# Note: Ensure .dockerignore excludes node_modules, .venv, Backups, etc.
COPY . .

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SOCRATES_ENV=production

# Run as a dedicated unprivileged user
RUN groupadd --gid 10001 socrates \
    && useradd --uid 10001 --gid socrates --shell /usr/sbin/nologin --create-home socrates \
    && chown -R socrates:socrates /app

USER socrates

# Expose Cloud Run default port
EXPOSE 8080

# Command to run the FastAPI application
CMD ["uvicorn", "src.server:app", "--host", "0.0.0.0", "--port", "8080"]
