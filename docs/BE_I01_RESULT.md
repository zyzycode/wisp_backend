# BE-I01 — closed-alpha backend implementation

**TASK:** [wisp_backend #1](https://github.com/zyzycode/wisp_backend/issues/1), implementing
[BE-A01](https://github.com/zyzycode/project_wisp/blob/95152d0/docs/engine/BE_A01_RESULT.md).
Base: `275cc8161e5f725681fdacc725708acaf74784b6`; implementation date: 2026-09-18.

**CHANGES:** Declared internal provider/usage/ledger contracts; added stdlib SQLite
atomic reservation, UTC daily/rate/concurrency limits, recovery, confirmed/uncertain
settlement, bounded deduplication/replay and retention. All SQLite work is outside the
event loop. Groq returns usage even when model text fails validation. Total/body
deadlines, downstream disconnect and shutdown cancellation preserve terminal outcomes;
late usage can refine charge once, without replacing timeout/cancel with cached success.

**FILES:** Runtime: `wisp_backend/contracts.py`, `ledger.py`, `service.py`,
`providers/base.py`, `providers/groq.py`, `api/boundary.py`, `api/chat.py`,
`application.py`, `config.py`, `errors.py`. Tests: `tests/conftest.py`,
`test_config.py`, `test_lifecycle.py`, new `test_ledger.py`, `test_admission_http.py`,
`test_cancellation.py`, `test_shared_fixtures.py`, and three exact shared JSON fixtures
under `tests/fixtures/desktop-backend-v1/`. Delivery/docs: runtime/dev requirements,
README, `docs/ENGINEERING.md`, wire-contract mirror and this result.

**BOUNDARIES:** Separate backend repository only. No desktop implementation or wire
changes, new runtime libraries, real LLM calls, credentials, deployment, auth, memories,
embeddings, commits or pushes. One process/one ASGI worker/no reload is required.
Operator owns private HTTPS ingress, individually revocable network access, Groq ZDR,
provider-region/retention verification and live acceptance. Windows/manual smoke is
external to these mocked tests. Existing development launcher remains reload-enabled;
README gives the explicit alpha Uvicorn command with reload/access logs disabled.

**SPRITES:** none.

**VERIFICATION:** Isolated Python 3.10 environment: all 24 exact dependency pins match;
`python -m pip check` passed; `python -m pytest -q --tb=short` passed **122 tests**;
`git diff --check` passed. Fixture SHA-256 and real-route success/error verification
pass; local documentation links checked. Two pre-existing Starlette/httpx/AnyIO
deprecation warnings remain. Tests require execution outside this environment's
restricted sandbox because thread scheduling stalls there; no live network is used
by the tests. OSV querybatch returned no advisory for the exact 24 package/version
pairs on 2026-09-18; this is not a CVE-free or production-security attestation.

**RECOMMENDED NEXT GATE:** done for BE-I01 implementation; independent review waived
by the user's temporary instruction. Coordinate task-scoped commit/push and live alpha
conditions separately. Future memory wire changes are a new gated slice.
