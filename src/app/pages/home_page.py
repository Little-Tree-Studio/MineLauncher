from __future__ import annotations
import threading
import flet as ft
from pathlib import Path
import orjson
from app.services.config_service import ConfigService
from app.services.i18n_service import I18nService
from app.services.utils_service import UtilsService

ASSET_DIR = Path(__file__).parent.parent.parent / "assets"

class HomePage:
    def __init__(self, page: ft.Page):
        self.cfg = ConfigService()
        self.lang = I18nService(self.cfg.load()["Language"])
        self.page = page

    # ---------- 版本列表异步加载 ----------
    def _load_versions_async(self, list_view: ft.ListView):
        def _task():
            versions_card = []
            root = Path(r"E:/###游戏/Minecraft/.minecraft/versions")
            for folder in UtilsService.list_dirs(root):
                ver = "未知版本"
                tags = []
                try:
                    file_path = root / folder / f"{folder}.json"
                    data = orjson.loads(file_path.read_bytes())
                    ver = data.get("clientVersion", folder)
                    raw = str(data).lower()
                    if "fabric" in raw:
                        tags.append("Fabric")
                    if "neoforge" in raw:
                        tags.append("NeoForge")
                except Exception:
                    pass
                txt = f"{folder} - {ver}" + (f" ({','.join(tags)})" if tags else "")
                versions_card.append(
                    ft.Card(
                        content=ft.Container(ft.Text(txt), padding=10),
                        elevation=2,
                    )
                )
            list_view.controls.extend(versions_card)
            list_view.update()

        threading.Thread(target=_task, daemon=True).start()

    # ---------- 主页整体 ----------
    def build(self) -> ft.View:
        # 右侧内容区
        self.content_area = ft.Column(
            [
                self._build_home_content()  # 默认首页
            ],
            expand=True,
        )

        # 导航栏切换
        def on_nav_change(e):
            index = e.control.selected_index
            self.content_area.controls.clear()
            if index == 0:
                self.content_area.controls.append(self._build_home_content())
            elif index == 1:
                lv = ft.ListView(expand=True, spacing=5)
                self.content_area.controls.append(lv)
                self._load_versions_async(lv)
            self.content_area.update()

        return ft.View(
            "/",
            [
                ft.AppBar(
                    leading=ft.Image(ASSET_DIR / "image" / "icon.png"),
                    title=ft.Text("MineLauncher"),
                    bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
                    actions=[
                        ft.TextButton(
                            self.lang.current.get("home", {}).get("top", {}).get("resource_center", "资源中心"),
                            icon=ft.Icons.SHOPPING_BASKET,
                            on_click=lambda _: self.page.go("/resources"),
                        ),
                        ft.TextButton(
                            self.lang.current.get("home", {}).get("top", {}).get("download_management", "下载管理"),
                            icon=ft.Icons.DOWNLOAD,
                            on_click=lambda _: self.page.go("/download_manager"),
                        ),
                        ft.VerticalDivider(),
                        ft.TextButton(
                            self.lang.current.get("home", {}).get("top", {}).get("settings", "设置"),
                            icon=ft.Icons.SETTINGS,
                            on_click=lambda _: self.page.go("/settings"),
                        ),
                        ft.TextButton(
                            self.lang.current.get("home", {}).get("top", {}).get("about", "关于"),
                            icon=ft.Icons.INFO,
                            on_click=lambda _: self.page.go("/about"),
                        ),
                    ],
                ),
                ft.Row(
                    [
                        ft.NavigationRail(
                            selected_index=0,
                            label_type=ft.NavigationRailLabelType.ALL,
                            min_width=80,
                            destinations=[
                                ft.NavigationRailDestination(
                                    icon=ft.Icons.HOME_OUTLINED,
                                    selected_icon=ft.Icons.HOME,
                                    label=self.lang.current.get("home", {}).get("title", "首页"),
                                ),
                                ft.NavigationRailDestination(
                                    icon=ft.Icons.VERTICAL_SPLIT_OUTLINED,
                                    selected_icon=ft.Icons.VERTICAL_SPLIT,
                                    label=self.lang.current.get("home", {}).get("version_list", "版本列表"),
                                ),
                            ],
                            on_change=on_nav_change,
                        ),
                        ft.VerticalDivider(width=1),
                        self.content_area,
                    ],
                    expand=True,
                ),
            ],
        )

    # ---------- 原来的首页内容 ----------
    def _build_home_content(self) -> ft.Column:
        return ft.Column(
            [
                ft.Column(
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    controls=[
                        ft.Row(
                            [
                                ft.Text(value="MineLauncher", size=45),
                                ft.Column(
                                    controls=[
                                        ft.Row(
                                            controls=[
                                                ft.Placeholder(fallback_height=20, fallback_width=20),
                                                ft.Text("zs_xiaoshu"),
                                            ]
                                        ),
                                        ft.Button(
                                            icon=ft.Icons.PEOPLE,
                                            text=self.lang.current.get("home", {}).get("account_settings", "账户设置"),
                                        ),
                                    ],
                                    horizontal_alignment=ft.CrossAxisAlignment.END,
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        ft.Column(
                            alignment=ft.MainAxisAlignment.CENTER,
                            controls=[
                                ft.Card(
                                    content=ft.Container(
                                        content=ft.Column(
                                            controls=[
                                                ft.Text("新闻", size=20, weight=ft.FontWeight.BOLD),
                                                ft.Text("标题"),
                                            ]
                                        ),
                                        padding=10,
                                        width=300,
                                        height=100,
                                    )
                                )
                            ],
                            scroll=ft.ScrollMode.AUTO,
                            expand=True,
                        ),
                        ft.Row(
                            controls=[
                                ft.ElevatedButton(
                                    self.lang.current.get("test", {}).get("test", "测试"),
                                    ft.Icons.SCIENCE,
                                    on_click=lambda _: print("test clicked"),
                                ),
                                ft.Card(
                                    content=ft.Container(
                                        content=ft.Column(
                                            [
                                                ft.Row(
                                                    [
                                                        ft.Image(ASSET_DIR / "image" / "grass.png", width=30, height=30),
                                                        ft.Text("MineCraft 1.20.1"),
                                                    ]
                                                ),
                                                ft.Row(
                                                    [
                                                        ft.TextButton(
                                                            self.lang.current.get("home", {})
                                                            .get("game", {})
                                                            .get("config", "配置"),
                                                            icon=ft.Icons.SETTINGS,
                                                            style=ft.ButtonStyle(
                                                                shape=ft.RoundedRectangleBorder(radius=5)
                                                            ),
                                                        ),
                                                        ft.FilledButton(
                                                            self.lang.current.get("home", {})
                                                            .get("game", {})
                                                            .get("launch", "启动"),
                                                            icon=ft.Icons.PLAY_ARROW,
                                                            style=ft.ButtonStyle(
                                                                shape=ft.RoundedRectangleBorder(radius=5)
                                                            ),
                                                        ),
                                                    ],
                                                    alignment=ft.MainAxisAlignment.END,
                                                ),
                                            ]
                                        ),
                                        width=300,
                                        padding=10,
                                    ),
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            vertical_alignment=ft.CrossAxisAlignment.END,
                        ),
                    ],
                    expand=True,
                ),
            ],
            expand=True,
        )