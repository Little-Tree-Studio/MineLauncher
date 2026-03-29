import asyncio
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx

from .config import DownloadConfig


@dataclass
class ServerCapabilities:
    supports_range_requests: bool = False
    supports_parallel_downloads: bool = False
    max_connections: int = 4
    content_length_available: bool = False
    content_length: int = -1
    accept_ranges: str | None = None
    etag: str | None = None
    last_modified: str | None = None
    content_type: str | None = None
    content_encoding: str | None = None
    server: str | None = None
    redirect_url: str | None = None
    requires_auth: bool = False
    auth_type: str | None = None
    chunk_coalescing: bool = False
    http_version: str = "HTTP/1.1"
    transfer_encoding: str | None = None
    connection_header: str | None = None
    detection_time: float = 0.0
    detection_errors: list[str] = field(default_factory=list)


@dataclass
class RangeTestResult:
    success: bool
    status_code: int
    content_range: str | None = None
    actual_bytes: int = 0
    expected_bytes: int = 0
    supports_parallel: bool = False


class ServerDetector:
    def __init__(self, config: DownloadConfig, client: httpx.AsyncClient) -> None:
        self.config = config
        self.client = client
        self._cache: dict[str, ServerCapabilities] = {}
        self._cache_ttl = 300.0

    async def detect_capabilities(self, url: str) -> ServerCapabilities:
        cache_key = self._get_cache_key(url)
        if cache_key in self._cache:
            cached = self._cache[cache_key]
            if time.time() - cached.detection_time < self._cache_ttl:
                return cached

        capabilities = ServerCapabilities()

        try:
            await self._probe_with_head(url, capabilities)
        except Exception as e:
            capabilities.detection_errors.append(f"HEAD probe failed: {e}")

        if self.config.auto_detect_range_support:
            try:
                await self._test_range_support(url, capabilities)
            except Exception as e:
                capabilities.detection_errors.append(f"Range test failed: {e}")

        if capabilities.content_length <= 0:
            try:
                await self._probe_content_length(url, capabilities)
            except Exception as e:
                capabilities.detection_errors.append(f"Content-Length probe failed: {e}")

        capabilities.detection_time = time.time()
        self._cache[cache_key] = capabilities

        return capabilities

    async def _probe_with_head(self, url: str, capabilities: ServerCapabilities) -> None:
        try:
            response = await self.client.head(
                url,
                headers=self.config.get_headers(url),
                follow_redirects=self.config.follow_redirects,
                timeout=self.config.connect_timeout,
            )

            self._parse_head_response(response, capabilities)

        except httpx.HTTPStatusError as e:
            if e.response.status_code in (401, 403):
                capabilities.requires_auth = True
                capabilities.auth_type = e.response.headers.get("WWW-Authenticate", "")
            raise

    def _parse_head_response(self, response: httpx.Response, capabilities: ServerCapabilities) -> None:
        headers = response.headers

        capabilities.server = headers.get("Server")

        accept_ranges = headers.get("Accept-Ranges", "").lower()
        capabilities.accept_ranges = accept_ranges
        capabilities.supports_range_requests = accept_ranges == "bytes"

        content_length = headers.get("Content-Length")
        if content_length:
            try:
                capabilities.content_length = int(content_length)
                capabilities.content_length_available = True
            except ValueError:
                pass

        capabilities.etag = headers.get("ETag")
        capabilities.last_modified = headers.get("Last-Modified")
        capabilities.content_type = headers.get("Content-Type")
        capabilities.content_encoding = headers.get("Content-Encoding")
        capabilities.transfer_encoding = headers.get("Transfer-Encoding")
        capabilities.connection_header = headers.get("Connection")

        if response.status_code in (301, 302, 303, 307, 308):
            capabilities.redirect_url = response.headers.get("Location")

        http_version = getattr(response, "http_version", "HTTP/1.1")
        capabilities.http_version = http_version if isinstance(http_version, str) else "HTTP/1.1"

        status = response.status_code
        if status in (401, 403):
            capabilities.requires_auth = True
            capabilities.auth_type = headers.get("WWW-Authenticate", "")

    async def _test_range_support(self, url: str, capabilities: ServerCapabilities) -> None:
        headers = self.config.get_headers(url)
        headers["Range"] = "bytes=0-1"

        try:
            response = await self.client.get(
                url,
                headers=headers,
                follow_redirects=self.config.follow_redirects,
                timeout=self.config.connect_timeout,
            )

            result = RangeTestResult(
                success=response.status_code == 206,
                status_code=response.status_code,
                content_range=response.headers.get("Content-Range"),
                actual_bytes=len(response.content),
                expected_bytes=2,
            )

            if result.success:
                capabilities.supports_range_requests = True

                parallel_result = await self._test_parallel_ranges(url, capabilities)
                capabilities.supports_parallel_downloads = parallel_result
                capabilities.max_connections = 8 if parallel_result else 2
            else:
                capabilities.supports_range_requests = False
                capabilities.supports_parallel_downloads = False

        except Exception:
            capabilities.supports_range_requests = False

    async def _test_parallel_ranges(self, url: str, capabilities: ServerCapabilities) -> bool:
        if capabilities.content_length <= 1024:
            return False

        headers1 = self.config.get_headers(url)
        headers1["Range"] = "bytes=0-0"

        headers2 = self.config.get_headers(url)
        headers2["Range"] = "bytes=1-1"

        try:
            tasks = [
                self.client.get(url, headers=headers1, timeout=self.config.connect_timeout),
                self.client.get(url, headers=headers2, timeout=self.config.connect_timeout),
            ]

            responses = await asyncio.gather(*tasks, return_exceptions=True)

            success_count = 0
            for resp in responses:
                if isinstance(resp, httpx.Response) and resp.status_code == 206:
                    success_count += 1

            return success_count == 2

        except Exception:
            return False

    async def _probe_content_length(self, url: str, capabilities: ServerCapabilities) -> None:
        try:
            headers = self.config.get_headers(url)
            headers["Range"] = "bytes=0-"

            response = await self.client.get(
                url,
                headers=headers,
                follow_redirects=self.config.follow_redirects,
                timeout=self.config.connect_timeout,
            )

            if response.status_code == 206:
                content_range = response.headers.get("Content-Range", "")
                if "/" in content_range:
                    total = content_range.split("/")[-1]
                    if total != "*":
                        try:
                            capabilities.content_length = int(total)
                            capabilities.content_length_available = True
                        except ValueError:
                            pass

            elif response.status_code == 200:
                content_length = response.headers.get("Content-Length")
                if content_length:
                    try:
                        capabilities.content_length = int(content_length)
                        capabilities.content_length_available = True
                    except ValueError:
                        pass

        except Exception:
            pass

    def _get_cache_key(self, url: str) -> str:
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

    def clear_cache(self) -> None:
        self._cache.clear()

    async def check_auth_required(self, url: str) -> tuple[bool, str | None]:
        try:
            response = await self.client.head(
                url,
                headers=self.config.get_headers(url),
                follow_redirects=True,
                timeout=self.config.connect_timeout,
            )

            if response.status_code in (401, 403):
                auth_header = response.headers.get("WWW-Authenticate", "")
                return True, auth_header
            return False, None

        except httpx.HTTPStatusError as e:
            if e.response.status_code in (401, 403):
                auth_header = e.response.headers.get("WWW-Authenticate", "")
                return True, auth_header
            return False, None
        except Exception:
            return False, None

    async def test_downloadability(self, url: str) -> dict[str, Any]:
        result: dict[str, Any] = {
            "accessible": False,
            "status_code": None,
            "content_length": -1,
            "supports_range": False,
            "error": None,
        }

        try:
            response = await self.client.head(
                url,
                headers=self.config.get_headers(url),
                follow_redirects=True,
                timeout=self.config.connect_timeout,
            )

            result["accessible"] = response.status_code < 400
            result["status_code"] = response.status_code

            content_length = response.headers.get("Content-Length")
            if content_length:
                result["content_length"] = int(content_length)

            accept_ranges = response.headers.get("Accept-Ranges", "").lower()
            result["supports_range"] = accept_ranges == "bytes"

        except httpx.HTTPStatusError as e:
            result["status_code"] = e.response.status_code
            result["error"] = f"HTTP {e.response.status_code}"
        except Exception as e:
            result["error"] = str(e)

        return result

    @staticmethod
    def get_optimal_chunk_count(
        capabilities: ServerCapabilities,
        file_size: int,
        config: DownloadConfig,
    ) -> int:
        if not capabilities.supports_range_requests:
            return 1

        if capabilities.max_connections < config.max_chunks:
            max_allowed = capabilities.max_connections
        else:
            max_allowed = config.max_chunks

        if file_size <= 0:
            return config.min_chunks

        if capabilities.supports_parallel_downloads:
            by_file_size = max(1, file_size // config.min_chunk_size)
            return min(max_allowed, max(config.min_chunks, by_file_size))
        else:
            return config.min_chunks
