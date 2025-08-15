import flet as ft


class ModDownloadPage:
    def __init__(self, page: ft.Page):
        self.page = page

    def build(self) -> ft.View:
        return ft.View("/mod_download", [])
