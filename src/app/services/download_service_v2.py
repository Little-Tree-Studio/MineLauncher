"""
Minecraft版本下载服务 - 基于littledl高性能下载库
支持IDM风格多线程分块下载、断点续传、智能调度
"""

from __future__ import annotations
import os
import json
import enum
import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Optional, Callable, Tuple, Any
from pathlib import Path
import requests
from dataclasses import dataclass, field

from ..littledl import (
    download_file,
    download_file_sync,
    batch_download_sync,
    DownloadConfig,
    DownloadStyle,
    StrategySelector,
    MultiSourceManager,
    SpeedLimitConfig,
    SpeedLimitMode,
    RetryConfig,
    RetryStrategy,
    ProxyConfig,
    ProxyMode,
    BatchDownloader,
    MCBatchDownloader,
    BatchProgress,
    FileTask,
    FileTaskStatus,
)
from ..littledl.batch import FileProgress

from ..info import UA
from ..services.logger_service import LoggerService


class DownloadSource(enum.Enum):
    """下载源优先级枚举"""

    BMCLAPI_FIRST = 0
    AUTO = 1
    OFFICIAL_FIRST = 2
    MIRROR_ONLY = 3
    MIRROR_FIRST = 4
    OFFICIAL_ONLY = 5


class VersionSource(enum.Enum):
    """版本列表源优先级枚举"""

    BMCLAPI_FIRST = 0
    MOJANG_FIRST = 1
    MOJANG_ONLY = 2


@dataclass
class DownloadProgress:
    """下载进度信息"""

    total: int = 0
    current: int = 0
    status: str = ""
    speed: float = 0.0
    total_files: int = 0
    finished_files: int = 0
    eta: float = 0.0
    connections: int = 0
    current_file: str = ""
    failed_files: int = 0
    active_files: int = 0
    speed_stability: float = 0.0
    elapsed_time: float = 0.0

    @property
    def percentage(self) -> float:
        if self.total == 0:
            return 0
        return min((self.current / self.total) * 100, 100)

    @property
    def total_percentage(self) -> float:
        if self.total_files == 0:
            return 0
        return min((self.finished_files / self.total_files) * 100, 100)

    @classmethod
    def from_batch_progress(
        cls, batch: BatchProgress, current_file: str = ""
    ) -> "DownloadProgress":
        """从 BatchProgress 创建 DownloadProgress"""
        active = batch.get_active_files()
        current = active[0] if active else None
        return cls(
            total=batch.total_bytes,
            current=batch.downloaded_bytes,
            status=f"下载中: {current.filename}"
            if current
            else batch.files[0].filename
            if batch.files
            else "",
            speed=batch.smooth_speed,
            total_files=batch.total_files,
            finished_files=batch.completed_files,
            eta=batch.eta,
            connections=len(active),
            current_file=current.filename if current else (current_file or ""),
            failed_files=batch.failed_files,
            active_files=batch.active_files,
            speed_stability=batch.speed_stability,
            elapsed_time=batch.elapsed_time,
        )


@dataclass
class MinecraftDownloadConfig:
    """Minecraft下载配置"""

    # 基础下载配置
    enable_chunking: bool = True
    max_chunks: int = 16
    chunk_size: int = 4 * 1024 * 1024  # 4MB
    buffer_size: int = 64 * 1024  # 64KB
    timeout: float = 300
    resume: bool = True
    verify_ssl: bool = True

    # 下载风格（新版littledl特性）
    download_style: DownloadStyle = DownloadStyle.ADAPTIVE

    # 速度限制
    speed_limit_enabled: bool = False
    max_speed: int = 0  # bytes/s, 0=unlimited

    # 重试配置
    retry_enabled: bool = True
    max_retries: int = 3
    retry_delay: float = 1.0

    # 代理配置
    proxy_mode: str = "SYSTEM"  # SYSTEM, CUSTOM, NONE
    http_proxy: str = ""
    https_proxy: str = ""
    socks5_proxy: str = ""

    # 下载源
    download_source: str = "auto"

    # 验证
    verify_hash: bool = True

    def to_littledl_config(self) -> DownloadConfig:
        """转换为littledl配置"""
        # 速度限制配置
        speed_limit = None
        if self.speed_limit_enabled and self.max_speed > 0:
            speed_limit = SpeedLimitConfig(
                enabled=True,
                mode=SpeedLimitMode.GLOBAL,
                max_speed=self.max_speed,
            )

        # 重试配置
        retry = RetryConfig(
            strategy=RetryStrategy.EXPONENTIAL,
            max_retries=self.max_retries if self.retry_enabled else 0,
        )

        # 代理配置
        proxy = None
        if self.proxy_mode == "SYSTEM":
            proxy = ProxyConfig(mode=ProxyMode.SYSTEM)
        elif self.proxy_mode == "CUSTOM":
            proxy = ProxyConfig(
                mode=ProxyMode.CUSTOM,
                http_proxy=self.http_proxy,
                https_proxy=self.https_proxy,
            )
        else:
            proxy = ProxyConfig(mode=ProxyMode.NONE)

        return DownloadConfig(
            enable_chunking=self.enable_chunking,
            max_chunks=self.max_chunks,
            chunk_size=self.chunk_size,
            buffer_size=self.buffer_size,
            timeout=self.timeout,
            resume=self.resume,
            verify_ssl=self.verify_ssl,
            verify_hash=self.verify_hash,
            speed_limit=speed_limit,
            retry=retry,
            proxy=proxy,
            headers={"User-Agent": UA},
            enable_h2=False,
            fallback_to_single_on_failure=True,
            enable_adaptive=True,
            enable_hybrid_turbo=True,
        )


class NetFile:
    """网络文件信息"""

    def __init__(
        self,
        urls: List[str],
        local_path: str,
        check_hash: Optional[str] = None,
        min_size: int = 0,
        file_name: str = "",
    ):
        self.urls = urls
        self.local_path = local_path
        self.check_hash = check_hash
        self.min_size = min_size
        self.file_name = file_name or Path(local_path).name


class MinecraftDownloader:
    """Minecraft下载器 - 基于littledl"""

    def __init__(
        self,
        mc_folder: str,
        config: Optional[MinecraftDownloadConfig] = None,
        download_source: DownloadSource = DownloadSource.AUTO,
        version_source: VersionSource = VersionSource.BMCLAPI_FIRST,
        progress_callback: Optional[Callable[[DownloadProgress], None]] = None,
    ):
        self.mc_folder = Path(mc_folder).resolve()
        self.config = config or MinecraftDownloadConfig()
        self.download_source = download_source
        self.version_source = version_source
        self.progress_callback = progress_callback

        # 确保目录存在
        self.mc_folder.mkdir(exist_ok=True, parents=True)

        # 下载状态
        self._cancelled = threading.Event()
        self._current_file = ""
        self._current_downloaded = 0
        self._current_total = 0
        self._current_speed = 0.0
        self._current_eta = 0.0

        # 镜像源配置
        self.mirrors = {
            "bmclapi": {
                "version_list": "https://bmclapi2.bangbang93.com/mc/game/version_manifest.json",
                "asset_base": "https://bmclapi2.bangbang93.com/assets",
                "library_base": "https://bmclapi2.bangbang93.com/maven",
                "launcher_meta": "https://bmclapi2.bangbang93.com",
            },
            "mojang": {
                "version_list": "https://piston-meta.mojang.com/mc/game/version_manifest.json",
                "asset_base": "https://resources.download.minecraft.net",
                "library_base": "https://libraries.minecraft.net",
                "launcher_meta": "https://launchermeta.mojang.com",
            },
        }

        # Session
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": UA})
        self.logger = LoggerService().logger
        self.last_error: str = ""

        # 版本列表缓存
        self._version_manifest_cache: Optional[Dict] = None
        self._version_list_loader_state = "idle"

        # 自动速度检测标志（响应时间 < 4000ms 则认为官方源可用）
        self._prefer_official: bool = False
        self._version_list_load_time: float = 0

    def _standardize_version_id(self, version_id: str) -> str:
        """标准化版本ID

        规则：
        1. 下划线替换为连字符：1.7.10_pre4 → 1.7.10-pre4
        2. 尾部.0移除（1.8.0 → 1.8），但1.0保持不变
        """
        result = version_id.replace("_", "-")
        if result.endswith(".0") and result != "1.0":
            result = result[:-2]
        return result

    def _get_version_list_timeouts(self, source: VersionSource) -> Tuple[int, int]:
        """获取版本列表请求的超时时间

        返回 (首选超时, 次选超时)，单位秒
        """
        if source == VersionSource.BMCLAPI_FIRST:
            return (30, 90)
        elif source == VersionSource.MOJANG_FIRST:
            return (5, 35)
        else:  # MOJANG_ONLY
            return (60, 120)

    def _hash_file(self, path: Path, algo: str = "sha1") -> str:
        """计算文件哈希"""
        import hashlib

        h = hashlib.new(algo)
        with open(path, "rb") as f:
            while True:
                data = f.read(65536)
                if not data:
                    break
                h.update(data)
        return h.hexdigest()

    def _should_skip(self, net_file: NetFile) -> Tuple[bool, str]:
        """检查是否跳过文件"""
        p = Path(net_file.local_path)
        if not p.exists():
            return False, ""
        try:
            size_ok = (net_file.min_size == 0) or (
                p.stat().st_size >= net_file.min_size
            )
            if not size_ok:
                return False, ""
            if net_file.check_hash and self.config.verify_hash:
                local_hash = self._hash_file(p, "sha1")
                if local_hash.lower() != net_file.check_hash.lower():
                    return False, ""
            return True, "已存在且验证通过"
        except Exception:
            return False, ""

    def _get_source_urls(
        self, original_url: str, is_asset: bool = False, is_library: bool = False
    ) -> List[str]:
        """获取下载源URL列表

        Args:
            original_url: 原始URL
            is_asset: 是否为资源文件
            is_library: 是否为库文件
        """
        mirror_url = original_url

        if is_asset:
            if "resources.download.minecraft.net" in original_url:
                mirror_url = original_url.replace(
                    "https://resources.download.minecraft.net",
                    "https://bmclapi2.bangbang93.com/assets",
                )
        elif is_library:
            if "libraries.minecraft.net" in original_url:
                mirror_url = original_url.replace(
                    "https://libraries.minecraft.net",
                    "https://bmclapi2.bangbang93.com/maven",
                )
        else:
            if "launcher.mojang.com" in original_url:
                mirror_url = original_url.replace(
                    "https://launcher.mojang.com",
                    "https://bmclapi2.bangbang93.com",
                )
            elif "piston-data.mojang.com" in original_url:
                mirror_url = original_url.replace(
                    "https://piston-data.mojang.com",
                    "https://bmclapi2.bangbang93.com",
                )
            elif "launchermeta.mojang.com" in original_url:
                mirror_url = original_url.replace(
                    "https://launchermeta.mojang.com",
                    "https://bmclapi2.bangbang93.com",
                )
            elif "piston-meta.mojang.com" in original_url:
                mirror_url = original_url.replace(
                    "https://piston-meta.mojang.com",
                    "https://bmclapi2.bangbang93.com",
                )

        special_mods = ["minecraftforge", "fabricmc", "neoforged"]
        is_special_mod_url = any(mod in original_url.lower() for mod in special_mods)

        if is_special_mod_url:
            return [mirror_url]

        if self.download_source == DownloadSource.BMCLAPI_FIRST:
            return [mirror_url, original_url]
        elif self.download_source == DownloadSource.OFFICIAL_FIRST:
            return [original_url, mirror_url]
        else:  # AUTO
            if self._prefer_official:
                return [original_url, mirror_url]
            else:
                return [mirror_url, original_url]

    def get_version_manifest(self) -> Dict:
        """获取版本列表

        根据PCL逻辑：
        1. 先测试Mojang源响应时间
        2. 如果 < 4000ms，则优先使用官方源
        3. 否则使用BMCLAPI镜像源
        """
        mojang_url = self.mirrors["mojang"]["version_list"]
        bmclapi_url = self.mirrors["bmclapi"]["version_list"]

        # 先测试Mojang官方源的响应时间
        try:
            start_time = time.time()
            response = self._session.get(mojang_url, timeout=30)
            response.raise_for_status()
            data = response.json()

            versions = data.get("versions", [])
            if len(versions) >= 200:
                elapsed_ms = (time.time() - start_time) * 1000
                self._prefer_official = elapsed_ms < 4000
                self._version_list_load_time = elapsed_ms

                self.logger.info(
                    f"Mojang官方源加载耗时：{elapsed_ms:.0f}ms，"
                    f"{'可优先使用官方源' if self._prefer_official else '将使用BMCLAPI镜像源'}"
                )

                self._version_manifest_cache = data
                self._version_list_loader_state = "completed"
                return data
        except Exception as e:
            self.logger.warning(f"Mojang官方源获取失败: {e}")

        # Mojang失败，尝试BMCLAPI镜像
        try:
            response = self._session.get(bmclapi_url, timeout=30)
            response.raise_for_status()
            data = response.json()

            versions = data.get("versions", [])
            if len(versions) >= 200:
                self._prefer_official = False
                self._version_list_loader_state = "completed"
                return data
        except Exception as e:
            self.logger.warning(f"BMCLAPI镜像源获取失败: {e}")

        raise Exception("无法获取版本列表")

    def get_version_info(self, version_id: str) -> Dict:
        """获取版本详细信息（处理继承链）"""
        standardized_id = self._standardize_version_id(version_id)
        manifest = self.get_version_manifest()

        version_url = None
        for version in manifest.get("versions", []):
            if version.get("id") == standardized_id:
                version_url = version.get("url")
                break

        if not version_url:
            raise Exception(f"找不到版本: {version_id}")

        version_info = self._fetch_version_manifest(version_url)

        if version_info and "inheritsFrom" in version_info:
            parent_info = self.get_version_info(version_info["inheritsFrom"])
            version_info = self._merge_version_info(parent_info, version_info)

        return version_info

    def _fetch_version_manifest(self, version_url: str) -> Dict:
        """获取版本Manifest JSON"""
        urls = self._get_source_urls(version_url)
        for url in urls:
            try:
                response = self._session.get(url, timeout=15)
                response.raise_for_status()
                return response.json()
            except Exception:
                continue
        raise Exception("无法获取版本Manifest")

    def _merge_version_info(self, parent: Dict, child: Dict) -> Dict:
        """合并父子版本信息，父版本的值会被子版本覆盖"""
        result = parent.copy()

        for key, value in child.items():
            if key == "inheritsFrom":
                continue
            if (
                isinstance(value, dict)
                and key in result
                and isinstance(result[key], dict)
            ):
                result[key] = self._merge_version_info(result[key], value)
            elif (
                isinstance(value, list)
                and key in result
                and isinstance(result[key], list)
            ):
                if key == "libraries":
                    existing_names = {
                        lib.get("name")
                        for lib in result.get("libraries", [])
                        if lib.get("name")
                    }
                    for lib in value:
                        if lib.get("name") not in existing_names:
                            result[key].append(lib)
                else:
                    result[key] = value
            else:
                result[key] = value

        return result

    def _download_single_file(self, net_file: NetFile) -> bool:
        """下载单个文件"""
        if self._cancelled.is_set():
            return False

        # 检查是否跳过
        skip, reason = self._should_skip(net_file)
        if skip:
            self._update_progress(
                status=f"跳过: {net_file.file_name}", current_file=net_file.file_name
            )
            return True

        # 确保目录存在
        Path(net_file.local_path).parent.mkdir(exist_ok=True, parents=True)

        # 尝试从各个源下载
        littledl_config = self.config.to_littledl_config()

        def progress_wrapper(downloaded: int, total: int, speed: float, eta: int):
            self._current_downloaded = downloaded
            self._current_total = total
            self._current_speed = speed
            self._current_eta = eta
            self._update_progress(
                status=f"下载中: {net_file.file_name}",
                current=downloaded,
                total=total,
                speed=speed,
                eta=float(eta),
                current_file=net_file.file_name,
            )

        # 为当前文件创建带进度回调的配置（禁用哈希校验）
        file_config = DownloadConfig(
            enable_chunking=littledl_config.enable_chunking,
            max_chunks=littledl_config.max_chunks,
            chunk_size=littledl_config.chunk_size,
            buffer_size=littledl_config.buffer_size,
            timeout=littledl_config.timeout,
            resume=littledl_config.resume,
            verify_ssl=littledl_config.verify_ssl,
            verify_hash=False,
            expected_hash=None,
            hash_algorithm="sha1",
            speed_limit=littledl_config.speed_limit,
            retry=littledl_config.retry,
            proxy=littledl_config.proxy,
            headers=littledl_config.headers,
            progress_callback=progress_wrapper,
            fallback_to_single_on_failure=True,
            enable_adaptive=True,
            enable_hybrid_turbo=True,
        )

        for url in net_file.urls:
            if self._cancelled.is_set():
                return False

            try:
                self._update_progress(
                    status=f"开始下载: {net_file.file_name}",
                    current_file=net_file.file_name,
                )

                # 使用littledl下载
                result_path = download_file_sync(
                    url=url,
                    save_path=str(Path(net_file.local_path).parent),
                    filename=Path(net_file.local_path).name,
                    config=file_config,
                )

                self._update_progress(
                    status=f"完成: {net_file.file_name}",
                    current_file=net_file.file_name,
                )
                return True

            except Exception as e:
                reason = f"下载失败: {net_file.file_name} -> {e}"
                self.last_error = reason
                self._update_progress(status=reason, current_file=net_file.file_name)
                self.logger.warning(f"{reason}; url={url}")
                continue

        if not self.last_error:
            self.last_error = f"失败: {net_file.file_name}"
        self._update_progress(status=self.last_error, current_file=net_file.file_name)
        return False

    def _update_progress(
        self,
        status: str = "",
        current: int = 0,
        total: int = 0,
        speed: float = 0.0,
        eta: float = 0.0,
        current_file: str = "",
        total_files: int = 0,
        finished_files: int = 0,
        failed_files: int = 0,
        active_files: int = 0,
        speed_stability: float = 0.0,
        elapsed_time: float = 0.0,
    ):
        """更新进度回调"""
        if self.progress_callback:
            progress = DownloadProgress(
                total=total,
                current=current,
                status=status,
                speed=speed,
                total_files=total_files,
                finished_files=finished_files,
                eta=eta,
                connections=self.config.max_chunks
                if self.config.enable_chunking
                else 1,
                current_file=current_file,
                failed_files=failed_files,
                active_files=active_files,
                speed_stability=speed_stability,
                elapsed_time=elapsed_time,
            )
            self.progress_callback(progress)

    def _download_batch(self, net_files: List[NetFile]) -> Tuple[bool, List[str]]:
        """使用 BatchDownloader 批量下载文件

        Returns:
            Tuple[bool, List[str]]: (是否全部成功, 失败文件列表)
        """
        try:
            result = asyncio.run(self._async_download_batch(net_files))
            return result
        except Exception as e:
            self.logger.error(f"批量下载异常: {e}")
            return False, [f.file_name for f in net_files]
        finally:
            self._update_progress(
                status="下载完成",
                total_files=len(net_files),
                finished_files=len(net_files),
            )

    async def _async_download_batch(
        self, net_files: List[NetFile]
    ) -> Tuple[bool, List[str]]:
        """异步批量下载实现"""
        downloader = MCBatchDownloader(
            max_concurrent_files=min(16, len(net_files)),
            max_total_threads=20,
        )

        failed_files: List[str] = []

        def batch_progress_callback(progress: BatchProgress):
            """批量下载进度回调"""
            active = progress.get_active_files()
            current = active[0] if active else None
            status_msg = (
                f"下载中: {current.filename} ({progress.completed_files}/{progress.total_files})"
                if current
                else f"下载中... ({progress.completed_files}/{progress.total_files})"
            )
            total_bytes = getattr(progress, "total_bytes", 0) or 0
            downloaded_bytes = getattr(progress, "downloaded_bytes", 0) or 0
            self._update_progress(
                status=status_msg,
                current=downloaded_bytes,
                total=total_bytes if total_bytes > 0 else progress.total_files,
                speed=getattr(progress, "smooth_speed", 0) or 0,
                eta=getattr(progress, "eta", 0) or 0,
                current_file=current.filename if current else "",
                total_files=progress.total_files,
                finished_files=progress.completed_files,
                failed_files=getattr(progress, "failed_files", 0) or 0,
                active_files=getattr(progress, "active_files", 0) or 0,
                speed_stability=getattr(progress, "speed_stability", 0.0) or 0.0,
                elapsed_time=getattr(progress, "elapsed_time", 0.0) or 0.0,
            )

        def file_complete_callback(task: FileTask):
            """文件完成回调"""
            filename = task.filename or "unknown"
            if task.status == FileTaskStatus.FAILED:
                self.logger.warning(f"文件下载失败: {filename}, error: {task.error}")
                failed_files.append(filename)
            elif task.status == FileTaskStatus.COMPLETED:
                self.logger.info(f"文件下载完成: {filename}")

        downloader.set_progress_callback(batch_progress_callback)
        downloader.set_file_complete_callback(file_complete_callback)

        added_count = 0
        skipped_count = 0
        for net_file in net_files:
            if self._cancelled.is_set():
                await downloader.cancel()
                return False, failed_files

            skip, reason = self._should_skip(net_file)
            if skip:
                self.logger.info(f"跳过: {net_file.file_name} - {reason}")
                skipped_count += 1
                continue

            Path(net_file.local_path).parent.mkdir(exist_ok=True, parents=True)

            save_path = str(Path(net_file.local_path).parent)
            filename = Path(net_file.local_path).name
            await downloader.add_url(net_file.urls[0], save_path, filename)
            added_count += 1

        total_to_download = len(net_files)
        self._update_progress(
            status=f"开始下载 {added_count} 个文件 ({skipped_count} 个跳过)...",
            total_files=total_to_download,
            finished_files=skipped_count,
        )
        await downloader.start()

        return len(failed_files) == 0, failed_files

    def download_version(
        self,
        version_id: str,
        cancel_event: Optional[threading.Event] = None,
        custom_name: Optional[str] = None,
        target_dir: Optional[str] = None,
    ) -> bool:
        """下载Minecraft版本"""
        try:
            self.last_error = ""
            # 设置取消事件
            if cancel_event:
                # 监听取消事件
                def check_cancel():
                    while not cancel_event.is_set():
                        time.sleep(0.1)
                    self._cancelled.set()

                threading.Thread(target=check_cancel, daemon=True).start()

            version_info = self.get_version_info(version_id)

            # 确定版本目录
            if target_dir:
                version_folder = Path(target_dir) / (custom_name or version_id)
            else:
                version_folder = (
                    self.mc_folder / "versions" / (custom_name or version_id)
                )

            version_folder.mkdir(exist_ok=True, parents=True)

            # 保存版本JSON
            json_path = version_folder / f"{custom_name or version_id}.json"
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(version_info, f, indent=2)

            # 收集所有需要下载的文件
            net_files: List[NetFile] = []

            # 客户端JAR
            client_info = version_info.get("downloads", {}).get("client")
            if client_info:
                client_url = client_info.get("url")
                client_hash = client_info.get("sha1")
                client_size = client_info.get("size", 0)
                client_path = version_folder / f"{custom_name or version_id}.jar"
                net_files.append(
                    NetFile(
                        urls=self._get_source_urls(client_url),
                        local_path=str(client_path),
                        check_hash=client_hash,
                        min_size=1024 * 100,
                        file_name=f"{custom_name or version_id}.jar",
                    )
                )

            # 库文件
            libraries = version_info.get("libraries", [])
            for lib in libraries:
                downloads = lib.get("downloads", {})
                artifact = downloads.get("artifact")
                if artifact:
                    lib_name = lib.get("name", "")
                    if not lib_name:
                        continue
                    parts = lib_name.split(":")
                    if len(parts) < 3:
                        continue
                    group, name, version = parts[:3]
                    path_parts = group.split(".") + [name, version]
                    filename = f"{name}-{version}.jar"
                    if len(parts) > 3:
                        filename = f"{name}-{version}-{parts[3]}.jar"
                    local_path = (
                        self.mc_folder
                        / "libraries"
                        / os.path.join(*path_parts)
                        / filename
                    )
                    url = artifact.get("url")
                    hash_value = artifact.get("sha1")
                    size = artifact.get("size", 0)
                    net_files.append(
                        NetFile(
                            urls=self._get_source_urls(url, is_library=True),
                            local_path=str(local_path),
                            check_hash=hash_value,
                            min_size=size if size > 0 else 1024,
                            file_name=filename,
                        )
                    )

            # 资源文件
            asset_index = version_info.get("assetIndex")
            if asset_index:
                index_url = asset_index.get("url")
                index_hash = asset_index.get("sha1")
                index_id = asset_index.get("id")
                index_path = self.mc_folder / "assets" / "indexes" / f"{index_id}.json"
                net_files.append(
                    NetFile(
                        urls=self._get_source_urls(index_url, is_asset=True),
                        local_path=str(index_path),
                        check_hash=index_hash,
                        min_size=1024,
                        file_name=f"{index_id}.json",
                    )
                )

                # 获取资源对象
                try:
                    resp = self._session.get(index_url, timeout=15)
                    resp.raise_for_status()
                    assets = resp.json().get("objects", {})
                    for asset_path, asset_info in assets.items():
                        asset_hash = asset_info.get("hash")
                        if not asset_hash:
                            continue
                        hash_dir = asset_hash[:2]
                        local_asset_path = (
                            self.mc_folder
                            / "assets"
                            / "objects"
                            / hash_dir
                            / asset_hash
                        )
                        asset_url = f"{self.mirrors['mojang']['asset_base']}/{hash_dir}/{asset_hash}"
                        net_files.append(
                            NetFile(
                                urls=self._get_source_urls(asset_url, is_asset=True),
                                local_path=str(local_asset_path),
                                check_hash=asset_hash,
                                min_size=asset_info.get("size", 0),
                                file_name=asset_hash,
                            )
                        )
                except Exception as e:
                    self.logger.warning(f"获取资源索引失败: {e}")

            # 下载所有文件（使用 BatchDownloader）
            total_files = len(net_files)

            self._update_progress(
                status="准备下载...", total_files=total_files, finished_files=0
            )

            success, failed_files = self._download_batch(net_files)

            # 下载完成
            if not success or failed_files:
                if not self.last_error:
                    self.last_error = f"下载失败文件: {', '.join(failed_files[:3])}"
                self._update_progress(
                    status=f"下载完成，{len(failed_files)}个文件失败: {', '.join(failed_files[:3])}",
                    total_files=total_files,
                    finished_files=total_files - len(failed_files),
                )
                self.logger.error(
                    f"版本下载失败: version={version_id}, failed_count={len(failed_files)}, reason={self.last_error}"
                )
                return False
            else:
                self._update_progress(
                    status=f"版本 {version_id} 下载完成",
                    total_files=total_files,
                    finished_files=total_files,
                )
                return True

        except Exception as e:
            self.last_error = f"下载失败: {str(e)}"
            self._update_progress(status=self.last_error)
            self.logger.exception(f"版本下载异常: version={version_id}")
            return False

    def cancel(self):
        """取消下载"""
        self._cancelled.set()

    def cleanup(self):
        """清理资源"""
        self._session.close()
