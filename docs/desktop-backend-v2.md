# Desktop ↔ Backend v2: ограниченная локальная память

Явное совместимое расширение рядом с v1, решение [P15-A02 #55](https://github.com/zyzycode/project_wisp/blob/95152d0/docs/engine/P15_A02_RESULT.md). Формы — [backend-memory-contract.ts](https://github.com/zyzycode/project_wisp/blob/95152d0/src/application/ports/backend-memory-contract.ts); imports только из автономных v1 wire types. Серверная реализация — отдельная задача в `wisp_backend`, клиентская — #56. Наличие этого документа не означает доступность `/v2/chat` на сервере.

## 1. Версия и границы

- `POST /v2/chat`, `version:2`, JSON UTF-8, `stream:false`, event только `user_message`. `/v1/chat` и его fixtures не меняются и по-прежнему отвергают memory/новые поля.
- Main явно выбирает provider API version1 или2 из доверенной конфигурации; default1 сохраняет #54. Нет автоматического probe, downgrade, повторного LLM или fake user events. v2 404/unsupported/unavailable — обычный safe fallback, локальная жизнь продолжается.
- Поля character/messages/locale/ID и весь HTTP/error dictionary имеют прежнюю семантику [v1 §1–3](desktop-backend-v1.md#1-транспорт-и-владение), кроме version2. Request ≤32 KiB, response ≤16 KiB; UTF-16 text limits и exact-shape сохраняются. `requestId:null` допустим только для нераспознанного/невалидного ID в ошибке.
- Wrong version на `/v2/chat` → HTTP400 `unsupported_version` с envelope version2; аналогично `/v1/chat` отвечает собственной version1. Ошибку протокола нельзя принимать за успешный memory response.
- Closed-network access, общие deployment budgets, UTC accounting, cancellation/deadline10s и retention остаются [v1 §5–6](desktop-backend-v1.md#5-закрытая-alpha-серверный-admission-учёт-и-повторы). Ledger общий для обеих версий; digest включает method+path+точные body bytes. Повтор ID на другом endpoint →409 conflict, а не вторая бесплатная генерация. Для v1-only ledger прежний body digest допустим; при внедрении v2 legacy records нельзя replay через v2, их прежний TTL соблюдается.
- 200ms desktop recall входит в прежний15s runtime deadline; adapter timeout12s от fetch start сохраняется. Нет auth, server memory, tools, scheduler, файлов, экрана или новых игровых сетевых событий.

## 2. Разрешённая memory projection

`memory` — обязательный объект с тремя обязательными массивами; пустые массивы — корректный degraded/пустой context. В него входят только локально отобранные данные, не полный SQLite dump. Local source IDs/session IDs/generation и schema/SQL не передаются.

| Поле | Валидация |
|---|---|
| `facts` | 0–5 уникальных registry keys из wire type; value непустой plain text: display_name/preferred_address ≤80, favorite_topic ≤120 UTF-16; reply_style строго brief/detailed, cursor_game строго like/dislike |
| `episodes` | 0–2 записей, из них ≤1 cursor_game; неизвестные варианты/поля запрещены |
| dialogue episode | userText 1–240, assistantText 1–400 UTF-16; occurredAt — календарно валидный UTC `YYYY-MM-DDTHH:mm:ss.sssZ` |
| cursor_game episode | Только реальный сохранённый playCompleted episode; outcome по wire enum; executedMs finite ≥0 и ≤60000; occurredAt как выше; координаты/участие пользователя не выводить из outcome |
| `characterPreferences` | 0–1 запись с key activity.cursor_game; value finite −100..100, confidence finite0.5..1; это learned Character affinity, не user fact |

Все memory text values вместе ≤2400 UTF-16 units: рекурсивная сумма всех string values внутри memory, включая registry key values, enum values и timestamps, без имён JSON properties. Числовые строки/booleans вместо чисел не принимаются. Остальной byte budget учитывает JSON escaping: если полный запрос не помещается, desktop убирает ranked episodes, затем прекращает отправку при всё ещё невалидном размере; ядро personality и текущий user text не сокращаются ради памяти. Пустая память не позволяет убрать обязательный memory object.

Backend включает memory в отдельный **untrusted context** блок. Precedence: system instructions → текущая явная пользовательская correction → актуальные registry facts → recalled episodes; это приоритет фактического контекста, не право user/memory менять system instruction. Старые эпизоды не доказывают нынешние предпочтения. Character projection всегда передаётся отдельно; модель не обещает знания о несохранённых/непереданных событиях.

## 3. Ответ и extraction

Envelope version/requestId/text/optional decision соответствует v1; дополнительно optional `memoryCandidates`, массив0–3. Каждый кандидат — key/value из registry + evidenceQuote1–240 UTF-16 units. evidenceQuote должен побуквенно совпадать с trim последнего user content текущего запроса. Чужие источники, source IDs, confidence, числовые state deltas и операции удаления не входят в предложение.

Provider получает один запрос на ответ и предложения, без отдельного extraction/summary call. Backend контролирует envelope, структурно валидирует candidate fields/limits и source quote. Desktop независимо повторяет wire validation, затем применяет локальный recognizer из [Memory §9](https://github.com/zyzycode/project_wisp/blob/95152d0/docs/engine/MEMORY_ENGINE.md#9-p15-a02-явные-знания-и-простой-recall). Модель предлагает, но не решает, что записать; local recognizer может сохранить точную поддержанную форму и при отсутствии candidate.

Невалидный required envelope/text делает весь ответ невалидным. Невалидный decision отбрасывается целиком по v1. Невалидный тип/слишком длинный memoryCandidates → удалить всё поле; невалидный отдельный candidate → удалить этот элемент; все элементы с повторённым key удалить. Валидные text/decision сохраняются. Unknown root keys по-прежнему запрещены. Кандидаты из fallback/старого generation не записываются; локальная проверка user text после успешного сохранения пары остаётся независимой.

System prompt запрещает объявлять факт durable-записанным/удалённым: backend не знает outcome desktop transaction. Temporary role, пожелание изменить характер, гипотеза и чужая цитата не основание state/fact write. Ответ может учитывать предпочтение в текущем разговоре, не обещая его сохранение.

## 4. Данные и удаление

Передаются пять разрешённых текущих scalar facts, максимум два выбранных эпизода и один learned preference; это дополнение к составу v1, выбранное только в режиме v2. Локальная SQLite — source of truth; backend использует memory только для текущего inference, не ведёт копию профиля/истории и не пишет memory в logs/APM. Server RAM response cache до10min может содержать реплику/кандидаты; requests очищаются после terminal. Ledger хранит digest/usage без содержимого по прежним TTL. Groq получает ровно selected context; для внешних тестеров обязательна подтверждённая ZDR-настройка из v1 §6.

Full local memory reset очищает источники и инвалидирует callbacks/recall/extraction; запрос уже у провайдера физически не отзывается гарантированно. Reset не удаляет server RAM cache немедленно и не обещает удаление provider metadata. Отдельного server deletion API нет. Диалоговый reset очищает volatile dialogue, но не подтверждённые facts/эпизоды. Исправленное значение используется в следующем запросе, старый transcript не передаётся как competing structured fact.

## 5. Общие fixtures и acceptance

Обе стороны используют **одни и те же** JSON-файлы из [desktop-backend-v2](../tests/fixtures/desktop-backend-v2/): [request.valid](../tests/fixtures/desktop-backend-v2/request.valid.json), [response.success](../tests/fixtures/desktop-backend-v2/response.success.json), [response.error](../tests/fixtures/desktop-backend-v2/response.error.json). Success/error — альтернативные HTTP200/503 outcomes. V1 fixtures остаются неизменными и продолжают проходить.

Проверить обе версии одновременно, mixed endpoint/requestId conflicts, byte/text caps, unknown fields, invalid hints/candidates/source quote, grounded correction, отсутствие model numeric writes, timeout/outage/disconnect, once-only usage и поздние callbacks после reset/dispose. Клиентские semantic tests дополнительно доказывают restart recall facts/game, отсутствие повторного extraction старой истории и сохранение completed reply при ошибке fact write.
