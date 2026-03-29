import asyncio
import contextlib
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from .callback import ProgressAggregator
from .config import DownloadConfig
from .connection import ConnectionPool
from .downloader import Downloader
from .exceptions import DownloadError
from .global_pool import GlobalThreadPool
from .reuse import FileReuseChecker, MultiSourceManager, SharedFileRegistry
from .utils import generate_download_id, normalize_url, validate_url


class FileTaskStatus(Enum):
    PENDING = "pending"
    PROBING = "probing"
    DOWNLOADING = "downloading"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PAUSED = "paused"


@dataclass
class FileTask:
    task_id: str
    url: str
    save_path: Path
    filename: str | None = None
    status: FileTaskStatus = FileTaskStatus.PENDING
    file_size: int = -1
    downloaded: int = 0
    speed: float = 0.0
    error: str | None = None
    retry_count: int = 0
    priority: int = 0
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    completed_at: float | None = None
    supports_range: bool = True
    chunks: int = 1
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    sources: list[str] = field(default_factory=list)
    current_source_index: int = 0
    source_manager: MultiSourceManager | None = None

    existing_file_path: Path | None = None
    is_existing_reused: bool = False
    existing_file_checked: bool = False

    @property
    def progress(self) -> float:
        if self.file_size <= 0:
            return 0.0
        return (self.downloaded / self.file_size) * 100

    @property
    def is_active(self) -> bool:
        return self.status == FileTaskStatus.DOWNLOADING

    @property
    def is_completed(self) -> bool:
        return self.status == FileTaskStatus.COMPLETED

    @property
    def is_failed(self) -> bool:
        return self.status == FileTaskStatus.FAILED

    @property
    def remaining(self) -> int:
        return max(0, self.file_size - self.downloaded)

    @property
    def is_small_file(self) -> bool:
        return 0 < self.file_size < 5 * 1024 * 1024

    @property
    def is_large_file(self) -> bool:
        return self.file_size > 100 * 1024 * 1024

    async def update_progress(self, downloaded: int, speed: float = 0.0) -> None:
        async with self._lock:
            self.downloaded = downloaded
            if speed > 0:
                self.speed = speed

    async def mark_probing(self) -> None:
        async with self._lock:
            self.status = FileTaskStatus.PROBING

    async def mark_downloading(self) -> None:
        async with self._lock:
            self.status = FileTaskStatus.DOWNLOADING
            if self.started_at is None:
                self.started_at = time.time()

    async def mark_completed(self) -> None:
        async with self._lock:
            self.status = FileTaskStatus.COMPLETED
            self.completed_at = time.time()
            self.downloaded = self.file_size

    async def mark_failed(self, error: str) -> None:
        async with self._lock:
            self.status = FileTaskStatus.FAILED
            self.error = error

    async def mark_cancelled(self) -> None:
        async with self._lock:
            self.status = FileTaskStatus.CANCELLED

    async def reset_for_retry(self) -> None:
        async with self._lock:
            self.retry_count += 1
            self.status = FileTaskStatus.PENDING
            self.error = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "url": self.url,
            "save_path": str(self.save_path),
            "filename": self.filename,
            "status": self.status.value,
            "file_size": self.file_size,
            "downloaded": self.downloaded,
            "speed": self.speed,
            "error": self.error,
            "retry_count": self.retry_count,
            "priority": self.priority,
            "supports_range": self.supports_range,
            "chunks": self.chunks,
        }


@dataclass(slots=True)
class FileProgress:
    task_id: str
    filename: str
    url: str
    status: str
    file_size: int
    downloaded: int
    speed: float
    progress: float
    error: str | None
    started_at: float | None
    completed_at: float | None


@dataclass(slots=True)
class BatchProgress:
    total_files: int = 0
    completed_files: int = 0
    failed_files: int = 0
    active_files: int = 0
    pending_files: int = 0
    total_bytes: int = 0
    downloaded_bytes: int = 0
    overall_speed: float = 0.0
    smooth_speed: float = 0.0
    eta: float = -1
    speed_stability: float = 1.0
    elapsed_time: float = 0.0
    files: tuple[FileProgress, ...] = ()

    @property
    def progress(self) -> float:
        if self.total_bytes <= 0:
            return 0.0
        return (self.downloaded_bytes / self.total_bytes) * 100

    @property
    def files_progress(self) -> float:
        if self.total_files <= 0:
            return 0.0
        return (self.completed_files / self.total_files) * 100

    def get_active_files(self) -> list[FileProgress]:
        return [f for f in self.files if f.status == FileTaskStatus.DOWNLOADING.value]

    def get_pending_files(self) -> list[FileProgress]:
        return [f for f in self.files if f.status == FileTaskStatus.PENDING.value]

    def get_completed_files(self) -> list[FileProgress]:
        return [f for f in self.files if f.status == FileTaskStatus.COMPLETED.value]

    def get_failed_files(self) -> list[FileProgress]:
        return [f for f in self.files if f.status == FileTaskStatus.FAILED.value]


class BatchProgressCallbackAdapter:
    """Normalize different batch callback styles into one internal path."""

    CALLBACK_MODE_NONE = "none"
    CALLBACK_MODE_LEGACY = "legacy"
    CALLBACK_MODE_KWARGS = "kwargs"
    CALLBACK_MODE_DICT = "dict"
    CALLBACK_MODE_EVENT = "event"
    CALLBACK_MODE_FILE_PROGRESS = "file_progress"

    def __init__(self, callback: Callable[..., Any] | None) -> None:
        self._callback = callback
        self._mode = self._detect_mode(callback)

    def _detect_mode(self, callback: Callable[..., Any] | None) -> str:
        if callback is None:
            return self.CALLBACK_MODE_NONE
        try:
            import inspect

            sig = inspect.signature(callback)
        except (TypeError, ValueError):
            return self.CALLBACK_MODE_LEGACY

        params = list(sig.parameters.values())
        if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params):
            return self.CALLBACK_MODE_KWARGS
        if any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params):
            return self.CALLBACK_MODE_LEGACY

        positional = [
            p
            for p in params
            if p.kind
            in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            )
        ]

        if len(positional) >= 5:
            return self.CALLBACK_MODE_LEGACY
        if len(positional) == 4:
            names = [p.name.lower() for p in positional]
            if set(names) == {"task_id", "downloaded", "total", "speed"}:
                return self.CALLBACK_MODE_FILE_PROGRESS
            return self.CALLBACK_MODE_LEGACY
        if len(positional) == 1:
            name = positional[0].name.lower()
            if name in {"data", "payload", "info", "state", "stats", "progress"}:
                return self.CALLBACK_MODE_DICT
            return self.CALLBACK_MODE_EVENT
        if len(positional) == 0:
            return self.CALLBACK_MODE_KWARGS

        return self.CALLBACK_MODE_LEGACY

    async def emit(self, progress: BatchProgress) -> None:
        if self._callback is None:
            return

        payload = {
            "total_files": progress.total_files,
            "completed_files": progress.completed_files,
            "failed_files": progress.failed_files,
            "active_files": progress.active_files,
            "pending_files": progress.pending_files,
            "total_bytes": progress.total_bytes,
            "downloaded_bytes": progress.downloaded_bytes,
            "overall_speed": progress.overall_speed,
            "smooth_speed": progress.smooth_speed,
            "eta": progress.eta,
            "speed_stability": progress.speed_stability,
            "progress": progress.progress,
            "files_progress": progress.files_progress,
            "elapsed_time": progress.elapsed_time,
            "files": progress.files,
        }

        import inspect

        result: Any
        if self._mode == self.CALLBACK_MODE_EVENT:
            result = self._callback(progress)
        elif self._mode == self.CALLBACK_MODE_DICT:
            result = self._callback(payload)
        elif self._mode == self.CALLBACK_MODE_KWARGS:
            result = self._callback(**payload)
        elif self._mode == self.CALLBACK_MODE_FILE_PROGRESS:
            for fp in progress.files:
                if fp.status == FileTaskStatus.DOWNLOADING.value:
                    result = self._callback(
                        fp.task_id, fp.downloaded, fp.file_size, fp.speed
                    )
                    if inspect.isawaitable(result):
                        await result
            if progress.active_files == 0:
                result = self._callback(
                    "",
                    progress.downloaded_bytes,
                    progress.total_bytes
                    if progress.total_bytes > 0
                    else progress.total_files,
                    progress.smooth_speed
                    if progress.smooth_speed > 0
                    else progress.overall_speed,
                )
                if inspect.isawaitable(result):
                    await result
            return
        else:
            result = self._callback(
                progress.completed_files,
                progress.total_files,
                progress.smooth_speed,
                int(progress.eta) if progress.eta > 0 else -1,
                progress.speed_stability,
            )

        if inspect.isawaitable(result):
            await result

    def __call__(self, progress: BatchProgress) -> Any:
        return self.emit(progress)


class FileScheduler:
    def __init__(
        self,
        max_concurrent_files: int = 8,
        max_concurrent_chunks_per_file: int = 4,
        small_file_threshold: int = 5 * 1024 * 1024,
        large_file_threshold: int = 100 * 1024 * 1024,
        enable_small_file_priority: bool = True,
    ) -> None:
        self.max_concurrent_files = max_concurrent_files
        self.max_concurrent_chunks_per_file = max_concurrent_chunks_per_file
        self.small_file_threshold = small_file_threshold
        self.large_file_threshold = large_file_threshold
        self.enable_small_file_priority = enable_small_file_priority

        self._pending_tasks: list[FileTask] = []
        self._active_tasks: dict[str, FileTask] = {}
        self._completed_tasks: list[FileTask] = []
        self._failed_tasks: list[FileTask] = []
        self._lock = asyncio.Lock()
        self._paused = False
        self._start_time: float = 0.0

        self._speed_history: list[float] = []
        self._speed_history_max_size: int = 30
        self._last_progress_check: float = 0.0
        self._current_network_speed: float = 0.0
        self._speed_stability: float = 1.0

    @property
    def pending_count(self) -> int:
        return len(self._pending_tasks)

    @property
    def active_count(self) -> int:
        return len(self._active_tasks)

    @property
    def completed_count(self) -> int:
        return len(self._completed_tasks)

    @property
    def failed_count(self) -> int:
        return len(self._failed_tasks)

    @property
    def total_tasks(self) -> int:
        return (
            len(self._pending_tasks)
            + len(self._active_tasks)
            + len(self._completed_tasks)
            + len(self._failed_tasks)
        )

    async def add_task(self, task: FileTask) -> None:
        async with self._lock:
            self._pending_tasks.append(task)
            if self.enable_small_file_priority:
                self._sort_pending_by_priority()

    def _sort_pending_by_priority(self) -> None:
        def get_priority(t: FileTask) -> tuple[int, float]:
            priority = 2
            if t.is_small_file:
                priority = 0
            elif t.is_large_file:
                priority = 3
            elif t.file_size > 0:
                priority = 1
            return (priority, t.created_at)

        self._pending_tasks.sort(key=get_priority)

    async def get_next_task(self) -> FileTask | None:
        async with self._lock:
            if self._paused:
                return None
            if not self._pending_tasks:
                return None
            if len(self._active_tasks) >= self.max_concurrent_files:
                return None

            task = self._pending_tasks.pop(0)
            self._active_tasks[task.task_id] = task
            return task

    async def task_completed(self, task: FileTask) -> None:
        async with self._lock:
            if task.task_id in self._active_tasks:
                del self._active_tasks[task.task_id]
            self._completed_tasks.append(task)

    async def task_failed(self, task: FileTask) -> None:
        async with self._lock:
            if task.task_id in self._active_tasks:
                del self._active_tasks[task.task_id]
            self._failed_tasks.append(task)

    async def task_cancelled(self, task: FileTask) -> None:
        async with self._lock:
            if task.task_id in self._active_tasks:
                del self._active_tasks[task.task_id]
            self._failed_tasks.append(task)

    def get_optimal_chunks_for_task(self, task: FileTask) -> int:
        if task.is_small_file:
            return 1

        base_chunks = self.max_concurrent_chunks_per_file

        if task.is_large_file:
            base_chunks = min(base_chunks, 8)
        else:
            base_chunks = min(base_chunks, 4)

        if self._current_network_speed > 0 and task.file_size > 0:
            target_chunk_time = 3.0
            optimal_chunk_size = int(self._current_network_speed * target_chunk_time)
            if optimal_chunk_size > self.max_concurrent_chunks_per_file * 1024 * 1024:
                size_based_chunks = max(2, task.file_size // optimal_chunk_size)
                base_chunks = min(base_chunks, size_based_chunks)

        if self._speed_stability < 0.4:
            base_chunks = min(base_chunks, 4)
        elif (
            self._speed_stability > 0.7
            and self._current_network_speed > 5 * 1024 * 1024
        ):
            base_chunks = min(base_chunks + 2, 8)

        return max(1, base_chunks)

    async def pause(self) -> None:
        async with self._lock:
            self._paused = True

    async def resume(self) -> None:
        async with self._lock:
            self._paused = False

    def start(self) -> None:
        self._start_time = time.time()

    def get_all_tasks(self) -> list[FileTask]:
        return (
            self._completed_tasks
            + list(self._active_tasks.values())
            + self._pending_tasks
            + self._failed_tasks
        )

    def get_progress(self, include_files: bool = True) -> BatchProgress:
        completed = self._completed_tasks.copy()
        active = list(self._active_tasks.values())
        pending = self._pending_tasks.copy()
        failed = self._failed_tasks.copy()

        total_files = len(completed) + len(active) + len(pending) + len(failed)
        completed_files = len(completed)
        failed_files = len(failed)
        active_files = len(active)
        pending_files = len(pending)

        total_bytes = sum(
            t.file_size for t in completed + active + pending if t.file_size > 0
        )
        downloaded_bytes = sum(t.downloaded for t in completed + active)

        active_speed = sum(t.speed for t in active if t.speed > 0)
        self._speed_history.append(active_speed)
        if len(self._speed_history) > self._speed_history_max_size:
            self._speed_history.pop(0)

        smooth_speed = self._get_smoothed_speed()
        speed_stability = self._get_speed_stability()
        self._current_network_speed = smooth_speed if smooth_speed > 0 else active_speed
        self._speed_stability = speed_stability

        eta: float = -1.0
        remaining = total_bytes - downloaded_bytes
        if remaining > 0:
            if smooth_speed > 0:
                eta = remaining / smooth_speed
            elif active_speed > 0 and speed_stability > 0.5:
                eta = remaining / active_speed

        elapsed = (
            time.time() - self._start_time
            if hasattr(self, "_start_time") and self._start_time > 0
            else 0.0
        )

        file_progress_list: tuple[FileProgress, ...] = ()
        if include_files:
            file_progress_list = tuple(
                FileProgress(
                    task_id=t.task_id,
                    filename=t.filename or "unknown",
                    url=t.url,
                    status=t.status.value,
                    file_size=t.file_size,
                    downloaded=t.downloaded,
                    speed=t.speed,
                    progress=t.progress,
                    error=t.error,
                    started_at=t.started_at,
                    completed_at=t.completed_at,
                )
                for t in completed + active + pending + failed
            )

        return BatchProgress(
            total_files=total_files,
            completed_files=completed_files,
            failed_files=failed_files,
            active_files=active_files,
            pending_files=pending_files,
            total_bytes=total_bytes,
            downloaded_bytes=downloaded_bytes,
            overall_speed=active_speed,
            smooth_speed=smooth_speed,
            eta=eta,
            speed_stability=speed_stability,
            elapsed_time=elapsed,
            files=file_progress_list,
        )

    def _get_smoothed_speed(self) -> float:
        if not self._speed_history:
            return 0.0
        if len(self._speed_history) < 3:
            return sum(self._speed_history) / len(self._speed_history)
        recent = (
            self._speed_history[-5:]
            if len(self._speed_history) >= 5
            else self._speed_history
        )
        weights = [0.5 ** (len(recent) - i - 1) for i in range(len(recent))]
        total_weight = sum(weights)
        return sum(s * w for s, w in zip(recent, weights)) / total_weight

    def _get_speed_stability(self) -> float:
        if len(self._speed_history) < 3:
            return 1.0
        avg = sum(self._speed_history) / len(self._speed_history)
        if avg == 0:
            return 0.0
        variance = sum((s - avg) ** 2 for s in self._speed_history) / len(
            self._speed_history
        )
        std_dev = variance**0.5
        return max(0.0, 1.0 - (std_dev / avg))


class AdaptiveConcurrencyController:
    def __init__(
        self,
        initial_concurrency: int = 3,
        min_concurrency: int = 1,
        max_concurrency: int = 10,
        speed_threshold: float = 0.3,
        adjustment_interval: float = 5.0,
        error_threshold: int = 3,
    ) -> None:
        self.initial_concurrency = initial_concurrency
        self.min_concurrency = min_concurrency
        self.max_concurrency = max_concurrency
        self.speed_threshold = speed_threshold
        self.adjustment_interval = adjustment_interval
        self.error_threshold = error_threshold

        self._current_concurrency: int = initial_concurrency
        self._speed_history: list[float] = []
        self._ewma_speed: float = 0.0
        self._ewma_alpha: float = 0.2
        self._error_count: int = 0
        self._last_adjustment_time: float = 0.0
        self._last_speed: float = 0.0
        self._speed_trend: float = 0.0
        self._lock = asyncio.Lock()

    @property
    def current_concurrency(self) -> int:
        return self._current_concurrency

    async def record_speed(self, speed: float) -> None:
        async with self._lock:
            self._speed_history.append(speed)
            if len(self._speed_history) > 20:
                self._speed_history.pop(0)
            if self._ewma_speed == 0:
                self._ewma_speed = speed
            else:
                self._ewma_speed = (
                    self._ewma_alpha * speed + (1 - self._ewma_alpha) * self._ewma_speed
                )
            self._last_speed = speed

    async def record_error(self) -> None:
        async with self._lock:
            self._error_count += 1
            if self._error_count >= self.error_threshold:
                await self._reduce_concurrency()

    async def record_success(self) -> None:
        async with self._lock:
            self._error_count = max(0, self._error_count - 1)

    async def should_adjust(self) -> bool:
        async with self._lock:
            now = time.time()
            return now - self._last_adjustment_time >= self.adjustment_interval

    def _calculate_trend(self) -> float:
        if len(self._speed_history) < 5:
            return 0.0
        recent = self._speed_history[-5:]
        older = (
            self._speed_history[-10:-5]
            if len(self._speed_history) >= 10
            else self._speed_history[:-5]
        )
        if not older:
            return 0.0
        recent_avg = sum(recent) / len(recent)
        older_avg = sum(older) / len(older)
        if older_avg <= 0:
            return 0.0
        return (recent_avg - older_avg) / older_avg

    async def adjust(self) -> int:
        async with self._lock:
            now = time.time()
            if now - self._last_adjustment_time < self.adjustment_interval:
                return self._current_concurrency

            self._last_adjustment_time = now

            if len(self._speed_history) < 5:
                return self._current_concurrency

            recent_speeds = (
                self._speed_history[-7:]
                if len(self._speed_history) >= 7
                else self._speed_history
            )
            avg_speed = sum(recent_speeds) / len(recent_speeds)
            self._speed_trend = self._calculate_trend()

            speed_change = 0.0
            if self._ewma_speed > 0 and avg_speed > 0:
                speed_change = (self._ewma_speed - avg_speed) / avg_speed

            magnitude = abs(speed_change)
            increase_by = max(1, int(magnitude * 3))
            decrease_by = max(1, int(magnitude * 4))

            if (
                self._speed_trend < -0.15
                and self._current_concurrency < self.max_concurrency
            ):
                self._current_concurrency = min(
                    self.max_concurrency, self._current_concurrency + increase_by
                )
            elif (
                self._speed_trend > 0.2
                and self._current_concurrency > self.min_concurrency
            ):
                if self._ewma_speed > avg_speed * 0.9:
                    self._current_concurrency = max(
                        self.min_concurrency, self._current_concurrency - decrease_by
                    )
            elif (
                speed_change < -0.3 and self._current_concurrency < self.max_concurrency
            ):
                self._current_concurrency = min(
                    self.max_concurrency, self._current_concurrency + 1
                )

            if (
                avg_speed > 0
                and self._ewma_speed < avg_speed * 0.5
                and self._current_concurrency > self.min_concurrency
            ):
                self._current_concurrency = max(
                    self.min_concurrency, self._current_concurrency - 1
                )

            return self._current_concurrency

    async def _reduce_concurrency(self) -> None:
        self._current_concurrency = max(
            self.min_concurrency, self._current_concurrency - 1
        )
        self._error_count = 0

    async def reset(self) -> None:
        async with self._lock:
            self._current_concurrency = self.initial_concurrency
            self._speed_history.clear()
            self._error_count = 0


class BatchDownloader:
    def __init__(
        self,
        config: DownloadConfig | None = None,
        max_concurrent_files: int = 8,
        max_concurrent_chunks_per_file: int = 4,
        enable_adaptive_concurrency: bool = True,
        enable_small_file_priority: bool = True,
    ) -> None:
        self.config = config or DownloadConfig()
        self.max_concurrent_files = max_concurrent_files
        self.max_concurrent_chunks_per_file = max_concurrent_chunks_per_file
        self.enable_adaptive_concurrency = enable_adaptive_concurrency

        self._scheduler = FileScheduler(
            max_concurrent_files=max_concurrent_files,
            max_concurrent_chunks_per_file=max_concurrent_chunks_per_file,
            enable_small_file_priority=enable_small_file_priority,
        )
        self._concurrency_controller = AdaptiveConcurrencyController(
            initial_concurrency=max(1, max_concurrent_files // 2),
            min_concurrency=1,
            max_concurrency=max_concurrent_files,
        )
        self._connection_pool: ConnectionPool | None = None
        self._running = False
        self._paused = False
        self._cancelled = False
        self._lock = asyncio.Lock()
        self._tasks: dict[str, FileTask] = {}
        self._progress_callback: Any = None
        self._file_complete_callback: Any = None
        self._completed_count: int = 0
        self._total_speed: float = 0.0

    async def add_url(
        self,
        url: str,
        save_path: str | Path = "./downloads",
        filename: str | None = None,
        priority: int = 0,
    ) -> str:
        url = normalize_url(url)
        if not validate_url(url):
            raise DownloadError(f"Invalid URL: {url}")

        task_id = generate_download_id(url)
        save_path = Path(save_path).expanduser().resolve()

        task = FileTask(
            task_id=task_id,
            url=url,
            save_path=save_path,
            filename=filename,
            priority=priority,
        )
        self._tasks[task_id] = task
        await self._scheduler.add_task(task)
        return task_id

    async def add_urls(
        self,
        urls: list[str],
        save_path: str | Path = "./downloads",
    ) -> list[str]:
        task_ids = []
        for url in urls:
            task_id = await self.add_url(url, save_path)
            task_ids.append(task_id)
        return task_ids

    def set_progress_callback(self, callback: Any) -> None:
        self._progress_callback = BatchProgressCallbackAdapter(callback)

    def set_file_complete_callback(self, callback: Any) -> None:
        self._file_complete_callback = callback

    async def start(self) -> None:
        if self._running:
            return
        self._running = True

        self._connection_pool = ConnectionPool(self.config)
        await self._connection_pool.initialize()

        self._scheduler.start()
        await self._batch_probe_all()
        await self._download_loop()

    async def _batch_probe_all(self) -> None:
        pending_tasks = [
            t for t in self._tasks.values() if t.status == FileTaskStatus.PENDING
        ]
        if not pending_tasks:
            return

        probe_semaphore = asyncio.Semaphore(min(20, len(pending_tasks)))

        async def probe_single(task: FileTask) -> None:
            async with probe_semaphore:
                if self._cancelled:
                    return
                try:
                    await self._probe_single(task)
                except Exception as e:
                    await task.mark_failed(str(e))
                    await self._scheduler.task_failed(task)

        await asyncio.gather(
            *[probe_single(t) for t in pending_tasks], return_exceptions=True
        )

    async def _probe_single(self, task: FileTask) -> None:
        await task.mark_probing()

        client = self._connection_pool.client if self._connection_pool else None
        if not client:
            raise DownloadError("Connection pool not initialized")

        from .connection import RequestBuilder

        builder = RequestBuilder(self.config)
        request_config = builder.build_head_request(task.url)

        try:
            response = await client.head(
                request_config["url"],
                headers=request_config["headers"],
                follow_redirects=request_config["follow_redirects"],
            )
        except Exception as e:
            raise DownloadError(f"Failed to probe URL: {e}") from None

        if response.status_code >= 400:
            raise DownloadError(f"HTTP {response.status_code}")

        task.file_size = (
            int(response.headers.get("Content-Length", 0))
            if response.headers.get("Content-Length")
            else -1
        )
        task.supports_range = (
            response.headers.get("Accept-Ranges", "").lower() == "bytes"
        )

        content_disposition = response.headers.get("Content-Disposition")
        if content_disposition and not task.filename:
            from .utils import parse_content_disposition

            task.filename = parse_content_disposition(content_disposition)

        if not task.filename:
            from .utils import determine_filename

            task.filename = determine_filename(
                task.url, content_disposition, response.headers.get("Content-Type")
            )

        if task.supports_range and task.file_size > 0:
            task.chunks = self._scheduler.get_optimal_chunks_for_task(task)

        task.status = FileTaskStatus.PENDING

    async def _download_loop(self) -> None:
        download_tasks: dict[str, asyncio.Task[None]] = {}
        last_progress_time = 0.0
        progress_interval = 0.5

        async def download_file(task: FileTask) -> None:
            try:
                await self._download_single_file(task)
            except Exception as e:
                if not task.is_failed:
                    await task.mark_failed(str(e))
                    await self._scheduler.task_failed(task)
                    await self._emit_progress()

        while self._running:
            if self._cancelled:
                for t in download_tasks.values():
                    t.cancel()
                break

            while self._paused:
                await asyncio.sleep(0.1)
                if self._cancelled:
                    break

            concurrency_limit = (
                self._concurrency_controller.current_concurrency
                if self.enable_adaptive_concurrency
                else self.max_concurrent_files
            )

            while len(download_tasks) < concurrency_limit:
                task = await self._scheduler.get_next_task()
                if task is None:
                    break
                download_tasks[task.task_id] = asyncio.create_task(download_file(task))

            done_tasks = [tid for tid, t in download_tasks.items() if t.done()]
            for tid in done_tasks:
                task = download_tasks.pop(tid)
                with contextlib.suppress(asyncio.CancelledError):
                    await task

            if (
                self.enable_adaptive_concurrency
                and await self._concurrency_controller.should_adjust()
            ):
                progress = self._scheduler.get_progress()
                display_speed = (
                    progress.smooth_speed
                    if progress.smooth_speed > 0
                    else progress.overall_speed
                )
                self._total_speed = display_speed
                await self._concurrency_controller.record_speed(display_speed)
                await self._concurrency_controller.adjust()

            now = time.time()
            if (
                self._progress_callback
                and (now - last_progress_time) >= progress_interval
            ):
                last_progress_time = now
                progress = self._scheduler.get_progress()
                try:
                    await self._progress_callback.emit(progress)
                except Exception:
                    pass

            if (
                not download_tasks
                and self._scheduler.pending_count == 0
                and self._scheduler.active_count == 0
            ):
                break

            await asyncio.sleep(0.05)

        if download_tasks:
            await asyncio.gather(*download_tasks.values(), return_exceptions=True)

    async def _download_single_file(self, task: FileTask) -> None:
        await task.mark_downloading()

        aggregator = ProgressAggregator(task.task_id, task.file_size, task.chunks)

        async def progress_updater(
            downloaded: int, total: int, speed: float, eta: int
        ) -> None:
            aggregator.set_downloaded(downloaded)
            downloaded_agg, _, speed_agg, _ = aggregator.get_progress()
            await task.update_progress(
                downloaded_agg, speed_agg if speed_agg > 0 else speed
            )

        file_config = DownloadConfig(
            enable_chunking=self.config.enable_chunking and task.supports_range,
            max_chunks=task.chunks,
            min_chunks=1,
            buffer_size=self.config.buffer_size,
            timeout=self.config.timeout,
            connect_timeout=self.config.connect_timeout,
            read_timeout=self.config.read_timeout,
            write_timeout=self.config.write_timeout,
            resume=self.config.resume,
            verify_ssl=self.config.verify_ssl,
            user_agent=self.config.user_agent,
            headers=self.config.headers.copy(),
            proxy=self.config.proxy,
            speed_limit=self.config.speed_limit,
            retry=self.config.retry,
            follow_redirects=self.config.follow_redirects,
            max_redirects=self.config.max_redirects,
        )

        downloader = Downloader(config=file_config)
        if self._connection_pool:
            downloader.set_connection_pool(self._connection_pool)

        try:
            await downloader.download(
                url=task.url,
                save_path=str(task.save_path),
                filename=task.filename,
                resume=self.config.resume,
                progress_callback=progress_updater,
            )
            await task.mark_completed()
            await self._scheduler.task_completed(task)
            await self._concurrency_controller.record_success()

            if self._file_complete_callback:
                with contextlib.suppress(Exception):
                    result = self._file_complete_callback(task)
                    if asyncio.iscoroutine(result):
                        await result

            await self._emit_progress()

        except Exception as e:
            await self._concurrency_controller.record_error()
            if task.retry_count < self.config.retry.max_retries:
                await task.reset_for_retry()
                await self._scheduler.add_task(task)
            else:
                await task.mark_failed(str(e))
                await self._scheduler.task_failed(task)
                await self._emit_progress()

    async def pause(self) -> None:
        async with self._lock:
            self._paused = True
            await self._scheduler.pause()

    async def resume(self) -> None:
        async with self._lock:
            self._paused = False
            await self._scheduler.resume()

    async def cancel(self) -> None:
        async with self._lock:
            self._cancelled = True
            self._running = False
            for task in self._tasks.values():
                if task.is_active:
                    await task.mark_cancelled()
                    await self._scheduler.task_cancelled(task)

    async def stop(self) -> None:
        self._running = False
        if self._connection_pool:
            await self._connection_pool.close()

    def get_task(self, task_id: str) -> FileTask | None:
        return self._tasks.get(task_id)

    def get_all_tasks(self) -> list[FileTask]:
        return self._scheduler.get_all_tasks()

    def get_progress(self) -> BatchProgress:
        return self._scheduler.get_progress()

    def get_stats(self) -> dict[str, Any]:
        progress = self.get_progress()
        return {
            "total_files": progress.total_files,
            "completed_files": progress.completed_files,
            "failed_files": progress.failed_files,
            "active_files": progress.active_files,
            "pending_files": self._scheduler.pending_count,
            "total_bytes": progress.total_bytes,
            "downloaded_bytes": progress.downloaded_bytes,
            "progress_percent": progress.progress,
            "overall_speed": progress.overall_speed,
            "current_concurrency": self._concurrency_controller.current_concurrency,
        }

    async def _emit_progress(self) -> None:
        if self._progress_callback is None:
            return
        progress = self._scheduler.get_progress()
        self._total_speed = (
            progress.smooth_speed
            if progress.smooth_speed > 0
            else progress.overall_speed
        )
        try:
            await self._progress_callback.emit(progress)
        except Exception:
            pass


class SharedConnectionBatchDownloader(BatchDownloader):
    def __init__(self, config: DownloadConfig | None = None, **kwargs: Any) -> None:
        super().__init__(config, **kwargs)


async def batch_download(
    urls: list[str],
    save_path: str = "./downloads",
    config: DownloadConfig | None = None,
    max_concurrent_files: int = 8,
    max_concurrent_chunks_per_file: int = 4,
    progress_callback: Any = None,
    file_complete_callback: Any = None,
) -> list[tuple[str, Path | None, str | None]]:
    downloader = BatchDownloader(
        config=config,
        max_concurrent_files=max_concurrent_files,
        max_concurrent_chunks_per_file=max_concurrent_chunks_per_file,
    )

    if progress_callback:
        downloader.set_progress_callback(progress_callback)
    if file_complete_callback:
        downloader.set_file_complete_callback(file_complete_callback)

    await downloader.add_urls(urls, save_path)
    await downloader.start()

    results: list[tuple[str, Path | None, str | None]] = []
    for task in downloader.get_all_tasks():
        if task.is_completed:
            final_path = task.save_path / (task.filename or "unknown")
            results.append((task.url, final_path, None))
        else:
            results.append((task.url, None, task.error))

    return results


def batch_download_sync(
    urls: list[str],
    save_path: str = "./downloads",
    config: DownloadConfig | None = None,
    **kwargs: Any,
) -> list[tuple[str, Path | None, str | None]]:
    return asyncio.run(
        batch_download(
            urls=urls,
            save_path=save_path,
            config=config,
            **kwargs,
        )
    )


class EnhancedBatchDownloader:
    """
    增强版批量下载器 - 基于PCL高速下载策略

    PCL优化策略集成：
    1. 全局线程池控制 - 所有文件共享线程资源
    2. 动态负载均衡 - 速度慢时自动追加线程
    3. 多源备份 - 支持多个备用URL
    4. 已有文件复用 - 避免重复下载
    5. 自适应速度限制 - 根据实际速度自动调整
    """

    def __init__(
        self,
        config: DownloadConfig | None = None,
        max_concurrent_files: int = 8,
        max_total_threads: int = 15,
        small_file_threshold: int = 1 * 1024 * 1024,
        enable_existing_file_reuse: bool = True,
        enable_multi_source: bool = True,
        enable_adaptive_speed: bool = True,
    ) -> None:
        self.config = config or DownloadConfig()
        self.max_concurrent_files = max_concurrent_files
        self.max_total_threads = max_total_threads
        self.small_file_threshold = small_file_threshold
        self.enable_existing_file_reuse = enable_existing_file_reuse
        self.enable_multi_source = enable_multi_source
        self.enable_adaptive_speed = enable_adaptive_speed

        self._global_pool = GlobalThreadPool(
            max_total_threads=max_total_threads,
            min_speed_threshold=256 * 1024,
        )

        self._file_reuse_checker = (
            FileReuseChecker() if enable_existing_file_reuse else None
        )
        self._shared_registry = SharedFileRegistry()

        self._scheduler = FileScheduler(
            max_concurrent_files=max_concurrent_files,
            max_concurrent_chunks_per_file=4,
            small_file_threshold=small_file_threshold,
        )

        self._connection_pool: ConnectionPool | None = None
        self._running = False
        self._paused = False
        self._cancelled = False
        self._lock = asyncio.Lock()
        self._tasks: dict[str, FileTask] = {}
        self._progress_callback: Any = None
        self._file_complete_callback: Any = None

        self._thread_check_task: asyncio.Task[None] | None = None
        self._speed_monitor_task: asyncio.Task[None] | None = None
        self._total_speed: float = 0.0

        self._download_stats = {
            "total_files": 0,
            "completed_files": 0,
            "failed_files": 0,
            "reused_files": 0,
            "bytes_saved": 0,
            "total_chunks": 0,
            "dynamic_chunks_added": 0,
        }

    async def add_url(
        self,
        url: str,
        save_path: str | Path = "./downloads",
        filename: str | None = None,
        priority: int = 0,
        backup_urls: list[str] | None = None,
    ) -> str:
        url = normalize_url(url)
        if not validate_url(url):
            raise DownloadError(f"Invalid URL: {url}")

        task_id = generate_download_id(url)
        save_path = Path(save_path).expanduser().resolve()

        sources = [url]
        if backup_urls:
            sources.extend(backup_urls)

        task = FileTask(
            task_id=task_id,
            url=url,
            save_path=save_path,
            filename=filename,
            priority=priority,
            sources=sources,
        )

        if self.enable_multi_source and len(sources) > 1:
            task.source_manager = MultiSourceManager()
            for i, src in enumerate(sources):
                task.source_manager.add_source(src, priority=len(sources) - i)

        self._tasks[task_id] = task
        await self._scheduler.add_task(task)
        self._download_stats["total_files"] += 1
        return task_id

    async def add_urls(
        self,
        urls: list[str],
        save_path: str | Path = "./downloads",
    ) -> list[str]:
        task_ids = []
        for url in urls:
            task_id = await self.add_url(url, save_path)
            task_ids.append(task_id)
        return task_ids

    def set_progress_callback(self, callback: Any) -> None:
        self._progress_callback = BatchProgressCallbackAdapter(callback)

    def set_file_complete_callback(self, callback: Any) -> None:
        self._file_complete_callback = callback

    async def start(self) -> None:
        if self._running:
            return
        self._running = True

        self._connection_pool = ConnectionPool(self.config)
        await self._connection_pool.initialize()

        await self._global_pool.start()

        self._scheduler.start()
        self._thread_check_task = asyncio.create_task(self._thread_check_loop())
        self._speed_monitor_task = asyncio.create_task(self._speed_monitor_loop())

        await self._batch_probe_all()
        await self._download_loop()

    async def _batch_probe_all(self) -> None:
        pending_tasks = [
            t for t in self._tasks.values() if t.status == FileTaskStatus.PENDING
        ]
        if not pending_tasks:
            return

        probe_semaphore = asyncio.Semaphore(min(20, len(pending_tasks)))

        async def probe_single(task: FileTask) -> None:
            async with probe_semaphore:
                if self._cancelled:
                    return
                try:
                    await self._probe_single(task)
                except Exception as e:
                    await task.mark_failed(str(e))
                    await self._scheduler.task_failed(task)

        await asyncio.gather(
            *[probe_single(t) for t in pending_tasks], return_exceptions=True
        )

    async def _probe_single(self, task: FileTask) -> None:
        await task.mark_probing()

        client = self._connection_pool.client if self._connection_pool else None
        if not client:
            raise DownloadError("Connection pool not initialized")

        from .connection import RequestBuilder

        builder = RequestBuilder(self.config)
        request_config = builder.build_head_request(task.url)

        try:
            response = await client.head(
                request_config["url"],
                headers=request_config["headers"],
                follow_redirects=request_config["follow_redirects"],
            )
        except Exception as e:
            raise DownloadError(f"Failed to probe URL: {e}") from None

        if response.status_code >= 400:
            raise DownloadError(f"HTTP {response.status_code}")

        task.file_size = (
            int(response.headers.get("Content-Length", 0))
            if response.headers.get("Content-Length")
            else -1
        )
        task.supports_range = (
            response.headers.get("Accept-Ranges", "").lower() == "bytes"
        )

        content_disposition = response.headers.get("Content-Disposition")
        if content_disposition and not task.filename:
            from .utils import parse_content_disposition

            task.filename = parse_content_disposition(content_disposition)

        if not task.filename:
            from .utils import determine_filename

            task.filename = determine_filename(
                task.url, content_disposition, response.headers.get("Content-Type")
            )

        if task.supports_range and task.file_size > 0:
            task.chunks = self._scheduler.get_optimal_chunks_for_task(task)

        if (
            self.enable_existing_file_reuse
            and self._file_reuse_checker
            and task.file_size > 0
        ):
            target_path = task.save_path / (task.filename or "unknown")
            existing = await self._check_existing_file(target_path, task.file_size)
            if existing:
                task.existing_file_path = existing
                task.is_existing_reused = True

        task.status = FileTaskStatus.PENDING

    async def _check_existing_file(
        self, target_path: Path, expected_size: int
    ) -> Path | None:
        if not self._file_reuse_checker:
            return None

        if not target_path.exists():
            search_paths = []
            for task in self._tasks.values():
                if task.save_path != target_path.parent:
                    search_paths.append(task.save_path)

            return self._file_reuse_checker.find_existing_file(
                target_path,
                search_paths=search_paths if search_paths else None,
                expected_size=expected_size,
            )

        error = self._file_reuse_checker.check_file(target_path, expected_size)
        if error is None:
            return target_path

        return None

    async def _download_loop(self) -> None:
        download_tasks: dict[str, asyncio.Task[None]] = {}
        last_progress_time = 0.0
        progress_interval = 0.5

        async def download_file(task: FileTask) -> None:
            try:
                await self._download_single_file(task)
            except Exception as e:
                if not task.is_failed:
                    await task.mark_failed(str(e))
                    await self._scheduler.task_failed(task)
                    await self._emit_progress()

        while self._running:
            if self._cancelled:
                for t in download_tasks.values():
                    t.cancel()
                break

            while self._paused:
                await asyncio.sleep(0.1)
                if self._cancelled:
                    break

            while len(download_tasks) < self.max_concurrent_files:
                task = await self._scheduler.get_next_task()
                if task is None:
                    break

                if task.is_existing_reused and task.existing_file_path:
                    await self._reuse_existing_file(task)
                    continue

                download_tasks[task.task_id] = asyncio.create_task(download_file(task))

            done_tasks = [tid for tid, t in download_tasks.items() if t.done()]
            for tid in done_tasks:
                task = download_tasks.pop(tid)
                with contextlib.suppress(asyncio.CancelledError):
                    await task

            now = time.time()
            if (
                self._progress_callback
                and (now - last_progress_time) >= progress_interval
            ):
                last_progress_time = now
                progress = self._scheduler.get_progress()
                self._total_speed = (
                    progress.smooth_speed
                    if progress.smooth_speed > 0
                    else progress.overall_speed
                )
                try:
                    await self._progress_callback.emit(progress)
                except Exception:
                    pass

            if (
                not download_tasks
                and self._scheduler.pending_count == 0
                and self._scheduler.active_count == 0
            ):
                break

            await asyncio.sleep(0.05)

        if download_tasks:
            await asyncio.gather(*download_tasks.values(), return_exceptions=True)

    async def _reuse_existing_file(self, task: FileTask) -> None:
        if not task.existing_file_path or not task.is_existing_reused:
            return

        target_path = task.save_path / (task.filename or "unknown")

        try:
            if task.existing_file_path != target_path:
                task.save_path.mkdir(parents=True, exist_ok=True)
                shutil.copy2(task.existing_file_path, target_path)

            await task.mark_completed()
            await self._scheduler.task_completed(task)

            self._download_stats["reused_files"] += 1
            if task.file_size > 0:
                self._download_stats["bytes_saved"] += task.file_size

            if self._file_reuse_checker:
                stats = self._file_reuse_checker.get_stats()

            if self._file_complete_callback:
                with contextlib.suppress(Exception):
                    result = self._file_complete_callback(task)
                    if asyncio.iscoroutine(result):
                        await result

            await self._emit_progress()

        except Exception as e:
            task.is_existing_reused = False
            task.existing_file_path = None

    async def _download_single_file(self, task: FileTask) -> None:
        await task.mark_downloading()

        await self._global_pool.acquire_thread(task.task_id)

        aggregator = ProgressAggregator(task.task_id, task.file_size, task.chunks)

        async def progress_updater(
            downloaded: int, total: int, speed: float, eta: int
        ) -> None:
            aggregator.set_downloaded(downloaded)
            downloaded_agg, _, speed_agg, _ = aggregator.get_progress()
            await task.update_progress(
                downloaded_agg, speed_agg if speed_agg > 0 else speed
            )

        try:
            file_config = DownloadConfig(
                enable_chunking=self.config.enable_chunking and task.supports_range,
                max_chunks=task.chunks,
                min_chunks=1,
                buffer_size=self.config.buffer_size,
                timeout=self.config.timeout,
                connect_timeout=self.config.connect_timeout,
                read_timeout=self.config.read_timeout,
                write_timeout=self.config.write_timeout,
                resume=self.config.resume,
                verify_ssl=self.config.verify_ssl,
                user_agent=self.config.user_agent,
                headers=self.config.headers.copy(),
                proxy=self.config.proxy,
                speed_limit=self.config.speed_limit,
                retry=self.config.retry,
                follow_redirects=self.config.follow_redirects,
                max_redirects=self.config.max_redirects,
            )

            downloader = Downloader(config=file_config)
            if self._connection_pool:
                downloader.set_connection_pool(self._connection_pool)

            url = task.url
            if task.source_manager:
                source_info = task.source_manager.get_next_available()
                if source_info:
                    url = source_info["url"]

            await downloader.download(
                url=url,
                save_path=str(task.save_path),
                filename=task.filename,
                resume=self.config.resume,
                progress_callback=progress_updater,
            )

            await task.mark_completed()
            await self._scheduler.task_completed(task)
            self._download_stats["completed_files"] += 1

            if task.source_manager:
                task.source_manager.mark_source_success(url)

            if self._file_complete_callback:
                with contextlib.suppress(Exception):
                    result = self._file_complete_callback(task)
                    if asyncio.iscoroutine(result):
                        await result

            await self._emit_progress()

        except Exception as e:
            if task.source_manager:
                task.source_manager.mark_source_failed(task.url, str(e))

            if task.source_manager and task.source_manager.has_available_source:
                next_source = task.source_manager.get_next_available()
                if next_source:
                    task.retry_count += 1
                    if task.retry_count < self.config.retry.max_retries:
                        await task.reset_for_retry()
                        await self._scheduler.add_task(task)
                        await self._global_pool.release_thread(task.task_id)
                        return

            await task.mark_failed(str(e))
            await self._scheduler.task_failed(task)
            self._download_stats["failed_files"] += 1
            await self._emit_progress()
        finally:
            await self._global_pool.release_thread(task.task_id)

    async def _emit_progress(self) -> None:
        if self._progress_callback is None:
            return
        progress = self._scheduler.get_progress()
        self._total_speed = (
            progress.smooth_speed
            if progress.smooth_speed > 0
            else progress.overall_speed
        )
        try:
            await self._progress_callback.emit(progress)
        except Exception:
            pass

    async def _thread_check_loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(0.02)

                if not self._global_pool.should_append_thread(""):
                    continue

                active_tasks = [t for t in self._tasks.values() if t.is_active]
                for task in active_tasks:
                    if not self._global_pool.is_full:
                        current_chunks = self._scheduler.get_optimal_chunks_for_task(
                            task
                        )
                        allocated = self._global_pool.get_thread_allocation(
                            task.task_id
                        )

                        if allocated < current_chunks:
                            self._download_stats["dynamic_chunks_added"] += 1

            except asyncio.CancelledError:
                break
            except Exception:
                pass

    async def _speed_monitor_loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(0.1)

                self._global_pool.record_speed(self._total_speed)

            except asyncio.CancelledError:
                break
            except Exception:
                pass

    async def pause(self) -> None:
        async with self._lock:
            self._paused = True
            await self._scheduler.pause()

    async def resume(self) -> None:
        async with self._lock:
            self._paused = False
            await self._scheduler.resume()

    async def cancel(self) -> None:
        async with self._lock:
            self._cancelled = True
            self._running = False
            for task in self._tasks.values():
                if task.is_active:
                    await task.mark_cancelled()
                    await self._scheduler.task_cancelled(task)

    async def stop(self) -> None:
        self._running = False
        if self._thread_check_task:
            self._thread_check_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._thread_check_task
        if self._speed_monitor_task:
            self._speed_monitor_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._speed_monitor_task
        await self._global_pool.stop()
        if self._connection_pool:
            await self._connection_pool.close()

    def get_task(self, task_id: str) -> FileTask | None:
        return self._tasks.get(task_id)

    def get_all_tasks(self) -> list[FileTask]:
        return self._scheduler.get_all_tasks()

    def get_progress(self) -> BatchProgress:
        return self._scheduler.get_progress()

    def get_stats(self) -> dict[str, Any]:
        progress = self.get_progress()
        pool_stats = self._global_pool.get_stats()

        return {
            "total_files": self._download_stats["total_files"],
            "completed_files": self._download_stats["completed_files"],
            "failed_files": self._download_stats["failed_files"],
            "reused_files": self._download_stats["reused_files"],
            "bytes_saved": self._download_stats["bytes_saved"],
            "active_files": progress.active_files,
            "pending_files": self._scheduler.pending_count,
            "total_bytes": progress.total_bytes,
            "downloaded_bytes": progress.downloaded_bytes,
            "progress_percent": progress.progress,
            "overall_speed": progress.overall_speed,
            "total_threads": pool_stats.total_threads,
            "active_threads": pool_stats.active_threads,
            "dynamic_chunks_added": self._download_stats["dynamic_chunks_added"],
        }

    def get_file_reuse_stats(self) -> dict[str, Any] | None:
        if self._file_reuse_checker:
            return self._file_reuse_checker.get_stats()
        return None


class MCBatchDownloader(EnhancedBatchDownloader):
    """
    Minecraft下载专用批量下载器 - 基于EnhancedBatchDownloader优化

    MC下载优化策略：
    1. 更高并发文件数 - MC文件小，16并发替代8并发
    2. 更低小文件阈值 - 256KB替代1MB，更激进优先级
    3. 跳过探测小文件 - <64KB文件直接单线程下载，不发HEAD请求
    4. 版本JSON优先 - 检测version/*.json并提升优先级
    5. 保守分块策略 - 小文件最多2块，减少线程开销
    6. 更快的进度更新 - 0.3s间隔替代0.5s
    7. 连接复用优化 - 长连接保持用于同域名
    """

    VERSION_JSON_PATTERN = ("version", ".json")
    ASSETS_INDEX_PATTERN = ("assets", "indexes")
    LIBRARIES_PATTERN = ("libraries",)
    NATIVES_PATTERN = ("natives",)

    def __init__(
        self,
        config: DownloadConfig | None = None,
        max_concurrent_files: int = 16,
        max_total_threads: int = 20,
        small_file_threshold: int = 256 * 1024,
        enable_existing_file_reuse: bool = True,
        enable_multi_source: bool = True,
        enable_adaptive_speed: bool = True,
        skip_probe_threshold: int = 64 * 1024,
    ) -> None:
        super().__init__(
            config=config,
            max_concurrent_files=max_concurrent_files,
            max_total_threads=max_total_threads,
            small_file_threshold=small_file_threshold,
            enable_existing_file_reuse=enable_existing_file_reuse,
            enable_multi_source=enable_multi_source,
            enable_adaptive_speed=enable_adaptive_speed,
        )
        self.skip_probe_threshold = skip_probe_threshold
        self._progress_interval = 0.3

        self._scheduler = FileScheduler(
            max_concurrent_files=max_concurrent_files,
            max_concurrent_chunks_per_file=2,
            small_file_threshold=small_file_threshold,
        )

    def _is_priority_file(self, url: str) -> bool:
        url_lower = url.lower()
        if (
            self.VERSION_JSON_PATTERN[0] in url_lower
            and self.VERSION_JSON_PATTERN[1] in url_lower
        ):
            return True
        if "minecraft" in url_lower and ".json" in url_lower:
            return True
        return False

    async def add_url(
        self,
        url: str,
        save_path: str | Path = "./downloads",
        filename: str | None = None,
        priority: int = 0,
        backup_urls: list[str] | None = None,
    ) -> str:
        if self._is_priority_file(url):
            priority = max(priority, 10)
        return await super().add_url(url, save_path, filename, priority, backup_urls)

    async def add_urls(
        self,
        urls: list[str],
        save_path: str | Path = "./downloads",
    ) -> list[str]:
        task_ids = []
        priority_urls = []
        normal_urls = []

        for url in urls:
            if self._is_priority_file(url):
                priority_urls.append(url)
            else:
                normal_urls.append(url)

        for url in priority_urls:
            task_id = await self.add_url(url, save_path, priority=10)
            task_ids.append(task_id)

        for url in normal_urls:
            task_id = await self.add_url(url, save_path)
            task_ids.append(task_id)

        return task_ids

    async def _probe_single(self, task: FileTask) -> None:
        if task.file_size > 0 and task.file_size < self.skip_probe_threshold:
            task.supports_range = False
            task.chunks = 1
            task.status = FileTaskStatus.PENDING
            if (
                self.enable_existing_file_reuse
                and self._file_reuse_checker
                and task.file_size > 0
            ):
                target_path = task.save_path / (task.filename or "unknown")
                existing = await self._check_existing_file(target_path, task.file_size)
                if existing:
                    task.existing_file_path = existing
                    task.is_existing_reused = True
            return

        await super()._probe_single(task)

        if task.is_small_file and task.chunks > 2:
            task.chunks = 2

    def get_optimal_chunks_for_task(self, task: FileTask) -> int:
        if task.is_small_file or task.file_size < 1024 * 1024:
            return 1
        base_chunks = self._scheduler.get_optimal_chunks_for_task(task)
        return min(base_chunks, 2)

    async def _download_loop(self) -> None:
        download_tasks: dict[str, asyncio.Task[None]] = {}
        last_progress_time = 0.0

        async def download_file(task: FileTask) -> None:
            try:
                await self._download_single_file(task)
            except Exception as e:
                if not task.is_failed:
                    await task.mark_failed(str(e))
                    await self._scheduler.task_failed(task)
                    await self._emit_progress()

        while self._running:
            if self._cancelled:
                for t in download_tasks.values():
                    t.cancel()
                break

            while self._paused:
                await asyncio.sleep(0.1)
                if self._cancelled:
                    break

            while len(download_tasks) < self.max_concurrent_files:
                task = await self._scheduler.get_next_task()
                if task is None:
                    break

                if task.is_existing_reused and task.existing_file_path:
                    await self._reuse_existing_file(task)
                    continue

                download_tasks[task.task_id] = asyncio.create_task(download_file(task))

            done_tasks = [tid for tid, t in download_tasks.items() if t.done()]
            for tid in done_tasks:
                task = download_tasks.pop(tid)
                with contextlib.suppress(asyncio.CancelledError):
                    await task

            now = time.time()
            if (
                self._progress_callback
                and (now - last_progress_time) >= self._progress_interval
            ):
                last_progress_time = now
                progress = self._scheduler.get_progress()
                self._total_speed = (
                    progress.smooth_speed
                    if progress.smooth_speed > 0
                    else progress.overall_speed
                )
                try:
                    await self._progress_callback.emit(progress)
                except Exception:
                    pass

            if (
                not download_tasks
                and self._scheduler.pending_count == 0
                and self._scheduler.active_count == 0
            ):
                break

            await asyncio.sleep(0.05)

        if download_tasks:
            await asyncio.gather(*download_tasks.values(), return_exceptions=True)
