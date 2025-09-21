from __future__ import annotations
import flet as ft
from ..services.i18n_service import I18nService
from ..services.config_service import ConfigService


class SettingsPage:
    def __init__(self, page: ft.Page):
        self.page = page
        self.path_open_btn = ft.ElevatedButton("打开")
        self.path_delete_btn = ft.ElevatedButton("删除")
        self.cfg = ConfigService()
        self.lang_error = ft.AlertDialog(
            modal=True,
            icon=ft.Icon(ft.Icons.ERROR, color=ft.Colors.RED_400, size=40),
            title=ft.Text("Language resources unavailable"),
            content=ft.Text("Please contact support with details for troubleshooting."),
            actions=[
                ft.TextButton(
                    "Feedback",
                    on_click=lambda e: self.page.close(self.lang_error),
                    icon=ft.Icons.FEEDBACK,
                ),
                ft.TextButton(
                    "Close",
                    on_click=lambda e: self.page.close(self.lang_error),
                    icon=ft.Icons.CLOSE,
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

    def _change_language(self, e: ft.ControlEvent):
        code = e.control.value
        if I18nService(code).current == {}:
            self.page.open(self.lang_error)
        self.cfg.save({**self.cfg.load(), "Language": code})

    def _change_color_mode(self, e: ft.ControlEvent):
        theme = e.control.value
        self.cfg.save({**self.cfg.load(), "Theme": theme})
        self.page.theme_mode = ft.ThemeMode.LIGHT if theme == "light" else ft.ThemeMode.DARK if theme == "dark" else ft.ThemeMode.SYSTEM
        self.page.update()

    def build(self) -> ft.View:
        return ft.View(
            "/settings",
            [
                ft.AppBar(
                    title=ft.Text("设置"),
                    automatically_imply_leading=True,
                    leading=ft.IconButton(
                        ft.Icons.ARROW_BACK, on_click=lambda _: self.page.go("/")
                    ),
                ),
                ft.Tabs(
                    selected_index=0,
                    tabs=[
                        ft.Tab(
                            text="显示和外观",
                            icon=ft.Icons.STYLE,
                            content=ft.Container(
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
                                                        ft.dropdown.Option(
                                                            "en", "English"
                                                        ),
                                                        ft.dropdown.Option(
                                                            "zh-cn", "简体中文"
                                                        ),
                                                        ft.dropdown.Option(
                                                            "wy-hx", "文言（华夏）"
                                                        ),
                                                        ft.dropdown.Option(
                                                            "zh-tw",
                                                            "繁體中文（中國台灣）",
                                                        ),
                                                        ft.dropdown.Option(
                                                            "zh-hk",
                                                            "繁體中文（中國香港）",
                                                        ),
                                                        ft.dropdown.Option(
                                                            "ja", "日本語"
                                                        ),
                                                        ft.dropdown.Option(
                                                            "ko", "한국어"
                                                        ),
                                                        ft.dropdown.Option(
                                                            "fr", "Français"
                                                        ),
                                                        ft.dropdown.Option(
                                                            "de", "Deutsch"
                                                        ),
                                                    ],
                                                    value=self.cfg.load().get(
                                                        "Language", "zh-cn"
                                                    ),
                                                    width=500,
                                                    on_change=self._change_language,
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
                                                        ft.dropdown.Option(
                                                            "light", "浅色"
                                                        ),
                                                        ft.dropdown.Option(
                                                            "dark", "深色"
                                                        ),
                                                        ft.dropdown.Option(
                                                            "system", "跟随系统"
                                                        ),
                                                    ],
                                                    value=self.cfg.load().get(
                                                        "Theme", "system"
                                                    ),
                                                    width=500,
                                                    on_change=self._change_color_mode,
                                                ),
                                                
                                            ],
                                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                        ),
                                    ]
                                ),
                                padding=10,
                            ),
                        ),
                        ft.Tab(
                            text="数据和缓存",
                            icon=ft.Icons.STORAGE,
                            content=ft.Column(
                                [
                                    ft.Text(
                                        "游戏路径管理",
                                        size=20,
                                        weight=ft.FontWeight.BOLD,
                                    ),
                                    ft.Row(
                                        controls=[
                                            ft.FilledButton(
                                                "添加游戏目录", icon=ft.Icons.ADD
                                            ),
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
                            ),
                        ),
                    ],
                ),
            ],
        )
