import asyncio
import contextlib
import hashlib
import inspect
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiofiles
import httpx
from loguru import logger

from .chunk import Chunk, ChunkManager
from .config import DownloadConfig
from .connection import ConnectionPool, RequestBuilder
from .exceptions import CancelledError, ConfigurationError, DownloadError, HTTPError, ResourceNotFoundError
from .limiter import SpeedLimiter
from .monitor import DownloadMonitor
from .resume import ResumeManager
from .scheduler import SmartScheduler
from .utils import generate_download_id, normalize_url, resolve_download_path, safe_filename, validate_url
from .writer import BufferedFileWriter


@dataclass(frozen=True)
class ProgressEvent:
    downloaded: int
    total: int
    speed: float
    eta: int
    progress: float
    remaining: int
    timestamp: float
    unknown_size: bool = False


@dataclass(frozen=True)
class ChunkEvent:
    chunk_index: int
    status: str
    downloaded: int
    total: int
    progress: float
    speed: float
    error: str | None
    timestamp: float


CallbackMode = str
CALLBACK_MODE_NONE = "none"
CALLBACK_MODE_LEGACY = "legacy"
CALLBACK_MODE_KWARGS = "kwargs"
CALLBACK_MODE_DICT = "dict"
CALLBACK_MODE_EVENT = "event"


def _detect_callback_mode(callback: Callable[..., Any] | None) -> CallbackMode:
    """Detect the callback signature style to normalize invocation."""
    if callback is None:
        return CALLBACK_MODE_NONE

    try:
        sig = inspect.signature(callback)
    except (TypeError, ValueError):
        return CALLBACK_MODE_LEGACY

    params = list(sig.parameters.values())
    if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params):
        return CALLBACK_MODE_KWARGS
    if any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params):
        return CALLBACK_MODE_LEGACY

    positional = [
        p for p in params if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]

    if len(positional) >= 4:
        return CALLBACK_MODE_LEGACY
    if len(positional) == 1:
        name = positional[0].name.lower()
        if name in {"data", "payload", "info", "state", "stats"}:
            return CALLBACK_MODE_DICT
        return CALLBACK_MODE_EVENT
    if len(positional) == 0:
        return CALLBACK_MODE_KWARGS

    return CALLBACK_MODE_LEGACY


class ProgressCallbackAdapter:
    """Normalize different callback styles into one internal path."""

    def __init__(self, callback: Callable[..., Any] | None) -> None:
        self._callback = callback
        self._mode = _detect_callback_mode(callback)

    async def emit(self, downloaded: int, total: int, speed: float, eta: int, unknown_size: bool = False) -> None:
        if self._callback is None:
            return

        total_for_calc = max(total, 0) if not unknown_size else 0
        progress = (downloaded / total_for_calc) * 100 if total_for_calc > 0 else -1.0
        event = ProgressEvent(
            downloaded=downloaded,
            total=total,
            speed=speed,
            eta=eta,
            progress=progress,
            remaining=max(total_for_calc - downloaded, 0),
            timestamp=time.time(),
            unknown_size=unknown_size,
        )
        payload = {
            "downloaded": event.downloaded,
            "total": event.total,
            "speed": event.speed,
            "eta": event.eta,
            "progress": event.progress,
            "remaining": event.remaining,
            "timestamp": event.timestamp,
            "unknown_size": event.unknown_size,
        }

        result: Any
        if self._mode == CALLBACK_MODE_EVENT:
            result = self._callback(event)
        elif self._mode == CALLBACK_MODE_DICT:
            result = self._callback(payload)
        elif self._mode == CALLBACK_MODE_KWARGS:
            result = self._callback(**payload)
        else:
            result = self._callback(event.downloaded, event.total, event.speed, event.eta)

        if inspect.isawaitable(result):
            await result

    def __call__(self, downloaded: int, total: int, speed: float, eta: int, unknown_size: bool = False) -> Any:
        return self.emit(downloaded, total, speed, eta, unknown_size)


class ChunkCallbackAdapter:
    """Normalize chunk callback styles into one internal path."""

    def __init__(self, callback: Callable[..., Any] | None) -> None:
        self._callback = callback
        self._mode = _detect_callback_mode(callback)

    async def emit(self, chunk: Chunk, status: str, speed: float = 0.0, error: str | None = None) -> None:
        if self._callback is None:
            return

        total = max(chunk.size, 0)
        downloaded = chunk.downloaded
        progress = (downloaded / total) * 100 if total > 0 else 0.0
        event = ChunkEvent(
            chunk_index=chunk.index,
            status=status,
            downloaded=downloaded,
            total=total,
            progress=progress,
            speed=speed,
            error=error,
            timestamp=time.time(),
        )
        payload = {
            "chunk_index": event.chunk_index,
            "status": event.status,
            "downloaded": event.downloaded,
            "total": event.total,
            "progress": event.progress,
            "speed": event.speed,
            "error": event.error,
            "timestamp": event.timestamp,
        }

        result: Any
        if self._mode == CALLBACK_MODE_EVENT:
            result = self._callback(event)
        elif self._mode == CALLBACK_MODE_DICT:
            result = self._callback(payload)
        elif self._mode == CALLBACK_MODE_KWARGS:
            result = self._callback(**payload)
        else:
            result = self._callback(
                event.chunk_index,
                event.status,
                event.downloaded,
                event.total,
                event.progress,
                event.speed,
                event.error,
            )

        if inspect.isawaitable(result):
            await result


class H2MultiPlexDownloader:
    def __init__(
        self,
        client: httpx.AsyncClient,
        config: DownloadConfig,
        output_path: Path,
        should_pause: Callable[[], bool] | None = None,
        should_cancel: Callable[[], bool] | None = None,
        bytes_callback: Callable[[int], None] | None = None,
        chunk_callback: ChunkCallbackAdapter | None = None,
    ) -> None:
        self.client = client
        self.config = config
        self.output_path = output_path
        self.writer = BufferedFileWriter(
            output_path,
            "r+b" if output_path.exists() else "wb",
            buffer_size=getattr(config, "buffer_size", 1024 * 1024),
            flush_interval=0.5,
            max_buffers=16,
        )
        self._download_speed = 0.0
        self._bytes_downloaded = 0
        self._start_time = 0.0
        self._should_pause = should_pause
        self._should_cancel = should_cancel
        self._bytes_callback = bytes_callback
        self._chunk_callback = chunk_callback
        self._last_progress_emit: float = 0.0
        self._progress_interval = max(0.1, float(self.config.progress_update_interval))
        self._last_chunk_emit: dict[int, float] = {}
        # 初始化速度限制器
        self._speed_limiter = None
        if config.speed_limit and config.speed_limit.enabled:
            self._speed_limiter = SpeedLimiter(config.speed_limit)

    async def download_chunk(
        self,
        chunk: Chunk,
        url: str,
        progress_callback: Callable[[int, int, float, int], None] | None = None,
    ) -> None:
        headers = self.config.get_headers()
        headers["Range"] = f"bytes={chunk.start_byte}-{chunk.end_byte - 1}"

        timeout = httpx.Timeout(
            connect=self.config.connect_timeout,
            read=self.config.read_timeout,
            write=self.config.write_timeout,
            pool=self.config.connect_timeout,
        )

        start_time = time.time()
        bytes_in_chunk = 0

        try:
            if self._chunk_callback:
                await self._chunk_callback.emit(chunk, "started", speed=0.0)

            async with self.client.stream(
                "GET",
                url,
                headers=headers,
                timeout=timeout,
                follow_redirects=True,
            ) as response:
                if response.status_code == 416:
                    return

                if response.status_code not in (200, 206):
                    raise HTTPError(f"HTTP {response.status_code}", response.status_code, url)

                async for data in response.aiter_bytes(chunk_size=self.config.buffer_size):
                    if not data:
                        continue

                    if self._should_cancel and self._should_cancel():
                        raise CancelledError("Download was cancelled", url)

                    while self._should_pause and self._should_pause():
                        await asyncio.sleep(0.1)

                    # 应用速度限制
                    if self._speed_limiter:
                        await self._speed_limiter.acquire(len(data))

                    await self.writer.write_at(chunk.start_byte + chunk.downloaded, data)
                    chunk.update_progress(len(data))
                    bytes_in_chunk += len(data)

                    if self._bytes_callback:
                        self._bytes_callback(len(data))

                    elapsed = time.time() - start_time
                    if elapsed > 0:
                        self._download_speed = bytes_in_chunk / elapsed

                    now = time.time()
                    if (
                        progress_callback
                        and self.config
                        and (now - self._last_progress_emit) >= self._progress_interval
                    ):
                        self._last_progress_emit = now
                        progress_callback(
                            chunk.start_byte + chunk.downloaded,
                            chunk.total_size,
                            self._download_speed,
                            0,
                        )

                    if self._chunk_callback:
                        last_chunk_emit = self._last_chunk_emit.get(chunk.index, 0.0)
                        if (now - last_chunk_emit) >= self._progress_interval:
                            self._last_chunk_emit[chunk.index] = now
                            await self._chunk_callback.emit(
                                chunk,
                                "downloading",
                                speed=self._download_speed,
                            )

                chunk.complete()
                if self._chunk_callback:
                    await self._chunk_callback.emit(chunk, "completed", speed=self._download_speed)

        except CancelledError:
            chunk.fail("Download cancelled")
            if self._chunk_callback:
                await self._chunk_callback.emit(chunk, "failed", speed=self._download_speed, error="Download cancelled")
            raise
        except httpx.HTTPError as e:
            chunk.fail(str(e))
            if self._chunk_callback:
                await self._chunk_callback.emit(chunk, "failed", speed=self._download_speed, error=str(e))
            raise
        except OSError as e:
            chunk.fail(str(e))
            if self._chunk_callback:
                await self._chunk_callback.emit(chunk, "failed", speed=self._download_speed, error=str(e))
            raise
        except Exception as e:
            chunk.fail(str(e))
            if self._chunk_callback:
                await self._chunk_callback.emit(chunk, "failed", speed=self._download_speed, error=str(e))
            raise


class Downloader:
    def __init__(self, config: DownloadConfig | None = None) -> None:
        self.config = config or DownloadConfig()
        self._connection_pool: ConnectionPool | None = None
        self._monitor: DownloadMonitor | None = None
        self._scheduler: SmartScheduler | None = None
        self._chunk_manager: ChunkManager | None = None
        self._resume_manager: ResumeManager | None = None
        self._running = False
        self._paused = False
        self._cancelled = False
        self._lock = asyncio.Lock()
        self._h2_downloader: H2MultiPlexDownloader | None = None

    def set_connection_pool(self, pool: ConnectionPool) -> None:
        self._connection_pool = pool

    async def download(
        self,
        url: str,
        save_path: str | Path = "./downloads",
        filename: str | None = None,
        resume: bool | None = None,
        progress_callback: Callable[..., Any] | None = None,
        chunk_callback: Callable[..., Any] | None = None,
    ) -> Path:
        url = normalize_url(url)
        if not validate_url(url):
            raise DownloadError(f"Invalid URL: {url}", url)

        save_path = Path(save_path).expanduser().resolve()
        if resume is None:
            resume = self.config.resume

        self._running = True
        self._cancelled = False
        callback_adapter = ProgressCallbackAdapter(progress_callback or self.config.progress_callback)
        chunk_callback_adapter = ChunkCallbackAdapter(chunk_callback or self.config.chunk_callback)

        try:
            self._connection_pool = ConnectionPool(self.config)
            client = await self._connection_pool.initialize()

            file_info = await self._probe_file_info(client, url)

            file_size = file_info["size"]
            supports_range = file_info["supports_range"]
            suggested_filename = file_info.get("filename") or "download.bin"
            self._validate_file_size_constraints(file_size)

            final_filename = filename or suggested_filename
            final_filename = safe_filename(final_filename, "download.bin")
            save_path, final_path = resolve_download_path(
                save_path, final_filename, save_path if save_path.is_dir() else None
            )

            if final_path.exists() and not resume and not self.config.overwrite:
                logger.info(f"File already exists: {final_path}")
                return final_path

            download_id = generate_download_id(url)
            temp_dir = Path(self.config.temp_dir).expanduser().resolve() if self.config.temp_dir else final_path.parent

            self._resume_manager = ResumeManager(temp_dir, download_id)

            if resume:
                try:
                    metadata = await self._resume_manager.load()
                    if metadata and self._resume_manager.can_resume():
                        file_size = metadata.file_size
                        supports_range = metadata.supports_range
                except Exception:
                    pass

            self._resume_manager.initialize(
                url=url,
                file_size=file_size,
                filename=final_filename,
                supports_range=supports_range,
                etag=file_info.get("etag"),
                last_modified=file_info.get("last_modified"),
                content_type=file_info.get("content_type"),
            )

            use_chunking = self.config.enable_chunking and supports_range and file_size > 0

            if not use_chunking:
                output = await self._download_single_stream(
                    client=client,
                    url=url,
                    output_path=final_path,
                    progress_callback=callback_adapter,
                )
                await self._verify_downloaded_file(output)
                return output

            try:
                output = await self._download_chunked_direct(
                    client=client,
                    url=url,
                    output_path=final_path,
                    file_size=file_size,
                    progress_callback=callback_adapter,
                    chunk_callback=chunk_callback_adapter,
                )
            except DownloadError:
                if not self.config.fallback_to_single_on_failure:
                    raise
                logger.warning("Chunked download failed, falling back to single-stream mode")
                output = await self._download_single_stream(
                    client=client,
                    url=url,
                    output_path=final_path,
                    progress_callback=callback_adapter,
                )

            await self._verify_downloaded_file(output)
            return output

        except asyncio.CancelledError:
            logger.warning("Download cancelled")
            raise CancelledError("Download was cancelled", url) from None
        except Exception as e:
            logger.error(f"Download failed: {e}")
            raise
        finally:
            await self._cleanup()

    async def _probe_file_info(self, client: httpx.AsyncClient, url: str) -> dict[str, Any]:
        builder = RequestBuilder(self.config)
        request_config = builder.build_head_request(url)

        try:
            response = await client.head(
                request_config["url"],
                headers=request_config["headers"],
                follow_redirects=request_config["follow_redirects"],
            )
        except httpx.HTTPError as e:
            status_code = getattr(getattr(e, "response", None), "status_code", None)
            if status_code == 404:
                raise ResourceNotFoundError(url) from None
            if status_code is not None:
                raise HTTPError(f"HTTP {status_code}", status_code, url) from None
            raise

        if response.status_code == 404:
            raise ResourceNotFoundError(url)
        if response.status_code >= 400:
            raise HTTPError(f"HTTP {response.status_code}", response.status_code, url)

        headers = response.headers
        accept_ranges = headers.get("Accept-Ranges", "").lower()
        supports_range = accept_ranges == "bytes"

        content_length = headers.get("Content-Length")
        file_size = int(content_length) if content_length else -1

        content_disposition = headers.get("Content-Disposition")
        content_type = headers.get("Content-Type")
        etag = headers.get("ETag")
        last_modified = headers.get("Last-Modified")

        filename = None
        if content_disposition:
            from .utils import parse_content_disposition

            filename = parse_content_disposition(content_disposition)
        if not filename:
            from .utils import extract_filename_from_url

            filename = extract_filename_from_url(url)

        if not filename and not supports_range:
            supports_range = await self._test_range_support(client, url)

        return {
            "size": file_size,
            "supports_range": supports_range,
            "filename": filename,
            "content_type": content_type,
            "etag": etag,
            "last_modified": last_modified,
        }

    async def _test_range_support(self, client: httpx.AsyncClient, url: str) -> bool:
        headers = self.config.get_headers()
        headers["Range"] = "bytes=0-0"

        try:
            response = await client.get(
                url,
                headers=headers,
                follow_redirects=True,
            )
            return response.status_code == 206
        except Exception:
            return False

    async def _download_single_stream(
        self,
        client: httpx.AsyncClient,
        url: str,
        output_path: Path,
        progress_callback: ProgressCallbackAdapter | None,
    ) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = output_path.with_suffix(output_path.suffix + ".tmp")

        downloaded = 0
        start_time = time.time()

        async with client.stream("GET", url, follow_redirects=True) as response:
            if response.status_code == 404:
                raise ResourceNotFoundError(url)
            if response.status_code >= 400:
                raise HTTPError(f"HTTP {response.status_code}", response.status_code, url)

            content_length = response.headers.get("Content-Length")
            total_size = int(content_length) if content_length else -1

            async with aiofiles.open(temp_path, "wb") as f:
                async for chunk_data in response.aiter_bytes(chunk_size=self.config.buffer_size):
                    if self._cancelled:
                        raise CancelledError("Download cancelled", url)
                    if self._paused:
                        await self._wait_for_resume()

                    await f.write(chunk_data)
                    downloaded += len(chunk_data)

                    if progress_callback:
                        elapsed = time.time() - start_time
                        speed = downloaded / elapsed if elapsed > 0 else 0
                        if total_size > 0:
                            eta = (total_size - downloaded) / speed if speed > 0 else -1
                            await progress_callback.emit(downloaded, total_size, speed, int(eta), unknown_size=False)
                        else:
                            await progress_callback.emit(downloaded, -1, speed, -1, unknown_size=True)

        with contextlib.suppress(Exception):
            temp_path.rename(output_path)

        return output_path

    async def _download_chunked_direct(
        self,
        client: httpx.AsyncClient,
        url: str,
        output_path: Path,
        file_size: int,
        progress_callback: ProgressCallbackAdapter | None,
        chunk_callback: ChunkCallbackAdapter | None,
    ) -> Path:
        self._chunk_manager = ChunkManager(
            file_size=file_size,
            max_chunks=self.config.max_chunks,
            min_chunk_size=self.config.min_chunk_size,
        )

        existing_progress = self._resume_manager.get_progress_dict() if self._resume_manager else {}
        self._chunk_manager.initialize_chunks(existing_progress)

        self._monitor = DownloadMonitor(
            total_size=file_size,
            update_interval=0.5,
            progress_callback=progress_callback,
        )

        self._h2_downloader = H2MultiPlexDownloader(
            client,
            self.config,
            output_path,
            should_pause=lambda: self._paused,
            should_cancel=lambda: self._cancelled,
            bytes_callback=lambda size: self._monitor.increment_downloaded(size) if self._monitor else None,
            chunk_callback=chunk_callback,
        )
        await self._h2_downloader.writer.open()

        self._scheduler = SmartScheduler(
            chunk_manager=self._chunk_manager,
            config=self.config,
            monitor=self._monitor,
        )

        await self._scheduler.start()
        self._monitor.start()

        # 使用信号量控制并发数，简化任务管理
        semaphore = asyncio.Semaphore(self.config.max_chunks)

        async def download_with_limit(chunk: Chunk) -> tuple[int, bool, str | None]:
            """带并发限制的下载任务"""
            async with semaphore:
                if self._cancelled:
                    return chunk.index, False, "Cancelled"

                if not self._h2_downloader:
                    return chunk.index, False, "Downloader not initialized"

                if self._scheduler:
                    self._scheduler.register_worker()
                if self._monitor and self._scheduler:
                    self._monitor.set_active_workers(self._scheduler.get_stats().active_workers)

                try:
                    await self._h2_downloader.download_chunk(
                        chunk=chunk,
                        url=url,
                        progress_callback=None,
                    )
                    return chunk.index, True, None
                except Exception as e:
                    return chunk.index, False, str(e)
                finally:
                    if self._scheduler:
                        self._scheduler.unregister_worker()
                    if self._monitor and self._scheduler:
                        self._monitor.set_active_workers(self._scheduler.get_stats().active_workers)

        checkpoint_task: asyncio.Task[None] | None = None

        async def checkpoint_loop() -> None:
            while True:
                await asyncio.sleep(1.0)
                if self._resume_manager and self._chunk_manager:
                    await self._resume_manager.update_from_chunk_manager(self._chunk_manager)
                    await self._resume_manager.save()

        try:
            if self._resume_manager:
                checkpoint_task = asyncio.create_task(checkpoint_loop())

            # 收集所有待下载的分片
            pending_chunks = [
                chunk
                for chunk in self._chunk_manager.chunks
                if not chunk.is_completed and chunk.status.name != "FAILED"
            ]

            # 创建所有任务并使用 gather 并发执行
            tasks = [asyncio.create_task(download_with_limit(chunk)) for chunk in pending_chunks]

            # 等待所有任务完成，处理结果
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # 处理结果
            for result in results:
                if isinstance(result, Exception):
                    # 记录错误但继续处理其他分片
                    continue

                # 确保 result 是 tuple 类型
                if isinstance(result, tuple) and len(result) == 3:
                    chunk_index, success, error = result
                    if success:
                        await self._chunk_manager.complete_chunk(chunk_index)
                    else:
                        await self._chunk_manager.fail_chunk(chunk_index, error or "Unknown error")

            # 更新监控状态
            if self._monitor and self._chunk_manager:
                self._monitor.update_downloaded(self._chunk_manager.total_downloaded)
                self._monitor.set_chunk_stats(
                    total=len(self._chunk_manager.chunks),
                    completed=len(self._chunk_manager.completed_chunks),
                    failed=len(self._chunk_manager.failed_chunks),
                )

            # 保存恢复数据
            if self._resume_manager:
                await self._resume_manager.update_from_chunk_manager(self._chunk_manager)
                await self._resume_manager.flush_pending()

        finally:
            if checkpoint_task:
                checkpoint_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await checkpoint_task
            await self._h2_downloader.writer.close()

        if self._cancelled:
            raise CancelledError("Download cancelled", url)

        if not self._chunk_manager.is_completed:
            # 如果有失败的分片，尝试重试一次
            if self._chunk_manager.failed_chunks and self.config.retry:
                await self._retry_failed_chunks(url, progress_callback)

            if not self._chunk_manager.is_completed:
                raise DownloadError("Download incomplete")

        if self._resume_manager:
            await self._resume_manager.mark_completed()
            await self._resume_manager.cleanup()

        return output_path

    async def _retry_failed_chunks(
        self,
        url: str,
        progress_callback: ProgressCallbackAdapter | None,
    ) -> None:
        """重试失败的分片"""
        if not self._chunk_manager or not self._h2_downloader:
            return

        failed_chunks = self._chunk_manager.failed_chunks.copy()
        for chunk in failed_chunks:
            if chunk.error_count < self.config.retry.max_retries:
                chunk.reset()
                try:
                    await self._h2_downloader.download_chunk(
                        chunk=chunk,
                        url=url,
                        progress_callback=None,
                    )
                    await self._chunk_manager.complete_chunk(chunk.index)
                except Exception:
                    pass

    def _validate_file_size_constraints(self, file_size: int) -> None:
        if file_size <= 0:
            return
        if self.config.min_file_size is not None and file_size < self.config.min_file_size:
            raise DownloadError(f"File size {file_size} is smaller than minimum {self.config.min_file_size}")
        if self.config.max_file_size is not None and file_size > self.config.max_file_size:
            raise DownloadError(f"File size {file_size} exceeds maximum {self.config.max_file_size}")

    async def _verify_downloaded_file(self, file_path: Path) -> None:
        if not self.config.verify_hash:
            return
        if not self.config.expected_hash:
            raise ConfigurationError("verify_hash is enabled but expected_hash is not set")

        expected = self.config.expected_hash.strip().lower()

        try:
            actual = await asyncio.to_thread(self._calculate_file_hash, file_path, self.config.hash_algorithm)
        except ValueError as e:
            raise ConfigurationError(str(e)) from None

        if actual.lower() != expected:
            raise DownloadError(f"Hash verification failed: expected {expected}, got {actual}")

    @staticmethod
    def _calculate_file_hash(file_path: Path, algorithm: str) -> str:
        try:
            digest = hashlib.new(algorithm)
        except ValueError as e:
            raise ValueError(f"Unsupported hash algorithm: {algorithm}") from e

        with file_path.open("rb") as f:
            while True:
                data = f.read(1024 * 1024)
                if not data:
                    break
                digest.update(data)

        return digest.hexdigest()

    async def _wait_for_resume(self) -> None:
        while self._paused:
            await asyncio.sleep(0.1)

    async def pause(self) -> None:
        async with self._lock:
            self._paused = True
            if self._monitor:
                self._monitor.pause()

    async def resume(self) -> None:
        async with self._lock:
            self._paused = False
            if self._monitor:
                self._monitor.resume()

    async def cancel(self) -> None:
        async with self._lock:
            self._cancelled = True
            self._running = False

    async def _cleanup(self) -> None:
        if self._scheduler:
            await self._scheduler.stop()
        if self._connection_pool:
            await self._connection_pool.close()
        self._running = False

    def get_stats(self) -> dict[str, Any] | None:
        if not self._monitor or not self._chunk_manager:
            return None

        monitor_stats = self._monitor.get_stats()
        scheduler_stats = self._scheduler.get_stats() if self._scheduler else None

        return {
            "download": {
                "total_size": monitor_stats.total_size,
                "downloaded": monitor_stats.downloaded,
                "progress": monitor_stats.progress,
                "speed": monitor_stats.speed,
                "average_speed": monitor_stats.average_speed,
                "eta": monitor_stats.eta,
                "elapsed_time": monitor_stats.elapsed_time,
            },
            "chunks": {
                "total": len(self._chunk_manager.chunks),
                "completed": len(self._chunk_manager.completed_chunks),
                "active": len(self._chunk_manager.active_chunks),
                "pending": len(self._chunk_manager.pending_chunks),
                "failed": len(self._chunk_manager.failed_chunks),
            },
            "scheduler": scheduler_stats.__dict__ if scheduler_stats else None,
        }


async def download_file(
    url: str,
    save_path: str = "./downloads",
    filename: str | None = None,
    config: DownloadConfig | None = None,
    progress_callback: Callable[..., Any] | None = None,
    chunk_callback: Callable[..., Any] | None = None,
    resume: bool = True,
) -> Path:
    downloader = Downloader(config or DownloadConfig(resume=resume))
    return await downloader.download(
        url=url,
        save_path=save_path,
        filename=filename,
        resume=resume,
        progress_callback=progress_callback,
        chunk_callback=chunk_callback,
    )


def download_file_sync(
    url: str,
    save_path: str = "./downloads",
    filename: str | None = None,
    config: DownloadConfig | None = None,
    progress_callback: Callable[..., Any] | None = None,
    chunk_callback: Callable[..., Any] | None = None,
    resume: bool = True,
) -> Path:
    return asyncio.run(
        download_file(
            url=url,
            save_path=save_path,
            filename=filename,
            config=config,
            progress_callback=progress_callback,
            chunk_callback=chunk_callback,
            resume=resume,
        )
    )
