from __future__ import annotations
import flet as ft

class AboutPage:
    def __init__(self, page: ft.Page):
        self.page = page

    def build(self) -> ft.View:
        return ft.View(
            "/about",
            [
                ft.AppBar(title=ft.Text("关于 MineLauncher"), automatically_imply_leading=True),
                ft.Column(
                    [
                        ft.Text("MineLauncher", size=40, weight=ft.FontWeight.BOLD),
                        ft.Text("一个示例启动器。"),
                        ft.TextButton("返回", on_click=lambda _: self.page.go("/"), icon=ft.Icons.ARROW_BACK),
                    ],
                    expand=True,
                    alignment=ft.MainAxisAlignment.CENTER,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                ),
            ],
        )
