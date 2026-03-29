import asyncio
import inspect
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


class EventType(Enum):
    FILE_PROGRESS = "file_progress"
    FILE_COMPLETE = "file_complete"
    FILE_ERROR = "file_error"
    FILE_RETRY = "file_retry"
    BATCH_PROGRESS = "batch_progress"
    BATCH_COMPLETE = "batch_complete"
    CHUNK_PROGRESS = "chunk_progress"
    CHUNK_COMPLETE = "chunk_complete"
    CHUNK_ERROR = "chunk_error"


@dataclass(frozen=True)
class BaseProgressEvent:
    event_type: EventType
    timestamp: float = field(default_factory=time.time)
    task_id: str = ""


@dataclass(frozen=True)
class FileProgressEvent(BaseProgressEvent):
    event_type: EventType = EventType.FILE_PROGRESS
    task_id: str = ""
    filename: str = ""
    url: str = ""
    file_size: int = 0
    downloaded: int = 0
    speed: float = 0.0
    progress: float = 0.0
    eta: float = -1.0
    chunks_total: int = 0
    chunks_completed: int = 0


@dataclass(frozen=True)
class FileCompleteEvent(BaseProgressEvent):
    event_type: EventType = EventType.FILE_COMPLETE
    task_id: str = ""
    filename: str = ""
    url: str = ""
    file_size: int = 0
    saved_path: str = ""
    error: str | None = None


@dataclass(frozen=True)
class ChunkProgressEvent(BaseProgressEvent):
    event_type: EventType = EventType.CHUNK_PROGRESS
    task_id: str = ""
    chunk_index: int = 0
    chunk_downloaded: int = 0
    chunk_size: int = 0
    chunk_speed: float = 0.0


@dataclass(frozen=True)
class BatchProgressEvent(BaseProgressEvent):
    event_type: EventType = EventType.BATCH_PROGRESS
    total_files: int = 0
    completed_files: int = 0
    failed_files: int = 0
    active_files: int = 0
    pending_files: int = 0
    total_bytes: int = 0
    downloaded_bytes: int = 0
    overall_speed: float = 0.0
    smooth_speed: float = 0.0
    eta: float = -1.0
    speed_stability: float = 1.0
    files: tuple[FileProgressEvent, ...] = ()


CallbackFunc = Callable[..., Any]


class UnifiedCallbackAdapter:
    """
    统一回调适配器 - 支持多种回调签名风格

    支持的回调风格:
    1. Event模式: callback(event) - 接收 ProgressEvent 对象
    2. Dict模式: callback({"downloaded": 100, "total": 1000, ...}) - 接收字典
    3. Kwargs模式: callback(downloaded=100, total=1000, ...) - 接收关键字参数
    4. Legacy模式: callback(downloaded, total, speed, eta) - 接收位置参数
    """

    MODE_NONE = "none"
    MODE_EVENT = "event"
    MODE_DICT = "dict"
    MODE_KWARGS = "kwargs"
    MODE_LEGACY = "legacy"

    def __init__(self, callback: CallbackFunc | None = None) -> None:
        self._callback = callback
        self._mode = self._detect_mode(callback)

    def _detect_mode(self, callback: CallbackFunc | None) -> str:
        if callback is None:
            return self.MODE_NONE

        try:
            sig = inspect.signature(callback)
        except (TypeError, ValueError):
            return self.MODE_LEGACY

        params = list(sig.parameters.values())

        if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params):
            return self.MODE_KWARGS
        if any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params):
            return self.MODE_LEGACY

        positional = [
            p for p in params if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        ]

        if len(positional) >= 5:
            return self.MODE_LEGACY
        if len(positional) == 1:
            name = positional[0].name.lower()
            if name in {"event", "progress", "data", "payload", "info", "state", "stats"}:
                return self.MODE_EVENT
            return self.MODE_DICT
        if len(positional) == 0:
            return self.MODE_KWARGS

        return self.MODE_LEGACY

    async def emit(self, event: BaseProgressEvent | dict[str, Any] | BatchProgressEvent) -> None:
        if self._callback is None:
            return

        payload = self._event_to_payload(event)

        result: Any
        if self._mode == self.MODE_EVENT:
            result = self._callback(event)
        elif self._mode == self.MODE_DICT:
            result = self._callback(payload)
        elif self._mode == self.MODE_KWARGS:
            result = self._callback(**payload)
        else:
            if isinstance(event, BatchProgressEvent):
                result = self._callback(
                    event.completed_files,
                    event.total_files,
                    event.smooth_speed,
                    int(event.eta) if event.eta > 0 else -1,
                    event.speed_stability,
                )
            elif isinstance(event, FileProgressEvent):
                result = self._callback(
                    event.task_id,
                    event.downloaded,
                    event.file_size,
                    event.speed,
                )
            elif isinstance(event, FileCompleteEvent):
                result = self._callback(
                    event.task_id,
                    event.saved_path,
                    event.error,
                )
            else:
                result = self._callback(**payload)

        if inspect.isawaitable(result):
            await result

    def _event_to_payload(self, event: BaseProgressEvent | dict[str, Any] | BatchProgressEvent) -> dict[str, Any]:
        if isinstance(event, dict):
            return event
        if isinstance(event, BatchProgressEvent):
            return {
                "total_files": event.total_files,
                "completed_files": event.completed_files,
                "failed_files": event.failed_files,
                "active_files": event.active_files,
                "pending_files": event.pending_files,
                "total_bytes": event.total_bytes,
                "downloaded_bytes": event.downloaded_bytes,
                "overall_speed": event.overall_speed,
                "smooth_speed": event.smooth_speed,
                "eta": event.eta,
                "speed_stability": event.speed_stability,
                "files": event.files,
            }
        if isinstance(event, FileProgressEvent):
            return {
                "task_id": event.task_id,
                "filename": event.filename,
                "url": event.url,
                "file_size": event.file_size,
                "downloaded": event.downloaded,
                "speed": event.speed,
                "progress": event.progress,
                "eta": event.eta,
                "chunks_total": event.chunks_total,
                "chunks_completed": event.chunks_completed,
            }
        if isinstance(event, FileCompleteEvent):
            return {
                "task_id": event.task_id,
                "filename": event.filename,
                "url": event.url,
                "file_size": event.file_size,
                "saved_path": event.saved_path,
                "error": event.error,
            }
        if isinstance(event, ChunkProgressEvent):
            return {
                "task_id": event.task_id,
                "chunk_index": event.chunk_index,
                "chunk_downloaded": event.chunk_downloaded,
                "chunk_size": event.chunk_size,
                "chunk_speed": event.chunk_speed,
            }
        return {"event_type": event.event_type.value if hasattr(event, "event_type") else "unknown"}

    def __call__(self, event: BaseProgressEvent | dict[str, Any] | BatchProgressEvent) -> Any:
        return self.emit(event)


class ThrottledCallback:
    """节流回调 - 限制回调频率，避免性能开销"""

    def __init__(self, callback: UnifiedCallbackAdapter, min_interval: float = 0.1) -> None:
        self._callback = callback
        self._min_interval = min_interval
        self._last_emit_time: float = 0.0
        self._pending_event: BaseProgressEvent | BatchProgressEvent | None = None
        self._lock = asyncio.Lock()

    async def emit(self, event: BaseProgressEvent | BatchProgressEvent) -> None:
        async with self._lock:
            now = time.time()
            if now - self._last_emit_time >= self._min_interval:
                await self._callback.emit(event)
                self._last_emit_time = now
                self._pending_event = None
            else:
                self._pending_event = event

    async def flush(self) -> None:
        async with self._lock:
            if self._pending_event is not None:
                await self._callback.emit(self._pending_event)
                self._last_emit_time = time.time()
                self._pending_event = None


class ProgressAggregator:
    """
    进度聚合器 - 将多个分片/Chunk的进度聚合为文件级别进度

    用于在批量下载时，将 Downloader 内部的 chunk 级别进度聚合为 file 级别进度
    """

    def __init__(self, task_id: str, file_size: int, chunks: int = 1) -> None:
        self.task_id = task_id
        self.file_size = file_size
        self.chunks = chunks
        self._downloaded: int = 0
        self._speed: float = 0.0
        self._last_update: float = 0.0
        self._bytes_history: list[tuple[float, int]] = []
        self._lock = asyncio.Lock()

    def add_bytes(self, bytes_count: int) -> None:
        self._downloaded += bytes_count
        self._update_speed()

    def set_downloaded(self, downloaded: int) -> None:
        self._downloaded = downloaded
        self._update_speed()

    def _update_speed(self) -> None:
        now = time.time()
        self._bytes_history.append((now, self._downloaded))
        if len(self._bytes_history) > 20:
            self._bytes_history.pop(0)

        if len(self._bytes_history) >= 2:
            first = self._bytes_history[0]
            last = self._bytes_history[-1]
            time_diff = last[0] - first[0]
            bytes_diff = last[1] - first[1]
            if time_diff > 0:
                self._speed = bytes_diff / time_diff
                self._last_update = now

    def get_progress(self) -> tuple[int, int, float, float]:
        """返回 (downloaded, file_size, speed, eta)"""
        remaining = max(0, self.file_size - self._downloaded)
        eta = remaining / self._speed if self._speed > 0 else -1.0
        return (self._downloaded, self.file_size, self._speed, eta)

    @property
    def downloaded(self) -> int:
        return self._downloaded

    @property
    def speed(self) -> float:
        return self._speed

    @property
    def progress(self) -> float:
        if self.file_size <= 0:
            return 0.0
        return (self._downloaded / self.file_size) * 100


class CallbackChain:
    """回调链 - 支持多个回调的链式调用"""

    def __init__(self) -> None:
        self._callbacks: list[UnifiedCallbackAdapter] = []

    def add(self, callback: CallbackFunc | None) -> "CallbackChain":
        if callback is not None:
            self._callbacks.append(UnifiedCallbackAdapter(callback))
        return self

    async def emit(self, event: BaseProgressEvent | BatchProgressEvent) -> None:
        for callback in self._callbacks:
            await callback.emit(event)

    def __call__(self, event: BaseProgressEvent | BatchProgressEvent) -> Any:
        return self.emit(event)
