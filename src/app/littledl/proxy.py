import os
import platform
import re
import subprocess
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from .config import ProxyConfig, ProxyMode


@dataclass
class ProxyInfo:
    http_proxy: str | None = None
    https_proxy: str | None = None
    ftp_proxy: str | None = None
    socks_proxy: str | None = None
    no_proxy: list[str] | None = None
    pac_url: str | None = None

    def get_proxy_for_scheme(self, scheme: str) -> str | None:
        scheme = scheme.lower()
        if scheme == "http":
            return self.http_proxy
        elif scheme == "https":
            return self.https_proxy or self.http_proxy
        elif scheme == "ftp":
            return self.ftp_proxy or self.http_proxy
        return self.http_proxy or self.https_proxy


class ProxyDetector:
    @staticmethod
    def detect_system_proxy() -> ProxyInfo:
        system = platform.system()
        if system == "Windows":
            return ProxyDetector._detect_windows_proxy()
        elif system == "Darwin":
            return ProxyDetector._detect_macos_proxy()
        elif system == "Linux":
            return ProxyDetector._detect_linux_proxy()
        else:
            return ProxyDetector._detect_env_proxy()

    @staticmethod
    def _detect_windows_proxy() -> ProxyInfo:
        info = ProxyInfo()
        try:
            import winreg

            def get_registry_proxy(key_path: str, value_name: str) -> str | None:
                try:
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                        value, _ = winreg.QueryValueEx(key, value_name)
                        return str(value) if value else None
                except Exception:
                    return None

            internet_settings = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"

            proxy_enable = get_registry_proxy(internet_settings, "ProxyEnable")
            if proxy_enable == "1":
                proxy_server = get_registry_proxy(internet_settings, "ProxyServer")
                if proxy_server:
                    if "=" in proxy_server:
                        for part in proxy_server.split(";"):
                            if "=" in part:
                                proto, addr = part.split("=", 1)
                                proto = proto.lower()
                                if proto == "http":
                                    info.http_proxy = ProxyDetector._normalize_proxy_url(addr, "http")
                                elif proto == "https":
                                    info.https_proxy = ProxyDetector._normalize_proxy_url(addr, "http")
                                elif proto in ("socks", "socks5"):
                                    info.socks_proxy = ProxyDetector._normalize_proxy_url(addr, "socks5")
                    else:
                        normalized = ProxyDetector._normalize_proxy_url(proxy_server, "http")
                        info.http_proxy = normalized
                        info.https_proxy = normalized

            auto_config_url = get_registry_proxy(internet_settings, "AutoConfigURL")
            if auto_config_url:
                info.pac_url = auto_config_url

            proxy_override = get_registry_proxy(internet_settings, "ProxyOverride")
            if proxy_override:
                info.no_proxy = [p.strip() for p in proxy_override.split(";") if p.strip()]

        except Exception:
            pass

        env_proxy = ProxyDetector._detect_env_proxy()
        info.http_proxy = info.http_proxy or env_proxy.http_proxy
        info.https_proxy = info.https_proxy or env_proxy.https_proxy
        info.socks_proxy = info.socks_proxy or env_proxy.socks_proxy
        info.no_proxy = info.no_proxy or env_proxy.no_proxy

        return info

    @staticmethod
    def _detect_macos_proxy() -> ProxyInfo:
        info = ProxyInfo()
        try:
            result = subprocess.run(
                ["scutil", "--proxy"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                output = result.stdout
                http_match = re.search(
                    r"HTTPEnable\s*:\s*1.*?HTTPProxy\s*:\s*(\S+).*?HTTPPort\s*:\s*(\d+)", output, re.DOTALL
                )
                if http_match:
                    host, port = http_match.groups()
                    info.http_proxy = f"http://{host}:{port}"

                https_match = re.search(
                    r"HTTPSEnable\s*:\s*1.*?HTTPSProxy\s*:\s*(\S+).*?HTTPSPort\s*:\s*(\d+)", output, re.DOTALL
                )
                if https_match:
                    host, port = https_match.groups()
                    info.https_proxy = f"http://{host}:{port}"

                socks_match = re.search(
                    r"SOCKSEnable\s*:\s*1.*?SOCKSProxy\s*:\s*(\S+).*?SOCKSPort\s*:\s*(\d+)", output, re.DOTALL
                )
                if socks_match:
                    host, port = socks_match.groups()
                    info.socks_proxy = f"socks5://{host}:{port}"

                pac_match = re.search(r"PACFileURL\s*:\s*(\S+)", output)
                if pac_match:
                    info.pac_url = pac_match.group(1)

        except Exception:
            pass

        env_proxy = ProxyDetector._detect_env_proxy()
        info.http_proxy = info.http_proxy or env_proxy.http_proxy
        info.https_proxy = info.https_proxy or env_proxy.https_proxy
        info.socks_proxy = info.socks_proxy or env_proxy.socks_proxy
        info.no_proxy = info.no_proxy or env_proxy.no_proxy

        return info

    @staticmethod
    def _detect_linux_proxy() -> ProxyInfo:
        info = ProxyDetector._detect_env_proxy()

        try:
            desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
            if "gnome" in desktop or "unity" in desktop:
                result = subprocess.run(
                    ["gsettings", "get", "org.gnome.system.proxy", "mode"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if "manual" in result.stdout:
                    http_host = subprocess.run(
                        ["gsettings", "get", "org.gnome.system.proxy.http", "host"],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    http_port = subprocess.run(
                        ["gsettings", "get", "org.gnome.system.proxy.http", "port"],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    if http_host.returncode == 0 and http_port.returncode == 0:
                        host = http_host.stdout.strip().strip("'\"")
                        port = http_port.stdout.strip()
                        if host and port:
                            info.http_proxy = f"http://{host}:{port}"

        except Exception:
            pass

        return info

    @staticmethod
    def _detect_env_proxy() -> ProxyInfo:
        info = ProxyInfo()

        info.http_proxy = os.environ.get("http_proxy") or os.environ.get("HTTP_PROXY")
        info.https_proxy = os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY")
        info.ftp_proxy = os.environ.get("ftp_proxy") or os.environ.get("FTP_PROXY")

        all_proxy = os.environ.get("all_proxy") or os.environ.get("ALL_PROXY")
        if all_proxy:
            if all_proxy.startswith("socks"):
                info.socks_proxy = all_proxy
            else:
                info.http_proxy = info.http_proxy or all_proxy
                info.https_proxy = info.https_proxy or all_proxy

        no_proxy = os.environ.get("no_proxy") or os.environ.get("NO_PROXY")
        if no_proxy:
            info.no_proxy = [p.strip() for p in no_proxy.split(",") if p.strip()]

        return info

    @staticmethod
    def _normalize_proxy_url(proxy_str: str, default_scheme: str = "http") -> str:
        proxy_str = proxy_str.strip()
        if not proxy_str:
            return ""
        if not proxy_str.startswith(("http://", "https://", "socks://", "socks5://")):
            proxy_str = f"{default_scheme}://{proxy_str}"
        return proxy_str


class ProxyResolver:
    def __init__(self) -> None:
        self._pac_cache: dict[str, str] = {}
        self._pac_client: httpx.AsyncClient | None = None

    async def resolve_from_pac(self, pac_url: str, target_url: str) -> str | None:
        cache_key = f"{pac_url}:{target_url}"
        if cache_key in self._pac_cache:
            return self._pac_cache[cache_key]

        try:
            if self._pac_client is None:
                self._pac_client = httpx.AsyncClient()

            response = await self._pac_client.get(pac_url, timeout=10)
            response.raise_for_status()
            pac_content = response.text

            result = await self._evaluate_pac(pac_content, target_url)
            if result:
                self._pac_cache[cache_key] = result
            return result

        except Exception:
            return None

    async def _evaluate_pac(self, pac_content: str, target_url: str) -> str | None:
        parsed = urlparse(target_url)
        host = parsed.hostname or ""
        target_url.lower()

        if "isPlainHostName" in pac_content and "." not in host:
            return "DIRECT"

        proxy_patterns = [
            (r'"PROXY\s+([^"]+)"', lambda m: f"http://{m.group(1).strip()}"),
            (r'"SOCKS\s+([^"]+)"', lambda m: f"socks5://{m.group(1).strip()}"),
            (r'"SOCKS5\s+([^"]+)"', lambda m: f"socks5://{m.group(1).strip()}"),
            (r'"DIRECT"', lambda _: "DIRECT"),
        ]

        for pattern, converter in proxy_patterns:
            matches = re.finditer(pattern, pac_content, re.IGNORECASE)
            for match in matches:
                result = converter(match)
                if result != "DIRECT":
                    return result

        return None

    async def close(self) -> None:
        if self._pac_client:
            await self._pac_client.aclose()
            self._pac_client = None


class ProxyManager:
    def __init__(self, config: ProxyConfig) -> None:
        self.config = config
        self._detector = ProxyDetector()
        self._resolver = ProxyResolver()
        self._detected_proxy: ProxyInfo | None = None

    async def initialize(self) -> None:
        if self.config.mode == ProxyMode.SYSTEM or (self.config.mode == ProxyMode.AUTO and self.config.trust_env):
            self._detected_proxy = self._detector.detect_system_proxy()

    def get_proxy(self, url: str) -> str | None:
        if self.config.mode == ProxyMode.NONE:
            return None

        if self.config.mode == ProxyMode.CUSTOM:
            return self.config.get_proxy_for_url(url)

        if self._detected_proxy:
            parsed = urlparse(url)
            scheme = parsed.scheme

            if self._detected_proxy.no_proxy:
                host = parsed.hostname or ""
                for no_proxy_host in self._detected_proxy.no_proxy:
                    if host == no_proxy_host or host.endswith(f".{no_proxy_host}"):
                        return None

            if scheme == "https":
                return self._detected_proxy.https_proxy or self._detected_proxy.http_proxy
            elif scheme == "http":
                return self._detected_proxy.http_proxy

            return self._detected_proxy.get_proxy_for_scheme(scheme)

        return None

    async def get_proxy_with_pac(self, url: str) -> str | None:
        pac_url = None
        if self.config.pac_url:
            pac_url = self.config.pac_url
        elif self._detected_proxy and self._detected_proxy.pac_url:
            pac_url = self._detected_proxy.pac_url

        if pac_url:
            resolved = await self._resolver.resolve_from_pac(pac_url, url)
            if resolved and resolved != "DIRECT":
                return resolved
            return None

        return self.get_proxy(url)

    def get_proxy_auth(self) -> tuple[str, str] | None:
        if self.config.proxy_username and self.config.proxy_password:
            return (self.config.proxy_username, self.config.proxy_password)
        return None

    async def close(self) -> None:
        await self._resolver.close()

    @property
    def has_proxy(self) -> bool:
        if self.config.mode == ProxyMode.NONE:
            return False
        if self.config.mode == ProxyMode.CUSTOM:
            return bool(self.config.http_proxy or self.config.https_proxy or self.config.socks_proxy)
        return bool(self._detected_proxy and (self._detected_proxy.http_proxy or self._detected_proxy.https_proxy))
