# Wisp backend

Backend для общения фронта с разными LLM API. Выбор провайдера, модели
и параметры запроса остаются на сервере. Сейчас подключён Groq.

Реализован `POST /v1/chat` по [Desktop ↔ Backend v1](docs/desktop-backend-v1.md):
JSON без стриминга, серверный system prompt, проверка запросов и модельного вывода.
Ответ содержит `version`, исходный `requestId`, `text` и необязательный `decision`.
Квоты и идемпотентность остаются несогласованными и не реализованы.

Предыдущие `/v1/chat/completions`, `/v1/assistants` и SSE удалены.
Провайдер и модель выбираются серверным профилем `default`.
Общий deadline вызова — 10 секунд, таймаут соединения — 3 секунды.

## Запуск

Нужен Python 3.10+. Создайте `.env` по примеру `.env.example` и укажите
`GROQ_API_KEY`. Запуск из PowerShell в папке проекта:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

Изменения Python-кода подхватываются автоматически. После изменения `.env`
нужен перезапуск. [Swagger](http://127.0.0.1:8000/docs) доступен после запуска.

## Структура

- `api/` — HTTP-маршруты.
- `schemas.py` — текущие схемы запросов и ответов.
- `service.py` — выбор профиля и провайдера.
- `providers/` — адаптеры LLM API.
- `config.py`, `application.py` — настройки и сборка приложения.

Код находится в `wisp_backend/`, тесты — в `tests/`.

## Тесты

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -v
```

Тесты не обращаются к реальным LLM API.

Локальный тестовый пример: `tests/fixtures/request.local.json`.
Три общих JSON fixtures из документа фронта пока не предоставлены;
локальный пример не считается их копией. Ссылки на desktop-файлы в контракте
сохранены как ссылки исходного документа.
