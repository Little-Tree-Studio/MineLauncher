import asyncio
import inspect
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from .utils import MovingAverage, format_size, format_speed, format_time


@dataclass
class SpeedSample:
    timestamp: float
    bytes_downloaded: int


@dataclass
class DownloadStats:
    total_size: int = 0
    downloaded: int = 0
    speed: float = 0.0
    average_speed: float = 0.0
    smoothed_speed: float = 0.0
    peak_speed: float = 0.0
    eta: float = -1.0
    progress: float = 0.0
    active_workers: int = 0
    total_chunks: int = 0
    completed_chunks: int = 0
    failed_chunks: int = 0
    start_time: float = 0.0
    elapsed_time: float = 0.0
    is_active: bool = False
    unknown_size: bool = False
    speed_stability: float = 1.0

    @property
    def remaining(self) -> int:
        return max(0, self.total_size - self.downloaded)

    @property
    def formatted_size(self) -> str:
        return format_size(self.downloaded)

    @property
    def formatted_total(self) -> str:
        return format_size(self.total_size)

    @property
    def formatted_speed(self) -> str:
        return format_speed(self.speed)

    @property
    def formatted_eta(self) -> str:
        return format_time(self.eta)


class SpeedMonitor:
    def __init__(
        self,
        window_size: int = 20,
        sample_interval: float = 0.5,
        speed_callback: Callable[[float], None] | None = None,
    ) -> None:
        self.window_size = window_size
        self.sample_interval = sample_interval
        self.speed_callback = speed_callback
        self._samples: deque[SpeedSample] = deque(maxlen=window_size)
        self._last_sample_time: float = 0.0
        self._last_downloaded: int = 0
        self._current_speed: float = 0.0
        self._instant_speed: float = 0.0
        self._speed_history: list[float] = []
        self._moving_average = MovingAverage(window_size=20)
        self._peak_speed: float = 0.0
        self._lock = asyncio.Lock()
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._ewma_speed: float = 0.0
        self._ewma_alpha: float = 0.15
        self._adaptive_alpha: bool = True
        self._speed_variance: float = 0.0

    @property
    def current_speed(self) -> float:
        return self._current_speed

    @property
    def average_speed(self) -> float:
        return self._moving_average.get_average()

    @property
    def smoothed_speed(self) -> float:
        return self._ewma_speed if self._ewma_speed > 0 else self._moving_average.get_smoothed_average(0.2)

    @property
    def peak_speed(self) -> float:
        return self._peak_speed

    @property
    def speed_trend(self) -> float:
        return self._moving_average.get_trend()

    @property
    def speed_stability(self) -> float:
        return self._moving_average.get_stability()

    @property
    def is_stable(self) -> bool:
        return self._moving_average.is_stable(0.3)

    def add_sample(self, total_downloaded: int) -> float:
        now = time.time()
        sample = SpeedSample(timestamp=now, bytes_downloaded=total_downloaded)
        self._samples.append(sample)
        if len(self._samples) >= 2:
            first = self._samples[0]
            last = self._samples[-1]
            time_diff = last.timestamp - first.timestamp
            if time_diff > 0:
                bytes_diff = last.bytes_downloaded - first.bytes_downloaded
                raw_speed = bytes_diff / time_diff

                if len(self._samples) >= 3:
                    prev_sample = self._samples[-2]
                    prev_time_diff = last.timestamp - prev_sample.timestamp
                    if prev_time_diff > 0:
                        self._instant_speed = (last.bytes_downloaded - prev_sample.bytes_downloaded) / prev_time_diff
                    else:
                        self._instant_speed = raw_speed
                else:
                    self._instant_speed = raw_speed

                if self._ewma_speed == 0:
                    self._ewma_speed = raw_speed
                else:
                    if self._adaptive_alpha:
                        alpha = self._calculate_adaptive_alpha(raw_speed)
                    else:
                        alpha = self._ewma_alpha
                    self._ewma_speed = alpha * raw_speed + (1 - alpha) * self._ewma_speed

                hybrid_speed = 0.3 * self._instant_speed + 0.7 * self._ewma_speed
                self._current_speed = hybrid_speed
                self._moving_average.add(self._current_speed)
                if self._current_speed > self._peak_speed:
                    self._peak_speed = self._current_speed
                if self.speed_callback:
                    self.speed_callback(self._current_speed)
        return self._current_speed

    def _calculate_adaptive_alpha(self, raw_speed: float) -> float:
        """根据速度变化率自适应调整alpha"""
        if len(self._speed_history) < 5:
            return self._ewma_alpha

        recent = self._speed_history[-5:]
        mean = sum(recent) / len(recent)
        if mean > 0:
            change_ratio = abs(raw_speed - mean) / mean
            if change_ratio > 0.5:
                return 0.3
            elif change_ratio > 0.3:
                return 0.2
            elif change_ratio > 0.1:
                return 0.15
            else:
                return 0.1
        return self._ewma_alpha

    def reset(self) -> None:
        self._samples.clear()
        self._current_speed = 0.0
        self._instant_speed = 0.0
        self._peak_speed = 0.0
        self._speed_history.clear()
        self._moving_average = MovingAverage(window_size=20)
        self._ewma_speed = 0.0

    def get_instantaneous_speed(self, bytes_downloaded: int, time_interval: float = 1.0) -> float:
        if time_interval <= 0:
            return self._current_speed
        now = time.time()
        recent_bytes = bytes_downloaded - self._last_downloaded
        if now - self._last_sample_time >= time_interval:
            speed = recent_bytes / (now - self._last_sample_time)
            self._last_sample_time = now
            self._last_downloaded = bytes_downloaded
            instant = speed
            hybrid = 0.4 * instant + 0.6 * self._current_speed if self._current_speed > 0 else instant
            return hybrid
        return self._current_speed


class DownloadMonitor:
    def __init__(
        self,
        total_size: int = 0,
        update_interval: float = 0.5,
        progress_callback: Callable[..., None] | None = None,
        speed_window_size: int = 10,
    ) -> None:
        self.total_size = total_size
        self.update_interval = update_interval
        self.progress_callback = progress_callback
        self._speed_monitor = SpeedMonitor(window_size=speed_window_size)
        self._downloaded: int = 0
        self._start_time: float = 0.0
        self._is_active: bool = False
        self._active_workers: int = 0
        self._total_chunks: int = 0
        self._completed_chunks: int = 0
        self._failed_chunks: int = 0
        self._lock = asyncio.Lock()
        self._last_update_time: float = 0.0
        self._pause_time: float = 0.0
        self._total_pause_time: float = 0.0

    @property
    def downloaded(self) -> int:
        return self._downloaded

    @property
    def unknown_size(self) -> bool:
        return self.total_size <= 0

    @property
    def progress(self) -> float:
        if self.total_size <= 0:
            return -1.0
        return (self._downloaded / self.total_size) * 100

    @property
    def eta(self) -> float:
        if self.total_size <= 0:
            return -1
        speed = self._speed_monitor.smoothed_speed
        if speed <= 0:
            speed = self._speed_monitor.average_speed
        if speed <= 0:
            return -1
        remaining = self.total_size - self._downloaded
        return remaining / speed

    @property
    def elapsed_time(self) -> float:
        if self._start_time == 0:
            return 0.0
        elapsed = time.time() - self._start_time - self._total_pause_time
        return max(0.0, elapsed)

    def start(self) -> None:
        self._start_time = time.time()
        self._is_active = True
        self._speed_monitor.reset()

    def pause(self) -> None:
        if self._is_active:
            self._pause_time = time.time()

    def resume(self) -> None:
        if self._pause_time > 0:
            self._total_pause_time += time.time() - self._pause_time
            self._pause_time = 0.0

    def stop(self) -> None:
        self._is_active = False

    def update_downloaded(self, bytes_count: int) -> None:
        self._downloaded = bytes_count
        self._speed_monitor.add_sample(bytes_count)
        self._maybe_notify_callback()

    def increment_downloaded(self, bytes_count: int) -> None:
        self._downloaded += bytes_count
        self._speed_monitor.add_sample(self._downloaded)
        self._maybe_notify_callback()

    def set_chunk_stats(self, total: int, completed: int, failed: int) -> None:
        self._total_chunks = total
        self._completed_chunks = completed
        self._failed_chunks = failed

    def set_active_workers(self, count: int) -> None:
        self._active_workers = count

    def get_stats(self) -> DownloadStats:
        return DownloadStats(
            total_size=self.total_size,
            downloaded=self._downloaded,
            speed=self._speed_monitor.current_speed,
            average_speed=self._speed_monitor.average_speed,
            smoothed_speed=self._speed_monitor.smoothed_speed,
            peak_speed=self._speed_monitor.peak_speed,
            eta=self.eta,
            progress=self.progress,
            active_workers=self._active_workers,
            total_chunks=self._total_chunks,
            completed_chunks=self._completed_chunks,
            failed_chunks=self._failed_chunks,
            start_time=self._start_time,
            elapsed_time=self.elapsed_time,
            is_active=self._is_active,
            unknown_size=self.unknown_size,
            speed_stability=self._speed_monitor.speed_stability,
        )

    def _maybe_notify_callback(self) -> None:
        if not self.progress_callback:
            return
        now = time.time()
        if now - self._last_update_time >= self.update_interval:
            self._last_update_time = now
            result = self.progress_callback(
                self._downloaded,
                self.total_size,
                self._speed_monitor.current_speed,
                int(self.eta),
                unknown_size=self.unknown_size,
            )
            if inspect.isawaitable(result):
                asyncio.create_task(result)

    def reset(self) -> None:
        self._downloaded = 0
        self._start_time = 0.0
        self._is_active = False
        self._active_workers = 0
        self._total_chunks = 0
        self._completed_chunks = 0
        self._failed_chunks = 0
        self._total_pause_time = 0.0
        self._pause_time = 0.0
        self._speed_monitor.reset()

    def is_speed_stable(self, threshold: float = 0.2) -> bool:
        trend = self._speed_monitor.speed_trend
        return abs(trend) < threshold

    def is_speed_declining(self) -> bool:
        return self._speed_monitor.speed_trend < -0.1

    def is_speed_improving(self) -> bool:
        return self._speed_monitor.speed_trend > 0.1
