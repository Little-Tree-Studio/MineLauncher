import asyncio
import math
import time
from dataclasses import dataclass, field
from typing import Callable

from .utils import MovingAverage


@dataclass
class ThreadPoolStats:
    total_threads: int = 0
    active_threads: int = 0
    idle_threads: int = 0
    total_speed: float = 0.0
    avg_speed: float = 0.0
    speed_trend: float = 0.0
    speed_variance: float = 0.0
    predicted_speed: float = 0.0
    low_speed_count: int = 0


class GlobalThreadPool:
    """
    全局线程池管理器 - 基于PCL改进的智能调度算法

    改进点：
    1. 基于文件大小和优先级的智能分配
    2. 指数加权移动平均(EWMA)替代简单平均
    3. 速度趋势预测，决定是否追加线程
    4. 动态负载均衡，考虑各文件完成进度
    """

    def __init__(
        self,
        max_total_threads: int = 15,
        min_speed_threshold: float = 256 * 1024,
        speed_check_interval: float = 0.1,
        ewma_alpha: float = 0.15,
    ) -> None:
        self.max_total_threads = max_total_threads
        self.min_speed_threshold = min_speed_threshold
        self.speed_check_interval = speed_check_interval
        self.ewma_alpha = ewma_alpha

        self._total_threads: int = 0
        self._active_threads: int = 0
        self._idle_threads: int = 0
        self._file_allocations: dict[str, int] = {}
        self._file_priorities: dict[str, float] = {}
        self._file_progress: dict[str, float] = {}
        self._lock = asyncio.Lock()
        self._running = False
        self._task: asyncio.Task[None] | None = None

        self._speed_history: list[float] = []
        self._ewma_speed: float = 0.0
        self._last_check_time: float = time.time()
        self._last_speed: float = 0.0
        self._low_speed_count: int = 0
        self._last_variance: float = 0.0
        self._variance_cache_time: float = 0.0

        self._speed_avg = MovingAverage(window_size=20)
        self._ewma_avg = MovingAverage(window_size=10)
        self._callbacks: list[Callable[[], None]] = []

        self._append_decision_history: list[bool] = []

    @property
    def total_threads(self) -> int:
        return self._total_threads

    @property
    def active_threads(self) -> int:
        return self._active_threads

    @property
    def available_threads(self) -> int:
        return max(0, self.max_total_threads - self._total_threads)

    @property
    def is_full(self) -> bool:
        return self._total_threads >= self.max_total_threads

    def register_callback(self, callback: Callable[[], None]) -> None:
        self._callbacks.append(callback)

    async def acquire_thread(self, file_id: str, priority: float = 1.0) -> bool:
        """请求分配一个线程（带优先级）"""
        async with self._lock:
            if self.is_full:
                return False

            self._total_threads += 1
            self._active_threads += 1
            self._file_allocations[file_id] = self._file_allocations.get(file_id, 0) + 1
            self._file_priorities[file_id] = priority
            return True

    async def release_thread(self, file_id: str) -> None:
        """释放一个线程"""
        async with self._lock:
            self._total_threads = max(0, self._total_threads - 1)
            self._active_threads = max(0, self._active_threads - 1)
            if file_id in self._file_allocations:
                self._file_allocations[file_id] = max(0, self._file_allocations[file_id] - 1)
                if self._file_allocations[file_id] == 0:
                    self._file_allocations.pop(file_id, None)
                    self._file_priorities.pop(file_id, None)
                    self._file_progress.pop(file_id, None)

    async def mark_thread_active(self, file_id: str) -> None:
        """标记线程为活跃"""
        async with self._lock:
            self._active_threads += 1

    async def mark_thread_idle(self, file_id: str) -> None:
        """标记线程为空闲"""
        async with self._lock:
            self._active_threads = max(0, self._active_threads - 1)
            self._idle_threads += 1

    def update_file_progress(self, file_id: str, progress: float) -> None:
        """更新文件下载进度"""
        self._file_progress[file_id] = progress

    def record_speed(self, bytes_per_second: float) -> None:
        """记录当前速度，使用EWMA平滑"""
        now = time.time()
        elapsed = now - self._last_check_time

        if elapsed > 0:
            current_speed = bytes_per_second
            self._speed_history.append(current_speed)
            if len(self._speed_history) > 30:
                self._speed_history.pop(0)

            if self._ewma_speed == 0:
                self._ewma_speed = current_speed
            else:
                self._ewma_speed = self.ewma_alpha * current_speed + (1 - self.ewma_alpha) * self._ewma_speed

            self._speed_avg.add(current_speed)
            self._ewma_avg.add(self._ewma_speed)
            self._last_speed = current_speed
            self._last_check_time = now

            if current_speed < self.min_speed_threshold:
                self._low_speed_count += 1
            else:
                self._low_speed_count = max(0, self._low_speed_count - 1)

    def _calculate_speed_variance(self, force_recalc: bool = False) -> float:
        """计算速度方差，衡量网络稳定性（带缓存）"""
        now = time.time()
        if not force_recalc and now - self._variance_cache_time < 0.2 and self._last_variance > 0:
            return self._last_variance

        if len(self._speed_history) < 5:
            self._last_variance = 0.0
        else:
            recent = self._speed_history[-20:] if len(self._speed_history) >= 20 else self._speed_history
            mean = sum(recent) / len(recent)
            if mean > 0:
                variance = sum((s - mean) ** 2 for s in recent) / len(recent)
                self._last_variance = math.sqrt(variance) / mean
            else:
                self._last_variance = 0.5
        self._variance_cache_time = now
        return self._last_variance

    def _predict_next_speed(self) -> float:
        """基于历史趋势预测下一个速度（线性回归 + EWMA混合）"""
        if len(self._speed_history) < 5:
            return self._ewma_speed

        recent = self._speed_history[-20:] if len(self._speed_history) >= 20 else self._speed_history
        n = len(recent)

        x = list(range(n))
        y = recent

        x_mean = sum(x) / n
        y_mean = sum(y) / n

        numerator = sum((x[i] - x_mean) * (y[i] - y_mean) for i in range(n))
        denominator = sum((x[i] - x_mean) ** 2 for i in range(n))

        if denominator == 0:
            return self._ewma_speed

        slope = numerator / denominator
        predicted = y_mean + slope * n

        variance = self._calculate_speed_variance()
        stability_weight = max(0.15, 1.0 - variance * 1.5)

        ewma_weight = 0.4
        weighted_predicted = (
            stability_weight * predicted
            + (1 - stability_weight - ewma_weight) * self._ewma_speed
            + ewma_weight * self._ewma_avg.get_average()
        )

        return max(0, weighted_predicted)

    def should_append_thread(self, file_id: str) -> bool:
        """
        判断是否应该为指定文件追加线程

        改进策略：
        1. 只有持续预测速度低时才追加线程（避免抖动）
        2. 速度方差大时不追加（网络不稳时不应扩张）
        3. 使用EWMA加权的趋势判断
        4. 结合绝对速度和相对变化
        """
        if self.is_full:
            return False

        predicted = self._predict_next_speed()
        trend = self._speed_avg.get_trend()
        variance = self._calculate_speed_variance()
        ewma = self._ewma_speed
        avg = self._speed_avg.get_average()
        stability = self._speed_avg.get_stability()

        should_append_score = 0

        if predicted < self.min_speed_threshold * 0.5 and ewma < self.min_speed_threshold * 0.7:
            should_append_score += 2
        elif predicted < self.min_speed_threshold * 0.7:
            should_append_score += 1

        if variance > 0.6:
            should_append_score -= 2
        elif variance > 0.4:
            should_append_score -= 1

        if trend < -0.3:
            should_append_score += 1
        elif trend > 0.2:
            should_append_score -= 2

        if stability < 0.3:
            should_append_score -= 1
        elif stability > 0.6:
            should_append_score += 1

        if avg > 0 and predicted < avg * 0.5:
            should_append_score += 1

        self._append_decision_history.append(should_append_score > 0)
        if len(self._append_decision_history) > 8:
            self._append_decision_history.pop(0)

        recent_decisions = self._append_decision_history[-5:]
        positive_count = sum(1 for d in recent_decisions if d)
        negative_count = sum(1 for d in recent_decisions if not d)

        if positive_count >= 4 and positive_count > negative_count:
            return True

        return False

    def get_thread_allocation(self, file_id: str) -> int:
        """获取指定文件的线程分配数"""
        return self._file_allocations.get(file_id, 0)

    def get_optimal_allocation(self) -> dict[str, int]:
        """
        基于优先级和进度计算最优线程分配

        改进策略：
        1. 大文件优先获得更多线程
        2. 快要完成的任务优先
        3. 高优先级任务获得更多资源
        4. 允许较大的分配跳跃以快速响应负载变化
        """
        if not self._file_allocations:
            return {}

        priorities = []
        for file_id in self._file_allocations:
            priority = self._file_priorities.get(file_id, 1.0)
            progress = self._file_progress.get(file_id, 0.0)
            threads = self._file_allocations[file_id]

            urgency = (1 - progress) * priority * math.log1p(threads + 1)
            priorities.append((file_id, urgency, priority, threads))

        priorities.sort(key=lambda x: x[1], reverse=True)

        total_available = self.max_total_threads
        allocations: dict[str, int] = {}
        base_threads = total_available // len(priorities)
        remainder = total_available % len(priorities)

        variance = self._calculate_speed_variance()
        stability = max(0.3, 1.0 - variance)

        max_jump = 3 if stability > 0.5 else 2

        for i, (file_id, urgency, priority, threads) in enumerate(priorities):
            target = base_threads + (1 if i < remainder else 0)
            target = max(1, min(target, threads + max_jump))
            allocations[file_id] = target

        return allocations

    def get_stats(self) -> ThreadPoolStats:
        """获取线程池统计信息"""
        avg_speed = self._speed_avg.get_average()
        trend = self._speed_avg.get_trend()
        variance = self._calculate_speed_variance()
        predicted = self._predict_next_speed()

        return ThreadPoolStats(
            total_threads=self._total_threads,
            active_threads=self._active_threads,
            idle_threads=self._idle_threads,
            total_speed=self._last_speed,
            avg_speed=avg_speed,
            speed_trend=trend,
            speed_variance=variance,
            predicted_speed=predicted,
            low_speed_count=self._low_speed_count,
        )

    async def rebalance(self, allocations: dict[str, int]) -> dict[str, int]:
        """
        重新平衡线程分配
        """
        async with self._lock:
            if self._total_threads == 0:
                return {}

            optimal = self.get_optimal_allocation()
            new_allocations: dict[str, int] = {}

            for file_id, current_threads in self._file_allocations.items():
                optimal_threads = optimal.get(file_id, current_threads)
                if optimal_threads != current_threads:
                    new_allocations[file_id] = optimal_threads

            return new_allocations

    async def start(self) -> None:
        """启动线程池管理循环"""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._manager_loop())

    async def stop(self) -> None:
        """停止线程池管理"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _manager_loop(self) -> None:
        """管理循环，定期检查并调整"""
        while self._running:
            try:
                await asyncio.sleep(self.speed_check_interval)

                if self._callbacks:
                    for callback in self._callbacks:
                        try:
                            callback()
                        except Exception:
                            pass

            except asyncio.CancelledError:
                break
            except Exception:
                pass


class SpeedAdaptiveController:
    """
    速度自适应控制器 - 基于PCL改进的预测算法

    改进点：
    1. EWMA平滑替代简单移动平均
    2. 速度预测（线性回归+趋势外推）
    3. 自适应阈值调整，考虑网络波动
    """

    def __init__(
        self,
        initial_low_threshold: float = 256 * 1024,
        ewma_alpha: float = 0.3,
        check_interval: float = 0.1,
        stability_weight: float = 0.2,
    ) -> None:
        self._low_threshold = initial_low_threshold
        self._ewma_alpha = ewma_alpha
        self._check_interval = check_interval
        self._stability_weight = stability_weight

        self._speed_history: list[float] = []
        self._ewma_speed: float = 0.0
        self._last_adjustment_time: float = 0.0
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

        self._threshold_history: list[float] = []
        self._on_threshold_changed: Callable[[float], None] | None = None
        self._on_should_append: Callable[[], bool] | None = None

    @property
    def low_threshold(self) -> float:
        return self._low_threshold

    def set_callbacks(
        self,
        on_threshold_changed: Callable[[float], None] | None = None,
        on_should_append: Callable[[], bool] | None = None,
    ) -> None:
        self._on_threshold_changed = on_threshold_changed
        self._on_should_append = on_should_append

    def record_speed(self, speed: float) -> None:
        """记录速度样本，使用EWMA平滑"""
        self._speed_history.append(speed)
        if len(self._speed_history) > 20:
            self._speed_history.pop(0)

        if self._ewma_speed == 0:
            self._ewma_alpha = speed
        else:
            self._ewma_speed = self._ewma_alpha * speed + (1 - self._ewma_alpha) * self._ewma_speed

    def get_average_speed(self) -> float:
        """获取EWMA平滑后的平均速度"""
        return self._ewma_speed

    def get_raw_average(self) -> float:
        """获取原始平均速度"""
        if not self._speed_history:
            return 0.0
        return sum(self._speed_history) / len(self._speed_history)

    def _calculate_stability(self) -> float:
        """计算速度稳定性（0-1，越高越稳定）"""
        if len(self._speed_history) < 5:
            return 1.0
        mean = sum(self._speed_history) / len(self._speed_history)
        variance = sum((s - mean) ** 2 for s in self._speed_history) / len(self._speed_history)
        cv = math.sqrt(variance) / max(mean, 1)
        return max(0, min(1, 1 - cv))

    def _predict_next_speed(self) -> float:
        """预测下一个速度"""
        if len(self._speed_history) < 3:
            return self._ewma_speed

        n = len(self._speed_history)
        x = list(range(n))
        y = self._speed_history

        x_mean = sum(x) / n
        y_mean = sum(y) / n

        numerator = sum((x[i] - x_mean) * (y[i] - y_mean) for i in range(n))
        denominator = sum((x[i] - x_mean) ** 2 for i in range(n))

        if denominator == 0:
            return self._ewma_speed

        slope = numerator / denominator
        predicted = y_mean + slope * (n + 1)

        stability = self._calculate_stability()
        weighted_predicted = stability * predicted + (1 - stability) * self._ewma_speed

        return max(0, weighted_predicted)

    async def _adjust_threshold(self) -> None:
        """根据预测速度动态调整阈值"""
        predicted = self._predict_next_speed()
        stability = self._calculate_stability()
        avg_speed = self.get_raw_average()

        if predicted < self._low_threshold:
            adjustment = predicted * (1 - stability * self._stability_weight)
            new_threshold = max(64 * 1024, adjustment)
            self._low_threshold = new_threshold
            self._threshold_history.append(new_threshold)
            if len(self._threshold_history) > 10:
                self._threshold_history.pop(0)

            if self._on_threshold_changed:
                self._on_threshold_changed(self._low_threshold)
        elif avg_speed > self._low_threshold * 1.5 and stability > 0.7:
            self._low_threshold = min(self._low_threshold * 1.1, avg_speed * 0.8)

    def should_append_thread(self) -> bool:
        """判断是否应该追加线程（基于预测）"""
        if len(self._speed_history) < 3:
            return False

        predicted = self._predict_next_speed()
        stability = self._calculate_stability()

        if predicted < self._low_threshold * 0.7:
            return True

        if stability < 0.3 and predicted < self._low_threshold:
            return True

        return False

    async def start(self) -> None:
        """启动自适应控制器"""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._control_loop())

    async def stop(self) -> None:
        """停止自适应控制器"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _control_loop(self) -> None:
        """控制循环"""
        while self._running:
            try:
                await asyncio.sleep(self._check_interval)

                if len(self._speed_history) >= 3:
                    await self._adjust_threshold()

            except asyncio.CancelledError:
                break
            except Exception:
                pass
