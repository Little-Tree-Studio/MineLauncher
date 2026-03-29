from __future__ import annotations
import flet as ft
from ..services.config_service import ConfigService
from ..services.java_detector import JavaDetector, JavaInfo


class JavaSettingsPage:
    def __init__(self, page: ft.Page):
        self.page = page
        self.cfg = ConfigService()
        self.java_detector: JavaDetector | None = None
        self.java_paths: list[JavaInfo] = []
        self._selected_java_info: JavaInfo | None = None
        self._scan_complete = False

    def _navigate(self, route: str):
        if self.java_detector:
            self.java_detector.cancel()

        async def do_navigate():
            await self.page.push_route(route)

        self.page.run_task(do_navigate)

    def _on_java_found(self, java_info: JavaInfo):
        self.java_paths.append(java_info)
        self.java_paths.sort(key=lambda x: x.score, reverse=True)
        self._update_java_list_incremental(java_info)

    def _update_java_list_incremental(self, new_java: JavaInfo):
        if not hasattr(self, "java_dd"):
            return

        options = [
            ft.dropdown.Option(j.path, self._get_java_display_text(j))
            for j in self.java_paths
        ]

        self.java_dd.options = options
        if not self.java_dd.value:
            self.java_dd.value = new_java.path
            self._selected_java_info = new_java
            self._update_java_details(new_java)

        if hasattr(self, "scan_status"):
            self.scan_status.value = f"已找到 {len(self.java_paths)} 个Java..."

        self.page.update()

    async def _scan_java_async(self, mc_path: str | None = None):
        self.java_detector = JavaDetector(mc_path)
        self.java_paths.clear()
        self._scan_complete = False
        self.java_detector.set_on_java_found(self._on_java_found)
        return await self.java_detector.scan_async()

    def _get_java_display_text(self, java_info: JavaInfo) -> str:
        parts = []
        if java_info.version:
            parts.append(f"Java {java_info.version}")
        else:
            parts.append("Unknown")

        if java_info.is_64bit:
            parts.append("64-bit")
        else:
            parts.append("32-bit")

        if java_info.is_jdk:
            parts.append("JDK")
        else:
            parts.append("JRE")

        return " ".join(parts)

    def _get_java_detail_text(self, java_info: JavaInfo) -> str:
        parts = [f"路径: {java_info.path}"]
        if java_info.version:
            parts.append(f"版本: {java_info.version}")
        parts.append("64-bit" if java_info.is_64bit else "32-bit")
        parts.append("JDK" if java_info.is_jdk else "JRE")
        parts.append("Minecraft相关" if java_info.is_mc_related else "通用")
        parts.append(f"评分: {java_info.score}")
        return "\n".join(parts)

    async def _on_java_select(self, e):
        selected_path = e.control.value
        for java_info in self.java_paths:
            if java_info.path == selected_path:
                self._selected_java_info = java_info
                self._update_java_details(java_info)
                self.cfg.save({**self.cfg.load(), "JavaPath": selected_path})
                break

    def _update_java_details(self, java_info: JavaInfo):
        if hasattr(self, "java_detail_text"):
            self.java_detail_text.value = self._get_java_detail_text(java_info)
            self.page.update()

    async def _scan_and_update(self):
        self.scan_indicator.visible = True
        self.scan_btn.disabled = True
        self.scan_status.value = "正在扫描Java..."
        self.java_dd.options = [ft.dropdown.Option("", "扫描中...")]
        self.page.update()

        await self._scan_java_async()

        self._scan_complete = True
        self.scan_indicator.visible = False
        self.scan_btn.disabled = False
        self.scan_status.value = f"共找到 {len(self.java_paths)} 个Java"

        self._update_java_list()
        self.page.update()

    def _update_java_list(self):
        current_value = self.java_dd.value if hasattr(self, "java_dd") else None

        self.java_dd.options = (
            [
                ft.dropdown.Option(j.path, self._get_java_display_text(j))
                for j in self.java_paths
            ]
            if self.java_paths
            else [ft.dropdown.Option("", "未找到Java，请点击重新扫描")]
        )

        if current_value and any(j.path == current_value for j in self.java_paths):
            self.java_dd.value = current_value
        elif self.java_paths:
            saved_path = self.cfg.load().get("JavaPath", "")
            if saved_path and any(j.path == saved_path for j in self.java_paths):
                self.java_dd.value = saved_path
            else:
                self.java_dd.value = self.java_paths[0].path
            self._selected_java_info = next(
                (j for j in self.java_paths if j.path == self.java_dd.value), None
            )
            if self._selected_java_info:
                self._update_java_details(self._selected_java_info)

    async def _import_java(self, e):
        pass

    def build(self) -> ft.View:
        self.java_dd = ft.Dropdown(
            label="选择Java",
            options=[],
            width=500,
            on_select=self._on_java_select,
        )

        self.java_detail_text = ft.Text(
            "",
            size=12,
            color=ft.Colors.GREY,
        )

        self.scan_indicator = ft.ProgressBar(visible=False, width=500)

        self.scan_status = ft.Text(
            "",
            size=12,
            color=ft.Colors.GREY,
        )

        self.scan_btn = ft.FilledButton(
            "扫描Java",
            icon=ft.Icons.SEARCH,
            on_click=lambda e: self.page.run_task(self._scan_and_update),
        )

        self.import_btn = ft.FilledButton(
            "手动导入",
            icon=ft.Icons.ADD,
            on_click=self._import_java,
        )

        jvm_args_input = ft.TextField(
            label="JVM参数",
            hint_text="例如: -Xmx4G -Xms2G -XX:+UseG1GC",
            value=self.cfg.load().get("JvmArguments", ""),
            width=500,
            on_blur=self._save_jvm_args,
        )
        self.jvm_args_input = jvm_args_input

        min_mem_input = ft.TextField(
            label="最小内存",
            hint_text="例如: 2G",
            value=self.cfg.load().get("MinMemory", "2G"),
            width=200,
            on_blur=self._save_mem_settings,
        )
        self.min_mem_input = min_mem_input

        max_mem_input = ft.TextField(
            label="最大内存",
            hint_text="例如: 4G",
            value=self.cfg.load().get("MaxMemory", "4G"),
            width=200,
            on_blur=self._save_mem_settings,
        )
        self.max_mem_input = max_mem_input

        content = ft.Container(
            padding=20,
            content=ft.Column(
                [
                    ft.Card(
                        content=ft.Container(
                            padding=15,
                            content=ft.Column(
                                [
                                    ft.Text(
                                        "Java 选择", size=18, weight=ft.FontWeight.BOLD
                                    ),
                                    ft.Text(
                                        "选择用于启动Minecraft的Java运行时",
                                        size=12,
                                        color=ft.Colors.GREY,
                                    ),
                                    ft.Divider(),
                                    self.java_dd,
                                    self.java_detail_text,
                                    ft.Row(
                                        [self.scan_btn, self.import_btn],
                                        alignment=ft.MainAxisAlignment.START,
                                    ),
                                    self.scan_indicator,
                                    self.scan_status,
                                ],
                            ),
                        ),
                        width=550,
                    ),
                    ft.Card(
                        content=ft.Container(
                            padding=15,
                            content=ft.Column(
                                [
                                    ft.Text(
                                        "内存设置", size=18, weight=ft.FontWeight.BOLD
                                    ),
                                    ft.Text(
                                        "设置Minecraft游戏内存分配",
                                        size=12,
                                        color=ft.Colors.GREY,
                                    ),
                                    ft.Divider(),
                                    ft.Row(
                                        [min_mem_input, max_mem_input],
                                        alignment=ft.MainAxisAlignment.START,
                                    ),
                                ],
                            ),
                        ),
                        width=550,
                    ),
                    ft.Card(
                        content=ft.Container(
                            padding=15,
                            content=ft.Column(
                                [
                                    ft.Text(
                                        "JVM参数", size=18, weight=ft.FontWeight.BOLD
                                    ),
                                    ft.Text(
                                        "高级Java虚拟机参数设置",
                                        size=12,
                                        color=ft.Colors.GREY,
                                    ),
                                    ft.Divider(),
                                    jvm_args_input,
                                    ft.Row(
                                        [
                                            ft.Text(
                                                "常用参数:",
                                                size=12,
                                                color=ft.Colors.GREY,
                                            ),
                                            ft.Text(
                                                "-Xmx 最大内存",
                                                size=11,
                                                color=ft.Colors.GREY,
                                            ),
                                            ft.Text(
                                                "-Xms 初始内存",
                                                size=11,
                                                color=ft.Colors.GREY,
                                            ),
                                            ft.Text(
                                                "-XX:+UseG1GC G1垃圾回收",
                                                size=11,
                                                color=ft.Colors.GREY,
                                            ),
                                        ],
                                        spacing=10,
                                    ),
                                ],
                            ),
                        ),
                        width=550,
                    ),
                ],
                scroll=ft.ScrollMode.AUTO,
            ),
            expand=True,
        )

        self.page.run_task(self._scan_and_update)

        return ft.View(
            route="/java_settings",
            controls=[
                ft.AppBar(
                    title=ft.Text("Java设置"),
                    automatically_imply_leading=True,
                    leading=ft.IconButton(
                        ft.Icons.ARROW_BACK,
                        on_click=lambda _: self._navigate("/settings"),
                    ),
                ),
                content,
            ],
        )

    def _save_jvm_args(self, e):
        jvm_args = e.control.value
        self.cfg.save({**self.cfg.load(), "JvmArguments": jvm_args})

    def _save_mem_settings(self, e):
        min_mem = self.min_mem_input.value
        max_mem = self.max_mem_input.value
        self.cfg.save({**self.cfg.load(), "MinMemory": min_mem, "MaxMemory": max_mem})
