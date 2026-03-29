from __future__ import annotations
import rtoml
from pathlib import Path
from typing import Any, Dict
from dataclasses import dataclass, field


@dataclass
class LaunchSettings:
    java_path: str = ""
    xmx: str = "2G"
    xms: str = "512M"
    jvm_args: str = ""
    game_args: str = ""
    width: int = 854
    height: int = 480
    auto_connect_server: str = ""
    auto_connect_ip: str = ""
    auto_connect_port: int = 25565
    resolution_width: int = 0
    resolution_height: int = 0
    java_auto_select: bool = True
    java_version: int = 0
    enable_native_dll: bool = True
    enable_shortcut: bool = False
    enable_game_overlay: bool = True
    enable_discord_rich_presence: bool = False
    wrapper_path: str = ""
    wrapper_enabled: bool = False
    env_vars: Dict[str, str] = field(default_factory=dict)
    pre_launch_command: str = ""
    post_exit_command: str = ""
    priority: int = 0
    close_launcher: bool = False
    auto_enter_server: bool = False
    server_ip: str = ""
    server_port: int = 25565


class ConfigService:
    DEFAULT = {
        "Language": "zh-cn",
        "Theme": "system",
        "Download": {
            "max_connections": 8,
            "min_connections": 2,
            "chunk_size_mb": 2,
            "enable_chunking": True,
            "speed_limit_kbps": 0,
            "timeout_seconds": 30,
            "max_retries": 3,
            "retry_delay_seconds": 2.0,
            "verify_hash": False,
            "adaptive_threads": True,
            "resume_enabled": True,
            "download_source": "auto",
            "version_source": "bmclapi_first",
            "smart_segment": {
                "min_chunk_size_kb": 512,
                "max_chunk_size_mb": 10,
                "dynamic_adjustment": True,
            },
        },
        "DownloadHistory": [],
        "VersionDirectoryEntries": [],
        "SelectedLaunchVersion": None,
        "Launch": {
            "JavaPath": "",
            "Xmx": "2G",
            "Xms": "512M",
            "JvmArgs": "",
            "GameArgs": "",
            "Width": 854,
            "Height": 480,
            "AutoConnectServer": "",
            "AutoConnectIp": "",
            "AutoConnectPort": 25565,
            "ResolutionWidth": 0,
            "ResolutionHeight": 0,
            "JavaAutoSelect": True,
            "JavaVersion": 0,
            "EnableNativeDll": True,
            "EnableShortcut": False,
            "EnableGameOverlay": True,
            "EnableDiscordRichPresence": False,
            "WrapperPath": "",
            "WrapperEnabled": False,
            "EnvVars": {},
            "PreLaunchCommand": "",
            "PostExitCommand": "",
            "Priority": 0,
            "CloseLauncher": False,
            "AutoEnterServer": False,
            "ServerIp": "",
            "ServerPort": 25565,
        },
    }

    def __init__(self) -> None:
        self.path = Path("MineLauncher/config/config.toml")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._cfg: Dict[str, Any] | None = None

    def load(self) -> Dict[str, Any]:
        if self._cfg is None:
            try:
                self._cfg = rtoml.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                self._cfg = self.DEFAULT.copy()
            self._cfg = self._merge_defaults(self._cfg, self.DEFAULT)
        return self._cfg

    def _merge_defaults(self, cfg: Dict, defaults: Dict) -> Dict:
        result = defaults.copy()
        for key, value in cfg.items():
            if (
                key in result
                and isinstance(result[key], dict)
                and isinstance(value, dict)
            ):
                result[key] = self._merge_defaults(value, result[key])
            else:
                result[key] = value
        return result

    def save(self, cfg: Dict[str, Any]) -> None:
        self._cfg = cfg
        self.path.write_text(rtoml.dumps(cfg), encoding="utf-8")

    def get_download_config(self) -> Dict[str, Any]:
        cfg = self.load()
        return cfg.get("Download", self.DEFAULT["Download"])

    def save_download_config(self, download_cfg: Dict[str, Any]) -> None:
        cfg = self.load()
        cfg["Download"] = download_cfg
        self.save(cfg)

    def add_download_history(self, record: Dict[str, Any]) -> None:
        cfg = self.load()
        history = cfg.get("DownloadHistory", [])
        history.insert(0, record)
        history = history[:100]
        cfg["DownloadHistory"] = history
        self.save(cfg)

    def get_download_history(self) -> list:
        cfg = self.load()
        return cfg.get("DownloadHistory", [])

    def clear_download_history(self) -> None:
        cfg = self.load()
        cfg["DownloadHistory"] = []
        self.save(cfg)

    def get_selected_launch_version(self) -> dict | None:
        cfg = self.load()
        return cfg.get("SelectedLaunchVersion")

    def save_selected_launch_version(self, version_info: dict) -> None:
        cfg = self.load()
        cfg["SelectedLaunchVersion"] = version_info
        self.save(cfg)

    def get_launch_settings(self) -> LaunchSettings:
        cfg = self.load()
        launch = cfg.get("Launch", self.DEFAULT["Launch"])
        return LaunchSettings(
            java_path=launch.get("JavaPath", ""),
            xmx=launch.get("Xmx", "2G"),
            xms=launch.get("Xms", "512M"),
            jvm_args=launch.get("JvmArgs", ""),
            game_args=launch.get("GameArgs", ""),
            width=launch.get("Width", 854),
            height=launch.get("Height", 480),
            auto_connect_server=launch.get("AutoConnectServer", ""),
            auto_connect_ip=launch.get("AutoConnectIp", ""),
            auto_connect_port=launch.get("AutoConnectPort", 25565),
            resolution_width=launch.get("ResolutionWidth", 0),
            resolution_height=launch.get("ResolutionHeight", 0),
            java_auto_select=launch.get("JavaAutoSelect", True),
            java_version=launch.get("JavaVersion", 0),
            enable_native_dll=launch.get("EnableNativeDll", True),
            enable_shortcut=launch.get("EnableShortcut", False),
            enable_game_overlay=launch.get("EnableGameOverlay", True),
            enable_discord_rich_presence=launch.get("EnableDiscordRichPresence", False),
            wrapper_path=launch.get("WrapperPath", ""),
            wrapper_enabled=launch.get("WrapperEnabled", False),
            env_vars=launch.get("EnvVars", {}),
            pre_launch_command=launch.get("PreLaunchCommand", ""),
            post_exit_command=launch.get("PostExitCommand", ""),
            priority=launch.get("Priority", 0),
            close_launcher=launch.get("CloseLauncher", False),
            auto_enter_server=launch.get("AutoEnterServer", False),
            server_ip=launch.get("ServerIp", ""),
            server_port=launch.get("ServerPort", 25565),
        )

    def save_launch_settings(self, settings: LaunchSettings) -> None:
        cfg = self.load()
        cfg["Launch"] = {
            "JavaPath": settings.java_path,
            "Xmx": settings.xmx,
            "Xms": settings.xms,
            "JvmArgs": settings.jvm_args,
            "GameArgs": settings.game_args,
            "Width": settings.width,
            "Height": settings.height,
            "AutoConnectServer": settings.auto_connect_server,
            "AutoConnectIp": settings.auto_connect_ip,
            "AutoConnectPort": settings.auto_connect_port,
            "ResolutionWidth": settings.resolution_width,
            "ResolutionHeight": settings.resolution_height,
            "JavaAutoSelect": settings.java_auto_select,
            "JavaVersion": settings.java_version,
            "EnableNativeDll": settings.enable_native_dll,
            "EnableShortcut": settings.enable_shortcut,
            "EnableGameOverlay": settings.enable_game_overlay,
            "EnableDiscordRichPresence": settings.enable_discord_rich_presence,
            "WrapperPath": settings.wrapper_path,
            "WrapperEnabled": settings.wrapper_enabled,
            "EnvVars": settings.env_vars,
            "PreLaunchCommand": settings.pre_launch_command,
            "PostExitCommand": settings.post_exit_command,
            "Priority": settings.priority,
            "CloseLauncher": settings.close_launcher,
            "AutoEnterServer": settings.auto_enter_server,
            "ServerIp": settings.server_ip,
            "ServerPort": settings.server_port,
        }
        self.save(cfg)

    def add_download_history(self, record: Dict[str, Any]) -> None:
        """添加下载历史记录"""
        cfg = self.load()
        history = cfg.get("DownloadHistory", [])
        history.insert(0, record)  # 最新的在前面
        # 保留最近100条记录
        history = history[:100]
        cfg["DownloadHistory"] = history
        self.save(cfg)

    def get_download_history(self) -> list:
        """获取下载历史记录"""
        cfg = self.load()
        return cfg.get("DownloadHistory", [])

    def clear_download_history(self) -> None:
        """清空下载历史"""
        cfg = self.load()
        cfg["DownloadHistory"] = []
        self.save(cfg)

    def get_selected_launch_version(self) -> dict | None:
        """获取当前选择的启动版本"""
        cfg = self.load()
        return cfg.get("SelectedLaunchVersion")

    def save_selected_launch_version(self, version_info: dict) -> None:
        """保存当前选择的启动版本"""
        cfg = self.load()
        cfg["SelectedLaunchVersion"] = version_info
        self.save(cfg)
