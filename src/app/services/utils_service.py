from __future__ import annotations
import zipfile
from pathlib import Path
from typing import List, Optional

class UtilsService:
    @staticmethod
    def list_dirs(path: Path) -> List[str]:
        return [p.name for p in path.iterdir() if p.is_dir()] if path.is_dir() else []

    @staticmethod
    def list_files(path: Path) -> List[str]:
        return [p.name for p in path.iterdir() if p.is_file()] if path.is_dir() else []

    @staticmethod
    def read_from_jar(jar: Path, inner: str) -> Optional[bytes]:
        try:
            with zipfile.ZipFile(jar) as z:
                return z.read(inner)
        except Exception:
            return None