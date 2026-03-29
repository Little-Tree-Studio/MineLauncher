from __future__ import annotations
import flet as ft
from ..services.i18n_service import I18nService
from ..services.config_service import ConfigService
from ..services.java_detector import JavaDetector, JavaInfo


class SettingsPage:
    def __init__(self, page: ft.Page):
        self.page = page
        self.path_open_btn = ft.Button("打开")
        self.path_delete_btn = ft.Button("删除")
        self.cfg = ConfigService()
        self.lang_error = ft.AlertDialog(
            modal=True,
            icon=ft.Icon(ft.Icons.ERROR, color=ft.Colors.RED_400, size=40),
            title=ft.Text("Language resources unavailable"),
            content=ft.Text("Please contact support with details for troubleshooting."),
            actions=[
                ft.TextButton(
                    "Feedback",
                    on_click=lambda e: self.page.pop_dialog(),
                    icon=ft.Icons.FEEDBACK,
                ),
                ft.TextButton(
                    "Close",
                    on_click=lambda e: self.page.pop_dialog(),
                    icon=ft.Icons.CLOSE,
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.java_detector: JavaDetector | None = None
        self.java_paths: list[JavaInfo] = []
        self._java_scan_in_progress = False

    def _navigate(self, route: str):
        async def do_navigate():
            await self.page.push_route(route)

        self.page.run_task(do_navigate)

    def _change_language(self, e):
        code = e.control.value
        if I18nService(code).current == {}:
            self.page.show_dialog(self.lang_error)
        self.cfg.save({**self.cfg.load(), "Language": code})

    def _change_color_mode(self, e):
        theme = e.control.value
        self.cfg.save({**self.cfg.load(), "Theme": theme})
        self.page.theme_mode = (
            ft.ThemeMode.LIGHT
            if theme == "light"
            else ft.ThemeMode.DARK
            if theme == "dark"
            else ft.ThemeMode.SYSTEM
        )
        self.page.update()

    async def _scan_java_async(self, mc_path: str | None = None):
        if self._java_scan_in_progress:
            return self.java_paths

        self._java_scan_in_progress = True
        self.java_detector = JavaDetector(mc_path)
        self.java_paths = await self.java_detector.scan_async()
        self._java_scan_in_progress = False
        return self.java_paths

    def _get_java_paths(self) -> list[JavaInfo]:
        return self.java_paths

    def _get_java_display_text(self, java_info: JavaInfo) -> str:
        parts = [java_info.path]
        if java_info.version:
            parts.append(f" ({java_info.version})")
        if java_info.is_64bit:
            parts.append(" [64-bit]")
        else:
            parts.append(" [32-bit]")
        if java_info.is_jdk:
            parts.append(" JDK")
        else:
            parts.append(" JRE")
        if java_info.is_mc_related:
            parts.append(" ⚙")
        return "".join(parts)

    def _change_java(self, e):
        selected = e.control.value
        self.cfg.save({**self.cfg.load(), "JavaPath": selected})
        self.page.show_dialog(ft.SnackBar(ft.Text(f"已选择Java: {selected}")))
        self.page.update()

    async def _scan_and_update_java(self):
        java_paths = await self._scan_java_async()
        self._update_java_dropdown(java_paths)

    def _update_java_dropdown(self, java_paths: list[JavaInfo]):
        if not hasattr(self, "java_dd"):
            return
        self.java_dd.options = (
            [
                ft.dropdown.Option(j.path, self._get_java_display_text(j))
                for j in java_paths
            ]
            if java_paths
            else [ft.dropdown.Option("", "未找到Java，请检查环境变量或手动设置。")]
        )
        self.java_dd.value = self.cfg.load().get(
            "JavaPath", java_paths[0].path if java_paths else ""
        )
        self.page.update()

    def build(self) -> ft.View:
        java_paths = self._get_java_paths()
        self.java_dd = ft.Dropdown(
            options=[
                ft.dropdown.Option(j.path, self._get_java_display_text(j))
                for j in java_paths
            ]
            if java_paths
            else [ft.dropdown.Option("", "未找到Java，请检查环境变量或手动设置。")],
            value=self.cfg.load().get(
                "JavaPath", java_paths[0].path if java_paths else ""
            ),
            width=500,
            on_select=self._change_java,
        )

        self.page.run_task(self._scan_and_update_java)

        # 当前标签页索引
        current_tab = [0]

        # 显示和外观内容
        display_content = ft.Container(
            ft.Column(
                [
                    ft.Row(
                        [
                            ft.Row(
                                [
                                    ft.Icon(ft.Icons.LANGUAGE),
                                    ft.Text("语言"),
                                ]
                            ),
                            ft.Dropdown(
                                options=[
                                    ft.dropdown.Option("en", "English"),
                                    ft.dropdown.Option("zh-cn", "简体中文"),
                                    ft.dropdown.Option("wy-hx", "文言（华夏）"),
                                    ft.dropdown.Option(
                                        "zh-tw",
                                        "繁體中文（中國台灣）",
                                    ),
                                    ft.dropdown.Option(
                                        "zh-hk",
                                        "繁體中文（中國香港）",
                                    ),
                                    ft.dropdown.Option("ja", "日本語"),
                                    ft.dropdown.Option("ko", "한국어"),
                                    ft.dropdown.Option("fr", "Français"),
                                    ft.dropdown.Option("de", "Deutsch"),
                                ],
                                value=self.cfg.load().get("Language", "zh-cn"),
                                width=500,
                                on_select=self._change_language,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Row(
                        [
                            ft.Row(
                                [
                                    ft.Icon(ft.Icons.CONTRAST),
                                    ft.Text("颜色模式"),
                                ]
                            ),
                            ft.Dropdown(
                                options=[
                                    ft.dropdown.Option("light", "浅色"),
                                    ft.dropdown.Option("dark", "深色"),
                                    ft.dropdown.Option("system", "跟随系统"),
                                ],
                                value=self.cfg.load().get("Theme", "system"),
                                width=500,
                                on_select=self._change_color_mode,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Row(
                        [
                            ft.Row(
                                [
                                    ft.Icon(ft.Icons.CODE),
                                    ft.Text("Java路径"),
                                ]
                            ),
                            ft.Row(
                                [
                                    self.java_dd,
                                    ft.IconButton(
                                        ft.Icons.SETTINGS,
                                        on_click=lambda _: self._navigate(
                                            "/java_settings"
                                        ),
                                        tooltip="Java设置",
                                    ),
                                ],
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                ]
            ),
            padding=10,
            expand=True,
        )

        # 数据和缓存内容
        data_content = ft.Container(
            padding=10,
            content=ft.Column(
                [
                    ft.Text(
                        "游戏路径管理",
                        size=20,
                        weight=ft.FontWeight.BOLD,
                    ),
                    ft.Row(
                        controls=[
                            ft.FilledButton("添加游戏目录", icon=ft.Icons.ADD),
                            ft.Row(
                                controls=[
                                    self.path_open_btn,
                                    self.path_delete_btn,
                                ],
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                ],
                expand=True,
            ),
        )

        # 下载设置内容
        download_content = ft.Container(
            content=ft.Column(
                [
                    ft.Card(
                        content=ft.Container(
                            padding=15,
                            content=ft.Column(
                                [
                                    ft.Text(
                                        "下载配置", size=16, weight=ft.FontWeight.BOLD
                                    ),
                                    ft.Text(
                                        "配置下载连接数、分块大小、速度限制等高级选项",
                                        size=12,
                                        color=ft.Colors.GREY,
                                    ),
                                    ft.FilledButton(
                                        "打开下载设置",
                                        icon=ft.Icons.SETTINGS,
                                        on_click=lambda _: self._navigate(
                                            "/download_settings"
                                        ),
                                    ),
                                ]
                            ),
                        )
                    ),
                    ft.Card(
                        content=ft.Container(
                            padding=15,
                            content=ft.Column(
                                [
                                    ft.Text(
                                        "下载管理", size=16, weight=ft.FontWeight.BOLD
                                    ),
                                    ft.Text(
                                        "查看和管理所有下载任务、历史记录",
                                        size=12,
                                        color=ft.Colors.GREY,
                                    ),
                                    ft.FilledButton(
                                        "打开下载管理",
                                        icon=ft.Icons.DOWNLOAD,
                                        on_click=lambda _: self._navigate(
                                            "/download_manager"
                                        ),
                                    ),
                                ]
                            ),
                        )
                    ),
                ]
            ),
            padding=10,
            expand=True,
        )

        # 内容区域
        content_area = ft.Container(expand=True, content=display_content)

        def switch_tab(index):
            current_tab[0] = index
            if index == 0:
                content_area.content = display_content
            elif index == 1:
                content_area.content = data_content
            else:
                content_area.content = download_content
            self.page.update()

        # 使用按钮模拟Tabs
        tab_buttons = ft.Row(
            [
                ft.TextButton(
                    "显示和外观",
                    icon=ft.Icons.STYLE,
                    style=ft.ButtonStyle(bgcolor=ft.Colors.BLUE_100),
                    on_click=lambda e: switch_tab(0),
                ),
                ft.TextButton(
                    "数据和缓存",
                    icon=ft.Icons.STORAGE,
                    style=ft.ButtonStyle(bgcolor=None),
                    on_click=lambda e: switch_tab(1),
                ),
                ft.TextButton(
                    "下载设置",
                    icon=ft.Icons.DOWNLOAD,
                    style=ft.ButtonStyle(bgcolor=None),
                    on_click=lambda e: switch_tab(2),
                ),
            ]
        )

        return ft.View(
            route="/settings",
            controls=[
                ft.AppBar(
                    title=ft.Text("设置"),
                    automatically_imply_leading=True,
                    leading=ft.IconButton(
                        ft.Icons.ARROW_BACK, on_click=lambda _: self._navigate("/")
                    ),
                ),
                ft.Column(
                    [
                        tab_buttons,
                        ft.Divider(),
                        content_area,
                    ],
                    expand=True,
                ),
            ],
        )
