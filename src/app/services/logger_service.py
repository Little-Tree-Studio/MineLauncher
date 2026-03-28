from __future__ import annotations
import datetime
import sys
from pathlib import Path
from loguru import logger


class LoggerService:
    _instance: "LoggerService | None" = None

    def __new__(cls) -> "LoggerService":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._setup()
        return cls._instance

    def _setup(self) -> None:
        logger.remove()

        ts = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        log_dir = Path("MineLauncher/log")
        log_dir.mkdir(parents=True, exist_ok=True)

        fmt = "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"

        logger.add(
            sys.stderr,
            format=fmt,
            level="INFO",
            colorize=True,
        )
        logger.add(
            str(log_dir / "latest.log"),
            format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
            level="DEBUG",
            encoding="utf-8",
            rotation="10 MB",
            retention="7 days",
        )
        logger.add(
            str(log_dir / f"log_{ts}.log"),
            format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
            level="DEBUG",
            encoding="utf-8",
        )

        self.logger = logger
