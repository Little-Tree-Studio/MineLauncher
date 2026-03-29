import asyncio
import contextlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .chunk import Chunk, ChunkManager
from .exceptions import ResumeDataCorruptedError
from .utils import generate_download_id, generate_meta_filename


@dataclass
class DownloadMetadata:
    download_id: str
    url: str
    file_size: int
    filename: str
    save_path: str
    created_at: float
    updated_at: float
    chunks: list[dict[str, Any]] = field(default_factory=list)
    supports_range: bool = True
    etag: str | None = None
    last_modified: str | None = None
    content_type: str | None = None
    total_downloaded: int = 0
    status: str = "pending"

    def to_dict(self) -> dict[str, Any]:
        return {
            "download_id": self.download_id,
            "url": self.url,
            "file_size": self.file_size,
            "filename": self.filename,
            "save_path": self.save_path,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "chunks": self.chunks,
            "supports_range": self.supports_range,
            "etag": self.etag,
            "last_modified": self.last_modified,
            "content_type": self.content_type,
            "total_downloaded": self.total_downloaded,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DownloadMetadata":
        return cls(
            download_id=data["download_id"],
            url=data["url"],
            file_size=data["file_size"],
            filename=data["filename"],
            save_path=data["save_path"],
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            chunks=data.get("chunks", []),
            supports_range=data.get("supports_range", True),
            etag=data.get("etag"),
            last_modified=data.get("last_modified"),
            content_type=data.get("content_type"),
            total_downloaded=data.get("total_downloaded", 0),
            status=data.get("status", "pending"),
        )


class ResumeManager:
    def __init__(self, save_dir: Path, download_id: str | None = None) -> None:
        self.save_dir = save_dir
        self.download_id = download_id or generate_download_id("")
        self._metadata: DownloadMetadata | None = None
        self._lock = asyncio.Lock()
        self._last_save_time: float = 0
        self._save_interval: float = 1.0
        self._pending_save: bool = False

    @property
    def metadata(self) -> DownloadMetadata | None:
        return self._metadata

    @property
    def meta_path(self) -> Path:
        return self.save_dir / generate_meta_filename(self.download_id)

    @property
    def temp_dir(self) -> Path:
        return self.save_dir

    def initialize(
        self,
        url: str,
        file_size: int,
        filename: str,
        supports_range: bool = True,
        etag: str | None = None,
        last_modified: str | None = None,
        content_type: str | None = None,
    ) -> None:
        now = time.time()
        self._metadata = DownloadMetadata(
            download_id=self.download_id,
            url=url,
            file_size=file_size,
            filename=filename,
            save_path=str(self.save_dir),
            created_at=now,
            updated_at=now,
            supports_range=supports_range,
            etag=etag,
            last_modified=last_modified,
            content_type=content_type,
            status="downloading",
        )

    async def load(self) -> DownloadMetadata | None:
        async with self._lock:
            if not self.meta_path.exists():
                return None
            try:
                content = await self._read_file(self.meta_path)
                data = json.loads(content)
                self._metadata = DownloadMetadata.from_dict(data)
                return self._metadata
            except json.JSONDecodeError as e:
                raise ResumeDataCorruptedError(f"Invalid metadata format: {e}") from None
            except Exception as e:
                raise ResumeDataCorruptedError(f"Failed to load metadata: {e}") from None

    async def save(self, force: bool = False) -> None:
        if not self._metadata:
            return
        now = time.time()
        if not force and (now - self._last_save_time) < self._save_interval:
            self._pending_save = True
            return
        async with self._lock:
            if not self._metadata:
                return
            self._metadata.updated_at = now
            self._metadata.total_downloaded = sum(chunk.get("downloaded", 0) for chunk in self._metadata.chunks)
            try:
                content = json.dumps(self._metadata.to_dict(), indent=2, ensure_ascii=False)
                await self._write_file(self.meta_path, content)
                self._last_save_time = now
                self._pending_save = False
            except Exception:
                raise

    async def update_from_chunk_manager(self, chunk_manager: ChunkManager) -> None:
        if not self._metadata:
            return
        async with self._lock:
            self._metadata.chunks = chunk_manager.to_dict()
            self._metadata.total_downloaded = chunk_manager.total_downloaded

    async def update_chunk_progress(self, chunk: Chunk) -> None:
        if not self._metadata:
            return
        async with self._lock:
            for i, chunk_data in enumerate(self._metadata.chunks):
                if chunk_data.get("index") == chunk.index:
                    self._metadata.chunks[i] = chunk.to_dict()
                    break
            else:
                self._metadata.chunks.append(chunk.to_dict())
            self._metadata.total_downloaded = sum(c.get("downloaded", 0) for c in self._metadata.chunks)

    def can_resume(self) -> bool:
        if not self._metadata:
            return False
        if not self._metadata.supports_range:
            return False
        return not self._metadata.total_downloaded >= self._metadata.file_size

    def get_progress_dict(self) -> dict[int, int]:
        if not self._metadata:
            return {}
        progress: dict[int, int] = {}
        for chunk_data in self._metadata.chunks:
            index = chunk_data.get("index", 0)
            downloaded = chunk_data.get("downloaded", 0)
            progress[index] = downloaded
        return progress

    async def mark_completed(self) -> None:
        if self._metadata:
            self._metadata.status = "completed"
            self._metadata.updated_at = time.time()
            await self.save(force=True)

    async def mark_failed(self, error: str) -> None:
        if self._metadata:
            self._metadata.status = f"failed: {error}"
            self._metadata.updated_at = time.time()
            await self.save(force=True)

    async def cleanup(self) -> None:
        async with self._lock:
            if self.meta_path.exists():
                with contextlib.suppress(Exception):
                    await self._delete_file(self.meta_path)

    async def flush_pending(self) -> None:
        if self._pending_save:
            await self.save(force=True)

    async def _read_file(self, path: Path) -> str:
        import aiofiles

        async with aiofiles.open(path, encoding="utf-8") as f:
            return await f.read()

    async def _write_file(self, path: Path, content: str) -> None:
        import aiofiles

        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(".tmp_write")
        async with aiofiles.open(temp_path, "w", encoding="utf-8") as f:
            await f.write(content)
        if path.exists():
            await self._delete_file(path)
        temp_path.rename(path)

    async def _delete_file(self, path: Path) -> None:
        import os

        await asyncio.to_thread(os.remove, path)

    @staticmethod
    def find_pending_downloads(directory: Path) -> list[Path]:
        meta_files = list(directory.glob(".*.meta"))
        pending: list[Path] = []
        for meta_file in meta_files:
            try:
                content = meta_file.read_text(encoding="utf-8")
                data = json.loads(content)
                if data.get("status") in ("downloading", "paused"):
                    pending.append(meta_file)
            except Exception:
                continue
        return pending

    @staticmethod
    def get_download_id_from_meta(meta_path: Path) -> str | None:
        filename = meta_path.name
        if filename.startswith(".") and filename.endswith(".meta"):
            download_id = filename[1:-5]
            if download_id:
                return download_id
        return None
