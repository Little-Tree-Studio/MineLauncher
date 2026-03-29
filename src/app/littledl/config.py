from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .strategy import DownloadStyle

DEFAULT_MIN_CHUNK_SIZE = 2 * 1024 * 1024
DEFAULT_MAX_CHUNK_SIZE = 8 * 1024 * 1024
DEFAULT_CHUNK_SIZE = 4 * 1024 * 1024
DEFAULT_BUFFER_SIZE = 64 * 1024
DEFAULT_MAX_CHUNKS = 16
DEFAULT_MIN_CHUNKS = 1
DEFAULT_TIMEOUT = 300
DEFAULT_CONNECT_TIMEOUT = 30
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_DELAY = 1.0
DEFAULT_MAX_RETRY_DELAY = 30.0
DEFAULT_SPEED_SAMPLE_WINDOW = 10
DEFAULT_RESPLIT_THRESHOLD = 0.5
DEFAULT_RESPLIT_COOLDOWN = 5.0
DEFAULT_ADAPTIVE_INTERVAL = 3.0
DEFAULT_LOW_SPEED_LIMIT = 1024
DEFAULT_LOW_SPEED_TIME = 30
DEFAULT_HYBRID_TARGET_CHUNK_TIME = 1.5
DEFAULT_HYBRID_SPEEDUP_THRESHOLD = 0.08
DEFAULT_HYBRID_SLOW_CHUNK_RATIO = 0.45
DEFAULT_HYBRID_MIN_REMAINING_BYTES = 512 * 1024


class ProxyMode(Enum):
    NONE = "none"
    SYSTEM = "system"
    CUSTOM = "custom"
    AUTO = "auto"


class AuthType(Enum):
    NONE = "none"
    BASIC = "basic"
    BEARER = "bearer"
    DIGEST = "digest"
    API_KEY = "api_key"
    OAUTH2 = "oauth2"
    CUSTOM = "custom"


class RetryStrategy(Enum):
    FIXED = "fixed"
    EXPONENTIAL = "exponential"
    LINEAR = "linear"
    ADAPTIVE = "adaptive"


class SpeedLimitMode(Enum):
    GLOBAL = "global"
    PER_CONNECTION = "per_connection"
    DYNAMIC = "dynamic"


@dataclass
class AuthConfig:
    auth_type: AuthType = AuthType.NONE
    username: str | None = None
    password: str | None = None
    token: str | None = None
    api_key: str | None = None
    api_key_header: str = "X-API-Key"
    oauth2_token_url: str | None = None
    oauth2_client_id: str | None = None
    oauth2_client_secret: str | None = None
    oauth2_refresh_token: str | None = None
    custom_headers: dict[str, str] = field(default_factory=dict)
    refresh_before_expiry: int = 300

    def needs_refresh(self) -> bool:
        return self.auth_type == AuthType.OAUTH2 and self.oauth2_refresh_token is not None

    def get_auth_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.auth_type == AuthType.BEARER and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        elif self.auth_type == AuthType.API_KEY and self.api_key:
            headers[self.api_key_header] = self.api_key
        elif self.auth_type == AuthType.CUSTOM:
            headers.update(self.custom_headers)
        return headers


@dataclass
class ProxyConfig:
    mode: ProxyMode = ProxyMode.AUTO
    http_proxy: str | None = None
    https_proxy: str | None = None
    socks_proxy: str | None = None
    proxy_username: str | None = None
    proxy_password: str | None = None
    no_proxy_hosts: list[str] = field(default_factory=lambda: ["localhost", "127.0.0.1"])
    pac_url: str | None = None
    trust_env: bool = True

    def get_proxy_for_url(self, url: str) -> str | None:
        from urllib.parse import urlparse

        parsed = urlparse(url)
        host = parsed.hostname or ""

        for no_proxy_host in self.no_proxy_hosts:
            if host == no_proxy_host or host.endswith(f".{no_proxy_host}"):
                return None

        scheme = parsed.scheme
        if scheme == "https":
            return self.https_proxy or self.http_proxy
        elif scheme == "http":
            return self.http_proxy or self.https_proxy
        return self.http_proxy or self.https_proxy or self.socks_proxy


@dataclass
class SpeedLimitConfig:
    enabled: bool = False
    mode: SpeedLimitMode = SpeedLimitMode.GLOBAL
    max_speed: int = 0
    burst_size: int = 0
    enable_burst: bool = True
    min_speed_threshold: int = DEFAULT_LOW_SPEED_LIMIT
    min_speed_duration: float = DEFAULT_LOW_SPEED_TIME

    def __post_init__(self) -> None:
        if self.burst_size == 0:
            self.burst_size = min(self.max_speed * 2, 10 * 1024 * 1024)


@dataclass
class RetryConfig:
    max_retries: int = DEFAULT_MAX_RETRIES
    strategy: RetryStrategy = RetryStrategy.EXPONENTIAL
    base_delay: float = DEFAULT_RETRY_DELAY
    max_delay: float = DEFAULT_MAX_RETRY_DELAY
    retry_on_status: list[int] = field(default_factory=lambda: [408, 429, 500, 502, 503, 504])
    retry_on_timeout: bool = True
    retry_on_connection_error: bool = True
    max_total_retries: int = 10
    jitter: bool = True
    backoff_factor: float = 2.0

    def calculate_delay(self, attempt: int) -> float:
        import random

        if self.strategy == RetryStrategy.FIXED:
            delay = self.base_delay
        elif self.strategy == RetryStrategy.LINEAR:
            delay = self.base_delay * attempt
        elif self.strategy == RetryStrategy.EXPONENTIAL:
            delay = self.base_delay * (self.backoff_factor**attempt)
        elif self.strategy == RetryStrategy.ADAPTIVE:
            delay = self.base_delay * (1.5**attempt)
        else:
            delay = self.base_delay

        delay = min(delay, self.max_delay)
        if self.jitter:
            delay = delay * (0.5 + random.random())
        return delay


@dataclass
class DownloadConfig:
    enable_chunking: bool = True
    auto_detect_range_support: bool = True
    fallback_to_single_on_failure: bool = True
    max_chunks: int = DEFAULT_MAX_CHUNKS
    min_chunks: int = DEFAULT_MIN_CHUNKS
    chunk_size: int = DEFAULT_CHUNK_SIZE
    min_chunk_size: int = DEFAULT_MIN_CHUNK_SIZE
    max_chunk_size: int = DEFAULT_MAX_CHUNK_SIZE
    buffer_size: int = DEFAULT_BUFFER_SIZE
    timeout: float = DEFAULT_TIMEOUT
    connect_timeout: float = DEFAULT_CONNECT_TIMEOUT
    read_timeout: float = DEFAULT_TIMEOUT
    write_timeout: float = DEFAULT_TIMEOUT
    progress_callback: Callable[..., Any] | None = None
    chunk_callback: Callable[..., Any] | None = None
    status_callback: Callable[[str, Any], None] | None = None
    resume: bool = True
    overwrite: bool = False
    speed_sample_window: int = DEFAULT_SPEED_SAMPLE_WINDOW
    enable_smart_resplit: bool = True
    resplit_threshold: float = DEFAULT_RESPLIT_THRESHOLD
    resplit_cooldown: float = DEFAULT_RESPLIT_COOLDOWN
    enable_adaptive: bool = True
    adaptive_interval: float = DEFAULT_ADAPTIVE_INTERVAL
    enable_hybrid_turbo: bool = True
    hybrid_target_chunk_time: float = DEFAULT_HYBRID_TARGET_CHUNK_TIME
    hybrid_aimd_increase_step: int = 1
    hybrid_aimd_decrease_factor: float = 0.5
    hybrid_speedup_threshold: float = DEFAULT_HYBRID_SPEEDUP_THRESHOLD
    hybrid_slow_chunk_ratio: float = DEFAULT_HYBRID_SLOW_CHUNK_RATIO
    hybrid_min_remaining_bytes: int = DEFAULT_HYBRID_MIN_REMAINING_BYTES
    hybrid_max_resplit_per_chunk: int = 2
    enable_predictive_scheduling: bool = True
    enable_connection_health_check: bool = True
    health_check_interval: float = 10.0
    verify_ssl: bool = True
    ssl_cert_path: str | None = None
    user_agent: str = "Little-Tree-Downloader/0.6.1"
    headers: dict[str, str] = field(default_factory=dict)
    auth: AuthConfig | None = None
    proxy: ProxyConfig | None = None
    speed_limit: SpeedLimitConfig | None = None
    retry: RetryConfig = field(default_factory=RetryConfig)
    follow_redirects: bool = True
    max_redirects: int = 10
    cookies: dict[str, str] | None = None
    cookie_file: str | None = None
    referer: str | None = None
    accept_ranges_fallback: bool = True
    temp_dir: str | None = None
    preserve_temp_on_failure: bool = False
    create_parent_dirs: bool = True
    file_permissions: int | None = None
    expected_hash: str | None = None
    hash_algorithm: str = "sha256"
    verify_hash: bool = False
    min_file_size: int | None = None
    max_file_size: int | None = None
    metadata_file: str | None = None
    enable_h2: bool = True
    connection_pool_size: int = 100
    keepalive_expiry: float = 30.0
    dns_cache_ttl: float = 300.0
    local_address: str | None = None
    interface: str | None = None
    log_level: str = "INFO"
    enable_progress_bar: bool = True
    progress_update_interval: float = 0.5

    def __post_init__(self) -> None:
        self._validate_chunk_constraints()
        self._validate_hybrid_parameters()
        self._ensure_proxy_initialized()

    def _validate_chunk_constraints(self) -> None:
        if self.max_chunks < self.min_chunks:
            self.max_chunks = self.min_chunks
        if self.chunk_size < self.min_chunk_size:
            self.chunk_size = self.min_chunk_size
        if self.chunk_size > self.max_chunk_size:
            self.chunk_size = self.max_chunk_size

    def _validate_hybrid_parameters(self) -> None:
        if self.resplit_threshold <= 0 or self.resplit_threshold >= 1:
            self.resplit_threshold = 0.5
        if self.hybrid_target_chunk_time <= 0:
            self.hybrid_target_chunk_time = DEFAULT_HYBRID_TARGET_CHUNK_TIME
        if self.hybrid_aimd_increase_step < 1:
            self.hybrid_aimd_increase_step = 1
        if self.hybrid_aimd_decrease_factor <= 0 or self.hybrid_aimd_decrease_factor >= 1:
            self.hybrid_aimd_decrease_factor = 0.5
        if self.hybrid_speedup_threshold <= 0:
            self.hybrid_speedup_threshold = DEFAULT_HYBRID_SPEEDUP_THRESHOLD
        if self.hybrid_slow_chunk_ratio <= 0 or self.hybrid_slow_chunk_ratio >= 1:
            self.hybrid_slow_chunk_ratio = DEFAULT_HYBRID_SLOW_CHUNK_RATIO
        if self.hybrid_min_remaining_bytes < 64 * 1024:
            self.hybrid_min_remaining_bytes = DEFAULT_HYBRID_MIN_REMAINING_BYTES
        if self.hybrid_max_resplit_per_chunk < 1:
            self.hybrid_max_resplit_per_chunk = 1

    def _ensure_proxy_initialized(self) -> None:
        if self.proxy is None:
            self.proxy = ProxyConfig()

    def apply_style(self, style: DownloadStyle | str) -> "DownloadConfig":
        """Apply a download style to configuration parameters."""
        style_name = getattr(style, "name", str(style)).upper()

        if style_name == "SINGLE":
            self.enable_chunking = False
            self.min_chunks = 1
            self.max_chunks = 1
            self.enable_adaptive = False
            self.enable_smart_resplit = False
            self.enable_hybrid_turbo = False
        elif style_name == "MULTI":
            self.enable_chunking = True
            self.min_chunks = max(2, self.min_chunks)
            self.enable_adaptive = False
            self.enable_smart_resplit = False
            self.enable_hybrid_turbo = False
        elif style_name == "ADAPTIVE":
            self.enable_chunking = True
            self.enable_adaptive = True
            self.enable_smart_resplit = True
            self.enable_hybrid_turbo = False
        elif style_name == "HYBRID_TURBO":
            self.enable_chunking = True
            self.enable_adaptive = True
            self.enable_smart_resplit = True
            self.enable_hybrid_turbo = True
            self.hybrid_slow_chunk_ratio = min(self.hybrid_slow_chunk_ratio, 0.45)
            self.hybrid_aimd_increase_step = max(1, self.hybrid_aimd_increase_step)
            self.hybrid_aimd_decrease_factor = max(0.1, min(0.9, self.hybrid_aimd_decrease_factor))
            self.adaptive_interval = min(self.adaptive_interval, 2.0)

        return self

    @property
    def speed_limit_bytes(self) -> int:
        if self.speed_limit and self.speed_limit.enabled:
            return self.speed_limit.max_speed
        return 0

    @speed_limit_bytes.setter
    def speed_limit_bytes(self, value: int) -> None:
        if value > 0:
            self.speed_limit = SpeedLimitConfig(enabled=True, max_speed=value)
        elif self.speed_limit:
            self.speed_limit.enabled = False

    def calculate_optimal_chunks(self, file_size: int, server_speed: float = 0) -> int:
        if not self.enable_chunking:
            return 1
        if file_size <= 0:
            return self.min_chunks
        chunks_by_size = file_size // self.min_chunk_size
        optimal = min(self.max_chunks, max(self.min_chunks, chunks_by_size))
        chunk_size = file_size // optimal if optimal > 0 else file_size
        while chunk_size > self.max_chunk_size and optimal < self.max_chunks:
            optimal += 1
            chunk_size = file_size // optimal
        while chunk_size < self.min_chunk_size and optimal > self.min_chunks:
            optimal -= 1
            chunk_size = file_size // optimal
        if server_speed > 0 and self.enable_adaptive:
            target_chunk_time = 2.0
            ideal_size = int(server_speed * target_chunk_time)
            if ideal_size > 0:
                adaptive_chunks = file_size // ideal_size
                optimal = max(self.min_chunks, min(self.max_chunks, adaptive_chunks, optimal))
        return optimal

    def calculate_chunk_range(
        self, file_size: int, chunk_index: int, total_chunks: int, downloaded: int = 0
    ) -> tuple[int, int]:
        if total_chunks <= 0:
            return (0, file_size)
        base_size = file_size // total_chunks
        remainder = file_size % total_chunks
        start = base_size * chunk_index + min(chunk_index, remainder)
        end = start + base_size + (1 if chunk_index < remainder else 0)
        start = max(start, downloaded)
        return (start, end)

    def get_headers(self, url: str | None = None) -> dict[str, str]:
        base_headers = {
            "User-Agent": self.user_agent,
            "Accept": "*/*",
            "Accept-Encoding": "identity",
            "Connection": "keep-alive",
        }
        base_headers.update(self.headers)
        if self.auth:
            auth_headers = self.auth.get_auth_headers()
            base_headers.update(auth_headers)
        if self.referer:
            base_headers["Referer"] = self.referer
        if url and self.cookies:
            from urllib.parse import urlparse

            urlparse(url)
            cookie_header = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
            base_headers["Cookie"] = cookie_header
        return base_headers

    def should_retry_status(self, status_code: int) -> bool:
        return status_code in self.retry.retry_on_status

    def get_proxy(self, url: str) -> str | None:
        if not self.proxy:
            return None
        return self.proxy.get_proxy_for_url(url)

    def to_dict(self) -> dict[str, Any]:
        return {
            "enable_chunking": self.enable_chunking,
            "max_chunks": self.max_chunks,
            "min_chunks": self.min_chunks,
            "chunk_size": self.chunk_size,
            "timeout": self.timeout,
            "connect_timeout": self.connect_timeout,
            "resume": self.resume,
            "verify_ssl": self.verify_ssl,
            "user_agent": self.user_agent,
            "enable_hybrid_turbo": self.enable_hybrid_turbo,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DownloadConfig":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class DownloadResult:
    success: bool
    file_path: str | None = None
    file_size: int = 0
    total_time: float = 0.0
    average_speed: float = 0.0
    peak_speed: float = 0.0
    total_chunks: int = 0
    chunks_completed: int = 0
    retries: int = 0
    error: str | None = None
    hash_verified: bool | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def formatted_size(self) -> str:
        from .utils import format_size

        return format_size(self.file_size)

    @property
    def formatted_speed(self) -> str:
        from .utils import format_speed

        return format_speed(self.average_speed)

    @property
    def formatted_time(self) -> str:
        from .utils import format_time

        return format_time(self.total_time)
