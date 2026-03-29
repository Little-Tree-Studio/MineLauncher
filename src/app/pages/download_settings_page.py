"""下载设置页面"""

from __future__ import annotations
import flet as ft
from ..services.config_service import ConfigService


class DownloadSettingsPage:
    """下载设置页面"""

    def __init__(self, page: ft.Page):
        self.page = page
        self.cfg = ConfigService()
        self.download_cfg = self.cfg.get_download_config()

    def _navigate(self, route: str):
        async def do_navigate():
            await self.page.push_route(route)

        self.page.run_task(do_navigate)

    def _show_message(self, text: str):
        self.page.show_dialog(ft.SnackBar(ft.Text(text)))
        self.page.update()

    def _save_setting(self, key: str, value):
        """保存单个设置"""
        self.download_cfg[key] = value
        self.cfg.save_download_config(self.download_cfg)
        self._show_message("设置已保存")

    def _save_smart_segment(self, key: str, value):
        """保存智能分段设置"""
        if "smart_segment" not in self.download_cfg:
            self.download_cfg["smart_segment"] = {}
        self.download_cfg["smart_segment"][key] = value
        self.cfg.save_download_config(self.download_cfg)
        self._show_message("设置已保存")

    def build(self) -> ft.View:
        # 最大连接数滑块
        max_conn_slider = ft.Slider(
            min=1,
            max=32,
            value=self.download_cfg.get("max_connections", 16),
            divisions=31,
            label="{value}",
            on_change=lambda e: self._save_setting(
                "max_connections", int(e.control.value)
            ),
        )

        # 最小连接数滑块
        min_conn_slider = ft.Slider(
            min=1,
            max=16,
            value=self.download_cfg.get("min_connections", 4),
            divisions=15,
            label="{value}",
            on_change=lambda e: self._save_setting(
                "min_connections", int(e.control.value)
            ),
        )

        # 分块大小滑块 (MB)
        chunk_size_slider = ft.Slider(
            min=0.5,
            max=10,
            value=self.download_cfg.get("chunk_size_mb", 2),
            divisions=19,
            label="{value}MB",
            on_change=lambda e: self._save_setting(
                "chunk_size_mb", round(e.control.value, 1)
            ),
        )

        # 速度限制输入
        speed_limit_field = ft.TextField(
            label="速度限制 (KB/s, 0=无限制)",
            value=str(self.download_cfg.get("speed_limit_kbps", 0)),
            width=200,
            on_change=lambda e: self._save_setting(
                "speed_limit_kbps", int(e.control.value or 0)
            ),
        )

        # 超时时间
        timeout_field = ft.TextField(
            label="超时时间 (秒)",
            value=str(self.download_cfg.get("timeout_seconds", 30)),
            width=150,
            on_change=lambda e: self._save_setting(
                "timeout_seconds", int(e.control.value or 30)
            ),
        )

        # 最大重试次数
        retry_field = ft.TextField(
            label="最大重试次数",
            value=str(self.download_cfg.get("max_retries", 5)),
            width=150,
            on_change=lambda e: self._save_setting(
                "max_retries", int(e.control.value or 5)
            ),
        )

        # 下载源选择
        source_dd = ft.Dropdown(
            label="下载源优先级",
            options=[
                ft.dropdown.Option("mirror_only", "仅镜像源"),
                ft.dropdown.Option("mirror_first", "镜像源优先 (推荐)"),
                ft.dropdown.Option("official_first", "官方源优先"),
                ft.dropdown.Option("official_only", "仅官方源"),
            ],
            value=self.download_cfg.get("download_source", "mirror_first"),
            width=250,
            on_select=lambda e: self._save_setting("download_source", e.control.value),
        )

        # 开关控件
        enable_chunking_switch = ft.Switch(
            label="启用多线程分块下载",
            value=self.download_cfg.get("enable_chunking", True),
            on_change=lambda e: self._save_setting("enable_chunking", e.control.value),
        )

        verify_hash_switch = ft.Switch(
            label="下载后验证文件哈希",
            value=self.download_cfg.get("verify_hash", True),
            on_change=lambda e: self._save_setting("verify_hash", e.control.value),
        )

        adaptive_switch = ft.Switch(
            label="自适应线程数调整",
            value=self.download_cfg.get("adaptive_threads", True),
            on_change=lambda e: self._save_setting("adaptive_threads", e.control.value),
        )

        resume_switch = ft.Switch(
            label="启用断点续传",
            value=self.download_cfg.get("resume_enabled", True),
            on_change=lambda e: self._save_setting("resume_enabled", e.control.value),
        )

        # 智能分段设置
        smart_segment_cfg = self.download_cfg.get("smart_segment", {})

        min_chunk_field = ft.TextField(
            label="最小分块大小 (KB)",
            value=str(smart_segment_cfg.get("min_chunk_size_kb", 512)),
            width=180,
            on_change=lambda e: self._save_smart_segment(
                "min_chunk_size_kb", int(e.control.value or 512)
            ),
        )

        max_chunk_field = ft.TextField(
            label="最大分块大小 (MB)",
            value=str(smart_segment_cfg.get("max_chunk_size_mb", 10)),
            width=180,
            on_change=lambda e: self._save_smart_segment(
                "max_chunk_size_mb", int(e.control.value or 10)
            ),
        )

        dynamic_adjust_switch = ft.Switch(
            label="动态调整分块大小",
            value=smart_segment_cfg.get("dynamic_adjustment", True),
            on_change=lambda e: self._save_smart_segment(
                "dynamic_adjustment", e.control.value
            ),
        )

        # 当前标签页索引
        current_tab = [0]

        # 基础设置内容
        basic_content = ft.Container(
            content=ft.Column(
                [
                    ft.Card(
                        content=ft.Container(
                            padding=15,
                            content=ft.Column(
                                [
                                    ft.Text(
                                        "连接设置", size=16, weight=ft.FontWeight.BOLD
                                    ),
                                    ft.Row(
                                        [
                                            ft.Text("最大连接数:", width=120),
                                            max_conn_slider,
                                            ft.Text(
                                                f"{self.download_cfg.get('max_connections', 16)}个",
                                                width=50,
                                            ),
                                        ]
                                    ),
                                    ft.Row(
                                        [
                                            ft.Text("最小连接数:", width=120),
                                            min_conn_slider,
                                            ft.Text(
                                                f"{self.download_cfg.get('min_connections', 4)}个",
                                                width=50,
                                            ),
                                        ]
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
                                        "分块设置", size=16, weight=ft.FontWeight.BOLD
                                    ),
                                    enable_chunking_switch,
                                    ft.Row(
                                        [
                                            ft.Text("分块大小:", width=120),
                                            chunk_size_slider,
                                            ft.Text(
                                                f"{self.download_cfg.get('chunk_size_mb', 2)}MB",
                                                width=50,
                                            ),
                                        ]
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
                                        "速度与超时", size=16, weight=ft.FontWeight.BOLD
                                    ),
                                    ft.Row(
                                        [
                                            speed_limit_field,
                                            ft.Text(
                                                "0表示无限制",
                                                size=12,
                                                color=ft.Colors.GREY,
                                            ),
                                        ]
                                    ),
                                    ft.Row(
                                        [
                                            timeout_field,
                                            retry_field,
                                        ]
                                    ),
                                ]
                            ),
                        )
                    ),
                ],
                scroll=ft.ScrollMode.AUTO,
            ),
            padding=10,
            expand=True,
        )

        # 高级设置内容
        advanced_content = ft.Container(
            content=ft.Column(
                [
                    ft.Card(
                        content=ft.Container(
                            padding=15,
                            content=ft.Column(
                                [
                                    ft.Text(
                                        "下载源", size=16, weight=ft.FontWeight.BOLD
                                    ),
                                    source_dd,
                                    ft.Text(
                                        "镜像源在国内速度更快，官方源更稳定",
                                        size=12,
                                        color=ft.Colors.GREY,
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
                                        "智能优化", size=16, weight=ft.FontWeight.BOLD
                                    ),
                                    adaptive_switch,
                                    resume_switch,
                                    verify_hash_switch,
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
                                        "智能分段", size=16, weight=ft.FontWeight.BOLD
                                    ),
                                    dynamic_adjust_switch,
                                    ft.Row(
                                        [
                                            min_chunk_field,
                                            max_chunk_field,
                                        ]
                                    ),
                                    ft.Text(
                                        "智能分段会根据网络状况自动调整分块大小",
                                        size=12,
                                        color=ft.Colors.GREY,
                                    ),
                                ]
                            ),
                        )
                    ),
                ],
                scroll=ft.ScrollMode.AUTO,
            ),
            padding=10,
            expand=True,
        )

        # 内容区域
        content_area = ft.Container(expand=True, content=basic_content)

        def switch_tab(index):
            current_tab[0] = index
            if index == 0:
                content_area.content = basic_content
                tab_buttons.controls[0].style = ft.ButtonStyle(
                    bgcolor=ft.Colors.BLUE_100
                )
                tab_buttons.controls[1].style = ft.ButtonStyle(bgcolor=None)
            else:
                content_area.content = advanced_content
                tab_buttons.controls[0].style = ft.ButtonStyle(bgcolor=None)
                tab_buttons.controls[1].style = ft.ButtonStyle(
                    bgcolor=ft.Colors.BLUE_100
                )
            self.page.update()

        # 使用按钮模拟Tabs
        tab_buttons = ft.Row(
            [
                ft.TextButton(
                    "基础设置",
                    icon=ft.Icons.SETTINGS,
                    style=ft.ButtonStyle(bgcolor=ft.Colors.BLUE_100),
                    on_click=lambda e: switch_tab(0),
                ),
                ft.TextButton(
                    "高级设置",
                    icon=ft.Icons.TUNE,
                    style=ft.ButtonStyle(bgcolor=None),
                    on_click=lambda e: switch_tab(1),
                ),
            ]
        )

        # 重置按钮
        def reset_to_defaults(_):
            self.download_cfg = self.cfg.DEFAULT["Download"].copy()
            self.cfg.save_download_config(self.download_cfg)
            self._show_message("已重置为默认设置")
            self.page.controls.clear()
            self.page.add(self.build())
            self.page.update()

        return ft.View(
            route="/download_settings",
            controls=[
                ft.AppBar(
                    title=ft.Text("下载设置"),
                    automatically_imply_leading=True,
                    leading=ft.IconButton(
                        ft.Icons.ARROW_BACK,
                        on_click=lambda _: self._navigate("/settings"),
                    ),
                    actions=[ft.TextButton("重置默认", on_click=reset_to_defaults)],
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
