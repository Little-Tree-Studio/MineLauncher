import asyncio
import os
import platform
import signal
import sys
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

WINDOWS = platform.system() == "Windows"
MACOS = platform.system() == "Darwin"
LINUX = platform.system() == "Linux"
FREEBSD = platform.system() == "FreeBSD"


@dataclass
class PlatformInfo:
    system: str
    release: str
    version: str
    machine: str
    processor: str
    python_version: str

    @property
    def is_windows(self) -> bool:
        return self.system == "Windows"

    @property
    def is_macos(self) -> bool:
        return self.system == "Darwin"

    @property
    def is_linux(self) -> bool:
        return self.system == "Linux"

    @property
    def is_unix(self) -> bool:
        return self.system in ("Darwin", "Linux", "FreeBSD")

    @property
    def supports_signals(self) -> bool:
        return not self.is_windows

    @property
    def supports_long_paths(self) -> bool:
        return self.is_windows

    @property
    def supports_unix_permissions(self) -> bool:
        return self.is_unix


def get_platform_info() -> PlatformInfo:
    return PlatformInfo(
        system=platform.system(),
        release=platform.release(),
        version=platform.version(),
        machine=platform.machine(),
        processor=platform.processor() or "unknown",
        python_version=platform.python_version(),
    )


def get_max_path_length() -> int:
    if WINDOWS:
        return 260
    elif MACOS:
        return 1024
    elif LINUX:
        try:
            with open("/proc/sys/fs/name_max") as f:
                return int(f.read().strip())
        except Exception:
            return 255
    else:
        return 255


def normalize_path(path: str | Path) -> Path:
    path = Path(path)
    if WINDOWS:
        path_str = str(path.resolve())
        if len(path_str) >= 260 and not path_str.startswith("\\?\\"):
            path = Path("\\?\\" + path_str)
    return path


def create_secure_file(path: Path, permissions: int | None = None) -> None:
    path = normalize_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if WINDOWS:
        path.touch()
    else:
        if permissions is None:
            permissions = 0o644
        path.touch(mode=permissions)


def set_file_permissions(path: Path, permissions: int) -> None:
    if not WINDOWS:
        os.chmod(path, permissions)


def is_path_valid(path: Path) -> bool:
    try:
        path = normalize_path(path)
        max_length = get_max_path_length()
        if WINDOWS and str(path).startswith("\\?\\"):
            return True
        return len(str(path)) <= max_length
    except Exception:
        return False


def get_temp_directory() -> Path:
    if WINDOWS:
        temp = os.environ.get("TEMP") or os.environ.get("TMP")
        if temp:
            return Path(temp)
    return Path(tempfile.gettempdir())


def get_default_download_directory() -> Path:
    if WINDOWS or MACOS:
        downloads = Path.home() / "Downloads"
        if downloads.exists():
            return downloads
    elif LINUX:
        xdg_download = os.environ.get("XDG_DOWNLOAD_DIR")
        if xdg_download:
            return Path(xdg_download)
        downloads = Path.home() / "Downloads"
        if downloads.exists():
            return downloads
    return Path.home()


class SignalHandler:
    def __init__(self, callback: Callable[[], None] | None = None) -> None:
        self.callback = callback
        self._original_handlers: dict[signal.Signals, Any] = {}
        self._installed = False

    def install(self) -> None:
        if self._installed:
            return
        if WINDOWS:
            try:
                signal.signal(signal.SIGINT, self._handle_signal)
                signal.signal(signal.SIGTERM, self._handle_signal)
            except Exception:
                pass
        else:
            signals_to_handle = [signal.SIGINT, signal.SIGTERM]
            if hasattr(signal, "SIGHUP"):
                signals_to_handle.append(signal.SIGHUP)
            for sig in signals_to_handle:
                with suppress(Exception):
                    self._original_handlers[sig] = signal.signal(sig, self._handle_signal)
        self._installed = True

    def _handle_signal(self, signum: int, frame: Any) -> None:
        if self.callback:
            self.callback()

    def restore(self) -> None:
        if not self._installed:
            return
        for sig, handler in self._original_handlers.items():
            with suppress(Exception):
                signal.signal(sig, handler)
        self._original_handlers.clear()
        self._installed = False


@contextmanager
def signal_context(callback: Callable[[], None] | None = None) -> Iterator[SignalHandler]:
    handler = SignalHandler(callback)
    handler.install()
    try:
        yield handler
    finally:
        handler.restore()


def setup_event_loop_policy() -> None:
    if WINDOWS and sys.version_info >= (3, 8):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def get_cpu_count() -> int:
    return os.cpu_count() or 4


def get_memory_info() -> dict[str, int]:
    result: dict[str, int] = {"total": 0, "available": 0, "used": 0}
    try:
        if LINUX:
            with open("/proc/meminfo") as f:
                meminfo: dict[str, int] = {}
                for line in f:
                    if ":" in line:
                        key, value = line.split(":", 1)
                        key = key.strip()
                        value = value.strip()
                        if value.endswith(" kB"):
                            value = int(value[:-3]) * 1024
                        else:
                            try:
                                value = int(value)
                            except ValueError:
                                continue
                        meminfo[key] = value
                result["total"] = meminfo.get("MemTotal", 0)
                result["available"] = meminfo.get("MemAvailable", meminfo.get("MemFree", 0))
                result["used"] = result["total"] - result["available"]
        elif MACOS:
            import subprocess
            output = subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True)
            result["total"] = int(output.strip())
        elif WINDOWS:
            import ctypes
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                ]
            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(stat)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            result["total"] = stat.ullTotalPhys
            result["available"] = stat.ullAvailPhys
            result["used"] = result["total"] - result["available"]
    except Exception:
        pass
    return result
