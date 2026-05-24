FROM python:3.11-slim

# System packages
RUN apt-get update && apt-get install -y \
    ffmpeg \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# App directory
WORKDIR /app

# Copy requirements first (better caching)
COPY requirements.txt .

# Install Python packages
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Create downloads folder
RUN mkdir -p downloads

# Environment
ENV PYTHONUNBUFFERED=1

# Expose port
EXPOSE 5000

# Start bot
CMD ["python", "bot.py"]
