# Используем лёгкий базовый образ Python
FROM python:3.11-slim

# Устанавливаем рабочую директорию внутри контейнера
WORKDIR /app

# Копируем файл с зависимостями (мы создадим его, если у тебя нет requirements.txt)
# Для простоты укажем зависимости прямо в Dockerfile
COPY requirements.txt .

# Устанавливаем зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь код приложения
COPY main.py .

# Создаём папку для загруженных файлов (на случай, если её нет)
RUN mkdir -p files


# Открываем порт, на котором работает приложение
EXPOSE 8000

# Команда запуска
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]