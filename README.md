# Телеграм-бот для генерации примеров для 3-го класса

## Инструкции по установке

### Предварительные требования

1. Разместите файл `.env` в корне проекта со следующей переменной окружения:
   ```
   TOKEN_API_BOT=<ваш_токен_телеграм_бота>
   ```

### Сборка и запуск Docker

#### Сборка Docker-образа

Для сборки Docker-образа бота выполните:

```bash
sudo docker build -t math-bot-img .
```

#### Запуск Docker-контейнера

Для запуска бота в Docker-контейнере с автоматическим перезапуском в случае сбоя выполните:

```bash
sudo docker run -d --name math-bot-container --restart unless-stopped --env-file .env math-bot-img
```

#### Просмотр логов

Для мониторинга логов бота в реальном времени выполните:

```bash
sudo docker logs -f math-bot-container
```

---

### Пересоздание Docker-окружения

Если вам нужно пересобрать бота с нуля:

1. Остановите и удалите существующий контейнер:
   ```bash
   sudo docker stop math-bot-container
   sudo docker container prune
   sudo docker image prune -a
   ```
2. Следуйте инструкциям по сборке и запуску выше.
