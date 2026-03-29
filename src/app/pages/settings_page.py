from __future__ import annotations
import flet as ft
from ..services.i18n_service import I18nService
from ..services.config_service import ConfigService
from ..services.java_detector import JavaDetector, JavaInfo


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
        self.java_detector: JavaDetector | None = None
        self.java_paths: list[JavaInfo] = []
        self._java_scan_in_progress = False
        self._java_file_picker = ft.FilePicker()

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

    async def _scan_java_async(self, mc_path: str | None = None):
        if self._java_scan_in_progress:
            return self.java_paths

        self._java_scan_in_progress = True
        self.java_detector = JavaDetector(mc_path)
        self.java_paths = await self.java_detector.scan_async()
        self._java_scan_in_progress = False
        return self.java_paths

    def _get_java_paths(self) -> list[JavaInfo]:
        return self.java_paths

    def _get_java_display_text(self, java_info: JavaInfo) -> str:
        parts = [java_info.path]
        if java_info.version:
            parts.append(f" ({java_info.version})")
        if java_info.is_64bit:
            parts.append(" [64-bit]")
        else:
            parts.append(" [32-bit]")
        if java_info.is_jdk:
            parts.append(" JDK")
        else:
            parts.append(" JRE")
        if java_info.is_mc_related:
            parts.append(" ⚙")
        return "".join(parts)

    def _change_java(self, e):
        selected = e.control.value
        self.cfg.save({**self.cfg.load(), "JavaPath": selected})
        self.page.show_dialog(ft.SnackBar(ft.Text(f"已选择Java: {selected}")))
        self.page.update()

    async def _scan_and_update_java(self):
        self._java_scan_indicator.visible = True
        self._java_scan_btn.disabled = True
        self._java_scan_status.value = "正在扫描Java..."
        self.java_dd.options = [ft.dropdown.Option("", "扫描中...")]
        self.page.update()

        java_paths = await self._scan_java_async()

        self._java_scan_indicator.visible = False
        self._java_scan_btn.disabled = False
        self._java_scan_status.value = f"共找到 {len(java_paths)} 个Java"
        self._update_java_dropdown(java_paths)

    def _update_java_dropdown(self, java_paths: list[JavaInfo]):
        if not hasattr(self, "java_dd"):
            return
        self.java_dd.options = (
            [
                ft.dropdown.Option(j.path, self._get_java_display_text(j))
                for j in java_paths
            ]
            if java_paths
            else [ft.dropdown.Option("", "未找到Java，请检查环境变量或手动设置。")]
        )
        self.java_dd.value = self.cfg.load().get(
            "JavaPath", java_paths[0].path if java_paths else ""
        )
        self.page.update()

    def _import_java(self, e):
        def on_java_selected(result: ft.FilePickerResult):
            if result.files:
                for f in result.files:
                    java_path = f.path
                    if java_path not in [j.path for j in self.java_paths]:
                        java_info = JavaInfo(
                            path=java_path,
                            version="",
                            is_64bit=True,
                            is_jdk=False,
                            is_mc_related=False,
                            score=0,
                        )
                        self.java_paths.append(java_info)
                        self._on_java_found(java_info)
                    self.cfg.save({**self.cfg.load(), "JavaPath": java_path})
                    self._change_java(
                        type(
                            "obj",
                            (object,),
                            {"control": type("obj", (object,), {"value": java_path})()},
                        )()
                    )

        self._java_file_picker.on_result = on_java_selected
        if self._java_file_picker not in self.page.controls:
            self.page.controls.append(self._java_file_picker)
        self._java_file_picker.pick_files(allow_multiple=False)

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
        self._java_scan_status.value = f"共找到 {len(self.java_paths)} 个Java"
        self.page.update()

    def build(self) -> ft.View:
        java_paths = self._get_java_paths()
        self.java_dd = ft.Dropdown(
            options=[
                ft.dropdown.Option(j.path, self._get_java_display_text(j))
                for j in java_paths
            ]
            if java_paths
            else [ft.dropdown.Option("", "未找到Java，请检查环境变量或手动设置。")],
            value=self.cfg.load().get(
                "JavaPath", java_paths[0].path if java_paths else ""
            ),
            width=500,
            on_select=self._change_java,
        )

        self.page.run_task(self._scan_and_update_java)

        current_tab = [0]

        display_content = ft.Container(
            content=ft.Column(
                [
                    ft.Card(
                        content=ft.Container(
                            padding=15,
                            content=ft.Column(
                                [
                                    ft.Text(
                                        "语言与主题", size=16, weight=ft.FontWeight.BOLD
                                    ),
                                    ft.Row(
                                        [
                                            ft.Text("语言:", width=80),
                                            ft.Dropdown(
                                                options=[
                                                    ft.dropdown.Option("en", "English"),
                                                    ft.dropdown.Option(
                                                        "zh-cn", "简体中文"
                                                    ),
                                                    ft.dropdown.Option(
                                                        "wy-hx", "文言（华夏）"
                                                    ),
                                                    ft.dropdown.Option(
                                                        "zh-tw", "繁體中文（中國台灣）"
                                                    ),
                                                    ft.dropdown.Option(
                                                        "zh-hk", "繁體中文（中國香港）"
                                                    ),
                                                    ft.dropdown.Option("ja", "日本語"),
                                                    ft.dropdown.Option("ko", "한국어"),
                                                    ft.dropdown.Option(
                                                        "fr", "Français"
                                                    ),
                                                    ft.dropdown.Option("de", "Deutsch"),
                                                ],
                                                value=self.cfg.load().get(
                                                    "Language", "zh-cn"
                                                ),
                                                width=200,
                                                on_select=self._change_language,
                                            ),
                                        ],
                                        spacing=10,
                                    ),
                                    ft.Row(
                                        [
                                            ft.Text("主题:", width=80),
                                            ft.Dropdown(
                                                options=[
                                                    ft.dropdown.Option("light", "浅色"),
                                                    ft.dropdown.Option("dark", "深色"),
                                                    ft.dropdown.Option(
                                                        "system", "跟随系统"
                                                    ),
                                                ],
                                                value=self.cfg.load().get(
                                                    "Theme", "system"
                                                ),
                                                width=200,
                                                on_select=self._change_color_mode,
                                            ),
                                        ],
                                        spacing=10,
                                    ),
                                ],
                                spacing=10,
                            ),
                        )
                    ),
                ],
                scroll=ft.ScrollMode.AUTO,
            ),
            padding=10,
            expand=True,
        )

        data_content = ft.Container(
            content=ft.Column(
                [
                    ft.Card(
                        content=ft.Container(
                            padding=15,
                            content=ft.Column(
                                [
                                    ft.Text(
                                        "游戏路径", size=16, weight=ft.FontWeight.BOLD
                                    ),
                                    ft.Text(
                                        "管理游戏目录位置",
                                        size=12,
                                        color=ft.Colors.GREY,
                                    ),
                                    ft.Row(
                                        [
                                            ft.FilledButton(
                                                "添加目录", icon=ft.Icons.ADD
                                            ),
                                            self.path_open_btn,
                                            self.path_delete_btn,
                                        ],
                                        spacing=10,
                                    ),
                                ],
                                spacing=10,
                            ),
                        )
                    ),
                ],
                scroll=ft.ScrollMode.AUTO,
            ),
            padding=10,
            expand=True,
        )

        download_cfg = self.cfg.get_download_config()

        def save_download_setting(key: str, value):
            download_cfg[key] = value
            self.cfg.save_download_config(download_cfg)

        max_conn_slider = ft.Slider(
            min=1,
            max=32,
            value=download_cfg.get("max_connections", 16),
            divisions=31,
            label="{value}",
            on_change=lambda e: save_download_setting(
                "max_connections", int(e.control.value or 16)
            ),
        )
        chunk_size_slider = ft.Slider(
            min=0.5,
            max=10,
            value=download_cfg.get("chunk_size_mb", 2),
            divisions=19,
            label="{value}MB",
            on_change=lambda e: save_download_setting(
                "chunk_size_mb", round(float(e.control.value or 2), 1)
            ),
        )
        speed_limit_field = ft.TextField(
            label="速度限制 (KB/s, 0=无限制)",
            value=str(download_cfg.get("speed_limit_kbps", 0)),
            width=180,
            on_change=lambda e: save_download_setting(
                "speed_limit_kbps", int(e.control.value or 0)
            ),
        )
        source_dd = ft.Dropdown(
            label="下载源",
            options=[
                ft.dropdown.Option("mirror_first", "镜像源优先 (推荐)"),
                ft.dropdown.Option("official_first", "官方源优先"),
                ft.dropdown.Option("mirror_only", "仅镜像源"),
                ft.dropdown.Option("official_only", "仅官方源"),
            ],
            value=download_cfg.get("download_source", "mirror_first"),
            width=200,
            on_select=lambda e: save_download_setting(
                "download_source", e.control.value
            ),
        )

        download_content = ft.Container(
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
                                            ft.Text("最大连接数:", width=100),
                                            max_conn_slider,
                                            ft.Text(
                                                f"{download_cfg.get('max_connections', 16)}个"
                                            ),
                                        ]
                                    ),
                                    ft.Row(
                                        [
                                            ft.Text("分块大小:", width=100),
                                            chunk_size_slider,
                                            ft.Text(
                                                f"{download_cfg.get('chunk_size_mb', 2)}MB"
                                            ),
                                        ]
                                    ),
                                    ft.Row(
                                        [
                                            ft.Text("速度限制:", width=100),
                                            speed_limit_field,
                                        ]
                                    ),
                                ],
                                spacing=10,
                            ),
                        )
                    ),
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
                                ],
                                spacing=10,
                            ),
                        )
                    ),
                    ft.Card(
                        content=ft.Container(
                            padding=15,
                            content=ft.Column(
                                [
                                    ft.Text(
                                        "高级选项", size=16, weight=ft.FontWeight.BOLD
                                    ),
                                    ft.Switch(
                                        label="启用多线程分块下载",
                                        value=download_cfg.get("enable_chunking", True),
                                        on_change=lambda e: save_download_setting(
                                            "enable_chunking", e.control.value
                                        ),
                                    ),
                                    ft.Switch(
                                        label="启用断点续传",
                                        value=download_cfg.get("resume_enabled", True),
                                        on_change=lambda e: save_download_setting(
                                            "resume_enabled", e.control.value
                                        ),
                                    ),
                                    ft.Switch(
                                        label="下载后验证文件哈希",
                                        value=download_cfg.get("verify_hash", True),
                                        on_change=lambda e: save_download_setting(
                                            "verify_hash", e.control.value
                                        ),
                                    ),
                                ],
                                spacing=10,
                            ),
                        )
                    ),
                    ft.Card(
                        content=ft.Container(
                            padding=15,
                            content=ft.Column(
                                [
                                    ft.Text(
                                        "跳转到下载管理",
                                        size=16,
                                        weight=ft.FontWeight.BOLD,
                                    ),
                                    ft.Text(
                                        "查看和管理下载任务、历史记录",
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
                                ],
                                spacing=10,
                            ),
                        )
                    ),
                ],
                scroll=ft.ScrollMode.AUTO,
                spacing=10,
            ),
            padding=10,
            expand=True,
        )

        launch_settings = self.cfg.get_launch_settings()
        self._xmx_field = ft.TextField(
            label="最大内存 (Xmx)",
            hint_text="例如: 2G, 4G",
            value=launch_settings.xmx,
            width=180,
        )
        self._xms_field = ft.TextField(
            label="初始内存 (Xms)",
            hint_text="例如: 512M, 1G",
            value=launch_settings.xms,
            width=180,
        )
        self._jvm_args_field = ft.TextField(
            label="JVM 参数",
            hint_text="例如: -XX:+UseG1GC",
            value=launch_settings.jvm_args,
            width=400,
        )
        self._game_args_field = ft.TextField(
            label="游戏参数",
            hint_text="例如: --fullscreen",
            value=launch_settings.game_args,
            width=400,
        )
        self._auto_connect_ip = ft.TextField(
            label="服务器 IP",
            hint_text="例如: play.example.com",
            value=launch_settings.auto_connect_ip,
            width=250,
        )
        self._auto_connect_port = ft.TextField(
            label="端口",
            hint_text="默认: 25565",
            value=str(launch_settings.auto_connect_port),
            width=100,
        )
        self._close_launcher_cb = ft.Checkbox(
            label="启动后关闭启动器",
            value=launch_settings.close_launcher,
        )

        self._java_scan_btn = ft.FilledButton(
            "扫描Java",
            icon=ft.Icons.SEARCH,
            on_click=lambda e: self.page.run_task(self._scan_and_update_java),
        )
        self._java_import_btn = ft.FilledButton(
            "手动导入",
            icon=ft.Icons.ADD,
            on_click=self._import_java,
        )
        self._java_scan_status = ft.Text(
            "",
            size=12,
            color=ft.Colors.GREY,
        )
        self._java_scan_indicator = ft.ProgressBar(visible=False, width=400)

        launch_content = ft.Container(
            content=ft.Column(
                [
                    ft.Card(
                        content=ft.Container(
                            padding=15,
                            content=ft.Column(
                                [
                                    ft.Text(
                                        "Java 设置", size=16, weight=ft.FontWeight.BOLD
                                    ),
                                    ft.Row(
                                        [
                                            self.java_dd,
                                            self._java_scan_btn,
                                            self._java_import_btn,
                                        ],
                                        spacing=10,
                                    ),
                                    self._java_scan_indicator,
                                    self._java_scan_status,
                                ],
                                spacing=10,
                            ),
                        )
                    ),
                    ft.Card(
                        content=ft.Container(
                            padding=15,
                            content=ft.Column(
                                [
                                    ft.Text(
                                        "内存设置", size=16, weight=ft.FontWeight.BOLD
                                    ),
                                    ft.Row(
                                        [self._xmx_field, self._xms_field], spacing=10
                                    ),
                                ],
                                spacing=10,
                            ),
                        )
                    ),
                    ft.Card(
                        content=ft.Container(
                            padding=15,
                            content=ft.Column(
                                [
                                    ft.Text(
                                        "JVM 参数", size=16, weight=ft.FontWeight.BOLD
                                    ),
                                    self._jvm_args_field,
                                    ft.Text(
                                        "游戏参数", size=16, weight=ft.FontWeight.BOLD
                                    ),
                                    self._game_args_field,
                                ],
                                spacing=10,
                            ),
                        )
                    ),
                    ft.Card(
                        content=ft.Container(
                            padding=15,
                            content=ft.Column(
                                [
                                    ft.Text(
                                        "自动连接服务器",
                                        size=16,
                                        weight=ft.FontWeight.BOLD,
                                    ),
                                    ft.Row(
                                        [
                                            self._auto_connect_ip,
                                            self._auto_connect_port,
                                        ],
                                        spacing=10,
                                    ),
                                ],
                                spacing=10,
                            ),
                        )
                    ),
                    ft.Card(
                        content=ft.Container(
                            padding=15,
                            content=ft.Column(
                                [
                                    ft.Text(
                                        "启动器选项", size=16, weight=ft.FontWeight.BOLD
                                    ),
                                    self._close_launcher_cb,
                                ],
                                spacing=10,
                            ),
                        )
                    ),
                    ft.FilledButton(
                        "保存设置",
                        icon=ft.Icons.SAVE,
                        on_click=self._save_launch_settings,
                    ),
                ],
                scroll=ft.ScrollMode.AUTO,
                spacing=10,
            ),
            padding=10,
            expand=True,
        )

        content_area = ft.Container(expand=True, content=display_content)

        def update_tab_buttons():
            for i, btn in enumerate(tab_buttons.controls):
                btn.style = ft.ButtonStyle(
                    bgcolor=ft.Colors.BLUE_100 if i == current_tab[0] else None
                )

        def switch_tab(index):
            current_tab[0] = index
            if index == 0:
                content_area.content = display_content
            elif index == 1:
                content_area.content = data_content
            elif index == 2:
                content_area.content = download_content
            else:
                content_area.content = launch_content
            update_tab_buttons()
            self.page.update()

        tab_buttons = ft.Row(
            [
                ft.TextButton(
                    "显示",
                    icon=ft.Icons.STYLE,
                    style=ft.ButtonStyle(bgcolor=ft.Colors.BLUE_100),
                    on_click=lambda e: switch_tab(0),
                ),
                ft.TextButton(
                    "游戏",
                    icon=ft.Icons.FOLDER,
                    style=ft.ButtonStyle(bgcolor=None),
                    on_click=lambda e: switch_tab(1),
                ),
                ft.TextButton(
                    "下载",
                    icon=ft.Icons.DOWNLOAD,
                    style=ft.ButtonStyle(bgcolor=None),
                    on_click=lambda e: switch_tab(2),
                ),
                ft.TextButton(
                    "启动",
                    icon=ft.Icons.PLAY_ARROW,
                    style=ft.ButtonStyle(bgcolor=None),
                    on_click=lambda e: switch_tab(3),
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

    def _save_launch_settings(self, e):
        from app.services.config_service import LaunchSettings

        old_settings = self.cfg.get_launch_settings()
        settings = LaunchSettings(
            java_path=old_settings.java_path,
            xmx=self._xmx_field.value or "2G",
            xms=self._xms_field.value or "512M",
            jvm_args=self._jvm_args_field.value or "",
            game_args=self._game_args_field.value or "",
            width=old_settings.width,
            height=old_settings.height,
            auto_connect_server="",
            auto_connect_ip=self._auto_connect_ip.value or "",
            auto_connect_port=int(self._auto_connect_port.value or "25565"),
            resolution_width=old_settings.resolution_width,
            resolution_height=old_settings.resolution_height,
            java_auto_select=old_settings.java_auto_select,
            java_version=old_settings.java_version,
            enable_native_dll=old_settings.enable_native_dll,
            enable_shortcut=old_settings.enable_shortcut,
            enable_game_overlay=old_settings.enable_game_overlay,
            enable_discord_rich_presence=old_settings.enable_discord_rich_presence,
            wrapper_path=old_settings.wrapper_path,
            wrapper_enabled=old_settings.wrapper_enabled,
            env_vars=old_settings.env_vars,
            pre_launch_command=old_settings.pre_launch_command,
            post_exit_command=old_settings.post_exit_command,
            priority=old_settings.priority,
            close_launcher=self._close_launcher_cb.value or False,
            auto_enter_server=bool(self._auto_connect_ip.value),
            server_ip=self._auto_connect_ip.value or "",
            server_port=int(self._auto_connect_port.value or "25565"),
        )
        self.cfg.save_launch_settings(settings)
        self.page.show_dialog(ft.SnackBar(ft.Text("启动设置已保存")))
        self.page.update()
