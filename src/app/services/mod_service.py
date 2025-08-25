import requests
import json
import time
from datetime import datetime
from enum import Enum
from typing import List, Dict, Optional, Any

class DownloadPriority(Enum):
    """下载源优先级枚举"""
    MIRROR_FIRST = 0    # 镜像源优先
    EQUAL = 1           # 平等对待
    OFFICIAL_FIRST = 2  # 官方源优先

class ModSource(Enum):
    """Mod来源枚举"""
    MODRINTH = "Modrinth"
    CURSEFORGE = "CurseForge"

class ModFileStatus(Enum):
    """Mod文件状态枚举"""
    RELEASE = "release"
    BETA = "beta"
    ALPHA = "alpha"

class ModInfo:
    """Mod信息类，存储单个Mod的详细信息"""
    def __init__(self, id: str, name: str, source: ModSource):
        self.id = id
        self.name = name
        self.source = source
        self.description = ""
        self.version = ""
        self.authors: List[str] = []
        self.download_count = 0
        self.followers = 0
        self.release_date = ""
        self.status = ModFileStatus.RELEASE
        self.download_urls: List[str] = []
        self.official_url = ""
        self.mirror_url = ""
        self.icon_url = ""
        self.mod_loaders: List[str] = []
        self.game_versions: List[str] = []
        
    def __str__(self) -> str:
        return f"{self.name} ({self.source.value}) - {self.version}"

class ModDownloader:
    """整合下载源的Mod下载器类"""
    def __init__(self, priority: DownloadPriority = DownloadPriority.EQUAL,
                 use_mirror: bool = False,
                 list_priority: DownloadPriority = DownloadPriority.EQUAL,
                 download_priority: DownloadPriority = DownloadPriority.EQUAL,
                 mirror_endpoints: Optional[Dict[str, str]] = None):
        # API密钥需要自行申请
        self.curseforge_api_key = ""  # 需要填入CurseForge API密钥
        # 全局优先级（旧行为兼容）
        self.priority = priority
        # 是否启用镜像服务（如 MCIM）
        self.use_mirror = use_mirror
        # 列表/搜索接口使用的优先级（镜像 vs 官方）
        self.list_priority = list_priority
        # 下载（文件 URL）使用的优先级（镜像 vs 官方）
        self.download_priority = download_priority

        # 可配置的镜像端点映射，方便替换为 MCIM 或其他镜像
        # keys: modrinth_api, modrinth_cdn, curseforge_api, curseforge_cdn
        self.mirror_endpoints = mirror_endpoints or {
            "modrinth_api": "https://mod.mcimirror.top/modrinth",
            "modrinth_cdn": "https://mod.mcimirror.top",
            "curseforge_api": "https://mod.mcimirror.top/curseforge",
            "curseforge_cdn": "https://mod.mcimirror.top",
        }
        # 缓存机制
        self.cache = {}
        self.cache_timeout = 3600  # 缓存有效期1小时
        # 重试设置
        self.max_retries = 3
        self.retry_delay = 2
        
    def search_mod(self, query: str, game_version: Optional[str] = None, 
                  mod_loader: Optional[str] = None, limit: int = 50) -> List[ModInfo]:
        """搜索Mod，从所有配置的源获取结果并合并排序"""
        results: List[ModInfo] = []
        
        # 从Modrinth搜索
        modrinth_results = self._search_modrinth(query, game_version, mod_loader, limit)
        results.extend(modrinth_results)
        
        # 从CurseForge搜索
        curseforge_results = self._search_curseforge(query, game_version, mod_loader, limit)
        results.extend(curseforge_results)
        
        # 按照PCL类似的规则排序
        return self._sort_results(results)
    
    def _search_modrinth(self, query: str, game_version: Optional[str] = None, 
                        mod_loader: Optional[str] = None, limit: int = 50) -> List[ModInfo]:
        """从Modrinth搜索Mod"""
        # 检查缓存
        cache_key = f"modrinth_{query}_{game_version}_{mod_loader}_{limit}"
        if cache_key in self.cache:
            cached_time, cached_data = self.cache[cache_key]
            if time.time() - cached_time < self.cache_timeout:
                return cached_data
        
        results: List[ModInfo] = []
        try:
            # 构造搜索端点列表，按 list_priority 决定镜像 vs 官方先后
            modrinth_official = "https://api.modrinth.com/v2/search"
            modrinth_mirror = self.mirror_endpoints.get("modrinth_api") + "/v2/search"

            if self.use_mirror and self.list_priority == DownloadPriority.MIRROR_FIRST:
                urls = [modrinth_mirror, modrinth_official]
            elif self.use_mirror and self.list_priority == DownloadPriority.OFFICIAL_FIRST:
                urls = [modrinth_official, modrinth_mirror]
            else:
                # EQUAL 或不启用镜像：先官方再镜像作为回退
                urls = [modrinth_official, modrinth_mirror]

            params = {
                "query": query,
                "limit": limit,
                "index": "relevance"
            }

            # Modrinth expects a `facets` parameter formatted as an array of arrays.
            # Example: [["categories:fabric"], ["versions:1.19.2"]]
            facets = []
            if game_version:
                facets.append([f"versions:{game_version}"])
            if mod_loader:
                facets.append([f"categories:{mod_loader}"])

            if facets:
                # The API requires the facets to be JSON-encoded when sent as a query param
                params["facets"] = json.dumps(facets)

            # 尝试按优先级请求候选 URL
            response = self._request_with_fallback(urls, params=params)
            if response.status_code == 200:
                data = response.json()
                
                for item in data.get("hits", []):
                    mod = ModInfo(item["project_id"], item["title"], ModSource.MODRINTH)
                    mod.description = item.get("description", "")
                    mod.download_count = item.get("downloads", 0)
                    mod.followers = item.get("follows", 0)
                    mod.icon_url = item.get("icon_url", "")
                    mod.official_url = f"https://modrinth.com/mod/{item['slug']}"

                    # 尝试使用 search hit 中的 latest_version（base62 id）获取详细版本信息。
                    # 注意：search hits 中的 `versions` 字段是支持的游戏版本（含 '.'），不能作为版本 id 使用。
                    latest_version_id = item.get("latest_version")

                    # 如果没有 latest_version_id，可以保底地把 search hit 中的游戏版本填入 mod.game_versions
                    mod.game_versions = item.get("versions", [])

                    if latest_version_id:
                        latest_version = self._get_modrinth_version(latest_version_id)
                        if latest_version:
                            mod.version = latest_version.get("version_number", "")
                            mod.release_date = latest_version.get("date_published", "")

                            # 获取下载URL
                            if latest_version.get("files") and len(latest_version["files"]) > 0:
                                file_url = latest_version["files"][0].get("url", "")
                                if file_url:
                                    mod.download_urls.append(file_url)
                                    mod.mirror_url = self._get_mirror_url(file_url)
                                    mod.download_urls.append(mod.mirror_url)

                            # 获取支持的游戏版本和加载器
                            mod.game_versions = latest_version.get("game_versions", mod.game_versions)
                            mod.mod_loaders = latest_version.get("loaders", [])

                    # 把填充好的 mod 加入结果列表（此前遗漏，导致返回空结果）
                    results.append(mod)
                            
                # 更新缓存
                self.cache[cache_key] = (time.time(), results)
        except Exception as e:
            print(f"Modrinth搜索错误: {e}")
        
        return results
    
    def _get_modrinth_version(self, version_id: str) -> Optional[Dict]:
        """获取Modrinth的版本信息"""
        try:
            url = f"https://api.modrinth.com/v2/version/{version_id}"
            response = self._request_with_retry(url)
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            print(f"获取Modrinth版本信息错误: {e}")
        return None
    
    def _search_curseforge(self, query: str, game_version: Optional[str] = None, 
                          mod_loader: Optional[str] = None, limit: int = 50) -> List[ModInfo]:
        """从CurseForge搜索Mod"""
        # 检查缓存
        cache_key = f"curseforge_{query}_{game_version}_{mod_loader}_{limit}"
        if cache_key in self.cache:
            cached_time, cached_data = self.cache[cache_key]
            if time.time() - cached_time < self.cache_timeout:
                return cached_data
        
        results: List[ModInfo] = []
        
        # 如果没有API密钥且未启用镜像，则跳过CurseForge搜索。
        # 当启用镜像（如 MCIM）且配置了镜像 API 时，可以在不提供官方 API key 的情况下使用镜像。
        has_mirror_api = self.use_mirror and bool(self.mirror_endpoints.get("curseforge_api"))
        if not self.curseforge_api_key and not has_mirror_api:
            print("警告: 未设置CurseForge API密钥且未启用镜像，跳过CurseForge搜索")
            return results
        
        try:
            # 构造候选 URL 列表，按 list_priority 决定镜像和官方顺序
            official = "https://api.curseforge.com/v1/mods/search"
            mirror_base = self.mirror_endpoints.get("curseforge_api")
            mirror_url = f"{mirror_base}/v1/mods/search" if mirror_base else None

            if self.use_mirror and self.list_priority == DownloadPriority.MIRROR_FIRST:
                urls = [u for u in (mirror_url, official) if u]
            elif self.use_mirror and self.list_priority == DownloadPriority.OFFICIAL_FIRST:
                urls = [u for u in (official, mirror_url) if u]
            else:
                urls = [official]
                if mirror_url:
                    urls.append(mirror_url)

            params = {
                "gameId": 432,  # Minecraft
                "searchFilter": query,
                "pageSize": limit,
                "sortOrder": "relevance"
            }

            if game_version:
                params["gameVersion"] = game_version

            # 逐个尝试候选 URL，官方 API 需要 x-api-key，镜像不需要
            response = None
            last_err = None
            for u in urls:
                try:
                    # 仅当请求官方 API 时使用 x-api-key（若提供）
                    headers = None
                    if u.startswith("https://api.curseforge.com"):
                        if not self.curseforge_api_key:
                            # 无法请求官方 API，跳过
                            print("警告: 未设置CurseForge API密钥，跳过官方 CurseForge 请求")
                            continue
                        headers = {"x-api-key": self.curseforge_api_key}

                    response = self._request_with_retry(u, headers=headers, params=params)
                    if response and response.status_code == 200:
                        break
                except Exception as e:
                    last_err = e
                    continue

            if response is None:
                if last_err:
                    print(f"CurseForge搜索错误: {last_err}")
                return results
            if response.status_code == 200:
                data = response.json()
                
                for item in data.get("data", []):
                    mod = ModInfo(str(item["id"]), item["name"], ModSource.CURSEFORGE)
                    mod.description = item.get("summary", "")
                    mod.download_count = item.get("downloadCount", 0)
                    mod.followers = item.get("totalDownloads", 0)  # CurseForge没有直接的follower计数
                    mod.icon_url = item.get("logo", {}).get("url", "")
                    mod.official_url = f"https://www.curseforge.com/minecraft/mc-mods/{item['slug']}"
                    
                    # 获取最新文件信息
                    latest_files = item.get("latestFiles", [])
                    if latest_files and len(latest_files) > 0:
                        latest_file = latest_files[0]
                        mod.version = latest_file.get("displayName", "")
                        mod.release_date = latest_file.get("fileDate", "")
                        
                        # 设置文件状态
                        if latest_file.get("releaseType") == 1:
                            mod.status = ModFileStatus.RELEASE
                        elif latest_file.get("releaseType") == 2:
                            mod.status = ModFileStatus.BETA
                        else:
                            mod.status = ModFileStatus.ALPHA
                        
                        # 获取下载URL
                        download_url = latest_file.get("downloadUrl", "")
                        mod.download_urls.append(download_url)
                        mod.mirror_url = self._get_mirror_url(download_url)
                        mod.download_urls.append(mod.mirror_url)
                        
                        # 获取支持的游戏版本和加载器
                        mod.game_versions = latest_file.get("gameVersions", [])
                        # CurseForge的loader信息在gameVersion中，需要解析
                        if mod_loader:
                            if any(mod_loader.lower() in version.lower() for version in mod.game_versions):
                                mod.mod_loaders.append(mod_loader)
                            
                # 更新缓存
                self.cache[cache_key] = (time.time(), results)
        except Exception as e:
            print(f"CurseForge搜索错误: {e}")
        
        return results
    
    def _get_mirror_url(self, original_url: str) -> str:
        """根据原始URL获取镜像URL，类似PCL的DlSourceModGet"""
        # 这里可以实现将官方URL转换为镜像URL的逻辑
        # 目前简单实现，实际使用时可以扩展支持更多镜像源
        if not self.use_mirror:
            return original_url

        # 优先使用配置的镜像 CDN 域名进行替换
        try:
            modrinth_cdn = self.mirror_endpoints.get("modrinth_cdn")
            curseforge_cdn = self.mirror_endpoints.get("curseforge_cdn")

            if "modrinth.com" in original_url and modrinth_cdn:
                # 按 MCIM 文档：cdn.modrinth.com -> mod.mcimirror.top
                return original_url.replace("https://cdn.modrinth.com", modrinth_cdn).replace("https://data.modrinth.com", modrinth_cdn)
            elif "curseforge.com" in original_url and curseforge_cdn:
                # 按 MCIM 文档：edge.forgecdn.net -> mod.mcimirror.top
                # 注意：不要替换 mediafilez.forgecdn.net
                return original_url.replace("https://edge.forgecdn.net", curseforge_cdn)
        except Exception:
            pass
        return original_url  # 默认返回原始URL
        return original_url  # 默认返回原始URL
    
    def _sort_results(self, mods: List[ModInfo]) -> List[ModInfo]:
        """按照PCL类似的规则排序Mod搜索结果"""
        # 1. 首先按照来源排序（可以根据用户偏好调整）
        # 2. 然后按照下载量、更新日期等排序
        # 这是一个简化的排序实现
        
        # 定义排序键函数
        def sort_key(mod: ModInfo):
            # 主要优先级：下载量（降序）
            # 次要优先级：更新日期（降序）
            # 第三优先级：名称（字母顺序）
            # 可以根据需要调整排序策略
            download_count = -mod.download_count  # 负号表示降序

            # 解析 ISO8601 时间，兼容带小数秒和以 'Z' 结尾的 UTC 时间
            def _parse_iso(dt_str: str) -> Optional[datetime]:
                if not dt_str:
                    return None
                try:
                    # 首选解析没有小数秒且以 Z 结尾的格式
                    return datetime.strptime(dt_str, "%Y-%m-%dT%H:%M:%SZ")
                except Exception:
                    try:
                        # 尝试使用 fromisoformat，先把末尾的 Z 替换为 +00:00
                        if dt_str.endswith('Z'):
                            dt_str = dt_str[:-1] + '+00:00'
                        return datetime.fromisoformat(dt_str)
                    except Exception:
                        return None

            parsed = _parse_iso(mod.release_date) if mod.release_date else None
            # 使用 timestamp()，若解析失败则降级为 0
            date_score = -parsed.timestamp() if parsed else 0

            name_score = mod.name.lower()

            return (download_count, date_score, name_score)
        
        # 应用排序
        return sorted(mods, key=sort_key)
    
    def _request_with_retry(self, url: str, method: str = "GET", headers: Dict[str, str] = None, 
                           params: Dict[str, Any] = None, json_data: Any = None) -> requests.Response:
        """带重试机制的HTTP请求"""
        retries = 0
        last_error = None
        
        while retries < self.max_retries:
            try:
                if method == "GET":
                    response = requests.get(url, headers=headers, params=params, timeout=10)
                elif method == "POST":
                    response = requests.post(url, headers=headers, params=params, json=json_data, timeout=10)
                else:
                    raise ValueError(f"不支持的请求方法: {method}")
                
                # 检查响应状态
                if response.status_code == 200:
                    return response
                
                print(f"请求失败，状态码: {response.status_code}, URL: {url}")
                last_error = Exception(f"请求失败，状态码: {response.status_code}")
                
            except Exception as e:
                print(f"请求异常: {e}, URL: {url}")
                last_error = e
            
            # 重试前等待
            time.sleep(self.retry_delay)
            retries += 1
            
        # 所有重试都失败
        raise last_error or Exception("请求失败，已达到最大重试次数")

    def _request_with_fallback(self, urls: List[str], method: str = "GET", headers: Dict[str, str] = None,
                               params: Dict[str, Any] = None, json_data: Any = None) -> Optional[requests.Response]:
        """尝试一组候选 URL（按优先级顺序），返回第一个成功的响应或 None。"""
        last_err = None
        for u in urls:
            try:
                resp = self._request_with_retry(u, method=method, headers=headers, params=params, json_data=json_data)
                if resp and resp.status_code == 200:
                    return resp
            except Exception as e:
                last_err = e
                # 尝试下一个候选 URL
                continue
        if last_err:
            raise last_err
        return None
    
    def get_download_urls(self, mod: ModInfo) -> List[str]:
        """获取Mod的下载链接，根据优先级排序"""
        # 根据设置的优先级返回不同顺序的URL列表
        if not mod.download_urls:
            return []
        # 简化：根据 download_priority 决定镜像是否优先
        # 生成对应的镜像 URL（如果尚未生成）
        official_urls = []
        mirror_urls = []
        for url in mod.download_urls:
            # 如果 URL 已经是镜像域名则当作 mirror
            if self.use_mirror:
                mirror_candidate = self._get_mirror_url(url)
            else:
                mirror_candidate = url

            # 将官方和镜像分别收集（避免重复）
            if url not in official_urls:
                official_urls.append(url)
            if mirror_candidate not in mirror_urls:
                mirror_urls.append(mirror_candidate)

        if self.download_priority == DownloadPriority.MIRROR_FIRST:
            # 镜像优先（去重且保持顺序）
            ordered = [u for u in mirror_urls if u] + [u for u in official_urls if u not in mirror_urls]
        elif self.download_priority == DownloadPriority.OFFICIAL_FIRST:
            ordered = [u for u in official_urls if u] + [u for u in mirror_urls if u not in official_urls]
        else:
            # EQUAL：尝试把官方和镜像交错或保持原始顺序（这里保持：官方后镜像）
            ordered = official_urls + [u for u in mirror_urls if u not in official_urls]

        return ordered

# 使用示例
if __name__ == "__main__":
    # 创建下载器实例，设置优先级为平等对待
    downloader = ModDownloader(priority=DownloadPriority.EQUAL)
    
    # 搜索Mod
    search_query = "sodium"
    game_version = "1.19.2"
    mod_loader = "fabric"
    
    print(f"搜索Mod: {search_query}, 游戏版本: {game_version}, 加载器: {mod_loader}")
    results = downloader.search_mod(search_query, game_version, mod_loader)
    
    # 显示结果
    print(f"找到 {len(results)} 个结果:")
    for i, mod in enumerate(results[:10]):  # 只显示前10个结果
        print(f"{i+1}. {mod}")
        print(f"   下载量: {mod.download_count}")
        print(f"   最后更新: {mod.release_date}")
        print(f"   支持的加载器: {', '.join(mod.mod_loaders)}")
        print(f"   下载链接数量: {len(mod.download_urls)}")
        print()