from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Dict

class ConfigService:
    DEFAULT = {"Language": "zh-cn"}

    def __init__(self) -> None:
        self.path = Path("MineLauncher/config/config.json")
        self.path.parent.mkdir(parents=True, exist_ok=True)  # 确保文件夹存在
        self._cfg: Dict[str, Any] | None = None

    def load(self) -> Dict[str, Any]:
        if self._cfg is None:
            try:
                self._cfg = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                self._cfg = self.DEFAULT.copy()
        return self._cfg

    def save(self, cfg: Dict[str, Any]) -> None:
        self._cfg = cfg
        self.path.write_text(json.dumps(cfg, ensure_ascii=False, indent=4), encoding="utf-8")