from __future__ import annotations
import datetime
import logging.config
from pathlib import Path

class LoggerService:
    _instance: "LoggerService | None" = None

    def __new__(cls) -> "LoggerService":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._setup()
        return cls._instance

    def _setup(self) -> None:
        ts = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        log_dir = Path("MineLauncher/log")
        log_dir.mkdir(parents=True, exist_ok=True)
        cfg = {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "std": {"format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s"}
            },
            "handlers": {
                "console": {"class": "logging.StreamHandler", "formatter": "std", "level": "INFO"},
                "latest": {
                    "class": "logging.FileHandler",
                    "filename": str(log_dir / "latest.log"),
                    "encoding": "utf-8",
                    "formatter": "std",
                },
                "backup": {
                    "class": "logging.FileHandler",
                    "filename": str(log_dir / f"log_{ts}.log"),
                    "encoding": "utf-8",
                    "formatter": "std",
                },
            },
            "root": {"handlers": ["console", "latest", "backup"], "level": "DEBUG"},
        }
        logging.config.dictConfig(cfg)
        self.logger = logging.getLogger("MineLauncher")