from __future__ import annotations
import flet as ft
from ..services.i18n_service import I18nService
from ..services.config_service import ConfigService


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

    def _get_java_paths(self):
        import os

        java_paths = set()
        possible_dirs = [
            os.environ.get("JAVA_HOME", ""),
            os.path.join(os.environ.get("ProgramFiles", ""), "Java"),
            os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Java"),
            os.path.join(os.environ.get("ProgramW6432", ""), "Java"),
            os.path.join(
                os.environ.get("LocalAppData", ""), "Programs", "AdoptOpenJDK"
            ),
        ]
        for base in possible_dirs:
            if base and os.path.exists(base):
                for root, dirs, files in os.walk(base):
                    for file in files:
                        if file.lower() == "java.exe":
                            java_paths.add(os.path.join(root, file))
        for p in os.environ.get("PATH", "").split(os.pathsep):
            exe = os.path.join(p, "java.exe")
            if os.path.exists(exe):
                java_paths.add(exe)
        return sorted(java_paths)

    def _change_java(self, e):
        selected = e.control.value
        self.cfg.save({**self.cfg.load(), "JavaPath": selected})
        self.page.show_dialog(ft.SnackBar(ft.Text(f"已选择Java: {selected}")))
        self.page.update()

    def build(self) -> ft.View:
        java_paths = self._get_java_paths()
        java_dd = ft.Dropdown(
            options=[ft.dropdown.Option(j, j) for j in java_paths]
            if java_paths
            else [ft.dropdown.Option("", "未找到Java，请检查环境变量或手动设置。")],
            value=self.cfg.load().get("JavaPath", java_paths[0] if java_paths else ""),
            width=500,
            on_select=self._change_java,
        )

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
                            java_dd,
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                ]
            ),
            padding=10,
            expand=True,
        )

        # 数据和缓存内容
        data_content = ft.Column(
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
            padding=10,
            expand=True,
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
                tab_buttons.controls[0].style = ft.ButtonStyle(
                    bgcolor=ft.Colors.BLUE_100
                )
                tab_buttons.controls[1].style = ft.ButtonStyle(bgcolor=None)
                tab_buttons.controls[2].style = ft.ButtonStyle(bgcolor=None)
            elif index == 1:
                content_area.content = data_content
                tab_buttons.controls[0].style = ft.ButtonStyle(bgcolor=None)
                tab_buttons.controls[1].style = ft.ButtonStyle(
                    bgcolor=ft.Colors.BLUE_100
                )
                tab_buttons.controls[2].style = ft.ButtonStyle(bgcolor=None)
            else:
                content_area.content = download_content
                tab_buttons.controls[0].style = ft.ButtonStyle(bgcolor=None)
                tab_buttons.controls[1].style = ft.ButtonStyle(bgcolor=None)
                tab_buttons.controls[2].style = ft.ButtonStyle(
                    bgcolor=ft.Colors.BLUE_100
                )
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
