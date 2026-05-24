FROM python:3.11-slim

# System packages + deno (yt-dlp ke liye JS challenge solving)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    gcc \
    curl \
    unzip \
    && curl -fsSL https://deno.land/install.sh | sh \
    && ln -s /root/.deno/bin/deno /usr/local/bin/deno \
    && rm -rf /var/lib/apt/lists/*

# App directory
WORKDIR /app

# Copy requirements first (better caching)
COPY requirements.txt .

# Install Python packages + latest yt-dlp
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir -U yt-dlp

# Copy project files
COPY . .

# Create downloads folder
RUN mkdir -p downloads

# Environment
ENV PYTHONUNBUFFERED=1
ENV DENO_INSTALL="/root/.deno"
ENV PATH="${DENO_INSTALL}/bin:${PATH}"

# Expose port
EXPOSE 5000

# Start bot
CMD ["python", "bot.py"]
