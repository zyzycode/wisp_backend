# Wisp backend

Python/FastAPI service for the Wisp desktop's cloud LLM calls. The backend owns
system prompts, provider credentials and the reviewed Groq model profile. Desktop
owns individual memory, personality and local behavior.

`POST /v1/chat` implements [Desktop ↔ Backend v1](docs/desktop-backend-v1.md): bounded
JSON, validated model output, no streaming. Admission adds deployment-wide quotas,
durable SQLite usage accounting and bounded ID deduplication without changing the wire.
This supports a closed alpha; public auth/deployment and live acceptance are separate.

`POST /v2/chat` explicitly adds [bounded selected memory](docs/desktop-backend-v2.md):
five registry facts, up to two recalled episodes and one learned preference. One Groq
call returns text and optional evidence-bound proposals; desktop validates and persists
facts independently. V1 still rejects memory. Both versions share quotas and durable
request IDs; changing the endpoint does not obtain a fresh budget or replay another version.
Memory is untrusted inference context, never a server-side user profile.

## Install and run

The exact dependency snapshot is verified on Python 3.10. In PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Configure `GROQ_API_KEY` using your server environment or local `.env`. Do not commit
credentials. `WISP_LEDGER_PATH` points to persistent state **outside the checkout**;
the default is `~/.local/state/wisp-backend/ledger.sqlite`. Alpha uses one worker,
no reload, no access logging:

```powershell
.\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000 --workers 1 --no-access-log
```

The existing `python main.py` launcher reloads in development; do not use it for alpha.
[Swagger](http://127.0.0.1:8000/docs) is available while running. Remote alpha requires
private ingress plus HTTPS and verified provider ZDR; no endpoint is published here.

Defaults are 12 admitted requests/minute, 2 concurrent, 100/day and 1,000,000 tokens/day.
Set `WISP_LIMITS_JSON` to override approved positive integer limits. Each attempt reserves
131,072 tokens before dispatch, then refunds against confirmed usage. Unknown usage
keeps full conservative charge. See [engineering/operator rules](docs/ENGINEERING.md)
for deadline, cancellation, retention, recovery, supported profiles and security checks.

## Structure and tests

`wisp_backend/api/` owns HTTP boundaries; `service.py` owns orchestration;
`providers/` owns Groq integration; `contracts.py` and `ledger.py` own internal accounting.
No server dialogue history or vector database is introduced.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m pytest -q
git diff --check
```

Tests mock provider calls and use isolated temporary ledgers. Both sets of shared
[v1 fixtures](tests/fixtures/desktop-backend-v1/) and [v2 fixtures](tests/fixtures/desktop-backend-v2/) are preserved byte-for-byte and
verified through the HTTP route. `tests/fixtures/request.local.json` additionally covers
optional boredom omission. No real credentials or LLM requests are needed for tests.
