# Use official Playwright Python base image
FROM mcr.microsoft.com/playwright/python:v1.48.0-jammy

# Set working directory
WORKDIR /app

# Install system dependencies and Microsoft fonts for Windows spoofing
RUN apt-get update && \
    echo "ttf-mscorefonts-installer msttcorefonts/accepted-mscorefonts-eula select true" | debconf-set-selections && \
    apt-get install -y --no-install-recommends \
    wget \
    gnupg \
    ca-certificates \
    fontconfig \
    ttf-mscorefonts-installer \
    fonts-ubuntu && \
    fc-cache -f -v && \
    rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create profiles directory with proper permissions
RUN mkdir -p /app/profiles && chmod 777 /app/profiles

# Copy application code
COPY . .

# The Playwright base image already has a user, so we'll use the existing user
# Set proper permissions for the app directory
RUN chown -R pwuser:pwuser /app

USER pwuser

# Set environment variables
ENV PYTHONPATH=/app
ENV PROFILES_DIR=/app/profiles
ENV PYTHONUNBUFFERED=1

# Expose health check port (optional)
EXPOSE 8000

# Default command
CMD ["python", "-u", "main.py"]
