import asyncio
import ssl
from typing import Any

import httpx

from .config import DownloadConfig
from .proxy import ProxyManager


class ConnectionPool:
    def __init__(self, config: DownloadConfig, proxy_manager: ProxyManager | None = None) -> None:
        self.config = config
        self.proxy_manager = proxy_manager
        self._client: httpx.AsyncClient | None = None
        self._connection_count: int = 0
        self._max_connections: int = config.connection_pool_size or config.max_chunks * 2

    @property
    def client(self) -> httpx.AsyncClient | None:
        return self._client

    @property
    def connection_count(self) -> int:
        return self._connection_count

    async def initialize(self, url: str | None = None) -> httpx.AsyncClient:
        if self._client:
            return self._client

        # 优化连接池配置：HTTP/2 场景下允许更高的并发流数
        max_conn = self._max_connections
        if self.config.enable_h2:
            # HTTP/2 可以多路复用，允许更多并发连接
            max_conn = max(max_conn, 100)

        limits = httpx.Limits(
            max_keepalive_connections=max_conn,
            max_connections=max_conn * 2 if self.config.enable_h2 else max_conn,
            keepalive_expiry=max(60.0, self.config.keepalive_expiry),  # 至少保持60秒
        )

        timeout = httpx.Timeout(
            connect=self.config.connect_timeout,
            read=self.config.read_timeout,
            write=self.config.write_timeout,
            pool=self.config.connect_timeout,
        )

        verify: bool | ssl.SSLContext = self.config.verify_ssl
        if self.config.verify_ssl and self.config.ssl_cert_path:
            verify = ssl.create_default_context(cafile=self.config.ssl_cert_path)
        elif self.config.verify_ssl:
            verify = ssl.create_default_context()

        proxy: str | None = None
        if self.proxy_manager:
            proxy = await self.proxy_manager.get_proxy_with_pac(url) if url else self.proxy_manager.get_proxy(url or "")
        elif self.config.proxy:
            proxy = self.config.get_proxy(url or "")

        http2_enabled = self.config.enable_h2

        # 配置传输层：添加连接池重试和 HTTP/2 支持
        transport = httpx.AsyncHTTPTransport(
            retries=2,  # 连接层重试，提高稳定性
            http2=http2_enabled,
            limits=limits,
        )

        self._client = httpx.AsyncClient(
            limits=limits,
            timeout=timeout,
            verify=verify,
            proxy=proxy,
            transport=transport,
            follow_redirects=self.config.follow_redirects,
            max_redirects=self.config.max_redirects,
            headers=self.config.get_headers(url),
        )

        return self._client

    async def preconnect(self, urls: list[str]) -> None:
        """预连接到多个 URL，建立 HTTP/2 连接并预热TLS

        Args:
            urls: 需要预连接的 URL 列表
        """
        if not self._client:
            return

        from urllib.parse import urlparse

        async def _preconnect_one(url: str) -> None:
            try:
                async with self._client.stream(
                    "GET",
                    url,
                    headers={"Range": "bytes=0-0"},
                    timeout=httpx.Timeout(
                        connect=5.0,
                        read=5.0,
                        write=5.0,
                        pool=5.0,
                    ),
                ) as _:
                    pass
            except Exception:
                pass

        tasks = []
        for url in urls:
            parsed = urlparse(url)
            if not parsed.scheme or not parsed.netloc:
                continue

            if not parsed.hostname:
                continue

            tasks.append(asyncio.create_task(_preconnect_one(url)))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    def increment_connection(self) -> None:
        self._connection_count += 1

    def decrement_connection(self) -> None:
        self._connection_count = max(0, self._connection_count - 1)

    def is_at_capacity(self) -> bool:
        return self._connection_count >= self._max_connections

    def get_available_slots(self) -> int:
        return max(0, self._max_connections - self._connection_count)


class ConnectionHealth:
    def __init__(self) -> None:
        self._latencies: list[float] = []
        self._errors: int = 0
        self._successful_requests: int = 0
        self._last_error_time: float = 0.0
        self._window_size: int = 20

    def record_latency(self, latency: float) -> None:
        self._latencies.append(latency)
        if len(self._latencies) > self._window_size:
            self._latencies.pop(0)

    def record_success(self) -> None:
        self._successful_requests += 1

    def record_error(self) -> None:
        import time

        self._errors += 1
        self._last_error_time = time.time()

    def get_average_latency(self) -> float:
        if not self._latencies:
            return 0.0
        return sum(self._latencies) / len(self._latencies)

    def get_error_rate(self) -> float:
        total = self._errors + self._successful_requests
        if total == 0:
            return 0.0
        return self._errors / total

    def is_healthy(self) -> bool:
        error_rate = self.get_error_rate()
        if error_rate > 0.5:
            return False
        avg_latency = self.get_average_latency()
        return avg_latency <= 10.0

    def should_backoff(self) -> bool:
        import time

        if self._errors >= 3:
            if time.time() - self._last_error_time < 30:
                return True
            self._errors = 0
        return False

    def reset(self) -> None:
        self._latencies.clear()
        self._errors = 0
        self._successful_requests = 0


class URLHandler:
    @staticmethod
    def parse_url(url: str) -> dict[str, Any]:
        from urllib.parse import parse_qs, urlparse

        parsed = urlparse(url)
        return {
            "scheme": parsed.scheme,
            "netloc": parsed.netloc,
            "path": parsed.path,
            "params": parsed.params,
            "query": parsed.query,
            "fragment": parsed.fragment,
            "query_params": parse_qs(parsed.query),
        }

    @staticmethod
    def is_valid_url(url: str) -> bool:
        from urllib.parse import urlparse

        try:
            parsed = urlparse(url)
            return bool(parsed.scheme in ("http", "https") and parsed.netloc)
        except Exception:
            return False

    @staticmethod
    def normalize_url(url: str) -> str:
        url = url.strip()
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"
        return url

    @staticmethod
    def extract_domain(url: str) -> str | None:
        from urllib.parse import urlparse

        try:
            parsed = urlparse(url)
            return parsed.netloc
        except Exception:
            return None


class RequestBuilder:
    def __init__(self, config: DownloadConfig) -> None:
        self.config = config

    def build_headers(
        self,
        url: str | None = None,
        range_start: int | None = None,
        range_end: int | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, str]:
        headers = self.config.get_headers(url)

        if range_start is not None:
            if range_end is not None:
                headers["Range"] = f"bytes={range_start}-{range_end}"
            else:
                headers["Range"] = f"bytes={range_start}-"

        if extra_headers:
            headers.update(extra_headers)

        return headers

    def build_head_request(self, url: str) -> dict[str, Any]:
        return {
            "method": "HEAD",
            "url": url,
            "headers": self.config.get_headers(url),
            "follow_redirects": self.config.follow_redirects,
        }

    def build_range_request(
        self,
        url: str,
        start: int,
        end: int | None = None,
    ) -> dict[str, Any]:
        return {
            "method": "GET",
            "url": url,
            "headers": self.build_headers(url, range_start=start, range_end=end),
            "follow_redirects": self.config.follow_redirects,
        }
