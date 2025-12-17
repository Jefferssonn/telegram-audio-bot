# Руководство по развертыванию telegram-audio-bot

## Обзор

В этом документе описаны рекомендации по развертыванию и эксплуатации Telegram-бота для улучшения аудио файлов в production среде.

## Подготовка к развертыванию

### 1. Создание Telegram-бота

1. Откройте Telegram и найдите @BotFather
2. Отправьте команду `/newbot`
3. Следуйте инструкциям для создания нового бота
4. Сохраните полученный токен

### 2. Настройка сервера

Для развертывания потребуется:
- Linux сервер (Ubuntu 20.04+ рекомендуется)
- Docker и docker-compose установленные
- Не менее 2GB свободного места
- Доступ к интернету

## Развертывание с помощью Docker Compose

### 1. Клонирование репозитория

```bash
git clone https://github.com/ваш-аккаунт/telegram-audio-bot.git
cd telegram-audio-bot
```

### 2. Настройка переменных окружения

Создайте файл `.env`:

```bash
echo "BOT_TOKEN=ваш_токен_бота" > .env
```

### 3. Запуск бота

```bash
# Сборка и запуск в фоне
docker-compose up -d

# Проверка статуса
docker-compose ps

# Просмотр логов
docker-compose logs -f audio-bot
```

## Альтернативные способы развертывания

### 1. Локальный запуск

```bash
# Установка зависимостей
pip install -r requirements.txt

# Запуск бота
BOT_TOKEN=ваш_токен_бота python bot_refactored.py
```

### 2. Развертывание в Kubernetes

Создайте файл `deployment.yaml`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: telegram-audio-bot
spec:
  replicas: 1
  selector:
    matchLabels:
      app: telegram-audio-bot
  template:
    metadata:
      labels:
        app: telegram-audio-bot
    spec:
      containers:
      - name: audio-bot
        image: ваш-репозиторий/telegram-audio-bot:latest
        env:
        - name: BOT_TOKEN
          valueFrom:
            secretKeyRef:
              name: bot-secrets
              key: token
        volumeMounts:
        - name: temp-storage
          mountPath: /app/temp
        - name: logs-storage
          mountPath: /app/logs
      volumes:
      - name: temp-storage
        persistentVolumeClaim:
          claimName: temp-pvc
      - name: logs-storage
        persistentVolumeClaim:
          claimName: logs-pvc
---
apiVersion: v1
kind: Service
metadata:
  name: telegram-audio-bot-service
spec:
  selector:
    app: telegram-audio-bot
  ports:
  - port: 80
    targetPort: 80
  type: ClusterIP
```

## Мониторинг и логирование

### Логирование

Бот записывает логи в стандартный вывод и в файлы в директории `/app/logs` внутри контейнера.

Для просмотра логов:

```bash
# Просмотр последних 100 строк логов
docker-compose logs --tail=100 audio-bot

# Постоянный просмотр логов
docker-compose logs -f audio-bot
```

### Метрики производительности

Для мониторинга производительности рекомендуется:

1. Отслеживать использование CPU и RAM
2. Контролировать размер временной директории
3. Мониторить количество активных сессий

## Безопасность

### 1. Защита от DDoS

- Ограничение размера файлов (до 50MB)
- TTL сессий пользователей (30 минут по умолчанию)
- Ограничение количества одновременных обработок

### 2. Безопасность контейнера

- Запуск от не-root пользователя
- Минимальные необходимые привилегии
- Изоляция процессов

### 3. Защита токена

- Хранение токена в переменной окружения
- Не хранить токен в коде
- Использовать secrets в production средах

## Масштабирование

### Горизонтальное масштабирование

Для увеличения производительности можно:

1. Использовать Redis для хранения сессий вместо памяти
2. Добавить балансировщик нагрузки
3. Запускать несколько экземпляров бота

### Пример конфигурации с Redis

Обновите `docker-compose.yml`:

```yaml
version: '3.8'

services:
  redis:
    image: redis:7-alpine
    restart: unless-stopped
    volumes:
      - redis-data:/data

  audio-bot:
    build: .
    container_name: telegram-audio-bot
    restart: unless-stopped
    depends_on:
      - redis
    environment:
      - BOT_TOKEN=${BOT_TOKEN}
      - REDIS_URL=redis://redis:6379
      - TZ=Europe/Moscow
      - PYTHONUNBUFFERED=1
    volumes:
      - ./temp:/app/temp
      - ./logs:/app/logs
    networks:
      - bot-network

volumes:
  redis-data:

networks:
  bot-network:
    driver: bridge
```

## Резервное копирование

### Регулярные задачи

Рекомендуется настроить регулярные задачи для:

1. Очистки временных файлов
2. Ротации логов
3. Резервного копирования важных данных

### Пример скрипта очистки

Создайте `cleanup.sh`:

```bash
#!/bin/bash
# Удаление временных файлов старше 1 часа
find /workspace/temp -type f -mmin +60 -delete

# Ротация логов
docker-compose exec audio-bot logrotate -f /etc/logrotate.conf
```

## Обновление бота

### Обновление через Docker Compose

```bash
# Остановка текущего контейнера
docker-compose down

# Обновление кода
git pull origin main

# Пересборка образа
docker-compose build

# Запуск обновленного бота
docker-compose up -d
```

## Устранение неполадок

### Распространенные проблемы

1. **Бот не отвечает**
   - Проверьте токен бота
   - Убедитесь, что бот не заблокирован пользователем
   - Проверьте подключение к интернету

2. **Ошибки при обработке аудио**
   - Проверьте формат файла
   - Убедитесь, что файл не поврежден
   - Проверьте размер файла

3. **Высокое потребление памяти**
   - Проверьте количество активных сессий
   - Увеличьте размер свопа при необходимости
   - Настройте автоматическую очистку

### Диагностика

Для диагностики проблем используйте:

```bash
# Проверка состояния контейнера
docker-compose ps

# Просмотр ресурсов контейнера
docker stats telegram-audio-bot

# Проверка логов
docker-compose logs audio-bot
```

## Рекомендации по производительности

1. Используйте SSD для хранения временных файлов
2. Обеспечьте достаточный объем RAM (минимум 1GB)
3. Регулярно очищайте временные файлы
4. Мониторьте использование ресурсов