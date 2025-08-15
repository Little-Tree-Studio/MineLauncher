from __future__ import annotations
import time
import flet as ft
from pathlib import Path
import orjson
from app.services.utils_service import UtilsService

class VersionsPage:
    def __init__(self, on_back):
        self.on_back = on_back
        self.root = Path(r"E:/###游戏/Minecraft/.minecraft/versions")

    def build(self) -> ft.View:
        versions_card = []
        start_time = time.time()
        for folder in UtilsService.list_dirs(self.root):
            is_neoforge = False
            is_fabric = False
            ver = "未知版本"
            try:
                file_path = self.root / folder / f"{folder}.json"
                data = orjson.loads(file_path.read_bytes())
                ver = data.get("clientVersion", "未知版本")
                raw = str(data).lower()
                is_neoforge = "neoforge" in raw
                is_fabric = "fabric" in raw
            except Exception:
                pass
            txt = f"{folder} - {ver} - {'Fabric' if is_fabric else ''} {'Neoforge' if is_neoforge else ''}"
            versions_card.append(
                ft.Card(
                    content=ft.Container(ft.Text(txt), padding=10),
                    elevation=2,
                )
            )
        end_time = time.time()
        print(f"读取版本列表耗时: {end_time - start_time:.2f} 秒")

        return ft.View(
            "/versions",
            [
                ft.Text("版本管理", size=30, weight=ft.FontWeight.BOLD),
                *versions_card,
            ],
            scroll=ft.ScrollMode.AUTO,
            # expand=True,
        )