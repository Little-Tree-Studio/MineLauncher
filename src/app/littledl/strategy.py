import math
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable

from .utils import MovingAverage


class DownloadStyle(Enum):
    """下载风格选项"""

    SINGLE = "single"
    MULTI = "multi"
    ADAPTIVE = "adaptive"
    HYBRID_TURBO = "hybrid_turbo"


@dataclass
class StyleDecision:
    """风格决策结果"""

    style: DownloadStyle
    confidence: float
    reason: str
    recommended_chunks: int = 1
    estimated_speedup: float = 1.0


@dataclass
class FileProfile:
    """文件特征画像"""

    url: str
    size: int = -1
    supports_range: bool = False
    is_unknown_size: bool = False
    content_type: str = ""
    server_type: str = ""
    is_small: bool = True
    is_large: bool = False
    is_medium: bool = False

    @property
    def size_category(self) -> str:
        if self.is_unknown_size:
            return "unknown"
        if self.size < 5 * 1024 * 1024:
            return "small"
        elif self.size < 100 * 1024 * 1024:
            return "medium"
        return "large"


@dataclass
class NetworkProfile:
    """网络状况画像"""

    avg_speed: float = 0.0
    speed_trend: float = 0.0
    speed_variance: float = 0.0
    stability: float = 1.0
    last_measurement: float = 0.0

    @property
    def is_stable(self) -> bool:
        return self.stability > 0.6

    @property
    def is_fast(self) -> bool:
        return self.avg_speed > 10 * 1024 * 1024


class StrategySelector:
    """
    智能策略选择器

    根据文件特征和网络状况自动选择最优下载风格。
    核心算法：
    1. 文件大小 + 服务器Range支持 → 基础风格
    2. 网络稳定性预测 → 是否追加线程
    3. 历史性能 → 动态调整阈值
    """

    SIZE_THRESHOLD_SMALL = 5 * 1024 * 1024
    SIZE_THRESHOLD_LARGE = 100 * 1024 * 1024

    CHUNK_SIZE_MIN = 256 * 1024
    CHUNK_SIZE_RECOMMENDED = 4 * 1024 * 1024
    CHUNKS_DEFAULT = 4
    CHUNKS_MAX = 16

    SPEED_THRESHOLD_LOW = 256 * 1024
    SPEED_THRESHOLD_HIGH = 10 * 1024 * 1024

    def __init__(
        self,
        default_style: DownloadStyle = DownloadStyle.HYBRID_TURBO,
        enable_single: bool = True,
        enable_multi: bool = True,
        min_chunk_size: int = CHUNK_SIZE_MIN,
        max_chunks: int = CHUNKS_MAX,
        size_threshold_small: int = SIZE_THRESHOLD_SMALL,
        size_threshold_large: int = SIZE_THRESHOLD_LARGE,
    ) -> None:
        self.default_style = default_style
        self.enable_single = enable_single
        self.enable_multi = enable_multi
        self.min_chunk_size = min_chunk_size
        self.max_chunks = max_chunks
        self.size_threshold_small = size_threshold_small
        self.size_threshold_large = size_threshold_large

        self._speed_history: list[float] = []
        self._speed_avg = MovingAverage(window_size=20)
        self._style_performance: dict[DownloadStyle, list[float]] = {style: [] for style in DownloadStyle}
        self._last_selection: DownloadStyle | None = None

    def analyze_file(
        self,
        url: str,
        size: int = -1,
        supports_range: bool = False,
        content_type: str = "",
        is_unknown_size: bool = False,
    ) -> FileProfile:
        """分析文件特征"""
        is_small = 0 < size < self.size_threshold_small
        is_large = size > self.size_threshold_large
        is_medium = not is_small and not is_large and size > 0

        server_type = self._detect_server_type(content_type)

        return FileProfile(
            url=url,
            size=size,
            supports_range=supports_range,
            is_unknown_size=is_unknown_size,
            content_type=content_type,
            server_type=server_type,
            is_small=is_small,
            is_large=is_large,
            is_medium=is_medium,
        )

    def _detect_server_type(self, content_type: str) -> str:
        """检测服务器类型"""
        if not content_type:
            return "unknown"
        ct = content_type.lower()
        if "application/octet-stream" in ct:
            return "generic"
        if "text/" in ct:
            return "text"
        if "image/" in ct:
            return "media"
        if "application/zip" in ct or "application/x-zip" in ct:
            return "archive"
        if "application/x-minecraft" in ct:
            return "minecraft"
        return "other"

    def analyze_network(self, bytes_per_second: float) -> NetworkProfile:
        """分析网络状况"""
        self._speed_history.append(bytes_per_second)
        if len(self._speed_history) > 30:
            self._speed_history.pop(0)

        self._speed_avg.add(bytes_per_second)

        avg_speed = self._speed_avg.get_average()
        trend = self._speed_avg.get_trend()
        variance = self._calculate_variance()
        stability = self._calculate_stability()

        return NetworkProfile(
            avg_speed=avg_speed,
            speed_trend=trend,
            speed_variance=variance,
            stability=stability,
            last_measurement=time.time(),
        )

    def _calculate_variance(self) -> float:
        """计算速度方差系数"""
        if len(self._speed_history) < 3:
            return 0.0
        mean = sum(self._speed_history) / len(self._speed_history)
        if mean == 0:
            return 1.0
        variance = sum((s - mean) ** 2 for s in self._speed_history) / len(self._speed_history)
        return math.sqrt(variance) / mean

    def _calculate_stability(self) -> float:
        """计算稳定性（0-1）"""
        variance = self._calculate_variance()
        return max(0.0, min(1.0, 1.0 - variance))

    def predict_next_speed(self) -> float:
        """预测下一时刻速度（线性回归）"""
        if len(self._speed_history) < 5:
            return self._speed_avg.get_average()

        n = len(self._speed_history)
        x = list(range(n))
        y = self._speed_history

        x_mean = sum(x) / n
        y_mean = sum(y) / n

        numerator = sum((x[i] - x_mean) * (y[i] - y_mean) for i in range(n))
        denominator = sum((x[i] - x_mean) ** 2 for i in range(n))

        if denominator == 0:
            return y_mean

        slope = numerator / denominator
        predicted = y_mean + slope * (n + 1)

        ewma_weight = 0.7
        return ewma_weight * max(0, predicted) + (1 - ewma_weight) * y_mean

    def select_style(
        self,
        file_profile: FileProfile,
        network_profile: NetworkProfile | None = None,
        forced_style: DownloadStyle | None = None,
    ) -> StyleDecision:
        """
        选择最优下载风格

        算法流程：
        1. 如果用户强制指定，直接使用
        2. 如果是未知大小，单线程
        3. 如果服务器不支持Range，单线程
        4. 如果是小文件，单线程
        5. 如果是大文件且网络稳定，多线程
        6. 否则自适应
        """
        if forced_style:
            return StyleDecision(
                style=forced_style,
                confidence=1.0,
                reason="用户指定",
                recommended_chunks=(
                    1
                    if forced_style == DownloadStyle.SINGLE
                    else self._calculate_hybrid_chunks(file_profile, network_profile)
                ),
            )

        if not self.enable_single and not self.enable_multi:
            fallback = DownloadStyle.SINGLE if self.enable_single else DownloadStyle.MULTI
            return StyleDecision(
                style=fallback,
                confidence=0.5,
                reason="无可用风格",
            )

        if file_profile.is_unknown_size or file_profile.size <= 0:
            return StyleDecision(
                style=DownloadStyle.SINGLE,
                confidence=0.95,
                reason="文件大小未知",
                recommended_chunks=1,
            )

        if not file_profile.supports_range:
            return StyleDecision(
                style=DownloadStyle.SINGLE,
                confidence=0.9,
                reason="服务器不支持断点续传",
                recommended_chunks=1,
            )

        if file_profile.is_small:
            chunks = 1
            if (
                network_profile
                and not network_profile.is_stable
                and network_profile.avg_speed < self.SPEED_THRESHOLD_LOW
            ):
                chunks = 2
            return StyleDecision(
                style=DownloadStyle.SINGLE,
                confidence=0.85,
                reason=f"小文件({file_profile.size_category})，单线程足够",
                recommended_chunks=chunks,
            )

        network = network_profile or NetworkProfile()

        if file_profile.is_large:
            chunks = self._calculate_hybrid_chunks(file_profile, network)
            reason = f"大文件({file_profile.size_category})使用 HYBRID_TURBO 拖尾抢占与自适应并发"
            confidence = 0.78
            if network.is_stable and network.avg_speed > self.SPEED_THRESHOLD_HIGH:
                reason = f"大文件({file_profile.size_category}) + 稳定快速网络，优先 HYBRID_TURBO"
                confidence = 0.92
            elif network.is_stable:
                reason = f"大文件({file_profile.size_category}) + 稳定网络，启用 HYBRID_TURBO"
                confidence = 0.84
            return StyleDecision(
                style=DownloadStyle.HYBRID_TURBO,
                confidence=confidence,
                reason=reason,
                recommended_chunks=chunks,
                estimated_speedup=self._estimate_speedup(chunks, network) * 1.1,
            )

        if file_profile.is_medium:
            chunks = min(self._calculate_hybrid_chunks(file_profile, network), 8)
            if network.is_stable and network.avg_speed > self.SPEED_THRESHOLD_MID:
                return StyleDecision(
                    style=DownloadStyle.HYBRID_TURBO,
                    confidence=0.78,
                    reason=f"中等文件({file_profile.size_category}) + 良好网络，使用 HYBRID_TURBO",
                    recommended_chunks=chunks,
                    estimated_speedup=self._estimate_speedup(chunks, network) * 1.05,
                )

        chunks = self._calculate_hybrid_chunks(file_profile, network)
        return StyleDecision(
            style=DownloadStyle.HYBRID_TURBO,
            confidence=0.68,
            reason="默认使用 HYBRID_TURBO，在速度和稳定之间动态平衡",
            recommended_chunks=chunks,
        )

    @property
    def SPEED_THRESHOLD_MID(self) -> float:
        return (self.SPEED_THRESHOLD_LOW + self.SPEED_THRESHOLD_HIGH) / 2

    def _calculate_chunks(self, file_profile: FileProfile, network: NetworkProfile | None = None) -> int:
        """计算推荐分块数"""
        if file_profile.size <= 0:
            return self.CHUNKS_DEFAULT

        size = file_profile.size

        base_chunks = max(1, min(self.max_chunks, size // self.min_chunk_size))

        target_chunk_time = 2.0
        if network and network.avg_speed > 0:
            ideal_size = int(network.avg_speed * target_chunk_time)
            ideal_chunks = max(1, min(self.max_chunks, size // max(ideal_size, self.min_chunk_size)))
            base_chunks = min(base_chunks, ideal_chunks + 2)

        if file_profile.is_large:
            base_chunks = max(base_chunks, 4)

        base_chunks = max(1, min(base_chunks, self.max_chunks))

        return base_chunks

    def _calculate_hybrid_chunks(self, file_profile: FileProfile, network: NetworkProfile | None = None) -> int:
        """计算 HYBRID_TURBO 推荐分块数。"""
        chunks = self._calculate_chunks(file_profile, network)
        if not network:
            return min(self.max_chunks, max(2, chunks))

        if network.is_stable and network.avg_speed > self.SPEED_THRESHOLD_HIGH:
            chunks += 2
        elif network.stability < 0.45:
            chunks = max(2, chunks - 2)
        elif network.speed_trend < -0.2:
            chunks += 1

        if file_profile.is_large:
            chunks = max(4, chunks)

        return max(1, min(self.max_chunks, chunks))

    def _estimate_speedup(self, chunks: int, network: NetworkProfile) -> float:
        """估算加速比"""
        if chunks <= 1:
            return 1.0

        stability_factor = network.stability if network else 0.7
        chunks_factor = min(chunks / 2, 3.0)

        speedup = chunks_factor * stability_factor

        if network and network.speed_trend < -0.2:
            speedup *= 0.8

        return min(speedup, chunks * 0.9)

    def record_performance(self, style: DownloadStyle, actual_speed: float, expected_speed: float) -> None:
        """记录风格表现，用于后续优化"""
        if style not in self._style_performance:
            self._style_performance[style] = []

        ratio = actual_speed / max(expected_speed, 1) if expected_speed > 0 else 1.0
        self._style_performance[style].append(ratio)

        if len(self._style_performance[style]) > 50:
            self._style_performance[style].pop(0)

    def get_style_accuracy(self, style: DownloadStyle) -> float:
        """获取某风格的实际表现准确率"""
        if style not in self._style_performance or not self._style_performance[style]:
            return 0.5
        return sum(self._style_performance[style]) / len(self._style_performance[style])

    def get_stats(self) -> dict:
        """获取选择器统计"""
        return {
            "enable_single": self.enable_single,
            "enable_multi": self.enable_multi,
            "default_style": self.default_style.value,
            "max_chunks": self.max_chunks,
            "size_threshold_small": self.size_threshold_small,
            "size_threshold_large": self.size_threshold_large,
            "single_accuracy": self.get_style_accuracy(DownloadStyle.SINGLE),
            "multi_accuracy": self.get_style_accuracy(DownloadStyle.MULTI),
            "adaptive_accuracy": self.get_style_accuracy(DownloadStyle.ADAPTIVE),
            "hybrid_turbo_accuracy": self.get_style_accuracy(DownloadStyle.HYBRID_TURBO),
            "speed_avg": self._speed_avg.get_average(),
            "speed_trend": self._speed_avg.get_trend(),
            "prediction": self.predict_next_speed(),
        }


class DynamicStyleAllocator:
    """
    动态风格分配器 - 多文件下载时智能分配下载风格

    算法：
    1. 批量分析所有文件的特征
    2. 根据全局资源（线程数）动态分配
    3. 考虑文件优先级和大小
    4. 实时调整分配策略
    """

    def __init__(
        self,
        selector: StrategySelector,
        max_concurrent_files: int = 8,
        max_total_chunks: int = 16,
        enable_auto_allocation: bool = True,
    ) -> None:
        self.selector = selector
        self.max_concurrent_files = max_concurrent_files
        self.max_total_chunks = max_total_chunks
        self.enable_auto_allocation = enable_auto_allocation

        self._file_profiles: dict[str, FileProfile] = {}
        self._file_assignments: dict[str, DownloadStyle] = {}
        self._file_chunks: dict[str, int] = {}
        import asyncio

        self._lock: asyncio.Lock = asyncio.Lock()

    async def add_file(
        self,
        file_id: str,
        url: str,
        size: int = -1,
        supports_range: bool = False,
        content_type: str = "",
        priority: int = 0,
        forced_style: DownloadStyle | None = None,
    ) -> StyleDecision:
        """添加文件并获取风格分配"""
        profile = self.selector.analyze_file(url, size, supports_range, content_type)
        self._file_profiles[file_id] = profile

        if forced_style:
            decision = self.selector.select_style(profile, forced_style=forced_style)
        else:
            decision = self.selector.select_style(profile)

        async with self._lock:
            self._file_assignments[file_id] = decision.style
            self._file_chunks[file_id] = decision.recommended_chunks

        return decision

    async def remove_file(self, file_id: str) -> None:
        """移除文件"""
        async with self._lock:
            self._file_profiles.pop(file_id, None)
            self._file_assignments.pop(file_id, None)
            self._file_chunks.pop(file_id, None)

    async def rebalance(self, available_chunks: int | None = None) -> dict[str, tuple[DownloadStyle, int]]:
        """
        重新平衡分配

        策略：
        1. 大文件优先多线程
        2. 优先级高的文件优先分配资源
        3. 考虑当前网络状况
        """
        available = available_chunks or self.max_total_chunks

        async with self._lock:
            files = list(self._file_profiles.keys())

            if not files:
                return {}

            files_with_priority = []
            for fid in files:
                profile = self._file_profiles[fid]
                current_chunks = self._file_chunks.get(fid, 1)
                files_with_priority.append((fid, profile, current_chunks))

            files_with_priority.sort(
                key=lambda x: (
                    -x[0].is_large if hasattr(x[1], "is_large") else False,
                    -x[2],
                    x[0].priority if hasattr(x[2], "priority") else 0,
                )
            )

            total_chunks = sum(self._file_chunks.values())
            if total_chunks <= available:
                return {fid: (self._file_assignments[fid], self._file_chunks[fid]) for fid in files}

            scale_factor = available / total_chunks
            allocations: dict[str, tuple[DownloadStyle, int]] = {}

            for fid, profile, current_chunks in files_with_priority:
                style = self._file_assignments[fid]
                new_chunks = max(1, int(current_chunks * scale_factor))

                if style == DownloadStyle.SINGLE:
                    new_chunks = 1

                allocations[fid] = (style, new_chunks)

            return allocations

    def get_allocation(self, file_id: str) -> tuple[DownloadStyle, int] | None:
        """获取文件的当前分配"""
        style = self._file_assignments.get(file_id)
        chunks = self._file_chunks.get(file_id, 1)
        if style:
            return (style, chunks)
        return None

    def get_stats(self) -> dict:
        """获取分配统计"""
        style_counts = {}
        total_chunks = 0

        for fid, style in self._file_assignments.items():
            style_counts[style.value] = style_counts.get(style.value, 0) + 1
            total_chunks += self._file_chunks.get(fid, 1)

        return {
            "total_files": len(self._file_profiles),
            "style_distribution": style_counts,
            "total_chunks": total_chunks,
            "available_chunks": self.max_total_chunks,
            "selector_stats": self.selector.get_stats(),
        }
