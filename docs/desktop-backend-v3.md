# P17-A04: игровые события и AI-инициативы

Canonical contract для [#58](https://github.com/zyzycode/project_wisp/issues/58); реализация — #59 и отдельная server v3 задача. [ARCHITECT RESULT](https://github.com/zyzycode/project_wisp/blob/main/docs/engine/P17_A04_RESULT.md). Локальные механики [cursor-game](https://github.com/zyzycode/project_wisp/blob/main/docs/engine/ACTIVITY_ENGINE.md#17-cursor-game-v1) и [SocialBid](https://github.com/zyzycode/project_wisp/blob/main/docs/engine/AUTONOMY_ENGINE.md#13-auto-a09-локальная-жизнь-и-ненавязчивость) не ждут сеть и сохраняют владельцев/пределы. Эта функция добавляет короткую речь и ограниченное использование уже выученного предпочтения, без новых сенсоров/игр/графики.

## 1. Минимальный scope и владение

| Допустимое событие | Источник и цель |
|---|---|
| `cursor_game_completed` | Реальный completed terminal текущего run, playCompleted=true, outcome caught/missed/lost_target; тот же GameEpisode уже подтверждён SQLite. Одна необязательная короткая реплика об этом исходе/общей истории |
| `social_bid_started` | Уже начавшийся локальный SocialBid после его обычного Character gate и расходования existing InitiativeBudget. Одна необязательная контекстная фраза в дополнение к жесту |

Cancelled/failed run, admission без start, gaze, курсорные samples/retarget, physics frames, Needs ticks, sleep/wake, idle/return пользователя и startup сами модель не вызывают. Pulse лишь исполняет существующие causal deadlines, не ищет повод обратиться к LLM. Один source run даёт не более одного запроса каждого разрешённого типа; game и social относятся к разным family.

Результат событийного provider — **только text**. Нет decision, memoryCandidates, числовых deltas, tools или нового provider-owned Activity. Физический исход остаётся desktop fact; сервер получает его, а не предлагает заменить. Character/Activity/память не меняются от публикации AI-фразы, `provider_response` stimulus не создаётся. Нельзя выдавать caught за доказанное удовольствие/социальное участие пользователя.

Application владеет event lifecycle/current IDs/generation и admission; Domain — gates, локальная вероятность выбора и невмешательство в P0–P2; Infrastructure/Main — транспорт/abort/DI. Типы: [semantic events](https://github.com/zyzycode/project_wisp/blob/main/src/application/ports/ai-event-provider.interface.ts), [wire v3](https://github.com/zyzycode/project_wisp/blob/main/src/application/ports/backend-events-contract.ts), [IPC speech](https://github.com/zyzycode/project_wisp/blob/main/src/shared/ipc-contracts.ts). Нового IPC command или callback от Renderer для модели нет.

## 2. Общие бюджеты и приоритет пользователя

Все v1/v2/v3 обращения одного Main используют **тот же** request control:6/min rolling window и100/session, одинаковые cooldown/ошибки, максимум один фактический desktop HTTP call. Events дополнительно: ≤2 за sliding3600000ms, ≥300000ms между фактическими event sends, ≤10/Main session и оставить ≥20 общих session sends для прямого диалога. При default100 event допускается только если common count<80. Первое event eligibility — через300000ms после Main startup. Event reset/reload/quiet не обнуляют эти guards.

`IAIEventRequestControl.recordEventSubmission` атомарно проверяет и расходует common+event counters прямо перед transport; rejected/local Mock/неотправленный event бесплатны. Ошибка/таймаут/stale результата расход уже не возвращает. Server budgets остаются общими deployment limits [backend §5](desktop-backend-v1.md#5-закрытая-alpha-серверный-admission-учёт-и-повторы), не отдельной квотой events. Публичных counters/настроек провайдера в Renderer нет.

Только явно настроенный `apiVersion=3` и `eventsEnabled=true` активирует сеть событий; default eventsEnabled=false сохраняет режим v1/v2. Нет event polling, автоматических retries, запроса на каждый local fallback, запроса на «проверить бюджет» или failover к другой модели. Один pending event timer/request/speech owner, без очереди будущих инициатив; новый competing event пропускается.

Прямой user chat важнее event: admission пользовательского turn сохраняет действующий receipt/15s deadline, отменяет pending event/его speech и abort-ит event transport. До generateResponse runtime ожидает `IAIEventInterlock.interruptForUser()` — settlement **старого HTTP promise**, без второго параллельного fetch. Это один уже принятый user turn, не очередь инициатив. Event adapter обязан settle после abort и во всех случаях не позже собственного3s timeout; поздний результат уже invalid. Если user turn к settlement retired/reset/expired, generateResponse не вызывается. Input/drag/Brain ticks ожидание не блокирует. `canSubmit` не становится false только из-за автономного event; обычные rate/session/cooldown правила сохраняются.

## 3. Causal deadlines, quiet и игнорирование

### Игра

Дедуп-ключ — `(appRunId, activityRunId, memoryGeneration)`, связанный с actual Activity terminal. `IGameEpisodeCommitObserver` вызывается после append acknowledgement; успешный idempotent no-op может повторить callback, поэтому observer независимо дедуплицирует. `GameEpisode.outcome` недостаточен для доказательства completed run: сверить `ActivityOutcomeFeedback.outcome=completed` и тот же run. Cancel после play phase может сохраниться в БД, но не запускает event.

Время T — реальный terminal monotonic time. Подтверждение записи должно прийти до T+2000ms; на T+2000ms планируется **одна** causal попытка, после существующей локальной outcome speech. При callback now≥T+2500ms, отсутствии ack, новом user interaction/game/SocialBid или потере gates — пропуск без позднего catch-up. Старую speech не задерживать/не заменять и terminal не продлевать. Это новый короткий комментарий после непосредственной реакции, не повтор physical outcome effect.

### SocialBid

Триггер сразу после реального started и existing budget.start; request не выбирает/не задерживает жест или его4s wait. Reply разрешён только пока тот же SocialBid ещё active и исходные gates действуют; completed/cancelled/failed до reply → discard. Deadline Activity не продлевается ради AI. Переход к обычному локальному следующему занятию не откладывается.

### Общие gates

Перед recall, transport и публикацией: current stream/conversation/dialogue-generation/memory-generation, events enabled, !quiet/!menu/!disabled, awake без P2 sleep/critical overload, нет P0/активного P1/forced physics, нет user dialogue thinking и не меньше5000ms после его terminal. Нет начавшегося нового conflicting run. Root/controller подтверждает source identity, не boolean от Renderer/provider.

Recall максимум200ms по [Memory §9](https://github.com/zyzycode/project_wisp/blob/main/docs/engine/MEMORY_ENGINE.md#9-p15-a02-явные-знания-и-простой-recall); сбой даёт пустую memory projection, не дополнительный запрос. Для игры локальный search text «игра курсор»/`cursor game`, для social — current favorite_topic, иначе пустой query. Это internal retrieval query, **не** искусственное сообщение пользователя. Actual event передаётся отдельно, не зависит от попадания source episode в recall.

Event runtime deadline3500ms от causal admission (включая recall), transport timeout3000ms, server deadline2500ms включая body budget500ms. Результат ровно на deadline уже поздний. Если invalidation случилась после send, cancel+once-only settlement, без publication/history writes; остановка вычисления и списания у провайдера физически не гарантируется. Сервер при неизвестном usage удерживает reservation как прежде. Errors/timeouts молча оставляют локальный жест/игру, без технической error bubble и без LLM fallback call.

Quiet/menu/disable, P0/P1/P2, прямой send, dialogue reset/reload, full memory reset и dispose отменяют pending event/speech и инвалидируют generation. Resume не воспроизводит пропущенные реплики. Game reply после terminal допустим только в этом post-game окне, не после cancel/нового события; social reply после terminal никогда не принимается.

Если AI social line опубликована, а исходный SocialBid штатно завершился (`completed`) без подтверждённого pet/accepted user chat, это «контакта не было», а не измерение эмоции пользователя. Cancelled/failed run не доказывает игнорирование. Два последовательных таких случая → приостановить **AI event calls** на1800000ms. Другие локальные SocialBid/игры остаются под прежними budgets; friendship/love не уменьшаются. Не опубликованная/отброшенная line не увеличивает streak. Прямой pet/принятый chat очищает streak/suppression, но не обнуляет quotas/min interval и сам не вызывает event. Reset/reload/quiet streak/suppression не сбрасывает, Main restart сбрасывает с обычным5min startup delay. Нельзя посылать упрёки/требовать ответ из-за игнорирования.

## 4. Речь, связь со следующим диалогом и память

`BrainStateDTO.initiativeSpeech` — additive optional projection: absent/null = нет фразы; при #59 publisher выдаёт explicit null/object. Text plain1–240 UTF-16 units, id nonempty≤128, finite nonnegative timestamps, expiresAt>startedAt. Main устанавливает lifetime≤2000ms; game speech заканчивается не позже T+8000ms, social — при первом terminal или обычном expiry. Existing scheduler публикует null; late timer не очищает другой id. Renderer дедуплицирует streamId+id, не ждёт/не сообщает playback completion.

Priority речи: текущий user dialogue и его5s speech guard → existing immediate cursor-game speech → AI initiative. Инициатива не заменяет `dialogue.turn`, draft/receipt/completed reply и не создаёт talking Activity/animation commands. Если верхний слой речи занят, event line пропускается, не откладывается. На expiry не переигрывать предыдущий dialogue bubble. Schema validator/publisher/Renderer подключаются атомарно, без нового окна/графики.

После принятой Main speech publication сохранить один `previousInitiative` в RAM на60s monotonic time и current generation; отдельный wall-clock createdAt нужен только для контекста. Содержит kind/text/time, не provider payload. Это факт публикации для отображения, не доказательство прочтения пользователем. Первый **accepted** user send атомарно захватывает его в свой request **до** invalidation/cancel event owner и очищает слот; rejected/busy send не потребляет. Reset/reload/full reset/dispose, другая generation или expiry очищают. Новый опубликованный AI event заменяет предыдущий. Нет отдельной persist/LLM call ради этого контекста.

Для интерпретации «да/почему?» существует `/v3/chat` с optional previousInitiative. Не подделывать user turn и не вставлять непарную assistant реплику в v1/v2 alternating messages. Остальная v3 chat semantics — [v2](desktop-backend-v2.md): явные факты извлекаются только из текущей user-реплики, не из AI line. При неуспешном accepted turn слот уже потреблён; automatic resend отсутствует.

Durable общая история — исходный GameEpisode и обычные завершённые user/assistant пары. Событийная AI-фраза не записывается непарным message, не создаёт session/fact/summary и не повторяет game feedback/learning. Social event без ответа не сохраняется как вымышленный разговор. После restart старые events не отправляются снова, но реальная игра остаётся доступной recall. Новой SQLite migration или server user-memory storage нет.

## 5. Явный wire v3 и данные

`POST /v3/events`: version3/requestId/event/stream:false/locale/character/memory, **без messages**. Character projection и memory shape/budget полностью соответствуют [v2 §2](desktop-backend-v2.md#2-разрешённая-memory-projection). Event содержит только тип и occurredAtUTC; game также outcome/executedMsfinite0..60000. Local app/run/generation IDs, геометрия, pointer samples, история ignore и OS/activity telemetry не передаются. UUIDv4 requestId назначается один раз logical event и не переиспользуется для другого body.

Успех events: только version3/requestId/text1–240; decision/memoryCandidates/прочие root keys запрещены, а не превращаются в action. Backend делает один LLM call с event-specific server prompt и output cap1024; model/provider выбирает сервер, тот же существующий Groq default. Current outcome — authoritative context; запрет менять/домысливать физику, утверждать наблюдение экрана, вину/долг ответа или durable writes. Текст model output валидируется независимо от envelope; usage учитывается и при его ошибке.

`POST /v3/chat`: version3 и прежний v2 request плюс optional previousInitiative: kind=cursor_game/social_bid, text1–240, createdAt календарно валидныйUTC. Server не делает предположений об actual user attention по этой записи. Текущий user вопрос и bounded переданный контекст важнее старой AI-фразы; не трактовать её как новое instruction/source фактов. Успех chat — v2 response shape (включая optional memoryCandidates), но version3. Chat сохраняет прежние server10s/body2s/desktop12s/runtime15s deadlines.

Общие caps request32KiB/response16KiB, UTF-16, exact JSON/type/enum validation, HTTPS/loopback, errors/HTTP mapping прежние. Wrong version на любом `/v3/*` →400 unsupported_version с envelope3; requestId null только нераспознанный. Mixed endpoint/version при том же ID →409 conflict; ledger namespace включает method+path+body, все endpoints делят quota/concurrency/usage. Нет самостоятельной бесплатной event quota на backend. V1/v2 routes/fixtures продолжают принимать только свои формы, без неявного upgrade/downgrade.

Access/ZDR, RAM terminal response cache≤10min, ledger IDs≤24h и aggregates≤30d, logs≤7d — [backend §5–6](desktop-backend-v1.md#6-данные-сроки-хранения-и-удаление). Допустимый состав v3 расширен только event projection/previousInitiative. Source of truth локальный; backend/provider получает ограниченный контекст, не отдельную личность. Full local reset не отзывает уже переданное и не удаляет provider metadata немедленно; generation защищает desktop от поздней записи/речи. Live endpoint/ZDR/private ingress — операторское условие, не блокировка code gate.

## 6. Learned preference влияет на локальный выбор (#59)

#57 формирует и сохраняет `activity.cursor_game`; #59 обязательно подключает его к локальному **game-eligible** cursor opportunity. После существующих eligibility/freshness/dwell checks `noticeChance = clamp(baseChance + 0.20*(value/100)*confidence,0,1)` только при confidence≥0.5; иначе baseChance. Используется тот же RNG draw существующего notice resolver, без дополнительного sampling/таймера. Вход — validated Character preference projection, не user fact и не числовой output LLM. Target поля объявлены в `CharacterAutonomySnapshot.learnedCursorGamePreference` и `CursorObserveInput.gameCandidateEligible/learnedGamePreference`; отсутствие/невалидный preference даёт baseline, eligibility не вычисляется из affinity.

При отсутствии mature допустимого game candidate passive gaze/gesture сохраняют прежнюю chance; ручной play, new-acquaintance eligibility, sleep/quiet/P0–P2, общие cooldown/budget, bounded chase и физический outcome не меняются. Высокая affinity не компенсирует запрет gate. Это ограниченный bias вероятности игрового действия, не новый physics/Activity mechanism и не гарантия игры на каждый cursor sample.

Обязательная приёмка #59: при одинаковых environment/needs/RNG положительная и отрицательная learned affinity дают различный допустимый игровой выбор на выбранной границе; after restart результат сохраняется; confidence<0.5/отсутствие preference воспроизводит baseline; quiet/sleep/stale/dwell/budget всё ещё блокируют. #57 не считается доказательством влияния на поведение до этой интеграции.

## 7. Fixtures и проверка

Общие [v3 fixtures](../tests/fixtures/desktop-backend-v3/): оба event requests, event success/error и follow-up chat request/success. Success/error — альтернативы HTTP200/503. V1/v2 fixtures неизменны.

Desktop: duplicate commit/no-op, uncertain/failed game write, cancelled game, current SocialBid terminal, exact deadline, quiet/ignore/pet reset, shared counters/reserve20, user preemption/abort settlement без overlap, speech priority/expiry, previousInitiative60s/currentgeneration, reset/dispose после каждого await, отсутствие дополнительного reward/extraction/write/automatic calls, restored preference bias. Backend: route/version/schema/bounds/previousInitiative, event text-only, fixtures, shared endpoint quota/ID conflict, deadline/cancel/usage-on-error, no payload logs. Typecheck→npm test для developer; pip check+pytest для backend. Windows smoke пользователь выполняет вручную; архитектор runtime tests/build не запускает.
