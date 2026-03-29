"""下载管理器 - 支持任务队列、进度跟踪、历史记录"""

import threading
import time
import json
from typing import Callable, Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from datetime import datetime


class TaskStatus(Enum):
    """任务状态"""

    WAITING = "等待中"
    DOWNLOADING = "下载中"
    PAUSED = "已暂停"
    COMPLETED = "已完成"
    FAILED = "失败"
    CANCELLED = "已取消"
    VERIFYING = "验证中"


@dataclass
class ChunkProgress:
    """分块进度"""

    chunk_id: int
    start: int
    end: int
    downloaded: int = 0
    speed: float = 0.0
    status: str = "pending"

    @property
    def progress(self) -> float:
        size = self.end - self.start
        return self.downloaded / size if size > 0 else 0.0


@dataclass
class DownloadTask:
    """下载任务"""

    task_id: str
    name: str
    version_id: str = ""
    target_dir: str = ""
    custom_name: str = ""
    total: int = 0
    downloaded: int = 0
    status: TaskStatus = TaskStatus.WAITING
    progress: float = 0.0
    speed: float = 0.0
    eta: float = 0.0  # 预计剩余时间(秒)
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    file_count: int = 0
    completed_files: int = 0
    current_file: str = ""
    connections: int = 0
    chunks: List[ChunkProgress] = field(default_factory=list)

    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _callbacks: List[Callable[["DownloadTask"], None]] = field(
        default_factory=list, repr=False
    )
    _cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)
    _pause_event: threading.Event = field(default_factory=threading.Event, repr=False)
    _file_paths: List[str] = field(default_factory=list, repr=False)

    def update(self, **kwargs):
        """更新任务状态"""
        with self._lock:
            for key, value in kwargs.items():
                if hasattr(self, key):
                    setattr(self, key, value)

            # 计算进度
            if self.total > 0:
                self.progress = min(self.downloaded / self.total, 1.0)

            # 计算ETA
            if self.speed > 0 and self.total > self.downloaded:
                self.eta = (self.total - self.downloaded) / self.speed

            # 通知回调
            for cb in self._callbacks:
                try:
                    cb(self)
                except Exception:
                    pass

    def on_update(self, callback: Callable[["DownloadTask"], None]):
        """注册更新回调"""
        self._callbacks.append(callback)

    def cancel(self):
        """取消任务"""
        self._cancel_event.set()
        self.status = TaskStatus.CANCELLED
        for cb in self._callbacks:
            try:
                cb(self)
            except Exception:
                pass

    def pause(self):
        """暂停任务"""
        self._pause_event.set()
        self.status = TaskStatus.PAUSED

    def resume(self):
        """恢复任务"""
        self._pause_event.clear()
        self.status = TaskStatus.DOWNLOADING

    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def is_paused(self) -> bool:
        return self._pause_event.is_set()

    def add_file_path(self, path: str):
        """添加文件路径"""
        with self._lock:
            if path not in self._file_paths:
                self._file_paths.append(path)

    def get_file_paths(self) -> List[str]:
        """获取所有文件路径"""
        with self._lock:
            return self._file_paths.copy()

    def delete_files(self):
        """删除所有相关文件"""
        import os

        for path in self._file_paths:
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass
        # 清理临时文件
        for path in self._file_paths:
            temp_path = path + ".tmp"
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass
            resume_path = path + ".resume"
            if os.path.exists(resume_path):
                try:
                    os.remove(resume_path)
                except Exception:
                    pass

    def get_duration(self) -> float:
        """获取下载耗时(秒)"""
        if self.started_at is None:
            return 0
        end_time = self.completed_at or time.time()
        return end_time - self.started_at

    def get_average_speed(self) -> float:
        """获取平均速度"""
        duration = self.get_duration()
        if duration > 0 and self.downloaded > 0:
            return self.downloaded / duration
        return 0

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典(用于历史记录)"""
        return {
            "task_id": self.task_id,
            "name": self.name,
            "version_id": self.version_id,
            "target_dir": self.target_dir,
            "custom_name": self.custom_name,
            "total": self.total,
            "downloaded": self.downloaded,
            "status": self.status.value,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration": self.get_duration(),
            "average_speed": self.get_average_speed(),
            "file_count": self.file_count,
            "completed_files": self.completed_files,
            "error": self.error,
        }


@dataclass
class DownloadHistory:
    """下载历史记录"""

    task_id: str
    name: str
    version_id: str
    status: str
    total: int
    downloaded: int
    created_at: float
    completed_at: Optional[float]
    duration: float
    average_speed: float
    file_count: int
    completed_files: int
    target_dir: str = ""
    custom_name: str = ""
    error: str = ""

    @classmethod
    def from_task(cls, task: DownloadTask) -> "DownloadHistory":
        return cls(
            task_id=task.task_id,
            name=task.name,
            version_id=task.version_id,
            status=task.status.value,
            total=task.total,
            downloaded=task.downloaded,
            created_at=task.created_at,
            completed_at=task.completed_at,
            duration=task.get_duration(),
            average_speed=task.get_average_speed(),
            file_count=task.file_count,
            completed_files=task.completed_files,
            target_dir=task.target_dir,
            custom_name=task.custom_name,
            error=task.error or "",
        )

    def format_size(self, size: int) -> str:
        """格式化文件大小"""
        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"

    def format_speed(self, speed: float) -> str:
        """格式化速度"""
        return self.format_size(int(speed)) + "/s"

    def format_duration(self, seconds: float) -> str:
        """格式化时长"""
        if seconds < 60:
            return f"{seconds:.0f}秒"
        elif seconds < 3600:
            minutes = seconds // 60
            secs = seconds % 60
            return f"{minutes:.0f}分{secs:.0f}秒"
        else:
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            return f"{hours:.0f}时{minutes:.0f}分"

    def format_time(self, timestamp: float) -> str:
        """格式化时间戳"""
        return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")


class DownloadManager:
    """下载管理器单例"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        self.tasks: Dict[str, DownloadTask] = {}
        self.history: List[DownloadHistory] = []
        self._archived_task_ids: set[str] = set()
        self._listeners: List[Callable[[], None]] = []
        self._history_lock = threading.Lock()

        # 加载历史记录
        self._load_history()

    @classmethod
    def instance(cls) -> "DownloadManager":
        return cls()

    def add_task(self, task: DownloadTask):
        """添加任务"""
        self.tasks[task.task_id] = task
        self._notify()

    def get_task(self, task_id: str) -> Optional[DownloadTask]:
        """获取任务"""
        return self.tasks.get(task_id)

    def cancel_task(self, task_id: str):
        """取消任务"""
        task = self.tasks.get(task_id)
        if task:
            task.cancel()
            self._notify()

    def pause_task(self, task_id: str):
        """暂停任务"""
        task = self.tasks.get(task_id)
        if task:
            task.pause()
            self._notify()

    def resume_task(self, task_id: str):
        """恢复任务"""
        task = self.tasks.get(task_id)
        if task:
            task.resume()
            self._notify()

    def remove_task(self, task_id: str):
        """移除任务"""
        if task_id in self.tasks:
            # 移除前先归档，避免已完成/失败任务丢失
            self.archive_task(task_id)

            del self.tasks[task_id]
            self._notify()

    def archive_task(self, task_id: str):
        """将任务写入历史记录（幂等，避免重复写入）"""
        task = self.tasks.get(task_id)
        if not task:
            return
        if task_id in self._archived_task_ids:
            return

        history = DownloadHistory.from_task(task)
        with self._history_lock:
            self.history.insert(0, history)
            self.history = self.history[:200]  # 保留最近200条
        self._archived_task_ids.add(task_id)
        self._save_history()
        self._notify()

    def get_tasks(self) -> List[DownloadTask]:
        """获取所有任务"""
        return list(self.tasks.values())

    def get_active_tasks(self) -> List[DownloadTask]:
        """获取活动任务"""
        return [
            t
            for t in self.tasks.values()
            if t.status
            in [TaskStatus.DOWNLOADING, TaskStatus.WAITING, TaskStatus.PAUSED]
        ]

    def get_completed_tasks(self) -> List[DownloadTask]:
        """获取已完成任务"""
        return [t for t in self.tasks.values() if t.status == TaskStatus.COMPLETED]

    def get_history(self) -> List[DownloadHistory]:
        """获取下载历史"""
        with self._history_lock:
            return self.history.copy()

    def clear_history(self):
        """清空历史记录"""
        with self._history_lock:
            self.history.clear()
        self._save_history()
        self._notify()

    def clear_completed_tasks(self):
        """清除已完成的任务"""
        completed = [
            tid for tid, t in self.tasks.items() if t.status == TaskStatus.COMPLETED
        ]
        for tid in completed:
            self.remove_task(tid)

    def on_change(self, callback: Callable[[], None]):
        """注册变更回调"""
        self._listeners.append(callback)

    def _notify(self):
        """通知所有监听器"""
        for cb in self._listeners:
            try:
                cb()
            except Exception:
                pass

    def _save_history(self):
        """保存历史记录"""
        try:
            from ..services.config_service import ConfigService

            cfg = ConfigService()
            history_data = [asdict(h) for h in self.history[:100]]
            config = cfg.load()
            config["DownloadHistory"] = history_data
            cfg.save(config)
        except Exception:
            pass

    def _load_history(self):
        """加载历史记录"""
        try:
            from ..services.config_service import ConfigService

            cfg = ConfigService()
            config = cfg.load()
            history_data = config.get("DownloadHistory", [])
            with self._history_lock:
                self.history = [
                    DownloadHistory(**h) for h in history_data if isinstance(h, dict)
                ]
        except Exception:
            self.history = []

    def get_statistics(self) -> Dict[str, Any]:
        """获取下载统计"""
        total_downloads = len(self.history) + len(self.tasks)
        completed = len([h for h in self.history if h.status == "已完成"])
        failed = len([h for h in self.history if h.status == "失败"])

        total_size = sum(h.downloaded for h in self.history if h.status == "已完成")
        total_time = sum(h.duration for h in self.history if h.status == "已完成")

        avg_speed = total_size / total_time if total_time > 0 else 0

        return {
            "total_downloads": total_downloads,
            "completed": completed,
            "failed": failed,
            "total_size": total_size,
            "average_speed": avg_speed,
            "active_tasks": len(self.get_active_tasks()),
        }
