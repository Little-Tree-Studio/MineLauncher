import threading
from typing import Callable, Dict, List, Optional


class DownloadTask:
    def __init__(self, task_id: str, name: str, total: int = 0):
        self.task_id = task_id
        self.name = name
        self.total = total
        self.downloaded = 0
        self.status = "等待中"
        self.progress = 0.0
        self.error: Optional[str] = None
        self._lock = threading.Lock()
        self._callbacks: List[Callable[["DownloadTask"], None]] = []
        self._cancel_event = threading.Event()
        self._file_path: Optional[str] = None  # 下载目标文件路径
        self._temp_path: Optional[str] = None  # 临时文件路径

    def update(self, downloaded: int, total: Optional[int] = None, status: Optional[str] = None, error: Optional[str] = None):
        with self._lock:
            self.downloaded = downloaded
            if total is not None:
                self.total = total
            if self.total > 0:
                self.progress = self.downloaded / self.total
            if status:
                self.status = status
            if error:
                self.error = error
            for cb in self._callbacks:
                cb(self)

    def on_update(self, callback: Callable[["DownloadTask"], None]):
        self._callbacks.append(callback)

    def cancel(self):
        self._cancel_event.set()
        self.status = "已取消"
        for cb in self._callbacks:
            cb(self)

    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def set_file_paths(self, file_path: str, temp_path: str):
        self._file_path = file_path
        self._temp_path = temp_path

    def delete_files(self):
        import os
        if self._file_path and os.path.exists(self._file_path):
            try:
                os.remove(self._file_path)
            except Exception:
                pass
        if self._temp_path and os.path.exists(self._temp_path):
            try:
                os.remove(self._temp_path)
            except Exception:
                pass

class DownloadManager:
    _instance = None
    _lock = threading.Lock()

    def __init__(self):
        self.tasks: Dict[str, DownloadTask] = {}
        self._listeners: List[Callable[[], None]] = []

    @classmethod
    def instance(cls):
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = DownloadManager()
        return cls._instance

    def add_task(self, task: DownloadTask):
        self.tasks[task.task_id] = task
        self._notify()

    def cancel_task(self, task_id: str):
        task = self.tasks.get(task_id)
        if task:
            task.cancel()
            self._notify()

    def remove_task(self, task_id: str):
        if task_id in self.tasks:
            del self.tasks[task_id]
            self._notify()

    def get_tasks(self) -> List[DownloadTask]:
        return list(self.tasks.values())

    def on_change(self, callback: Callable[[], None]):
        self._listeners.append(callback)

    def _notify(self):
        for cb in self._listeners:
            cb()
