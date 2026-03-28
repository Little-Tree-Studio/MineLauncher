from __future__ import annotations
import flet as ft


class ResourcesPage:
    def __init__(self, page: ft.Page):
        self.page = page

    def _navigate(self, route: str):
        async def do_navigate():
            await self.page.push_route(route)
        self.page.run_task(do_navigate)

    def build(self) -> ft.View:
        return ft.View(
            route="/resources",
            controls=[
                ft.AppBar(title=ft.Text("资源中心"), automatically_imply_leading=True, leading=ft.IconButton(ft.Icons.ARROW_BACK, on_click=lambda _: self._navigate("/"))),
                ft.Column(
                    [
                        ft.Row(
                            controls=[
                                ft.Container(
                                    content=ft.Column(
                                        controls=[
                                            ft.Icon(ft.Icons.API),
                                            ft.Text("核心下载"),
                                        ],
                                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                                        alignment=ft.MainAxisAlignment.CENTER,
                                        expand=True,
                                    ),
                                    ink=True,
                                    width=100,
                                    height=100,
                                    on_click=lambda _: self._navigate("/core_download")
                                ),
                                ft.Container(
                                    content=ft.Column(
                                        controls=[
                                            ft.Icon(ft.Icons.EXTENSION),
                                            ft.Text("Mod下载"),
                                        ],
                                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                                        alignment=ft.MainAxisAlignment.CENTER,
                                        expand=True,
                                    ),
                                    ink=True,
                                    width=100,
                                    height=100,
                                    on_click=lambda _: self._navigate("/mod_download")
                                ),
                                ft.Container(
                                    content=ft.Column(
                                        controls=[
                                            ft.Icon(ft.Icons.INVENTORY),
                                            ft.Text("整合包下载"),
                                        ],
                                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                                        alignment=ft.MainAxisAlignment.CENTER,
                                        expand=True,
                                    ),
                                    ink=True,
                                    width=100,
                                    height=100,
                                    on_click=lambda _: self._navigate("/mod_download")
                                ),
                                ft.Container(
                                    content=ft.Column(
                                        controls=[
                                            ft.Icon(ft.Icons.LIGHT_MODE),
                                            ft.Text("光影下载"),
                                        ],
                                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                                        alignment=ft.MainAxisAlignment.CENTER,
                                        expand=True,
                                    ),
                                    ink=True,
                                    width=100,
                                    height=100,
                                    on_click=lambda _: self._navigate("/shader_download")
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_AROUND,
                        ),
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    expand=True,
                ),
            ],
        )
