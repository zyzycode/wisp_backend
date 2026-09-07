# Wisp backend

Backend для общения фронта с разными LLM API. Выбор провайдера, модели
и параметры запроса остаются на сервере. Сейчас подключён Groq.

**Контракт API на согласовании.** Короткий документ для фронта:
[черновик контракта](docs/frontend-contract-draft.md).
Текущая реализация и Swagger — рабочий прототип, не утверждённая спецификация.
Формат ошибок пока не согласован.

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
