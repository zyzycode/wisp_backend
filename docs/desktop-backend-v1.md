Desktop ↔ Backend v1: wire-контракт

Канонический внешний API. Не зависит от Domain, Electron, локальных Application DTO или выбранного серверного языка. Полные формы полей и enum — [backend-ai-contract.ts](../../src/application/ports/backend-ai-contract.ts): файл самодостаточен, без импортов. Изменение локальных типов персонажа не меняет wire автоматически; преобразование принадлежит desktop adapter. Клиентский lifecycle и ограничения частоты — в [AI Provider](AI_PROVIDER_CONTRACT.md#desktop--backend-v1).

## 1. Транспорт и владение

- `POST /v1/chat`, JSON UTF-8; request `Content-Type: application/json`, `Accept: application/json`, JSON responses `Content-Type: application/json`. Успех — HTTP 200. Только `stream: false`; SSE, tools и файлы не входят в v1.
- Удалённый backend — HTTPS; HTTP допустим только loopback при разработке. Base URL — доверенная конфигурация Main. Desktop не следует redirect, не принимает URL от Renderer/модели.
- Первая версия без авторизации, cookies и login UI. LLM credential остаётся на backend; requestId/IP/installation ID не подтверждают личность пользователя.
- Backend формирует system prompt, выбирает модель, проверяет вход и модельный вывод. Пользовательские сообщения и character — недоверенные данные, не системные инструкции. Модель не исполняет команды, не выбирает URL/инструменты и не меняет сохранённое состояние desktop.
- Отправляются только текущий ограниченный диалог и character projection. Экран, окна, курсор, файлы, memories и credentials не входят в запрос. Server dialogue state не требуется: каждый запрос содержит свой контекст. История не пишется в application logs; ошибки не раскрывают prompts, stack traces или provider internals.

## 2. Поля и валидация

`version` строго 1; `requestId` — UUID v4, созданный desktop для нового обращения. Backend возвращает тот же ID. Локальные conversationId/generation/streamId не отправляются. `event.type` только `user_message`; `locale` только `ru`/`en`.

`messages`: 1–7 записей, до трёх полных пар истории и последнее user message, порядок `user, assistant, …, user`. `role` только user/assistant; content после trim непустой, user ≤240, assistant ≤2000 UTF-16 code units. System/developer/tool roles запрещены. Данные example не заменяют реальную character projection.

Все числовые границы **включительные**, числа конечные; числовые строки, null, NaN/Infinity и выход за диапазон не принимаются. Boolean поля принимают только JSON boolean, не 0/1 или строки. Отсутствие допускается только для полей, помеченных optional в wire type.

| Поле character | Диапазон / тип |
|---|---|
| `needs.energy`, `attention`, `play`, `comfort` | `[0, 100]`, обязательны |
| `needs.boredom` | `[0, 100]`, optional; отсутствие не заменять нулём |
| `personality.traits.shyness`, `playfulness`, `sensitivity`, `boldness` | `[0, 1]`, все четыре обязательны |
| `relationship.friendship`, `love` | `[0, 1000]` |
| `relationship.loveUnlocked` | boolean |
| `intimacy.flirtiness`, `romanticCharge` | `[0, 100]` |
| `intimacy.userConsentEnabled` | boolean |
| `personality.presetId` | непустая строка, ≤128 code units |
| `personality.aiSelfConcept` | непустая строка, ≤500 code units |
| `synthesizedTone` | отдельный wire enum `BackendCharacterTone` |

Request body ≤32 KiB, response body ≤16 KiB после декодирования; превышение прекращает чтение. Неизвестные ключи/неверная форма отклоняются, в том числе произвольные needs keys; исключение для необязательных response hints описано ниже. Текст plain text, контролы кроме newline/tab запрещены. Длины строк считаются в UTF-16 code units на обеих сторонах; нормализация не делает out-of-range значение допустимым.

Успех содержит version/requestId/text и optional decision. `text` после trim 1–2000 code units. `decision`: обязательные behavior и confidence, optional tone/mood; confidence finite `[0,1]`. Перечни behavior/tone/mood автономно определены wire-типами. Отсутствующий decision — корректный text-only success. Обязательного или optional поля quota в согласованной форме сейчас нет.

Модель предлагает одно semantic behavior; локальный Character проверяет актуальность, P0–P5, Needs, сон, quiet и cooldown. Confidence не даёт приоритет или право исполнения. Координаты, маршруты, клипы, длительности, изменение числовых traits/отношений, memory writes и команды ОС запрещены. Backend сам формирует envelope/requestId, не доверяет этим полям модельного вывода.

Некорректный decision при валидном тексте backend удаляет целиком и возвращает text-only success; desktop также отбрасывает некорректный decision. Невалидный обязательный envelope/text/version/requestId делает ответ целиком невалидным. Эта деградация hints не разрешает дополнительные поля верхнего уровня.

## 3. HTTP и ошибки

Ошибка содержит version/requestId/error; точная форма — `BackendAIErrorResponse`. requestId=null только когда входной ID не прочитан/невалиден. HTTP status и error.code должны соответствовать таблице; неожиданный status, HTML, пустое тело или несовместимая пара — transport/protocol failure у desktop, без принятия model decision.

| HTTP | `error.code` | Значение |
|---|---|---|
| 400 | `invalid_request` | Невалидные JSON, поля, enums или диапазоны. |
| 400 | `unsupported_version` | Версия API не поддерживается. |
| 413 | `payload_too_large` | Размер payload превышает допустимый. |
| 409 | `request_conflict` | Конфликт requestId; условия определения согласуются отдельно. |
| 409 | `request_in_progress` | Запрос с этим ID обрабатывается; правила повторов согласуются отдельно. |
| 429 | `rate_limited` | Сервер отклонил по своей политике частоты; числовые лимиты не заданы desktop. |
| 429 | `budget_exhausted` | Исчерпан серверный бюджет; scope/период/учёт согласуются отдельно. |
| 503 | `upstream_unavailable` | LLM/provider недоступен. |
| 504 | `upstream_timeout` | Deadline серверного вызова истёк. |
| 502 | `invalid_model_response` | Нельзя получить валидный текст из ответа модели. |

`error.retryAfterMs` optional: integer 1–86 400 000 ms; это подсказка о минимальном ожидании, не гарантия будущего admission и не команда автоматически повторять запрос. Наличие/отсутствие поля не определяет формулу серверной квоты. Техническое сообщение пользователю desktop берёт из локального каталога, не из provider error body.

## 4. Общие JSON fixtures

Эти файлы — общие payload fixtures для desktop и backend. Использовать один и тот же JSON, не пересобирать вручную отдельные примеры. HTTP status — транспортные метаданные из таблицы, не поле JSON body.

| Fixture | Использование |
|---|---|
| [request.valid.json](../contracts/fixtures/desktop-backend-v1/request.valid.json) | Валидное тело POST /v1/chat. |
| [response.success.json](../contracts/fixtures/desktop-backend-v1/response.success.json) | HTTP 200, успешный ответ на этот requestId. |
| [response.error.json](../contracts/fixtures/desktop-backend-v1/response.error.json) | HTTP 503, альтернативный error outcome того же запроса. |

Success и error — альтернативы, не два ответа одного исполнения. В реализации обе стороны дополнительно проверяют границы 0/верхний предел, значения за ними, неверный тип, отсутствие обязательного поля, неизвестный ключ, text-only success и malformed decision.

## 5. Серверные quota и повторы: ожидают предложения backend

Числа, scope, периоды, token accounting/reservation, concurrency, хранение/reset и форма quota metadata **не согласованы** этой версией документа. Прежние предположения desktop о глобальных 100 запросах/20 000 токенах в сутки не действуют. Клиентские 6 запросов в минуту и 100 за Main session — только локальные ограничения, не серверный бюджет и не требование повторить их на сервере.

requestId сейчас гарантирует корреляцию ответа с обращением, но не exactly-once/idempotency. Backend отдельно предлагает поведение одинакового ID с тем же/другим body, concurrent duplicate, replay/cache TTL, восстановление после restart и повторный учёт. HTTP-коды 409 согласованы как словарь ошибок, не как уже согласованный алгоритм. Digest, durable ledger, TTL и replay гарантия не предписаны. Desktop не делает автоматических retries; новая ручная отправка имеет новый UUID.

После согласования предложения обновить этот контракт, wire types и fixtures вместе. До этого не добавлять поле quota и не выводить серверные гарантии из клиентской policy. Базовые schema/endpoint/validation/error mapping можно реализовывать независимо; серверные quota/idempotency остаются отдельным незавершённым решением.
