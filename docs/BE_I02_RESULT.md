# BE-I02 — bounded memory API v2

**TASK:** [backend #2](https://github.com/zyzycode/wisp_backend/issues/2), implementing
[P15-A02](https://github.com/zyzycode/project_wisp/blob/main/docs/engine/P15_A02_RESULT.md).
Base commit: `5d74958`; implementation date: 2026-09-18.

**CHANGES:** Added `/v2/chat` alongside v1 with strict memory projection, versioned
response/errors and internal provider reply context. A single Groq call receives a
separate untrusted memory block and returns optional source-bound candidates.
Malformed/duplicate candidates degrade independently; text/root validation and usage
accounting stay strict. Shared ledger admission uses endpoint-aware digests, preserves
legacy v1 body-only digest TTL and shares every quota across versions.

**BOUNDARIES:** Desktop SQLite remains memory authority. No memory persistence on the
server, new dependencies, real provider calls, deployment, desktop changes, auth,
embeddings, game event API, commit or push. V1 fields/fixtures remain unchanged.
Manual Windows acceptance belongs to the user; private ingress/ZDR and live provider
acceptance remain external operator conditions, not blockers for this code gate.

**SPRITES:** none.

**VERIFICATION:** Exact pinned isolated Python 3.10 environment: `pip check` PASS;
`pytest -q --tb=short` PASS: 174 passed, 2 warnings in 7.12s. Two existing Starlette/httpx/AnyIO deprecation
warnings remain. V2 fixtures match desktop byte-for-byte and pass real-route mocked
HTTP tests; all original v1 tests remain. Local links, unchanged exact dependency pins
and diff whitespace checked. No real LLM or live endpoint testing was performed.

**RECOMMENDED NEXT GATE:** done for BE-I02 code. Independent review temporarily waived
by the user. The future events/initiative bridge is a separate gated task.

## Files

- `README.md`
- `docs/BE_I02_RESULT.md`
- `docs/ENGINEERING.md`
- `docs/desktop-backend-v2.md`
- `tests/fixtures/desktop-backend-v2/request.valid.json`
- `tests/fixtures/desktop-backend-v2/response.error.json`
- `tests/fixtures/desktop-backend-v2/response.success.json`
- `tests/test_memory_admission.py`
- `tests/test_memory_lifecycle.py`
- `tests/test_memory_route.py`
- `tests/test_memory_validation.py`
- `wisp_backend/api/boundary.py`
- `wisp_backend/api/chat.py`
- `wisp_backend/api/memory.py`
- `wisp_backend/application.py`
- `wisp_backend/contracts.py`
- `wisp_backend/ledger.py`
- `wisp_backend/memory_schemas.py`
- `wisp_backend/prompts.py`
- `wisp_backend/providers/base.py`
- `wisp_backend/providers/groq.py`
- `wisp_backend/service.py`
