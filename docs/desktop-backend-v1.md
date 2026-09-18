# Desktop ↔ Backend v1: wire-контракт

Канонический внешний API. Не зависит от Domain, Electron, локальных Application DTO или выбранного серверного языка. Полные формы полей и enum — [backend-ai-contract.ts](https://github.com/zyzycode/project_wisp/blob/main/src/application/ports/backend-ai-contract.ts): файл самодостаточен, без импортов. Изменение локальных типов персонажа не меняет wire автоматически; преобразование принадлежит desktop adapter. Клиентский lifecycle и ограничения частоты — в [AI Provider](https://github.com/zyzycode/project_wisp/blob/main/docs/engine/AI_PROVIDER_CONTRACT.md#desktop--backend-v1).

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
| 409 | `request_conflict` | Изменён body либо результат уже нельзя повторить; см. §5. |
| 409 | `request_in_progress` | Этот ID с тем же body сейчас обрабатывается; см. §5. |
| 429 | `rate_limited` | Превышен серверный rate/concurrency limit; см. §5. |
| 429 | `budget_exhausted` | Для нового обращения недостаточно глобального дневного бюджета; см. §5. |
| 503 | `upstream_unavailable` | LLM/provider недоступен. |
| 504 | `upstream_timeout` | Deadline серверного вызова истёк. |
| 502 | `invalid_model_response` | Нельзя получить валидный текст из ответа модели. |

`error.retryAfterMs` optional: integer 1–86 400 000 ms; это подсказка о минимальном ожидании, не гарантия будущего admission и не команда автоматически повторять запрос. Наличие/отсутствие поля не определяет формулу серверной квоты. Техническое сообщение пользователю desktop берёт из локального каталога, не из provider error body.

## 4. Общие JSON fixtures

Эти файлы — общие payload fixtures для desktop и backend. Использовать один и тот же JSON, не пересобирать вручную отдельные примеры. HTTP status — транспортные метаданные из таблицы, не поле JSON body.

| Fixture | Использование |
|---|---|
| [request.valid.json](../tests/fixtures/desktop-backend-v1/request.valid.json) | Валидное тело POST /v1/chat. |
| [response.success.json](../tests/fixtures/desktop-backend-v1/response.success.json) | HTTP 200, успешный ответ на этот requestId. |
| [response.error.json](../tests/fixtures/desktop-backend-v1/response.error.json) | HTTP 503, альтернативный error outcome того же запроса. |

Success и error — альтернативы, не два ответа одного исполнения. В реализации обе стороны дополнительно проверяют границы 0/верхний предел, значения за ними, неверный тип, отсутствие обязательного поля, неизвестный ключ, text-only success и malformed decision.

## 5. Закрытая alpha: серверный admission, учёт и повторы

Решение [BE-A01 #52](https://github.com/zyzycode/project_wisp/blob/main/docs/engine/BE_A01_RESULT.md); реализация — отдельный backend #53. Wire v1, его типы и три fixtures не меняются; quota/auth metadata не добавляются. Ниже — целевое поведение, не утверждение о готовности сервера. Клиентские ограничения остаются независимыми.

### Доступ и топология

Один экземпляр сервера, один ASGI worker, один локальный durable SQLite ledger через Python `sqlite3`. Внешняя SQL-служба/Redis/новый Python-пакет не нужны. Admission атомарен, работа с ledger не блокирует event loop; I/O failure закрывает новые обращения с 503, без вызова LLM. Многопроцессный/горизонтальный запуск вне этой схемы.

Без application auth разрешены только разработка через loopback и закрытый тест через управляемый оператором приватный туннель/VPN с индивидуально отзываемым сетевым доступом; удалённый endpoint всё равно HTTPS. Публичный ingress закрыт. Это ограничение сети, не личность пользователя в API: бюджеты общие для deployment, IP/requestId/installation ID не используются как аккаунт. Публичная регистрация и персональные квоты потребуют отдельного auth-контракта. Перед допуском тестеров оператор проверяет сетевой запрет и настройки хранения у провайдера (§6).

### Бюджеты и reservation

Начальные operator-configurable пределы закрытой alpha: **12 новых admitted обращений / скользящие 60 s**, **2 одновременно**, **100 / UTC-сутки**, **1 000 000 tokens / UTC-сутки**. Это консервативные эксплуатационные defaults, не тариф или обещание пользователю. Верхние границы включительны; для rate окно `(now−60s, now]`. Нет очереди и автоматических server retries. Локальный reset/restart desktop счётчики сервера не меняет.

До upstream атомарно проверяются duplicate, rate/concurrency и дневной остаток; затем сохраняются ID, digest, UTC bucket, admission timestamp и reservation. Invalid/rejected/duplicate обращения не расходуют новый budget. Admitted попытка расходует один request даже при ошибке; rate/concurrency rejection → 429 `rate_limited`, дневной cap или недостаток reservation → 429 `budget_exhausted`. `retryAfterMs` вычисляется до освобождения rate-окна/начала следующих UTC-суток; для занятого concurrency slot — 1000 ms. Подсказка не гарантирует admission.

Для выбранного Groq `openai/gpt-oss-20b` начальная reservation — **131 072 total tokens** на вызов: полный документированный context limit, включающий input и output. Это намеренно завышенная безопасная граница без нового tokenizer-пакета; output cap остаётся **4096**, text cap — 2000 UTF-16 units. Допуск: `charged + reserved + 131072 ≤ dailyTokenCap`. Новый model/profile разрешается только с подтверждённой верхней границей общего расхода; произвольная модель из конфигурации не обходит ledger. [Лимиты модели](https://console.groq.com/docs/model/openai/gpt-oss-20b), [семантика context limit](https://console.groq.com/docs/api-reference).

Provider adapter передаёт service внутренний результат генерации и usage отдельно от wire. На валидном `prompt_tokens`, `completion_tokens`, `total_tokens` (неотрицательные integers, total равен сумме и не выше reservation) reservation заменяется фактическим total; prompt/completion сохраняются раздельно, включая оплачиваемые reasoning tokens в completion. Невалидный model text не отменяет известный расход. При timeout, disconnect, crash, отсутствии/невалидном usage удерживается полная reservation как консервативный charge; это не подтверждённое число реально оплаченных токенов. Раздельно хранить confirmed и uncertain расход. Usage сверх согласованной границы закрывает дальнейший admission до проверки конфигурации оператором; перерасход не скрывается.

Ledger сохраняет дневные totals и допускает завершение только один раз. Пересечение полуночи завершает charge в bucket исходного admission. Restart не обнуляет budget: незавершённые записи превращаются в uncertain terminal с полным charge, физическое завершение у провайдера не предполагается. Ошибка записи terminal state также не разрешает повторный upstream. UTC используется для daily buckets, monotonic time — для deadline; backward clock не создаёт новый/пустой budget bucket.

### Повтор requestId

Сравнение — SHA-256 точных принятых UTF-8 body bytes; перестановка ключей/пробелов считается другим body. Сначала полная wire validation, затем duplicate check. Один ID хранится 24 h от admission независимо от окончания UTC-суток:

| Состояние ID | Тот же body | Другой body |
|---|---|---|
| In-flight | 409 `request_in_progress`, без нового вызова | 409 `request_conflict` |
| Terminal, ответ ещё в RAM cache | Повтор того же HTTP status/body, без нового учёта | 409 `request_conflict` |
| Terminal, cache истёк/утрачен при restart; uncertain | 409 `request_conflict`, без нового вызова | 409 `request_conflict` |
| Запись старше 24 h и удалена | Обычный новый admission | Обычный новый admission |

Terminal cache — до 10 min, максимум 100 ответов (по 16 KiB), только RAM; eviction допустим и переводит ID в третью строку. Persisted ledger не содержит запросы/ответы. Это bounded at-most-once dispatch в пределах ledger TTL, не exactly-once выполнение модели и не обещание replay после restart. Desktop по-прежнему не повторяет автоматически; ручная новая отправка получает новый UUID. Узнавание ID не даёт доступа к иной истории или чтению ledger.

### Deadline и cancellation

Общий серверный deadline — 10 s от входа в `/v1/chat`, включая body/admission/upstream; body должен завершиться за 2 s, иначе 400 `invalid_request`, upstream не вызывается. Upstream получает остаток общего deadline; connect/pool timeout не выше 3 s и остатка. Нет очереди ожидания capacity. Исчерпание общего deadline после приёма body → 504 `upstream_timeout`; byte caps проверяются при чтении, не после полной загрузки.

Disconnect/shutdown отменяет upstream task и закрывает HTTP response stream, освобождает concurrency в `finally`; terminal ledger settlement выполняется независимо от доставки ответа клиенту. Физическая остановка вычисления/списания у Groq не гарантируется. Late success не заменяет уже terminal timeout/cancel и не запускает второй вызов; достоверный usage может уточнить uncertain charge не более одного раза. Desktop сохраняет собственные 12 s transport/15 s runtime deadlines и generation guards.

## 6. Данные, сроки хранения и удаление

| Данные | Source of truth / размещение | Retention и удаление |
|---|---|---|
| Личность, отношения, индивидуальная история | Desktop SQLite | По локальной memory policy; server storage отсутствует |
| Ограниченные messages и character projection v1 | Текущий запрос; RAM backend и Groq | Backend освобождает после terminal; не пишет в SQLite, логи, traces/APM или exception dump |
| Terminal response cache | RAM backend, производная копия | ≤10 min или restart/eviction; не резервируется на диск |
| ID/digest/status/timestamps/request count/token usage | Backend SQLite, оператор deployment | ID-записи ≤24 h; дневные aggregates без IDs ≤30 суток; cleanup при startup и не реже минуты, expired записи не используются уже с TTL boundary |
| Диагностика без body/character/credentials/IP | Backend logs, оператор | Status/code, длительность, агрегированные counters ≤7 суток; logging payload и provider error body запрещён |

Ledger-файлы не попадают в обычные backups alpha; при удалении строк очищаются SQLite pages/WAL в обслуживании. Оператор может удалить cache/ledger/logs deployment; это не удаляет provider metadata и не должно использоваться как штатный сброс бюджета. Локальный memory reset не отправляет deletion request: такого endpoint в v1 нет, он не отменяет уже переданное и временный response cache.

Для alpha используется только inference endpoint Groq, без batch/fine-tuning/файлов. До передачи данных внешних тестеров оператор включает **ZDR** в Data Controls и фиксирует проверку; без неё допустимы только синтетические тестовые данные. По [политике Groq](https://console.groq.com/docs/your-data) от 2026-09-18 без ZDR возможны reliability/abuse logs inputs/outputs до 30 дней (дольше при юридической необходимости); usage metadata сохраняется отдельно, точный срок документацией не указан. ZDR относится к customer content, не обещает удаление metadata. Регион и договорные условия провайдера проверяются перед открытием доступа; нельзя объявлять удалённой провайдерскую копию по локальному reset.
