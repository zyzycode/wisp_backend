"""Public error codes have one canonical HTTP mapping."""
from wisp_backend.schemas import ErrorCode

ERROR_STATUS = {
    "invalid_request": 400, "unsupported_version": 400, "payload_too_large": 413,
    "request_conflict": 409, "request_in_progress": 409, "rate_limited": 429,
    "budget_exhausted": 429, "upstream_unavailable": 503, "upstream_timeout": 504,
    "invalid_model_response": 502,
}


class ServiceError(Exception):
    def __init__(self, code: ErrorCode, retry_after_ms: int | None = None):
        super().__init__(code)
        self.code = code
        self.retry_after_ms = retry_after_ms
        self.status = ERROR_STATUS[code]


def invalid_response() -> ServiceError:
    return ServiceError("invalid_model_response")
