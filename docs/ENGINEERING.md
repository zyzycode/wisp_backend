# Backend engineering and operator rules

This repository implements the existing FastAPI/Groq service. The canonical
[desktop wire and alpha policy](https://github.com/zyzycode/project_wisp/blob/main/docs/engine/BACKEND_API_CONTRACT.md)
and [BE-A01 gate](https://github.com/zyzycode/project_wisp/blob/main/docs/engine/BE_A01_RESULT.md)
own the API. The [local mirror](desktop-backend-v1.md) changes links only.

## Boundaries and verification

- `api/`: bounded body/schema, HTTP mapping, downstream cancellation.
- `service.py`: admission, deadline, provider lifetime, terminal settlement.
- `contracts.py` and `providers/base.py`: internal interfaces declared before implementation.
- `providers/groq.py`: bounded upstream response, validated model reply and separate usage.
- `ledger.py`: one-worker SQLite adapter; all SQLite I/O on worker threads under a process lock.
- Desktop owns personality, memories, relationships and behavior. No history database,
  embeddings, autonomous actions, user identity or auth fields are added here.
- Use the existing dependencies. New runtime libraries require a new architecture decision.
- Bug fixes begin with a failing regression. Tests use synthetic data and mocked providers;
  never load production credentials or make real LLM requests.
- Required checks: `python -m pip check`, then `python -m pytest -q`, `git diff --check`.
  Desktop npm/build checks do not apply. Independent review is temporarily waived by the user.

## Runtime and dependency snapshot

`requirements.txt` and `requirements-dev.txt` pin all 24 packages in the verified
Python 3.10 environment, including transitive dependencies. Install both for tests;
production needs only runtime requirements. A newer Python interpreter is a separate
compatibility check, despite the application syntax baseline being Python 3.10+.

The exact 24 name/version pairs were queried through the public
[OSV querybatch API](https://google.github.io/osv.dev/api/#osvquerybatch) on 2026-09-18;
no matching advisory was returned. This is a database check at a point in time,
not a claim of no vulnerabilities or a production security approval. Recheck before
release and when changing pins. No new runtime dependencies were introduced.

The existing Starlette TestClient/httpx and AnyIO alias emit two deprecation warnings.
They do not fail the suite; switching HTTP client families is outside this change.

## Operation for closed alpha

Use one server process, **one worker and no reload**. Do not launch multiple instances
against the same ledger: startup treats old in-flight entries as crashed requests.
The existing `main.py` development launcher enables reload, so alpha uses the explicit
Uvicorn command in README. No endpoint is provisioned by this repository change.

Configuration is loaded once from environment over `.env`:

| Setting | Meaning |
| --- | --- |
| `GROQ_API_KEY` | Server-only Groq credential; legacy `token_api` fallback remains |
| `ASSISTANTS_JSON` | Server profiles; only Groq `openai/gpt-oss-20b` is reviewed; output ≤4096 |
| `WISP_LEDGER_PATH` | Durable path outside the checkout; default `~/.local/state/wisp-backend/ledger.sqlite` |
| `WISP_LIMITS_JSON` | Optional object with positive integer `rate_limit`, `concurrent_limit`, `daily_requests`, `daily_tokens` |

Defaults: 12 admitted requests per sliding 60 seconds, 2 concurrent, 100 requests per
UTC day, 1,000,000 total tokens per UTC day. The token cap must permit one reservation
of 131,072 tokens. Unsupported profiles/limits fail startup. `request_timeout` may
only be reduced from 10 seconds; connect/pool timeouts are capped at 3 seconds and
at the remaining request deadline. Body read is capped at 2 seconds and 32 KiB.

A full-model-context reservation is intentionally conservative. Confirmed usage
refunds unused reserve; missing/invalid usage and cancellation charge the full reserve
as uncertain. Invalid model text still records valid usage. Over-limit usage records
the actual reported count and persistently halts new admission with 503. Stop service,
inspect model limits/provider usage and reconcile the ledger before operator recovery;
do not clear budgets merely to bypass a limit. No automated retry occurs.

The general deadline begins at entry to `/v1/chat`, including body and admission.
A timed-out admission cannot dispatch later; any late committed reservation is settled
uncertain. Provider cancellation closes cooperative HTTP streams; physical provider
execution/billing may continue. Late trustworthy usage only refines accounting once.
Timeout/cancel responses never become late success or replayable cached output.

## Data and recovery

- SQLite stores IDs, body SHA-256, timestamps, accounting state and daily aggregates.
  Requests, responses, prompts and credentials never enter the ledger.
- Confirmed terminal response cache lives only in RAM, ≤100 responses, ≤16 KiB each,
  ≤10 minutes. Uncertain, expired/evicted or restart-lost responses return 409 on reuse.
- IDs expire at 24 hours from admission; daily aggregates at the 30-day UTC bucket
  boundary. Cleanup runs at startup, on admission, and every 60 seconds.
- SQLite uses `secure_delete`, a DELETE rollback journal and FULL synchronous writes.
  Cleared pages are overwritten; there is no persistent WAL. Exclude ledger, journals,
  process dumps and swap-derived content from backups. Storage-level copies/snapshots
  require operator deletion; SQL deletion is not a claim about an SSD's physical cells.
- Startup recovers in-flight reservations as uncertain full charge. UTC bucket belongs
  to admission, even over midnight; a persisted clock watermark prevents backward time
  from creating a fresh older bucket. A significantly wrong forward clock needs operator
  correction and budget reconciliation; do not remove the ledger to reset quota.
- Any SQLite I/O/transaction failure closes subsequent admission for this process.
  Restart only after fixing storage; durable reservations recover conservatively.
- This code emits no payload diagnostics. Operators must disable content capture in
  reverse proxy, access logs, traces/APM and exception tooling. Disable access logging
  in alpha (Uvicorn's default includes IP); any approved aggregate diagnostics retain ≤7 days.

Application auth is absent. Loopback development and private VPN/tunnel alpha only;
remote access still requires HTTPS and individually revocable network access. Before
external testers, verify public ingress is blocked and Groq ZDR is enabled. Until then,
use synthetic test content only. Provider metadata retention, region and contractual
terms require a separate operator check; local deletion does not delete provider copies.
See [Groq data policy](https://console.groq.com/docs/your-data).

Tests do not certify private ingress, ZDR, live model output, live provider billing,
Windows desktop drag/cursor behavior, or production readiness.
