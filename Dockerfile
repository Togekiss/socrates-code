# Use Python 3.12 slim image (Debian 12 Bookworm)
FROM python:3.12-slim-bookworm

# Install required system tools and add Microsoft package repository
RUN apt-get update && apt-get install -y \
    wget \
    curl \
    apt-transport-https \
    ca-certificates \
    gnupg \
    && wget https://packages.microsoft.com/config/debian/12/packages-microsoft-prod.deb -O packages-microsoft-prod.deb \
    && dpkg -i packages-microsoft-prod.deb \
    && rm packages-microsoft-prod.deb

# Install .NET 9 Runtime (required for DiscordChatExporter CLI)
RUN apt-get update && apt-get install -y \
    dotnet-runtime-9.0 \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy the requirements file and install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
# Note: Ensure .dockerignore excludes node_modules, .venv, Backups, etc.
COPY . .

# Expose Cloud Run default port
EXPOSE 8080

# Command to run the FastAPI application
CMD ["uvicorn", "src.server:app", "--host", "0.0.0.0", "--port", "8080"]
