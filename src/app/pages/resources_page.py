from __future__ import annotations
import flet as ft


class ResourcesPage:
    def __init__(self, page: ft.Page):
        self.page = page

    def build(self) -> ft.View:
        return ft.View(
            "/resources",
            [
                ft.AppBar(title=ft.Text("资源中心"), automatically_imply_leading=True),
                ft.Column(
                    [
                        ft.Row(
                            controls=[
                                ft.Container(
                                    content=ft.Column(
                                        controls=[
                                            ft.Icon(name=ft.Icons.API),
                                            ft.Text("核心下载"),
                                        ],
                                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                                        alignment=ft.MainAxisAlignment.CENTER,
                                        expand=True,
                                    ),
                                    ink=True,
                                    width=100,
                                    height=100,
                                    on_click=lambda _: self.page.go("/core_download")

                                ),
                                ft.Container(
                                    content=ft.Column(
                                        controls=[
                                            ft.Icon(name=ft.Icons.EXTENSION),
                                            ft.Text("Mod下载"),
                                        ],
                                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                                        alignment=ft.MainAxisAlignment.CENTER,
                                        expand=True,
                                    ),
                                    ink=True,
                                    width=100,
                                    height=100,
                                    on_click=lambda _: self.page.go("/mod_download")

                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_AROUND,
                        ),
                        ft.TextButton(
                            "返回",
                            on_click=lambda _: self.page.go("/"),
                            icon=ft.Icons.ARROW_BACK,
                        ),
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    expand=True,
                ),
            ],
        )
