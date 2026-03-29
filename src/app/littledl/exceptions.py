class DownloadError(Exception):
    def __init__(self, message: str, url: str | None = None) -> None:
        super().__init__(message)
        self.url = url


class NetworkError(DownloadError):
    def __init__(self, message: str, url: str | None = None, original_error: Exception | None = None) -> None:
        super().__init__(message, url)
        self.original_error = original_error


class ConnectionError(NetworkError):
    pass


class TimeoutError(NetworkError):
    pass


class HTTPError(DownloadError):
    def __init__(self, message: str, status_code: int, url: str | None = None) -> None:
        super().__init__(message, url)
        self.status_code = status_code


class ResourceNotFoundError(HTTPError):
    def __init__(self, url: str) -> None:
        super().__init__(f"Resource not found: {url}", 404, url)


class ForbiddenError(HTTPError):
    def __init__(self, url: str) -> None:
        super().__init__(f"Access forbidden: {url}", 403, url)


class RangeNotSupportedError(HTTPError):
    def __init__(self, url: str) -> None:
        super().__init__(f"Server does not support range requests: {url}", 200, url)


class ChunkError(DownloadError):
    def __init__(self, message: str, chunk_id: int, url: str | None = None) -> None:
        super().__init__(message, url)
        self.chunk_id = chunk_id


class ChunkDownloadError(ChunkError):
    def __init__(self, chunk_id: int, url: str | None = None, original_error: Exception | None = None) -> None:
        super().__init__(f"Failed to download chunk {chunk_id}", chunk_id, url)
        self.original_error = original_error


class ChunkResplitError(ChunkError):
    def __init__(self, chunk_id: int, reason: str) -> None:
        super().__init__(f"Chunk {chunk_id} needs resplit: {reason}", chunk_id)


class ResumeError(DownloadError):
    def __init__(self, message: str, url: str | None = None) -> None:
        super().__init__(message, url)


class ResumeDataCorruptedError(ResumeError):
    pass


class ResumeDataNotFoundError(ResumeError):
    pass


class SpeedLimitExceededError(DownloadError):
    def __init__(self, current_speed: int, limit: int) -> None:
        super().__init__(f"Speed limit exceeded: {current_speed} > {limit}")
        self.current_speed = current_speed
        self.limit = limit


class ConfigurationError(DownloadError):
    pass


class ValidationError(DownloadError):
    pass


class CancelledError(DownloadError):
    def __init__(self, message: str = "Download was cancelled", url: str | None = None) -> None:
        super().__init__(message, url)
