import os
import json
import enum
import requests
import threading
import time
from typing import List, Dict, Optional, Callable, Tuple
from pathlib import Path
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed


class DownloadSource(enum.Enum):
    """下载源优先级枚举"""
    MIRROR_ONLY = 0      # 仅使用镜像源
    MIRROR_FIRST = 1     # 优先使用镜像源
    OFFICIAL_FIRST = 2   # 优先使用官方源
    OFFICIAL_ONLY = 3    # 仅使用官方源


class NetFile:
    """网络文件下载信息"""
    def __init__(self, urls: List[str], local_path: str, check_hash: Optional[str] = None, min_size: int = 0):
        self.urls = urls
        self.local_path = local_path
        self.check_hash = check_hash
        self.min_size = min_size


class DownloadProgress:
    """下载进度信息"""
    def __init__(self, total: int = 0, current: int = 0, status: str = "", speed: float = 0.0):
        self.total = total
        self.current = current
        self.status = status
        self.speed = speed  # 单位：字节/秒
        self.percentage = 0 if total == 0 else (current / total) * 100


class MinecraftDownloader:
    """Minecraft版本下载器，支持多线程和实时速度统计"""
    def __init__(self,
                 mc_folder: str,
                 download_source: DownloadSource = DownloadSource.MIRROR_FIRST,
                 progress_callback: Optional[Callable[[DownloadProgress], None]] = None,
                 max_workers: int = 8):
        """
        初始化下载器
        :param mc_folder: Minecraft安装目录
        :param download_source: 下载源优先级
        :param progress_callback: 进度回调函数
        :param max_workers: 最大下载线程数
        """
        self.mc_folder = Path(mc_folder).resolve()
        self.download_source = download_source
        self.progress_callback = progress_callback
        self._lock = threading.Lock()
        self._temp_folder = self.mc_folder / "temp"
        self._temp_folder.mkdir(exist_ok=True, parents=True)
        self.max_workers = max_workers

        # 速度统计
        self._total_bytes = 0
        self._last_bytes = 0
        self._speed = 0.0
        self._speed_lock = threading.Lock()
        self._stop_speed = threading.Event()
        self._progress_total = 0
        self._progress_current = 0

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
            }
        }

    def _start_speed_monitor(self):
        def monitor():
            while not self._stop_speed.is_set():
                time.sleep(1)
                with self._speed_lock:
                    now = self._total_bytes
                    self._speed = now - self._last_bytes
                    self._last_bytes = now
                # 进度回调
                self._update_progress(DownloadProgress(
                    total=self._progress_total,
                    current=self._progress_current,
                    status="下载中...",
                    speed=self._speed
                ))
        self._stop_speed.clear()
        t = threading.Thread(target=monitor, daemon=True)
        t.start()
        self._speed_thread = t

    def _stop_speed_monitor(self):
        self._stop_speed.set()
        if hasattr(self, '_speed_thread'):
            self._speed_thread.join(timeout=2)

    def _update_progress(self, progress: DownloadProgress):
        """更新下载进度"""
        if self.progress_callback:
            self.progress_callback(progress)

    def _download_file(self, net_file: NetFile) -> bool:
        """下载单个文件（线程安全，支持速度统计）"""
        target_dir = Path(net_file.local_path).parent
        target_dir.mkdir(exist_ok=True, parents=True)
        for url in net_file.urls:
            try:
                self._update_progress(DownloadProgress(status=f"开始下载: {Path(net_file.local_path).name}"))
                with requests.get(url, stream=True, timeout=15) as r:
                    r.raise_for_status()
                    total_size = int(r.headers.get('content-length', 0))
                    downloaded_size = 0
                    with open(net_file.local_path, 'wb') as f:
                        for chunk in r.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
                                chunk_len = len(chunk)
                                downloaded_size += chunk_len
                                with self._speed_lock:
                                    self._total_bytes += chunk_len
                    # 验证文件
                    file_size = os.path.getsize(net_file.local_path)
                    if net_file.min_size > 0 and file_size < net_file.min_size:
                        raise Exception(f"文件大小不足: {file_size} < {net_file.min_size}")
                self._update_progress(DownloadProgress(status=f"下载完成: {Path(net_file.local_path).name}"))
                return True
            except Exception as e:
                self._update_progress(DownloadProgress(status=f"下载失败: {str(e)}"))
                continue
        return False

    def _get_version_list_urls(self) -> List[str]:
        """获取版本列表URL，根据下载源优先级"""
        official_url = self.mirrors["mojang"]["version_list"]
        mirror_url = self.mirrors["bmclapi"]["version_list"]

        if self.download_source == DownloadSource.OFFICIAL_ONLY:
            return [official_url]
        elif self.download_source == DownloadSource.MIRROR_ONLY:
            return [mirror_url]
        elif self.download_source == DownloadSource.OFFICIAL_FIRST:
            return [official_url, mirror_url]
        else:  # MIRROR_FIRST
            return [mirror_url, official_url]

    def _get_source_urls(self, original_url: str, is_asset: bool = False) -> List[str]:
        """根据原始URL生成不同源的URL列表"""
        base_type = "asset_base" if is_asset else "library_base"
        mirror_base = self.mirrors["bmclapi"][base_type]
        official_base = self.mirrors["mojang"][base_type]

        # 替换为镜像源URL
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

        # 根据优先级排序URL
        if self.download_source == DownloadSource.OFFICIAL_ONLY:
            return [original_url]
        elif self.download_source == DownloadSource.MIRROR_ONLY:
            return [mirror_url]
        elif self.download_source == DownloadSource.OFFICIAL_FIRST:
            return [original_url, mirror_url]
        else:  # MIRROR_FIRST
            return [mirror_url, original_url]

    def get_version_manifest(self) -> Dict:
        """获取版本列表清单"""
        urls = self._get_version_list_urls()

        for url in urls:
            try:
                self._update_progress(DownloadProgress(status=f"获取版本列表: {url}"))
                response = requests.get(url, timeout=15)
                response.raise_for_status()
                return response.json()
            except Exception as e:
                self._update_progress(DownloadProgress(status=f"获取版本列表失败: {str(e)}"))
                continue

        raise Exception("无法获取版本列表")

    def get_version_info(self, version_id: str) -> Dict:
        """获取特定版本的详细信息"""
        manifest = self.get_version_manifest()

        # 查找版本
        for version in manifest.get("versions", []):
            if version.get("id") == version_id:
                version_url = version.get("url")
                break
        else:
            raise Exception(f"找不到版本: {version_id}")

        # 获取版本详细信息
        urls = self._get_source_urls(version_url)
        for url in urls:
            try:
                self._update_progress(DownloadProgress(status=f"获取版本信息: {version_id}"))
                response = requests.get(url, timeout=15)
                response.raise_for_status()
                return response.json()
            except Exception as e:
                self._update_progress(DownloadProgress(status=f"获取版本信息失败: {str(e)}"))
                continue

        raise Exception(f"无法获取版本信息: {version_id}")

    def download_version(self, version_id: str) -> bool:
        """下载指定版本，支持多线程和实时速度"""
        try:
            # 获取版本信息
            version_info = self.get_version_info(version_id)
            version_folder = self.mc_folder / "versions" / version_id
            version_folder.mkdir(exist_ok=True, parents=True)

            # 保存版本JSON
            json_path = version_folder / f"{version_id}.json"
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(version_info, f, indent=2)

            # 下载客户端Jar
            client_info = version_info.get("downloads", {}).get("client")
            if client_info:
                client_url = client_info.get("url")
                client_hash = client_info.get("sha1")
                client_path = version_folder / f"{version_id}.jar"

                net_file = NetFile(
                    urls=self._get_source_urls(client_url),
                    local_path=str(client_path),
                    check_hash=client_hash,
                    min_size=1024*100  # 最小100KB
                )

                if not self._download_file(net_file):
                    raise Exception("下载客户端Jar失败")

            # 多线程下载依赖库和资源
            self._start_speed_monitor()
            try:
                self._download_libraries(version_info, threaded=True)
                self._download_assets(version_info, threaded=True)
            finally:
                self._stop_speed_monitor()

            self._update_progress(DownloadProgress(status=f"版本 {version_id} 下载完成", speed=self._speed))
            return True

        except Exception as e:
            self._update_progress(DownloadProgress(status=f"下载失败: {str(e)}"))
            return False

    def _download_libraries(self, version_info: Dict, threaded: bool = False):
        """下载依赖库，支持多线程"""
        libraries = version_info.get("libraries", [])
        tasks = []
        net_files = []
        for lib in libraries:
            downloads = lib.get("downloads", {})
            artifact = downloads.get("artifact")
            if not artifact:
                continue
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
            local_path = self.mc_folder / "libraries" / os.path.join(*path_parts) / filename
            url = artifact.get("url")
            hash_value = artifact.get("sha1")
            size = artifact.get("size", 0)
            net_file = NetFile(
                urls=self._get_source_urls(url),
                local_path=str(local_path),
                check_hash=hash_value,
                min_size=size if size > 0 else 1024
            )
            net_files.append(net_file)

        self._progress_total += len(net_files)
        if threaded and net_files:
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = [executor.submit(self._threaded_download_file, nf) for nf in net_files]
                for fut in as_completed(futures):
                    pass
        else:
            for nf in net_files:
                self._download_file(nf)

    def _threaded_download_file(self, net_file: NetFile):
        result = self._download_file(net_file)
        with self._lock:
            self._progress_current += 1
        return result

    def _download_assets(self, version_info: Dict, threaded: bool = False):
        """下载资源文件，支持多线程"""
        asset_index = version_info.get("assetIndex")
        if not asset_index:
            self._update_progress(DownloadProgress(status="没有找到资源索引信息"))
            return
        index_url = asset_index.get("url")
        index_hash = asset_index.get("sha1")
        index_id = asset_index.get("id")
        index_path = self.mc_folder / "assets" / "indexes" / f"{index_id}.json"
        index_path.parent.mkdir(exist_ok=True, parents=True)
        net_file = NetFile(
            urls=self._get_source_urls(index_url, is_asset=True),
            local_path=str(index_path),
            check_hash=index_hash,
            min_size=1024
        )
        if not self._download_file(net_file):
            raise Exception("下载资源索引失败")
        with open(index_path, 'r', encoding='utf-8') as f:
            assets = json.load(f).get("objects", {})
        net_files = []
        for asset_path, asset_info in assets.items():
            asset_hash = asset_info.get("hash")
            if not asset_hash:
                continue
            hash_dir = asset_hash[:2]
            hash_filename = asset_hash
            local_asset_path = self.mc_folder / "assets" / "objects" / hash_dir / hash_filename
            local_asset_path.parent.mkdir(exist_ok=True, parents=True)
            asset_url = f"{self.mirrors['mojang']['asset_base']}/{hash_dir}/{hash_filename}"
            net_file = NetFile(
                urls=self._get_source_urls(asset_url, is_asset=True),
                local_path=str(local_asset_path),
                check_hash=asset_hash,
                min_size=asset_info.get('size', 0)
            )
            net_files.append(net_file)
        self._progress_total += len(net_files)
        if threaded and net_files:
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = [executor.submit(self._threaded_download_file, nf) for nf in net_files]
                for fut in as_completed(futures):
                    pass
        else:
            for nf in net_files:
                self._download_file(nf)

    def cleanup(self):
        """清理临时文件"""
        if self._temp_folder.exists():
            shutil.rmtree(self._temp_folder)
            self._temp_folder.mkdir(exist_ok=True)


# 使用示例
if __name__ == "__main__":
    def progress_handler(progress: DownloadProgress):
        speed_str = f"，速度：{progress.speed/1024:.1f} KB/s" if progress.speed else ""
        print(f"{progress.status} - {progress.percentage:.1f}%{speed_str}")

    downloader = MinecraftDownloader(
        mc_folder=r"D:\Minecraft",
        download_source=DownloadSource.MIRROR_FIRST,
        progress_callback=progress_handler,
        max_workers=8
    )
    try:
        version_id = "1.19.4"
        print(f"开始下载Minecraft {version_id}...")
        if downloader.download_version(version_id):
            print(f"Minecraft {version_id} 下载完成！")
        else:
            print(f"Minecraft {version_id} 下载失败！")
    finally:
        downloader.cleanup()