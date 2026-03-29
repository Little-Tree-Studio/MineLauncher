from __future__ import annotations
import rtoml
from pathlib import Path
from typing import Any, Dict


class ConfigService:
    DEFAULT = {
        "Language": "zh-cn",
        "Theme": "system",
        # 下载设置
        "Download": {
            "max_connections": 8,
            "min_connections": 2,
            "chunk_size_mb": 2,
            "enable_chunking": True,
            "speed_limit_kbps": 0,  # 0=无限制
            "timeout_seconds": 30,
            "max_retries": 3,
            "retry_delay_seconds": 2.0,
            "verify_hash": False,
            "adaptive_threads": True,
            "resume_enabled": True,
            "download_source": "auto",  # bmclapi_first, auto, official_first
            "version_source": "bmclapi_first",  # bmclapi_first, mojang_first, mojang_only
            "smart_segment": {
                "min_chunk_size_kb": 512,
                "max_chunk_size_mb": 10,
                "dynamic_adjustment": True,
            },
        },
        # 下载历史
        "DownloadHistory": [],
        # 版本目录
        "VersionDirectoryEntries": [],
        # 当前选择的启动版本
        "SelectedLaunchVersion": None,
    }

    def __init__(self) -> None:
        self.path = Path("MineLauncher/config/config.toml")
        self.path.parent.mkdir(parents=True, exist_ok=True)  # 确保文件夹存在
        self._cfg: Dict[str, Any] | None = None

    def load(self) -> Dict[str, Any]:
        if self._cfg is None:
            try:
                self._cfg = rtoml.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                self._cfg = self.DEFAULT.copy()
            # 确保所有默认值都存在
            self._cfg = self._merge_defaults(self._cfg, self.DEFAULT)
        return self._cfg

    def _merge_defaults(self, cfg: Dict, defaults: Dict) -> Dict:
        """合并默认值到配置中"""
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
        """获取下载配置"""
        cfg = self.load()
        return cfg.get("Download", self.DEFAULT["Download"])

    def save_download_config(self, download_cfg: Dict[str, Any]) -> None:
        """保存下载配置"""
        cfg = self.load()
        cfg["Download"] = download_cfg
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
