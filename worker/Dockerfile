# Use official Playwright Python base image
FROM mcr.microsoft.com/playwright/python:v1.48.0-jammy

# Set working directory
WORKDIR /app

# ── Font + rendering stack ──────────────────────────────────────────────────
# Install a rich consumer-grade font set so the font-enumeration fingerprint
# matches a real OS rather than a bare server.
# Also install Mesa/GLX so Chromium can use ANGLE software rendering instead
# of falling back to a SwiftShader path that is trivially detectable.
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    wget \
    gnupg \
    ca-certificates \
    fonts-liberation \
    fonts-liberation2 \
    fonts-ubuntu \
    fonts-noto \
    fonts-noto-color-emoji \
    fonts-urw-base35 \
    fonts-open-sans \
    fonts-dejavu-core \
    fonts-freefont-ttf \
    libfontconfig1 \
    libfreetype6 \
    fontconfig \
    libgl1-mesa-glx \
    libgl1-mesa-dri \
    libgles2-mesa \
    libegl1-mesa \
    mesa-utils \
    libx11-6 \
    libx11-xcb1 \
    libxcb1 \
    libxcomposite1 \
    libxcursor1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxi6 \
    libxrandr2 \
    libxrender1 \
    libxss1 \
    libxtst6 \
    && fc-cache -f -v \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create profiles directory with proper permissions
RUN mkdir -p /app/profiles && chmod 777 /app/profiles

# Copy application code
COPY . .

# Set proper permissions for the app directory
RUN chown -R pwuser:pwuser /app

USER pwuser

# ── Environment ─────────────────────────────────────────────────────────────
ENV PYTHONPATH=/app
ENV PROFILES_DIR=/app/profiles
ENV PYTHONUNBUFFERED=1
ENV FONTCONFIG_PATH=/etc/fonts
ENV LIBGL_ALWAYS_SOFTWARE=1
ENV MESA_DEBUG=silent

# Expose health check port (optional)
EXPOSE 8000

# Default command
CMD ["python", "-u", "main.py"]
