from __future__ import annotations
import yaml
from pathlib import Path

ASSET_DIR = Path(__file__).parent.parent.parent / "assets"

class I18nService:
    def __init__(self, lang: str) -> None:
        self.lang_dir = ASSET_DIR / "lang"
        self.current = self.load(lang)

    def load(self, lang: str) -> dict:
        file = self.lang_dir / f"{lang}.yaml"
        try:
            return yaml.safe_load(file.read_text(encoding="utf-8")) or {}
        except Exception:
            from app.services.logger_service import LoggerService
            LoggerService().logger.exception(f"加载语言文件失败: {file}")
            return {}