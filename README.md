# Локальный Grok proxy

Отдельный Python 3.10+ сервис FastAPI. Код приложения находится в пакете
`wisp_backend`, конфигурация и точка запуска — в корне проекта.

## Структура и расширение

```text
main.py                       # Совместимая точка запуска и ASGI app
wisp_backend/
  application.py              # Фабрика приложения, lifespan, сборка зависимостей
  config.py                   # Типизированные настройки, чтение .env
  schemas.py                  # Контракты запросов
  upstream.py                 # Создание HTTP-клиента, авторизация и таймауты
  proxy.py                    # Пересылка ответов, SSE, обработка сетевых ошибок
  api/
    dependencies.py           # Получение прокси из состояния приложения
    chat.py                   # Маршрут Chat Completions
    health.py                 # Проверка работоспособности
tests/                        # Тесты без обращений к реальному API
```

Новый endpoint добавляйте отдельным `APIRouter` в `api/` и подключайте через
`include_router` в `application.py`. Контракты размещайте в `schemas.py`
(при росте их можно разделить на пакет), обработку ответов — в соответствующем
сервисе, настройки соединения — в `upstream.py`.

`create_app(transport=None, *, settings=None)` поддерживает явную передачу
`Settings` и тестового HTTP transport. Например, `Settings` позволяет задать
`base_url`, `request_timeout`, `connect_timeout`, `pool_timeout` и `api_key`.
Без явных настроек ключ загружается из `.env` при старте. Чтение конфигурации
не изменяет окружение процесса; секрет скрыт в строковом представлении настроек.

HTTP-клиент создаётся один раз на lifespan приложения и закрывается при остановке.
Маршрут получает `ChatProxy` через `get_chat_proxy`: его можно заменить через
`app.dependency_overrides` при тестировании или подключении другой реализации.
`proxy.py` отвечает за HTTP-пересылку и использует Starlette responses;
логику, не связанную с HTTP, при появлении следует вынести в отдельные сервисы.

Команды `python main.py`, `uvicorn main:app` и `start.bat` сохраняются.

## Запуск в Windows в один клик

1. Установите Python 3.10+ и скачайте проект.
2. Дважды щёлкните `start.bat` в папке проекта.
3. При первом запуске скрипт автоматически создаст `.venv`, установит зависимости
   и создаст `.env` из `.env.example`. Впишите свой `XAI_API_KEY` в `.env`, затем
   снова запустите `start.bat`.

После сообщения `Uvicorn running on http://127.0.0.1:8000` сервис готов.
Оставьте окно открытым; остановка сервиса — Ctrl+C или закрытие окна.

## Ручной запуск в Windows (PowerShell)

Если не хотите использовать `start.bat`, откройте PowerShell в папке проекта
и выполните:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

Оставьте этот терминал открытым, пока проверяете запросы. После сообщения
`Uvicorn running on http://127.0.0.1:8000` сервис готов.
Активация окружения не требуется. Перед запуском создайте `.env` по примеру
`.env.example` и укажите свой ключ. Остановка: Ctrl+C.

Linux/macOS:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python main.py
```

## Адреса локального сервиса

Ссылки работают после запуска:

- [Swagger UI — отправить запрос из браузера](http://127.0.0.1:8000/docs).
- [OpenAPI — JSON-схема API](http://127.0.0.1:8000/openapi.json).
- [Health — проверка запуска](http://127.0.0.1:8000/health): ожидается `{"status":"ok"}`.
- Endpoint для POST-запроса: `http://127.0.0.1:8000/v1/chat/completions`.

`GET /health` проверяет только локальный сервис, без обращения к xAI.

## Проверить Grok через Swagger

1. Откройте [Swagger UI](http://127.0.0.1:8000/docs).
2. Раскройте `POST /v1/chat/completions` и нажмите **Try it out**.
3. Замените содержимое **Request body** на JSON из раздела «Запрос» ниже.
4. Нажмите **Execute**. Ключ вручную вводить не нужно: сервер читает его из `.env`.
5. Посмотрите **Server response → Response body**. При успехе код — `200`,
   текст ответа находится в `choices[0].message.content`.

Это реальный запрос в xAI, который расходует баланс API. Если xAI возвращает
ошибку доступа к модели, укажите в `model` модель, доступную вашему аккаунту.
Если браузер не открывает даже `/health`, проверьте, что терминал сервера работает
и при запуске нет ошибки занятого порта `8000`.

## Настройки

Ключ читается из `.env` рядом с `main.py`, независимо от рабочей директории.
Поддерживается существующая переменная `token_api` и стандартная `XAI_API_KEY`
(имеет приоритет). Переменные процесса имеют приоритет над одноимёнными значениями `.env`.
Исходный `.env` не изменён; пример конфигурации — `.env.example`.
При отсутствии ключа приложение останавливается с понятной ошибкой.

## Запрос

`POST /v1/chat/completions` перенаправляет JSON на фиксированный адрес
`https://api.x.ai/v1/chat/completions` с серверным `Authorization: Bearer <key>`.
Клиенту передавать ключ не нужно. Обязательны `model` и непустой `messages`.
Дополнительные поля, включая `tools`, `response_format`, `temperature`, передаются xAI.
Поддержку параметров и модели окончательно проверяет xAI.

```json
{
  "model": "grok-4.6",
  "messages": [
    {"role": "system", "content": "Отвечай кратко по-русски."},
    {"role": "user", "content": "Сколько будет 2 + 2?"}
  ],
  "stream": false
}
```

Альтернатива Swagger — выполните во втором окне PowerShell
(выберите модель, доступную вашему аккаунту):

```powershell
$body = @{ model = 'grok-4.6'; messages = @(@{ role = 'user'; content = 'Say hello' }); stream = $false } | ConvertTo-Json -Depth 10
$response = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/v1/chat/completions' -Method Post -ContentType 'application/json' -Body $body
$response.choices[0].message.content
```

JSON ответа возвращается без преобразования; текст обычно находится в
`choices[0].message.content`. При `stream: true` возвращается поток SSE.
HTTP-ошибки xAI и `Retry-After` передаются клиенту; сбой соединения даёт 502,
таймаут — 504. Таймаут чтения составляет 3600 секунд для reasoning-моделей.
Если поток оборвался после начала ответа, соединение закрывается: HTTP-статус
уже отправленного ответа изменить невозможно. Автоматических повторов нет.

Сервис предназначен для локальных клиентов: авторизация входящих запросов и CORS
не настроены. Ключ не возвращается в health или документации; тела запросов не логируются.

Документация xAI: https://docs.x.ai/developers/model-capabilities/legacy/chat-completions
Chat Completions помечен как legacy, но поддерживается; новые возможности xAI
развивает в Responses API. Этот сервис реализует только Chat Completions.

## Проверка без расходов на API

```powershell
.\.venv\Scripts\python.exe -m unittest -v
.\.venv\Scripts\python.exe -m pip check
```

Тесты используют поддельный HTTP transport и тестовый ключ, без сетевых вызовов.
