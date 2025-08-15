import os
import json
import enum
import requests
import threading
import time
import hashlib
from typing import List, Dict, Optional, Callable, Tuple
from pathlib import Path
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from ..info import VER


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
    """下载进度信息

    total_percentage 计算规则：
    - 默认 = finished_files / total_files * 100
    - 若传入 custom_total_percentage，则用该值（可包含当前文件的部分进度），
      同时 finished_files 仍保持为整数（仅在文件完整完成后递增）。
    """
    def __init__(self, total: int = 0, current: int = 0, status: str = "", speed: float = 0.0,
                 total_files: int = 0, finished_files: int = 0, custom_total_percentage: float | None = None):
        self.total = total
        self.current = current
        self.status = status
        self.speed = speed  # 单位：字节/秒
        self.total_files = total_files
        # 确保显示用的 finished_files 为整数
        self.finished_files = int(finished_files)
        if total == 0:
            self.percentage = 0
        else:
            self.percentage = min((current / total) * 100, 100)
        if custom_total_percentage is not None:
            self.total_percentage = min(custom_total_percentage, 100)
        elif total_files > 0:
            self.total_percentage = min((self.finished_files / total_files) * 100, 100)
        else:
            self.total_percentage = 0


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
        # requests Session 复用 TCP 连接，减少握手开销
        self._session = self._build_session()

        # 速度统计
        self._total_bytes = 0
        self._last_bytes = 0
        self._speed = 0.0
        self._speed_lock = threading.Lock()
        self._stop_speed = threading.Event()
        self._progress_total = 0
        self._progress_current = 0
        self._last_total_percentage = 0.0

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

    # ---------------------- Session / 工具方法 ----------------------
    def _build_session(self) -> requests.Session:
        """创建带连接池的 Session, 减少重复握手。
        pool size 设为 max_workers * 2 以兼顾突发小文件请求。
        """
        session = requests.Session()
        from requests.adapters import HTTPAdapter
        adapter = HTTPAdapter(pool_connections=self.max_workers * 2, pool_maxsize=self.max_workers * 2, max_retries=2)
        session.mount('http://', adapter)
        session.mount('https://', adapter)
        # 统一的 headers
        session.headers.update({
            'User-Agent': f'MineLauncher/{VER}'
        })
        return session

    def _hash_file(self, path: Path, algo: str = 'sha1', chunk: int = 65536) -> str:
        h = hashlib.new(algo)
        with open(path, 'rb') as f:
            while True:
                data = f.read(chunk)
                if not data:
                    break
                h.update(data)
        return h.hexdigest()

    def _should_skip(self, net_file: 'NetFile') -> Tuple[bool, str]:
        """判断是否跳过文件：已存在并满足大小与（若有）哈希。返回(跳过?,原因)。"""
        p = Path(net_file.local_path)
        if not p.exists():
            return False, ''
        try:
            size_ok = (net_file.min_size == 0) or (p.stat().st_size >= net_file.min_size)
            if not size_ok:
                return False, ''
            if net_file.check_hash:
                # 只对较大文件或随机抽样验证可优化，这里对所有带 hash 的文件校验一次
                local_hash = self._hash_file(p, 'sha1')
                if local_hash.lower() != net_file.check_hash.lower():
                    return False, ''
            return True, '已存在且验证通过'
        except Exception:
            return False, ''

    # ---------------------- 下载核心 ----------------------

    def _start_speed_monitor(self):
        def monitor():
            while not self._stop_speed.is_set():
                time.sleep(1)
                with self._speed_lock:
                    now = self._total_bytes
                    self._speed = now - self._last_bytes
                    self._last_bytes = now
                # 仅在有实际进度时回调
                if self._progress_total > 0:
                    # 速度监控也一并回传总文件统计，避免UI在长时间单文件下载时显示 0/0
                    total_files = getattr(self, '_total_files', 0)
                    finished_files = getattr(self, '_finished_files', 0)
                    self._update_progress(DownloadProgress(
                        total=self._progress_total,
                        current=self._progress_current,
                        status="下载中...",
                        speed=self._speed,
                        total_files=total_files,
                        finished_files=finished_files
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
        # 只在有意义的进度变化时回调进度条和速度
        if self.progress_callback:
            # 如果是仅状态变更（如status有内容但current/total均为0），则不回调进度条
            if (progress.total == 0 and progress.current == 0 and progress.speed == 0):
                # 只更新状态文本
                self.progress_callback(DownloadProgress(status=progress.status))
            else:
                # 确保 total_percentage 单调不回退
                if hasattr(progress, 'total_percentage'):
                    if progress.total_percentage < self._last_total_percentage:
                        progress.total_percentage = self._last_total_percentage
                    else:
                        self._last_total_percentage = progress.total_percentage
                self.progress_callback(progress)

    def _download_file(self, net_file: NetFile) -> bool:
        """下载单个文件（线程安全，支持速度统计 + 断点/跳过）。"""
        target_dir = Path(net_file.local_path).parent
        target_dir.mkdir(exist_ok=True, parents=True)

        # 跳过已存在的有效文件
        skip, reason = self._should_skip(net_file)
        total_files = getattr(self, '_total_files', 0)
        finished_files = getattr(self, '_finished_files', 0)
        if skip:
            self._update_progress(DownloadProgress(
                status=f"跳过: {Path(net_file.local_path).name} ({reason})",
                total_files=total_files,
                finished_files=finished_files
            ))
            return True

        # 若存在部分文件，尝试断点续传（ Range ）
        existing_size = 0
        p = Path(net_file.local_path)
        temp_path = p.with_suffix(p.suffix + '.part')
        if p.exists():
            # 将已存在完整文件重命名为 part，用于继续写入（防止直接覆盖）
            try:
                existing_size = p.stat().st_size
                p.rename(temp_path)
            except Exception:
                existing_size = 0

        for url in net_file.urls:
            try:
                self._update_progress(DownloadProgress(
                    status=f"开始下载: {Path(net_file.local_path).name}",
                    total_files=total_files,
                    finished_files=finished_files
                ))
                headers = {}
                if existing_size > 0:
                    headers['Range'] = f'bytes={existing_size}-'
                # 连接
                with self._session.get(url, stream=True, timeout=20, headers=headers) as r:
                    if r.status_code == 416:  # 请求范围无效，重置
                        existing_size = 0
                        if temp_path.exists():
                            temp_path.unlink()
                        # 重试无 Range
                        continue
                    r.raise_for_status()
                    content_length = r.headers.get('content-length')
                    total_size = int(content_length) + existing_size if content_length else (net_file.min_size or 0)
                    downloaded_size = existing_size
                    # 打开文件（追加 / 覆盖）
                    open_mode = 'ab' if existing_size > 0 else 'wb'
                    with open(temp_path, open_mode) as f:
                        # 动态 chunk：大文件更大块（128KB），小文件保持 32KB
                        dynamic_chunk = 131072 if total_size > 5 * 1024 * 1024 else 32768
                        for chunk in r.iter_content(chunk_size=dynamic_chunk):
                            if not chunk:
                                continue
                            f.write(chunk)
                            chunk_len = len(chunk)
                            downloaded_size += chunk_len
                            with self._speed_lock:
                                self._total_bytes += chunk_len
                            # 动态读取最新已完成文件数，避免回退
                            dynamic_finished = getattr(self, '_finished_files', finished_files)
                            self._update_progress(DownloadProgress(
                                total=total_size if total_size > 0 else net_file.min_size,
                                current=downloaded_size,
                                status=f"下载中: {Path(net_file.local_path).name}",
                                speed=self._speed,
                                total_files=total_files,
                                finished_files=dynamic_finished
                            ))
                # 下载完成 -> 原子替换
                temp_path.replace(p)
                # 验证大小 / hash
                file_size = p.stat().st_size
                if net_file.min_size > 0 and file_size < net_file.min_size:
                    raise Exception(f"文件大小不足: {file_size} < {net_file.min_size}")
                if net_file.check_hash:
                    local_hash = self._hash_file(p, 'sha1')
                    if local_hash.lower() != net_file.check_hash.lower():
                        raise Exception("哈希不匹配")
                self._update_progress(DownloadProgress(
                    total=total_size if total_size > 0 else net_file.min_size,
                    current=file_size,
                    status=f"下载完成: {Path(net_file.local_path).name}",
                    speed=self._speed,
                    total_files=total_files,
                    finished_files=finished_files
                ))
                return True
            except Exception as e:
                self._update_progress(DownloadProgress(
                    status=f"下载失败: {Path(net_file.local_path).name} -> {str(e)}",
                    total_files=getattr(self, '_total_files', 0),
                    finished_files=getattr(self, '_finished_files', 0)
                ))
                # 失败清理临时文件，尝试下一个源
                if temp_path.exists():
                    try:
                        temp_path.unlink()
                    except Exception:
                        pass
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
                response = self._session.get(url, timeout=15)
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
                response = self._session.get(url.replace("/maven", ""), timeout=15)
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

            # 先解析所有待下载文件，严格根据json内容统计
            net_files = []
            # 客户端jar
            client_info = version_info.get("downloads", {}).get("client")
            if client_info:
                client_url = client_info.get("url")
                client_hash = client_info.get("sha1")
                client_path = version_folder / f"{version_id}.jar"
                net_files.append(NetFile(
                    urls=self._get_source_urls(client_url),
                    local_path=str(client_path),
                    check_hash=client_hash,
                    min_size=1024*100
                ))
            # libraries
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
                    local_path = self.mc_folder / "libraries" / os.path.join(*path_parts) / filename
                    url = artifact.get("url")
                    hash_value = artifact.get("sha1")
                    size = artifact.get("size", 0)
                    net_files.append(NetFile(
                        urls=self._get_source_urls(url),
                        local_path=str(local_path),
                        check_hash=hash_value,
                        min_size=size if size > 0 else 1024
                    ))
            # assets
            asset_index = version_info.get("assetIndex")
            if asset_index:
                index_url = asset_index.get("url")
                index_hash = asset_index.get("sha1")
                index_id = asset_index.get("id")
                index_path = self.mc_folder / "assets" / "indexes" / f"{index_id}.json"
                net_files.append(NetFile(
                    urls=self._get_source_urls(index_url, is_asset=True),
                    local_path=str(index_path),
                    check_hash=index_hash,
                    min_size=1024
                ))
                # 统计资源文件数
                try:
                    resp = self._session.get(index_url, timeout=15)
                    resp.raise_for_status()
                    assets = resp.json().get("objects", {})
                    for asset_path, asset_info in assets.items():
                        asset_hash = asset_info.get("hash")
                        if not asset_hash:
                            continue
                        hash_dir = asset_hash[:2]
                        hash_filename = asset_hash
                        local_asset_path = self.mc_folder / "assets" / "objects" / hash_dir / hash_filename
                        asset_url = f"{self.mirrors['mojang']['asset_base']}/{hash_dir}/{hash_filename}"
                        net_files.append(NetFile(
                            urls=self._get_source_urls(asset_url, is_asset=True),
                            local_path=str(local_asset_path),
                            check_hash=asset_hash,
                            min_size=asset_info.get('size', 0)
                        ))
                except Exception:
                    pass

            total_files = len(net_files)
            self._progress_total = total_files
            self._progress_current = 0
            self._total_files = total_files
            self._finished_files = 0
            # 立即回调一次总进度，确保UI能显示总文件数
            self._update_progress(DownloadProgress(
                status="准备下载...",
                total_files=self._total_files,
                finished_files=0
            ))

            # 启动速度监控
            self._start_speed_monitor()
            try:
                # 顺序下载所有文件，支持多线程
                # 将文件分成大文件与小文件，避免大文件占满线程队列
                large_threshold = 5 * 1024 * 1024  # 5MB
                large_files = [f for f in net_files if f.min_size and f.min_size >= large_threshold]
                small_files = [f for f in net_files if f not in large_files]

                def download_one(nf):
                    if self._download_file(nf):
                        with self._lock:
                            self._finished_files += 1
                            self._update_progress(DownloadProgress(
                                status=f"文件下载完成: {os.path.basename(nf.local_path)}",
                                total_files=self._total_files,
                                finished_files=self._finished_files
                            ))
                # 先并发小文件（提高总体完成数反馈速度）
                if small_files:
                    with ThreadPoolExecutor(max_workers=self.max_workers) as ex_small:
                        list(ex_small.map(download_one, small_files))
                # 再下载大文件，限制线程数量，避免过度争抢带宽
                if large_files:
                    with ThreadPoolExecutor(max_workers=min(4, self.max_workers)) as ex_large:
                        list(ex_large.map(download_one, large_files))
            finally:
                self._stop_speed_monitor()

            self._update_progress(DownloadProgress(
                status=f"版本 {version_id} 下载完成",
                speed=self._speed,
                total_files=self._total_files,
                finished_files=self._total_files
            ))
            return True

        except Exception as e:
            self._update_progress(DownloadProgress(status=f"下载失败: {str(e)}"))
            return False

    def _download_libraries(self, version_info: Dict, threaded: bool = False):
        """下载依赖库，支持多线程"""
        libraries = version_info.get("libraries", [])

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
                if self._download_file(nf):
                    with self._lock:
                        if hasattr(self, '_finished_files') and hasattr(self, '_total_files'):
                            self._finished_files += 1
                            self._update_progress(DownloadProgress(
                                status=f"文件下载完成: {os.path.basename(nf.local_path)}",
                                total_files=self._total_files,
                                finished_files=self._finished_files
                            ))

    def _threaded_download_file(self, net_file: NetFile):
        result = self._download_file(net_file)
        with self._lock:
            self._progress_current += 1
            if hasattr(self, '_finished_files') and hasattr(self, '_total_files'):
                self._finished_files += 1
                self._update_progress(DownloadProgress(
                    status=f"文件下载完成: {os.path.basename(net_file.local_path)}",
                    total_files=self._total_files,
                    finished_files=self._finished_files
                ))
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
        # 资源索引文件也算作一个已完成文件
        with self._lock:
            if hasattr(self, '_finished_files') and hasattr(self, '_total_files'):
                self._finished_files += 1
                self._update_progress(DownloadProgress(
                    status="资源索引下载完成",
                    total_files=self._total_files,
                    finished_files=self._finished_files
                ))
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
                if self._download_file(nf):
                    with self._lock:
                        if hasattr(self, '_finished_files') and hasattr(self, '_total_files'):
                            self._finished_files += 1
                            self._update_progress(DownloadProgress(
                                status=f"文件下载完成: {os.path.basename(nf.local_path)}",
                                total_files=self._total_files,
                                finished_files=self._finished_files
                            ))

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
        mc_folder=r"D:\Minecraft2",
        download_source=DownloadSource.MIRROR_FIRST,
        progress_callback=progress_handler,
        max_workers=128
    )
    try:
        version_id = "1.21.8"
        print(f"开始下载Minecraft {version_id}...")
        if downloader.download_version(version_id):
            print(f"Minecraft {version_id} 下载完成！")
        else:
            print(f"Minecraft {version_id} 下载失败！")
    finally:
        downloader.cleanup()