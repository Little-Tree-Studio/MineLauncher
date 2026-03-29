import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .utils import generate_chunk_id


class ChunkStatus(Enum):
    PENDING = "pending"
    DOWNLOADING = "downloading"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    RESPLITTING = "resplitting"


@dataclass
class Chunk:
    index: int
    start_byte: int
    end_byte: int
    total_size: int
    status: ChunkStatus = ChunkStatus.PENDING
    downloaded: int = 0
    chunk_id: str = field(default_factory=generate_chunk_id)
    error_count: int = 0
    last_error: str | None = None
    start_time: float | None = None
    end_time: float | None = None
    worker_id: str | None = None
    temp_file: str | None = None
    speed_samples: list[float] = field(default_factory=list)
    last_resplit_time: float = 0.0

    @property
    def size(self) -> int:
        return self.end_byte - self.start_byte

    @property
    def remaining(self) -> int:
        return self.size - self.downloaded

    @property
    def progress(self) -> float:
        if self.size == 0:
            return 100.0
        return (self.downloaded / self.size) * 100

    @property
    def is_completed(self) -> bool:
        return self.status == ChunkStatus.COMPLETED or self.downloaded >= self.size

    @property
    def is_active(self) -> bool:
        return self.status in (ChunkStatus.DOWNLOADING, ChunkStatus.RESPLITTING)

    @property
    def is_failed(self) -> bool:
        return self.status == ChunkStatus.FAILED

    @property
    def average_speed(self) -> float:
        if not self.speed_samples:
            return 0.0
        return sum(self.speed_samples) / len(self.speed_samples)

    @property
    def current_download_start(self) -> int:
        return self.start_byte + self.downloaded

    def start_download(self, worker_id: str) -> None:
        self.status = ChunkStatus.DOWNLOADING
        self.worker_id = worker_id
        self.start_time = time.time()

    def update_progress(self, bytes_downloaded: int, speed: float = 0.0) -> None:
        self.downloaded = min(self.downloaded + bytes_downloaded, self.size)
        if speed > 0:
            self.speed_samples.append(speed)
            if len(self.speed_samples) > 20:
                self.speed_samples.pop(0)
        if self.downloaded >= self.size:
            self.complete()

    def complete(self) -> None:
        self.status = ChunkStatus.COMPLETED
        self.downloaded = self.size
        self.end_time = time.time()

    def fail(self, error: str) -> None:
        self.status = ChunkStatus.FAILED
        self.error_count += 1
        self.last_error = error
        self.worker_id = None

    def pause(self) -> None:
        if self.status == ChunkStatus.DOWNLOADING:
            self.status = ChunkStatus.PAUSED
            self.worker_id = None

    def resume(self) -> None:
        if self.status == ChunkStatus.PAUSED:
            self.status = ChunkStatus.PENDING

    def reset(self) -> None:
        self.status = ChunkStatus.PENDING
        self.worker_id = None
        self.start_time = None
        self.end_time = None
        self.speed_samples.clear()

    def mark_for_resplit(self) -> None:
        self.status = ChunkStatus.RESPLITTING
        self.last_resplit_time = time.time()

    def can_resplit(self, cooldown: float = 5.0, global_avg_speed: float = 0.0) -> bool:
        if self.status not in (ChunkStatus.DOWNLOADING, ChunkStatus.FAILED):
            return False
        if self.downloaded >= self.size * 0.75:
            return False
        if global_avg_speed > 0 and self.average_speed > global_avg_speed * 1.5:
            return False
        return time.time() - self.last_resplit_time >= cooldown

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "start_byte": self.start_byte,
            "end_byte": self.end_byte,
            "total_size": self.total_size,
            "status": self.status.value,
            "downloaded": self.downloaded,
            "chunk_id": self.chunk_id,
            "error_count": self.error_count,
            "last_error": self.last_error,
            "temp_file": self.temp_file,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Chunk":
        chunk = cls(
            index=data["index"],
            start_byte=data["start_byte"],
            end_byte=data["end_byte"],
            total_size=data["total_size"],
            downloaded=data.get("downloaded", 0),
            chunk_id=data.get("chunk_id", generate_chunk_id()),
            error_count=data.get("error_count", 0),
            last_error=data.get("last_error"),
            temp_file=data.get("temp_file"),
        )
        chunk.status = ChunkStatus(data.get("status", "pending"))
        return chunk


class ChunkManager:
    def __init__(self, file_size: int, max_chunks: int = 8, min_chunk_size: int = 2 * 1024 * 1024) -> None:
        self.file_size = file_size
        self.max_chunks = max_chunks
        self.min_chunk_size = min_chunk_size
        self.chunks: list[Chunk] = []
        self._chunk_index_map: dict[int, int] = {}
        self._lock = asyncio.Lock()
        self._chunk_counter = 0

    @property
    def total_downloaded(self) -> int:
        return sum(chunk.downloaded for chunk in self.chunks)

    @property
    def total_remaining(self) -> int:
        return self.file_size - self.total_downloaded

    @property
    def overall_progress(self) -> float:
        if self.file_size == 0:
            return 100.0
        return (self.total_downloaded / self.file_size) * 100

    @property
    def active_chunks(self) -> list[Chunk]:
        return [c for c in self.chunks if c.is_active]

    @property
    def pending_chunks(self) -> list[Chunk]:
        return [c for c in self.chunks if c.status == ChunkStatus.PENDING]

    @property
    def completed_chunks(self) -> list[Chunk]:
        return [c for c in self.chunks if c.is_completed]

    @property
    def failed_chunks(self) -> list[Chunk]:
        return [c for c in self.chunks if c.is_failed]

    @property
    def is_completed(self) -> bool:
        return len(self.completed_chunks) == len(self.chunks)

    def initialize_chunks(self, existing_progress: dict[int, int] | None = None) -> None:
        self.chunks.clear()
        self._chunk_index_map.clear()
        self._chunk_counter = 0
        optimal_chunks = self._calculate_optimal_chunks()
        chunk_size = self.file_size // optimal_chunks
        remainder = self.file_size % optimal_chunks
        current_pos = 0
        for i in range(optimal_chunks):
            chunk_end = current_pos + chunk_size + (1 if i < remainder else 0)
            chunk = Chunk(
                index=i,
                start_byte=current_pos,
                end_byte=chunk_end,
                total_size=self.file_size,
            )
            if existing_progress and i in existing_progress:
                chunk.downloaded = existing_progress[i]
                if chunk.downloaded >= chunk.size:
                    chunk.complete()
            self.chunks.append(chunk)
            self._chunk_index_map[chunk.index] = len(self.chunks) - 1
            current_pos = chunk_end
        self._chunk_counter = optimal_chunks

    def _calculate_optimal_chunks(self) -> int:
        if self.file_size <= 0:
            return 1
        chunks = self.file_size // self.min_chunk_size
        return max(1, min(self.max_chunks, chunks))

    async def get_next_chunk(self) -> Chunk | None:
        async with self._lock:
            pending = [c for c in self.chunks if c.status == ChunkStatus.PENDING]
            if pending:
                chunk = pending[0]
                return chunk
            for chunk in self.chunks:
                if chunk.status == ChunkStatus.FAILED and chunk.error_count < 3:
                    chunk.reset()
                    return chunk
            return None

    async def update_chunk_progress(self, chunk_index: int, bytes_downloaded: int, speed: float = 0.0) -> None:
        async with self._lock:
            if 0 <= chunk_index < len(self.chunks):
                self.chunks[chunk_index].update_progress(bytes_downloaded, speed)

    async def complete_chunk(self, chunk_index: int) -> None:
        async with self._lock:
            if 0 <= chunk_index < len(self.chunks):
                self.chunks[chunk_index].complete()

    async def fail_chunk(self, chunk_index: int, error: str) -> None:
        async with self._lock:
            if 0 <= chunk_index < len(self.chunks):
                self.chunks[chunk_index].fail(error)

    def resplit_chunk(self, chunk_index: int, num_splits: int = 2) -> list[Chunk] | None:
        if chunk_index >= len(self.chunks):
            return None
        chunk = self.chunks[chunk_index]
        if not chunk.can_resplit():
            return None
        remaining = chunk.remaining
        min_size = self.min_chunk_size // num_splits
        if remaining < min_size:
            num_splits = max(2, remaining // self.min_chunk_size)
            if num_splits < 2:
                return None
        new_chunks: list[Chunk] = []
        chunk_size = remaining // num_splits
        current_start = chunk.start_byte + chunk.downloaded
        for i in range(num_splits):
            chunk_end = current_start + chunk_size + (1 if i < remaining % num_splits else 0)
            new_chunk = Chunk(
                index=self._chunk_counter if i > 0 else chunk.index,
                start_byte=current_start,
                end_byte=chunk_end,
                total_size=self.file_size,
                downloaded=0,
            )
            self._chunk_counter += 1
            new_chunks.append(new_chunk)
            current_start = chunk_end
        return new_chunks

    def get_slow_chunks(self, threshold_ratio: float = 0.5) -> list[Chunk]:
        active = self.active_chunks
        if len(active) < 2:
            return []
        speeds = [c.average_speed for c in active if c.average_speed > 0]
        if not speeds:
            return []
        avg_speed = sum(speeds) / len(speeds)
        threshold = avg_speed * threshold_ratio
        return [c for c in active if c.average_speed > 0 and c.average_speed < threshold]

    def get_chunk_by_index(self, index: int) -> Chunk | None:
        pos = self._chunk_index_map.get(index)
        if pos is None or pos >= len(self.chunks):
            return None
        return self.chunks[pos]

    def get_stats(self) -> dict[str, Any]:
        return {
            "total_chunks": len(self.chunks),
            "completed": len(self.completed_chunks),
            "active": len(self.active_chunks),
            "pending": len(self.pending_chunks),
            "failed": len(self.failed_chunks),
            "total_downloaded": self.total_downloaded,
            "total_remaining": self.total_remaining,
            "progress": self.overall_progress,
        }

    def to_dict(self) -> list[dict[str, Any]]:
        return [chunk.to_dict() for chunk in self.chunks]

    @classmethod
    def from_dict(cls, data: list[dict[str, Any]], file_size: int) -> "ChunkManager":
        manager = cls(file_size=file_size, max_chunks=len(data))
        manager.chunks = [Chunk.from_dict(chunk_data) for chunk_data in data]
        manager._chunk_counter = max(c.index for c in manager.chunks) + 1
        return manager
