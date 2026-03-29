import hashlib
import os
from pathlib import Path
from typing import Any

from .utils import calculate_file_hash, format_size


FILE_SIGNATURES: dict[bytes, str] = {
    b"\x89PNG\r\n\x1a\n": "png",
    b"\xff\xd8\xff": "jpg",
    b"GIF87a": "gif",
    b"GIF89a": "gif",
    b"PK\x03\x04": "zip",
    b"%PDF": "pdf",
    b"Rar!\x1a\x07": "rar",
    b"\x1f\x8b\x08": "gz",
    b"BZh": "bz2",
    b"\xfd7zXZ\x00": "xz",
    b"7z\xbc\xaf\x27\x1c": "7z",
    b"\x50\x4b\x03\x04": "docx/xlsx/pptx",
    b"\x4f\x67\x67\x53": "ogg",
    b"\x49\x44\x33": "mp3",
    b"\xff\xfb": "mp3",
    b"\x49\x49\x2a\x00": "tif",
    b"\x42\x4d": "bmp",
}


class FileReuseChecker:
    """
    文件复用检查器 - 基于PCL改进的内容感知匹配

    改进点：
    1. 使用文件签名（magic bytes）进行内容感知匹配
    2. 支持跨目录的文件复用
    3. 基于文件大小和部分哈希的快速预检
    4. 增量哈希计算（首尾块）
    """

    def __init__(
        self,
        check_hash: bool = False,
        hash_algorithm: str = "md5",
        enable_content_matching: bool = True,
        quick_hash_size: int = 64 * 1024,
    ) -> None:
        self.check_hash = check_hash
        self.hash_algorithm = hash_algorithm
        self.enable_content_matching = enable_content_matching
        self.quick_hash_size = quick_hash_size

        self._cache: dict[str, str | None] = {}
        self._quick_hash_cache: dict[str, str | None] = {}
        self._signature_cache: dict[str, str | None] = {}
        self._stats = {
            "checks": 0,
            "hits": 0,
            "misses": 0,
            "bytes_saved": 0,
            "quick_hash_hits": 0,
            "content_matched": 0,
        }

    def check_file(self, file_path: Path, expected_size: int = -1, expected_hash: str | None = None) -> str | None:
        """
        检查文件是否可用

        Returns:
            None - 文件可用
            str - 错误描述
        """
        self._stats["checks"] += 1

        if not file_path.exists():
            return "文件不存在"

        if not file_path.is_file():
            return "不是文件"

        actual_size = file_path.stat().st_size

        if expected_size > 0 and actual_size != expected_size:
            return f"文件大小不匹配: 期望 {expected_size}, 实际 {actual_size}"

        if expected_hash:
            actual_hash = self._get_cached_hash(file_path)
            if actual_hash != expected_hash.lower():
                return f"文件哈希不匹配: 期望 {expected_hash}, 实际 {actual_hash}"

        return None

    def find_existing_file(
        self,
        primary_path: Path,
        search_paths: list[Path] | None = None,
        expected_size: int = -1,
        expected_hash: str | None = None,
    ) -> Path | None:
        """
        在多个路径中查找已存在的可用文件

        策略：
        1. 先检查主路径
        2. 再在搜索路径中查找同名文件
        3. 验证文件完整性
        """
        if primary_path.exists() and primary_path.is_file():
            error = self.check_file(primary_path, expected_size, expected_hash)
            if error is None:
                self._record_hit(primary_path.stat().st_size)
                return primary_path

        if not search_paths:
            self._record_miss()
            return None

        filename = primary_path.name
        parent_dirs = primary_path.parent

        for search_path in search_paths:
            candidate = search_path / filename

            if candidate == primary_path:
                continue

            if candidate.exists() and candidate.is_file():
                error = self.check_file(candidate, expected_size, expected_hash)
                if error is None:
                    self._record_hit(candidate.stat().st_size)
                    return candidate

        self._record_miss()
        return None

    def find_matching_file_by_content(
        self,
        target_path: Path,
        search_directory: Path,
        size_tolerance: float = 0.01,
    ) -> Path | None:
        """
        根据文件内容特征查找匹配文件

        改进策略：
        1. 先用文件签名匹配类型
        2. 再用大小+快速哈希（首尾块）预检
        3. 最后才计算完整哈希
        """
        if not search_directory.exists():
            return None

        target_size = target_path.stat().st_size if target_path.exists() else -1
        target_signature = self._detect_signature(target_path) if self.enable_content_matching else None
        target_quick_hash = self._get_quick_hash(target_path) if self.enable_content_matching else None

        for candidate in search_directory.rglob("*"):
            if not candidate.is_file() or candidate == target_path:
                continue

            if candidate.suffix in (".tmp", ".part", ".downloading"):
                continue

            candidate_size = candidate.stat().st_size

            if target_size > 0 and candidate_size > 0:
                size_diff = abs(target_size - candidate_size) / target_size
                if size_diff > size_tolerance:
                    continue

            if target_signature:
                candidate_sig = self._detect_signature(candidate)
                if candidate_sig and candidate_sig != target_signature:
                    continue

            if target_quick_hash:
                candidate_quick = self._get_quick_hash(candidate)
                if candidate_quick and candidate_quick != target_quick_hash:
                    self._stats["quick_hash_hits"] += 1
                    continue

            if self.check_file(candidate) is None:
                self._stats["content_matched"] += 1
                return candidate

        return None

    def _detect_signature(self, file_path: Path) -> str | None:
        """检测文件签名（magic bytes）"""
        path_str = str(file_path)

        if path_str in self._signature_cache:
            return self._signature_cache[path_str]

        try:
            with open(file_path, "rb") as f:
                header = f.read(16)

            for signature, file_type in FILE_SIGNATURES.items():
                if header.startswith(signature):
                    self._signature_cache[path_str] = file_type
                    return file_type

            self._signature_cache[path_str] = None
            return None
        except Exception:
            return None

    def _get_quick_hash(self, file_path: Path) -> str | None:
        """
        获取快速哈希（首尾块组合）
        改进：使用首块+尾块组合，比PCL的单点哈希更可靠
        """
        path_str = str(file_path)

        if path_str in self._quick_hash_cache:
            return self._quick_hash_cache[path_str]

        try:
            file_size = file_path.stat().st_size

            with open(file_path, "rb") as f:
                head = f.read(min(self.quick_hash_size, file_size))

                if file_size > self.quick_hash_size * 2:
                    f.seek(-self.quick_hash_size, 2)
                    tail = f.read(self.quick_hash_size)
                else:
                    tail = b""

            combined = head + tail
            quick_hash = hashlib.new(self.hash_algorithm, combined).hexdigest()
            self._quick_hash_cache[path_str] = quick_hash
            return quick_hash
        except Exception:
            return None

    def _get_cached_hash(self, file_path: Path) -> str | None:
        """获取文件哈希（带缓存）"""
        path_str = str(file_path)

        if path_str in self._cache:
            return self._cache[path_str]

        try:
            hash_value = calculate_file_hash(file_path, self.hash_algorithm)
            self._cache[path_str] = hash_value
            return hash_value
        except Exception:
            self._cache[path_str] = None
            return None

    def _record_hit(self, file_size: int) -> None:
        """记录缓存命中"""
        self._stats["hits"] += 1
        self._stats["bytes_saved"] += file_size

    def _record_miss(self) -> None:
        """记录缓存未命中"""
        self._stats["misses"] += 1

    def get_stats(self) -> dict[str, Any]:
        """获取统计信息"""
        total = self._stats["checks"]
        hit_rate = self._stats["hits"] / total if total > 0 else 0.0

        return {
            "checks": self._stats["checks"],
            "hits": self._stats["hits"],
            "misses": self._stats["misses"],
            "hit_rate": f"{hit_rate:.1%}",
            "bytes_saved": self._stats["bytes_saved"],
            "bytes_saved_formatted": format_size(self._stats["bytes_saved"]),
            "quick_hash_hits": self._stats["quick_hash_hits"],
            "content_matched": self._stats["content_matched"],
        }

    def clear_cache(self) -> None:
        """清空所有缓存"""
        self._cache.clear()
        self._quick_hash_cache.clear()
        self._signature_cache.clear()


class MultiSourceManager:
    """
    多源备份管理器 - 仿照PCL的多源备份策略

    功能：
    1. 管理多个下载源
    2. 按优先级排序
    3. 故障自动切换
    4. 支持单线程专用的源
    """

    def __init__(self) -> None:
        self._sources: list[dict[str, Any]] = []
        self._single_thread_sources: list[dict[str, Any]] = []
        self._current_index: int = 0
        self._lock: Any = None

        import asyncio

        self._lock = asyncio.Lock()

    def add_source(self, url: str, priority: int = 0, single_thread_only: bool = False) -> None:
        """添加一个下载源"""
        source = {
            "url": url,
            "priority": priority,
            "fail_count": 0,
            "is_failed": False,
            "is_single_thread": single_thread_only,
            "last_error": None,
        }

        if single_thread_only:
            self._single_thread_sources.append(source)
        else:
            self._sources.append(source)

        self._sources.sort(key=lambda s: (-s["priority"], s["fail_count"]))

    def get_next_available(self, prefer_multi_thread: bool = True) -> dict[str, Any] | None:
        """获取下一个可用的下载源"""
        if prefer_multi_thread and not self._single_thread_only_mode:
            for source in self._sources:
                if not source["is_failed"]:
                    return source

            if self._single_thread_sources:
                return self._single_thread_sources[0]

        for source in self._single_thread_sources:
            if not source["is_failed"]:
                return source

        for source in self._sources:
            if not source["is_failed"]:
                return source

        return None

    def mark_source_failed(self, url: str, error: str | None = None) -> None:
        """标记源为失败"""
        for source in self._sources + self._single_thread_sources:
            if source["url"] == url:
                source["fail_count"] += 1
                source["last_error"] = error

                if self._should_disable(source):
                    source["is_failed"] = True
                break

    def mark_source_success(self, url: str) -> None:
        """标记源成功（重置失败计数）"""
        for source in self._sources + self._single_thread_sources:
            if source["url"] == url:
                source["fail_count"] = 0
                source["last_error"] = None
                break

    def _should_disable(self, source: dict[str, Any]) -> bool:
        """判断是否应该禁用此源"""
        if source["is_single_thread"]:
            return source["fail_count"] >= 3

        url = source["url"]
        error = source.get("last_error", "") or ""

        if "416" in error or "Range" in error:
            return True
        if "404" in error:
            return True
        if "502" in error or "503" in error:
            return True

        if source["fail_count"] >= 5:
            return True

        if "bmclapi" in url.lower():
            if "403" in error or "429" in error:
                return False

        return False

    def reset_all(self) -> None:
        """重置所有源状态"""
        for source in self._sources + self._single_thread_sources:
            source["is_failed"] = False
            source["fail_count"] = 0
            source["last_error"] = None

    @property
    def has_available_source(self) -> bool:
        """是否有可用的下载源"""
        for source in self._sources + self._single_thread_sources:
            if not source["is_failed"]:
                return True
        return False

    @property
    def _single_thread_only_mode(self) -> bool:
        """是否所有多线程源都已失败"""
        return all(s["is_failed"] for s in self._sources)

    def get_stats(self) -> dict[str, Any]:
        """获取源统计信息"""
        all_sources = self._sources + self._single_thread_sources
        return {
            "total_sources": len(all_sources),
            "available_sources": len([s for s in all_sources if not s["is_failed"]]),
            "failed_sources": len([s for s in all_sources if s["is_failed"]]),
            "current_source": self._sources[self._current_index]["url"] if self._sources else None,
        }


class SharedFileRegistry:
    """
    共享文件注册表 - 仿照PCL的AllFiles设计

    功能：
    1. 全局文件字典，避免重复下载
    2. 多个任务共享同一文件的下载状态
    """

    def __init__(self) -> None:
        self._files: dict[str, dict[str, Any]] = {}
        self._lock: Any = None

        import asyncio

        self._lock = asyncio.Lock()

    async def register(self, file_id: str, task_id: str, info: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """
        注册一个文件下载任务

        Returns:
            如果文件已存在且正在下载，返回现有文件信息
            否则返回None并注册新文件
        """
        async with self._lock:
            if file_id in self._files:
                existing = self._files[file_id]
                if existing["state"] in ("downloading", "waiting"):
                    existing["waiting_tasks"].append(task_id)
                    return existing

            self._files[file_id] = {
                "file_id": file_id,
                "state": "waiting",
                "downloaded": 0,
                "total_size": 0,
                "speed": 0.0,
                "waiting_tasks": [task_id],
                "info": info or {},
            }
            return None

    async def unregister(self, file_id: str, task_id: str) -> None:
        """取消注册一个任务"""
        async with self._lock:
            if file_id in self._files:
                file_info = self._files[file_id]
                if task_id in file_info["waiting_tasks"]:
                    file_info["waiting_tasks"].remove(task_id)

                if not file_info["waiting_tasks"]:
                    del self._files[file_id]

    async def update_state(self, file_id: str, state: str) -> None:
        """更新文件状态"""
        async with self._lock:
            if file_id in self._files:
                self._files[file_id]["state"] = state

    async def update_progress(self, file_id: str, downloaded: int, speed: float = 0.0) -> None:
        """更新下载进度"""
        async with self._lock:
            if file_id in self._files:
                self._files[file_id]["downloaded"] = downloaded
                if speed > 0:
                    self._files[file_id]["speed"] = speed

    def get_file_info(self, file_id: str) -> dict[str, Any] | None:
        """获取文件信息（同步）"""
        return self._files.get(file_id)

    def get_all_files(self) -> dict[str, dict[str, Any]]:
        """获取所有文件（同步）"""
        return self._files.copy()

    def get_stats(self) -> dict[str, Any]:
        """获取统计信息"""
        states = {}
        for file_info in self._files.values():
            state = file_info["state"]
            states[state] = states.get(state, 0) + 1

        return {
            "total_files": len(self._files),
            "by_state": states,
        }
