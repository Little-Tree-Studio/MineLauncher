import asyncio
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from .config import SpeedLimitConfig, SpeedLimitMode


class RateLimiter(ABC):
    @abstractmethod
    async def acquire(self, tokens: int = 1) -> bool:
        pass

    @abstractmethod
    def get_current_rate(self) -> float:
        pass

    @abstractmethod
    def reset(self) -> None:
        pass


@dataclass
class TokenBucketState:
    tokens: float
    last_update: float
    total_acquired: int
    total_wait_time: float


class TokenBucketLimiter(RateLimiter):
    def __init__(self, rate: int, burst: int | None = None) -> None:
        self.rate = float(rate)
        self.burst = float(burst or rate)
        self._tokens = self.burst
        self._last_update = time.time()
        self._lock = asyncio.Lock()
        self._total_acquired = 0
        self._total_wait_time = 0.0
        self._rate_adjustments: list[float] = []
        self._last_rate_adjustment = time.time()

    async def acquire(self, tokens: int = 1) -> bool:
        async with self._lock:
            now = time.time()
            elapsed = now - self._last_update
            self._tokens = min(self.burst, self._tokens + elapsed * self.rate)
            self._last_update = now

            if self._tokens >= tokens:
                self._tokens -= tokens
                self._total_acquired += tokens
                return True
            else:
                needed = tokens - self._tokens
                wait_time = needed / self.rate

                await asyncio.sleep(wait_time)

                self._tokens = 0
                self._total_acquired += tokens
                self._total_wait_time += wait_time
                self._last_update = time.time()
                return True

    async def try_acquire(self, tokens: int = 1) -> bool:
        async with self._lock:
            now = time.time()
            elapsed = now - self._last_update
            self._tokens = min(self.burst, self._tokens + elapsed * self.rate)
            self._last_update = now

            if self._tokens >= tokens:
                self._tokens -= tokens
                self._total_acquired += tokens
                return True
            return False

    def get_current_rate(self) -> float:
        return self.rate

    def get_state(self) -> TokenBucketState:
        return TokenBucketState(
            tokens=self._tokens,
            last_update=self._last_update,
            total_acquired=self._total_acquired,
            total_wait_time=self._total_wait_time,
        )

    def set_rate(self, new_rate: int) -> None:
        self.rate = float(new_rate)
        self._rate_adjustments.append(new_rate)
        self._last_rate_adjustment = time.time()

    def reset(self) -> None:
        self._tokens = self.burst
        self._last_update = time.time()
        self._total_acquired = 0
        self._total_wait_time = 0.0


class LeakyBucketLimiter(RateLimiter):
    def __init__(self, rate: int, capacity: int | None = None) -> None:
        self.rate = float(rate)
        self.capacity = float(capacity or rate)
        self._water = 0.0
        self._last_leak = time.time()
        self._lock = asyncio.Lock()
        self._total_acquired = 0

    async def acquire(self, tokens: int = 1) -> bool:
        async with self._lock:
            now = time.time()
            elapsed = now - self._last_leak
            self._water = max(0, self._water - elapsed * self.rate)
            self._last_leak = now

            if self._water + tokens <= self.capacity:
                self._water += tokens
                self._total_acquired += tokens
                return True
            else:
                overflow = self._water + tokens - self.capacity
                wait_time = overflow / self.rate
                await asyncio.sleep(wait_time)

                self._water = tokens
                self._total_acquired += tokens
                self._last_leak = time.time()
                return True

    def get_current_rate(self) -> float:
        return self.rate

    def reset(self) -> None:
        self._water = 0.0
        self._last_leak = time.time()
        self._total_acquired = 0


class SlidingWindowLimiter(RateLimiter):
    def __init__(self, rate: int, window_size: float = 1.0) -> None:
        self.rate = rate
        self.window_size = window_size
        self._timestamps: list[float] = []
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: int = 1) -> bool:
        async with self._lock:
            now = time.time()
            cutoff = now - self.window_size
            self._timestamps = [t for t in self._timestamps if t > cutoff]

            if len(self._timestamps) + tokens <= self.rate:
                self._timestamps.extend([now] * tokens)
                return True
            else:
                oldest = self._timestamps[0] if self._timestamps else now
                wait_time = (oldest + self.window_size) - now
                if wait_time > 0:
                    await asyncio.sleep(wait_time)
                self._timestamps.extend([time.time()] * tokens)
                return True

    def get_current_rate(self) -> float:
        now = time.time()
        cutoff = now - self.window_size
        recent = [t for t in self._timestamps if t > cutoff]
        return len(recent) / self.window_size

    def reset(self) -> None:
        self._timestamps.clear()


class AdaptiveLimiter(RateLimiter):
    def __init__(
        self,
        initial_rate: int,
        min_rate: int = 1024,
        max_rate: int = 100 * 1024 * 1024,
        increase_factor: float = 1.2,
        decrease_factor: float = 0.8,
    ) -> None:
        self._bucket = TokenBucketLimiter(initial_rate)
        self.min_rate = min_rate
        self.max_rate = max_rate
        self.increase_factor = increase_factor
        self.decrease_factor = decrease_factor
        self._congestion_events = 0
        self._last_adjustment = time.time()
        self._adjustment_cooldown = 5.0

    async def acquire(self, tokens: int = 1) -> bool:
        return await self._bucket.acquire(tokens)

    def get_current_rate(self) -> float:
        return self._bucket.get_current_rate()

    def signal_congestion(self) -> None:
        self._congestion_events += 1
        now = time.time()
        if now - self._last_adjustment >= self._adjustment_cooldown and self._congestion_events >= 3:
            new_rate = max(self.min_rate, int(self._bucket.rate * self.decrease_factor))
            self._bucket.set_rate(new_rate)
            self._congestion_events = 0
            self._last_adjustment = now

    def signal_success(self) -> None:
        now = time.time()
        if now - self._last_adjustment >= self._adjustment_cooldown:
            new_rate = min(self.max_rate, int(self._bucket.rate * self.increase_factor))
            self._bucket.set_rate(new_rate)
            self._last_adjustment = now

    def reset(self) -> None:
        self._bucket.reset()
        self._congestion_events = 0


class SpeedLimiter:
    def __init__(self, config: SpeedLimitConfig) -> None:
        self.config = config
        self._global_limiter: RateLimiter | None = None
        self._connection_limiters: dict[int, RateLimiter] = {}
        self._adaptive_limiter: AdaptiveLimiter | None = None
        self._lock = asyncio.Lock()
        self._connection_counter = 0

        self._initialize_limiters()

    def _initialize_limiters(self) -> None:
        if not self.config.enabled or self.config.max_speed <= 0:
            return

        if self.config.mode == SpeedLimitMode.GLOBAL:
            self._global_limiter = TokenBucketLimiter(
                rate=self.config.max_speed,
                burst=self.config.burst_size if self.config.enable_burst else self.config.max_speed,
            )
        elif self.config.mode == SpeedLimitMode.DYNAMIC:
            self._adaptive_limiter = AdaptiveLimiter(
                initial_rate=self.config.max_speed,
            )

    async def acquire(self, bytes_count: int, connection_id: int | None = None) -> None:
        if not self.config.enabled:
            return

        if self._global_limiter:
            await self._global_limiter.acquire(bytes_count)
        elif self._adaptive_limiter:
            await self._adaptive_limiter.acquire(bytes_count)
        elif connection_id is not None and connection_id in self._connection_limiters:
            await self._connection_limiters[connection_id].acquire(bytes_count)

    async def try_acquire(self, bytes_count: int, connection_id: int | None = None) -> bool:
        if not self.config.enabled:
            return True

        if isinstance(self._global_limiter, TokenBucketLimiter):
            return await self._global_limiter.try_acquire(bytes_count)

        return True

    def register_connection(self) -> int:
        self._connection_counter += 1
        connection_id = self._connection_counter

        if self.config.mode == SpeedLimitMode.PER_CONNECTION and self.config.enabled:
            per_connection_rate = self.config.max_speed
            self._connection_limiters[connection_id] = TokenBucketLimiter(
                rate=per_connection_rate,
            )

        return connection_id

    def unregister_connection(self, connection_id: int) -> None:
        if connection_id in self._connection_limiters:
            del self._connection_limiters[connection_id]

    def signal_slow_speed(self) -> None:
        if self._adaptive_limiter:
            self._adaptive_limiter.signal_congestion()

    def signal_good_speed(self) -> None:
        if self._adaptive_limiter:
            self._adaptive_limiter.signal_success()

    def get_current_rate(self) -> float:
        if self._global_limiter:
            return self._global_limiter.get_current_rate()
        if self._adaptive_limiter:
            return self._adaptive_limiter.get_current_rate()
        return 0.0

    def set_rate(self, new_rate: int) -> None:
        self.config.max_speed = new_rate
        if isinstance(self._global_limiter, TokenBucketLimiter):
            self._global_limiter.set_rate(new_rate)

    def reset(self) -> None:
        if self._global_limiter:
            self._global_limiter.reset()
        if self._adaptive_limiter:
            self._adaptive_limiter.reset()
        for limiter in self._connection_limiters.values():
            limiter.reset()

    def get_stats(self) -> dict[str, Any]:
        return {
            "enabled": self.config.enabled,
            "mode": self.config.mode.value,
            "max_speed": self.config.max_speed,
            "current_rate": self.get_current_rate(),
            "active_connections": len(self._connection_limiters),
        }
