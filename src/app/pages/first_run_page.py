from __future__ import annotations
import itertools
import threading
import time
import flet as ft
from app.services.config_service import ConfigService
from app.services.i18n_service import I18nService

class FirstRunPage:
    """
    首次启动的 OOBE 页面：展示“你好”轮播 + 语言选择
    """
    def __init__(self, on_done):
        self.on_done = on_done               # 回调：语言已选好，进入主界面
        self.cfg = ConfigService()
        self.hello_text = ft.Text("你好", size=35)

    def build(self) -> ft.View:
        threading.Thread(target=self._cycle_hello, daemon=True).start()

        def change_language(e):
            code = e.control.value
            self.cfg.save({**self.cfg.load(), "Language": code})
            # 立即刷新语言包
            self.lang = I18nService(code)

        return ft.View(
            "/start",
            [
                ft.AppBar(title=ft.Text("欢迎"), automatically_imply_leading=False),
                ft.Column(
                    [
                        ft.Text("MineLauncher", size=45),
                        ft.Row(
                            [ft.Icon(ft.Icons.WAVING_HAND, size=45), self.hello_text],
                            alignment=ft.MainAxisAlignment.CENTER,
                        ),
                        ft.Text("请选择语言 / Select Language", size=20),
                        ft.Dropdown(
                            options=[
                                ft.dropdown.Option("zh-cn", "简体中文"),
                                ft.dropdown.Option("en", "English"),
                                ft.dropdown.Option("ja", "日本語"),
                                ft.dropdown.Option("wy-hx", "文言(華夏)")
                            ],
                            value=self.cfg.load().get("Language", "zh-cn"),
                            on_change=change_language,
                        ),
                        ft.Row(
                            [
                                ft.ElevatedButton(
                                    "进入启动器",
                                    icon=ft.Icons.NAVIGATE_NEXT,
                                    on_click=lambda _: self.on_done(),
                                )
                            ],
                            alignment=ft.MainAxisAlignment.END,
                        ),
                    ],
                    spacing=30,
                    alignment=ft.MainAxisAlignment.CENTER,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    expand=True,
                ),
            ],
        )

    def _cycle_hello(self):
        for word in itertools.cycle(["你好", "Hello", "Bonjour", "Hola", "こんにちは"]):
            time.sleep(1.2)
            try:
                self.hello_text.value = word
                self.hello_text.update()
            except Exception:
                break