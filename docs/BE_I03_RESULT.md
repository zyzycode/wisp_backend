# BE-I03 — companion events and follow-up chat v3

**TASK:** [backend #3](https://github.com/zyzycode/wisp_backend/issues/3), implementing
[P17-A04](https://github.com/zyzycode/project_wisp/blob/95152d0/docs/engine/P17_A04_RESULT.md).
Base commit: `af21c36`; implementation date: 2026-09-18.

**CHANGES:** Added strict `/v3/events` with text-only model output, maximum 1024 output
tokens, 500 ms body budget and 2.5-second overall deadline. Added `/v3/chat` over v2
memory with one optional, separately attributed previous AI initiative. The current
last user message alone supplies candidate evidence. Both routes use one provider call
and the existing shared quotas/ID namespace/reservation/usage ledger.

**REGRESSION FIX:** A reproduced commit/deadline race could cache a successful response
before a delayed terminal completion while the caller returned timeout. The existing
publication cancellation guard now also gates RAM replay. The failing regression
returned 200 instead of 409 before the fix; it and v1/v2 lifecycle regressions now pass.
Exact deadline checks apply before accepting provider output or a replayed result.

**BOUNDARIES:** No new packages/models/storage, desktop edits, real LLM calls, secrets,
auth, server character history, event scheduler, deployment, commits or pushes. Current
event outcome is authoritative prompt context; server cannot independently prove local
activity eligibility, SQLite acknowledgement or user attention. Those remain desktop
responsibilities. Original v1/v2 schemas/fixtures and legacy v1 ID TTL are preserved.

**SPRITES:** none.

**VERIFICATION:** Exact isolated Python 3.10 environment: `pip check` PASS;
`pytest -q --tb=short` PASS: 224 passed, 2 warnings in 9.24s. Two previous Starlette/httpx/AnyIO deprecation
warnings remain. Six v3 fixture copies are byte-identical to desktop and covered by
mocked HTTP/hash tests. Route versions, caps, text-only failures/usage, provenance,
shared quotas/IDs, body/overall deadlines, disconnect/shutdown and late accounting are
covered. Local documentation links, unchanged dependency pins and diff whitespace checked.
No live provider or Windows test was performed.

**LIMITATIONS:** One worker/no reload; private HTTPS ingress, ZDR/provider settings and
live endpoint acceptance remain operator actions. Manual Windows acceptance belongs
to the user. Local reset cannot delete provider metadata or immediately purge remote RAM.

**RECOMMENDED NEXT GATE:** done for BE-I03 code; independent review temporarily waived
by the user. Coordinate the task-scoped commit separately.

## Files

- `README.md`
- `docs/BE_I03_RESULT.md`
- `docs/ENGINEERING.md`
- `docs/desktop-backend-v3.md`
- `tests/fixtures/desktop-backend-v3/request.chat.json`
- `tests/fixtures/desktop-backend-v3/request.game.json`
- `tests/fixtures/desktop-backend-v3/request.social.json`
- `tests/fixtures/desktop-backend-v3/response.chat.success.json`
- `tests/fixtures/desktop-backend-v3/response.error.json`
- `tests/fixtures/desktop-backend-v3/response.event.success.json`
- `tests/test_events_lifecycle.py`
- `tests/test_events_route.py`
- `tests/test_events_validation.py`
- `wisp_backend/api/boundary.py`
- `wisp_backend/api/events.py`
- `wisp_backend/application.py`
- `wisp_backend/contracts.py`
- `wisp_backend/event_prompts.py`
- `wisp_backend/events_schemas.py`
- `wisp_backend/ledger.py`
- `wisp_backend/prompts.py`
- `wisp_backend/providers/groq.py`
- `wisp_backend/service.py`
