"""Safe service errors; never carry upstream bodies to clients."""


class ServiceError(Exception):
    def __init__(self, code: str, message: str, status: int):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def invalid_response() -> ServiceError:
    return ServiceError("invalid_response", "The assistant returned an invalid response.", 502)
