from __future__ import annotations
import flet as ft


class SettingsPage:
    def __init__(self, page: ft.Page):
        self.page = page
        self.path_open_btn = ft.ElevatedButton(
            "打开"
        )
        self.path_delete_btn = ft.ElevatedButton("删除")

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
                            text="外观",
                            icon=ft.Icons.SETTINGS,
                            content=ft.Column(
                                [
                                    ft.Text("主题设置"),
                                    ft.Dropdown(
                                        options=[
                                            ft.dropdown.Option("light", "浅色主题"),
                                            ft.dropdown.Option("dark", "深色主题"),
                                            ft.dropdown.Option("system", "跟随系统"),
                                        ],
                                        value="system",
                                    ),
                                ]
                            ),
                        ),
                        ft.Tab(
                            text="资源",
                            icon=ft.Icons.INFO,
                            content=ft.Column(
                                [
                                    ft.Text(
                                        "资源路径管理",
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
                                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                            ),
                                        ]
                                    ),
                                ],
                            ),
                        ),
                    ],
                ),
            ],
        )
