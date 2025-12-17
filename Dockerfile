FROM python:3.11-slim

# Установка зависимостей системы и аудио библиотек
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Создание пользователя для безопасности
RUN groupadd -r appuser && useradd -r -g appuser appuser

COPY bot.py bot_refactored.py ./
RUN mkdir -p /app/temp /app/logs && \
    chown -R appuser:appuser /app

USER appuser

ENV PYTHONUNBUFFERED=1

CMD ["python", "bot_refactored.py"]
