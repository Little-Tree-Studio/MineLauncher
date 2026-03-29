import asyncio
import contextlib
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiofiles
import httpx

from .chunk import Chunk
from .config import DownloadConfig
from .exceptions import (
    ChunkDownloadError,
    ConnectionError,
    ForbiddenError,
    HTTPError,
    ResourceNotFoundError,
    TimeoutError,
)
from .utils import generate_temp_filename


@dataclass
class WorkerStats:
    worker_id: str
    chunks_completed: int = 0
    bytes_downloaded: int = 0
    errors: int = 0
    current_chunk: int | None = None
    current_speed: float = 0.0
    start_time: float | None = None
    is_active: bool = False
    last_error: str | None = None


class DownloadWorker:
    def __init__(
        self,
        worker_id: str,
        client: httpx.AsyncClient,
        config: DownloadConfig,
        chunk_complete_callback: Any = None,
        chunk_error_callback: Any = None,
        progress_callback: Any = None,
    ) -> None:
        self.worker_id = worker_id
        self.client = client
        self.config = config
        self.chunk_complete_callback = chunk_complete_callback
        self.chunk_error_callback = chunk_error_callback
        self.progress_callback = progress_callback
        self._current_chunk: Chunk | None = None
        self._running = False
        self._paused = False
        self._stats = WorkerStats(worker_id=worker_id)
        self._last_progress_time: float = 0.0
        self._last_progress_bytes: int = 0

    @property
    def stats(self) -> WorkerStats:
        return self._stats

    @property
    def is_active(self) -> bool:
        return self._running and self._current_chunk is not None

    async def download_chunk(
        self,
        chunk: Chunk,
        url: str,
        temp_dir: Path,
    ) -> Path:
        self._current_chunk = chunk
        self._stats.is_active = True
        self._stats.current_chunk = chunk.index
        self._stats.start_time = time.time()
        self._last_progress_time = time.time()
        self._last_progress_bytes = chunk.downloaded

        chunk.start_download(self.worker_id)
        temp_file = temp_dir / generate_temp_filename(chunk.chunk_id, chunk.index)
        chunk.temp_file = str(temp_file)

        try:
            result = await self._download_with_retry(
                chunk=chunk,
                url=url,
                temp_file=temp_file,
            )
            self._stats.chunks_completed += 1
            if self.chunk_complete_callback:
                await self.chunk_complete_callback(chunk.index)
            return result
        except Exception as e:
            self._stats.errors += 1
            self._stats.last_error = str(e)
            if self.chunk_error_callback:
                await self.chunk_error_callback(chunk.index, str(e))
            chunk.fail(str(e))
            raise
        finally:
            self._current_chunk = None
            self._stats.is_active = False
            self._stats.current_chunk = None

    async def _download_with_retry(
        self,
        chunk: Chunk,
        url: str,
        temp_file: Path,
    ) -> Path:
        last_error: Exception | None = None
        retry_config = self.config.retry

        for attempt in range(retry_config.max_retries):
            try:
                return await self._download_chunk_attempt(
                    chunk=chunk,
                    url=url,
                    temp_file=temp_file,
                    attempt=attempt,
                )
            except (TimeoutError, ConnectionError) as e:
                last_error = e
                delay = retry_config.calculate_delay(attempt)
                await asyncio.sleep(delay)
            except (ResourceNotFoundError, ForbiddenError):
                raise
            except Exception as e:
                last_error = e
                chunk.error_count += 1
                if chunk.error_count >= retry_config.max_retries:
                    raise
                delay = retry_config.calculate_delay(attempt)
                await asyncio.sleep(delay)

        raise ChunkDownloadError(
            chunk.index,
            url,
            last_error or Exception("Unknown error"),
        )

    async def _download_chunk_attempt(
        self,
        chunk: Chunk,
        url: str,
        temp_file: Path,
        attempt: int,
    ) -> Path:
        headers = self.config.get_headers()
        start_byte = chunk.start_byte + chunk.downloaded
        end_byte = chunk.end_byte - 1

        if start_byte > 0 or end_byte > 0:
            headers["Range"] = f"bytes={start_byte}-{end_byte}"

        timeout = httpx.Timeout(
            connect=self.config.connect_timeout,
            read=self.config.timeout,
            write=self.config.timeout,
            pool=self.config.connect_timeout,
        )

        try:
            async with self.client.stream(
                "GET",
                url,
                headers=headers,
                timeout=timeout,
                follow_redirects=True,
            ) as response:
                self._validate_response(response, url, attempt > 0)

                mode = "ab" if chunk.downloaded > 0 and attempt == 0 else "wb"
                if mode == "wb":
                    chunk.downloaded = 0

                temp_file.parent.mkdir(parents=True, exist_ok=True)

                async with aiofiles.open(temp_file, mode) as f:
                    async for data in response.aiter_bytes(chunk_size=self.config.buffer_size):
                        if self._paused:
                            await self._wait_for_resume()

                        if not data:
                            continue

                        await f.write(data)
                        bytes_written = len(data)
                        chunk.update_progress(bytes_written)
                        self._stats.bytes_downloaded += bytes_written
                        self._update_speed(bytes_written)

                        if self.progress_callback:
                            await self._notify_progress(chunk)

                chunk.complete()
                return temp_file

        except httpx.TimeoutException as e:
            raise TimeoutError(
                f"Request timed out: {e}",
                url,
                e,
            ) from None
        except httpx.ConnectError as e:
            raise ConnectionError(
                f"Connection failed: {e}",
                url,
                e,
            ) from None
        except httpx.HTTPStatusError as e:
            self._handle_http_error(e, url)
            raise ConnectionError(f"HTTP error: {e}", url, e) from None

    def _validate_response(
        self,
        response: httpx.Response,
        url: str,
        is_retry: bool,
    ) -> None:
        status = response.status_code

        if status == 404:
            raise ResourceNotFoundError(url)
        if status == 403:
            raise ForbiddenError(url)
        if status >= 400:
            raise HTTPError(f"HTTP {status}", status, url)

        if is_retry and status == 200:
            pass
        elif self._current_chunk and self._current_chunk.downloaded > 0 and status != 206:
            raise HTTPError(
                f"Expected 206 Partial Content, got {status}",
                status,
                url,
            )

    def _handle_http_error(self, error: httpx.HTTPStatusError, url: str) -> None:
        status = error.response.status_code
        if status == 404:
            raise ResourceNotFoundError(url)
        if status == 403:
            raise ForbiddenError(url)
        raise HTTPError(f"HTTP {status}", status, url)

    def _update_speed(self, bytes_downloaded: int) -> None:
        now = time.time()
        time_diff = now - self._last_progress_time
        if time_diff >= 1.0:
            bytes_diff = self._stats.bytes_downloaded - self._last_progress_bytes
            self._stats.current_speed = bytes_diff / time_diff
            self._last_progress_time = now
            self._last_progress_bytes = self._stats.bytes_downloaded

    async def _notify_progress(self, chunk: Chunk) -> None:
        if not self.progress_callback:
            return
        with contextlib.suppress(Exception):
            await self.progress_callback(chunk.index, chunk.downloaded, chunk.size)

    async def _wait_for_resume(self) -> None:
        while self._paused:
            await asyncio.sleep(0.1)

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    def cancel(self) -> None:
        self._running = False
        self._paused = False


class WorkerPool:
    def __init__(
        self,
        max_workers: int,
        client: httpx.AsyncClient,
        config: DownloadConfig,
    ) -> None:
        self.max_workers = max_workers
        self.client = client
        self.config = config
        self._workers: dict[str, DownloadWorker] = {}
        self._worker_id_counter = 0
        self._lock = asyncio.Lock()

    @property
    def active_count(self) -> int:
        return sum(1 for w in self._workers.values() if w.is_active)

    @property
    def total_stats(self) -> dict[str, Any]:
        completed = sum(w.stats.chunks_completed for w in self._workers.values())
        downloaded = sum(w.stats.bytes_downloaded for w in self._workers.values())
        errors = sum(w.stats.errors for w in self._workers.values())
        return {
            "workers_active": self.active_count,
            "workers_total": len(self._workers),
            "chunks_completed": completed,
            "bytes_downloaded": downloaded,
            "total_errors": errors,
        }

    async def create_worker(
        self,
        chunk_complete_callback: Any = None,
        chunk_error_callback: Any = None,
        progress_callback: Any = None,
    ) -> DownloadWorker:
        async with self._lock:
            self._worker_id_counter += 1
            worker_id = f"worker_{self._worker_id_counter}"
            worker = DownloadWorker(
                worker_id=worker_id,
                client=self.client,
                config=self.config,
                chunk_complete_callback=chunk_complete_callback,
                chunk_error_callback=chunk_error_callback,
                progress_callback=progress_callback,
            )
            self._workers[worker_id] = worker
            return worker

    async def remove_worker(self, worker_id: str) -> None:
        async with self._lock:
            if worker_id in self._workers:
                del self._workers[worker_id]

    def get_worker(self, worker_id: str) -> DownloadWorker | None:
        return self._workers.get(worker_id)

    def pause_all(self) -> None:
        for worker in self._workers.values():
            worker.pause()

    def resume_all(self) -> None:
        for worker in self._workers.values():
            worker.resume()

    def cancel_all(self) -> None:
        for worker in self._workers.values():
            worker.cancel()

    def get_all_stats(self) -> list[WorkerStats]:
        return [w.stats for w in self._workers.values()]
