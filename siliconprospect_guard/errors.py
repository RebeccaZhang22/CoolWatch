class SiliconProspectError(Exception):
    """Base exception raised by the SDK."""


class SiliconProspectAPIError(SiliconProspectError):
    """An HTTP/API error returned by the safety service."""

    def __init__(self, message: str, *, status_code: int | None = None, code: str | None = None,
                 request_id: str | None = None, param: str | None = None, retry_after: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.request_id = request_id
        self.param = param
        self.retry_after = retry_after
