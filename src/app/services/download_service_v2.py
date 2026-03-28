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
from typing import List, Dict, Optional, Callable, Tuple, Any
from pathlib import Path
import requests
from dataclasses import dataclass, field

from littledl import (
    download_file,
    download_file_sync,
    DownloadConfig,
    SpeedLimitConfig,
    SpeedLimitMode,
    RetryConfig,
    RetryStrategy,
    ProxyConfig,
    ProxyMode,
)

from ..info import UA


class DownloadSource(enum.Enum):
    """下载源优先级枚举"""

    MIRROR_ONLY = 0
    MIRROR_FIRST = 1
    OFFICIAL_FIRST = 2
    OFFICIAL_ONLY = 3


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
    download_source: str = "mirror_first"

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
        retry = None
        if self.retry_enabled:
            retry = RetryConfig(
                enabled=True,
                strategy=RetryStrategy.EXPONENTIAL,
                max_retries=self.max_retries,
                initial_delay=self.retry_delay,
                max_delay=60.0,
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
                socks5_proxy=self.socks5_proxy,
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
            speed_limit=speed_limit,
            retry=retry,
            proxy=proxy,
            headers={"User-Agent": UA},
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
        download_source: DownloadSource = DownloadSource.MIRROR_FIRST,
        progress_callback: Optional[Callable[[DownloadProgress], None]] = None,
    ):
        self.mc_folder = Path(mc_folder).resolve()
        self.config = config or MinecraftDownloadConfig()
        self.download_source = download_source
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
            },
            "mojang": {
                "version_list": "https://piston-meta.mojang.com/mc/game/version_manifest.json",
                "asset_base": "https://resources.download.minecraft.net",
                "library_base": "https://libraries.minecraft.net",
            },
        }

        # Session
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": UA})

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

    def _get_source_urls(self, original_url: str, is_asset: bool = False) -> List[str]:
        """获取下载源URL列表"""
        base_type = "asset_base" if is_asset else "library_base"
        mirror_base = self.mirrors["bmclapi"][base_type]

        mirror_url = original_url
        for official_domain, mirror_domain in [
            ("https://piston-data.mojang.com", mirror_base),
            ("https://piston-meta.mojang.com", mirror_base),
            ("https://resources.download.minecraft.net", mirror_base),
            ("https://libraries.minecraft.net", mirror_base),
        ]:
            if official_domain in mirror_url:
                mirror_url = mirror_url.replace(official_domain, mirror_domain)
                break

        if self.download_source == DownloadSource.OFFICIAL_ONLY:
            return [original_url]
        elif self.download_source == DownloadSource.MIRROR_ONLY:
            return [mirror_url]
        elif self.download_source == DownloadSource.OFFICIAL_FIRST:
            return [original_url, mirror_url]
        else:
            return [mirror_url, original_url]

    def get_version_manifest(self) -> Dict:
        """获取版本列表"""
        urls = self._get_source_urls(self.mirrors["mojang"]["version_list"])

        for url in urls:
            try:
                response = self._session.get(url, timeout=15)
                response.raise_for_status()
                return response.json()
            except Exception:
                continue

        raise Exception("无法获取版本列表")

    def get_version_info(self, version_id: str) -> Dict:
        """获取版本详细信息"""
        manifest = self.get_version_manifest()

        for version in manifest.get("versions", []):
            if version.get("id") == version_id:
                version_url = version.get("url")
                break
        else:
            raise Exception(f"找不到版本: {version_id}")

        urls = self._get_source_urls(version_url)
        for url in urls:
            try:
                response = self._session.get(url.replace("/maven", ""), timeout=15)
                response.raise_for_status()
                return response.json()
            except Exception:
                continue

        raise Exception(f"无法获取版本信息: {version_id}")

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

        # 为当前文件创建带进度回调的配置
        file_config = DownloadConfig(
            enable_chunking=littledl_config.enable_chunking,
            max_chunks=littledl_config.max_chunks,
            chunk_size=littledl_config.chunk_size,
            buffer_size=littledl_config.buffer_size,
            timeout=littledl_config.timeout,
            resume=littledl_config.resume,
            verify_ssl=littledl_config.verify_ssl,
            speed_limit=littledl_config.speed_limit,
            retry=littledl_config.retry,
            proxy=littledl_config.proxy,
            headers=littledl_config.headers,
            progress_callback=progress_wrapper,
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

                # 验证文件
                if net_file.check_hash and self.config.verify_hash:
                    local_hash = self._hash_file(Path(net_file.local_path), "sha1")
                    if local_hash.lower() != net_file.check_hash.lower():
                        print(f"哈希验证失败: {net_file.file_name}")
                        continue

                self._update_progress(
                    status=f"完成: {net_file.file_name}",
                    current_file=net_file.file_name,
                )
                return True

            except Exception as e:
                print(f"下载失败 {url}: {e}")
                continue

        self._update_progress(
            status=f"失败: {net_file.file_name}", current_file=net_file.file_name
        )
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
            )
            self.progress_callback(progress)

    def download_version(
        self,
        version_id: str,
        cancel_event: Optional[threading.Event] = None,
        custom_name: Optional[str] = None,
        target_dir: Optional[str] = None,
    ) -> bool:
        """下载Minecraft版本"""
        try:
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
                            urls=self._get_source_urls(url),
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
                    print(f"获取资源索引失败: {e}")

            # 下载所有文件
            total_files = len(net_files)
            completed_files = 0
            failed_files = []

            self._update_progress(
                status="准备下载...", total_files=total_files, finished_files=0
            )

            for net_file in net_files:
                if self._cancelled.is_set():
                    self._update_progress(status="下载已取消")
                    return False

                success = self._download_single_file(net_file)

                if success:
                    completed_files += 1
                else:
                    failed_files.append(net_file.file_name)

                self._update_progress(
                    total_files=total_files, finished_files=completed_files
                )

            # 下载完成
            if failed_files:
                self._update_progress(
                    status=f"下载完成，{len(failed_files)}个文件失败",
                    total_files=total_files,
                    finished_files=completed_files,
                )
                return False
            else:
                self._update_progress(
                    status=f"版本 {version_id} 下载完成",
                    total_files=total_files,
                    finished_files=completed_files,
                )
                return True

        except Exception as e:
            self._update_progress(status=f"下载失败: {str(e)}")
            return False

    def cancel(self):
        """取消下载"""
        self._cancelled.set()

    def cleanup(self):
        """清理资源"""
        self._session.close()
