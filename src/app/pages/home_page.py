from __future__ import annotations
import os
import asyncio
import shutil
import subprocess
import sys
import flet as ft
from pathlib import Path
import orjson
from app.services.config_service import ConfigService
from app.services.i18n_service import I18nService
from app.services.utils_service import UtilsService
from app.services.logger_service import LoggerService

ASSET_DIR = Path(__file__).parent.parent.parent / "assets"


class HomePage:
    def __init__(self, page: ft.Page):
        self.cfg = ConfigService()
        self.lang = I18nService(self.cfg.load()["Language"])
        self.page = page
        self.logger = LoggerService().logger
        self._versions_root: Path | None = None
        self._versions_list_view: ft.ListView | None = None
        self._versions_root_text: ft.Text | None = None
        self._versions_source_dd: ft.Dropdown | None = None
        self._versions_refresh_ring: ft.ProgressRing | None = None
        self._versions_refresh_btn: ft.OutlinedButton | None = None
        self._version_dir_entries: list[dict[str, str]] = []
        self._selected_versions_root: str | None = None

    async def _navigate_to(self, route: str):
        """异步导航到指定路由"""
        await self.page.push_route(route)

    def _create_navigate_handler(self, route: str):
        """创建导航事件处理器 - 正确处理异步调用"""

        def handler(e):
            async def do_navigate():
                await self.page.push_route(route)

            self.page.run_task(do_navigate)

        return handler

    # ---------- 版本列表与文件夹管理 ----------
    def _resolve_default_versions_root(self) -> Path:
        """解析默认版本目录路径，优先使用标准目录并回退到常见目录。"""
        root = Path.home() / ".minecraft" / "versions"
        if not root.exists():
            alt_paths = [
                Path(r"E:/###游戏/Minecraft/.minecraft/versions"),
                Path(
                    r"C:/Users/%s/AppData/Roaming/.minecraft/versions"
                    % os.getenv("USERNAME", "")
                ),
                Path(r"D:/Minecraft/.minecraft/versions"),
            ]
            for alt_path in alt_paths:
                if alt_path.exists():
                    root = alt_path
                    break
        return root

    def _load_version_dir_entries(self) -> list[dict[str, str]]:
        cfg = self.cfg.load()
        raw_entries = cfg.get("VersionDirectoryEntries", [])
        entries: list[dict[str, str]] = []
        seen_paths: set[str] = set()

        if isinstance(raw_entries, list):
            for item in raw_entries:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name", "")).strip()
                path = str(item.get("path", "")).strip()
                if not path:
                    continue
                norm_path = str(Path(path).expanduser())
                key = norm_path.lower()
                if key in seen_paths:
                    continue
                seen_paths.add(key)
                entries.append(
                    {
                        "name": name or Path(norm_path).name or norm_path,
                        "path": norm_path,
                    }
                )

        if not entries:
            default_root = self._resolve_default_versions_root()
            entries = [
                {
                    "name": "默认版本目录",
                    "path": str(default_root),
                }
            ]

        selected = cfg.get("SelectedVersionDirectoryPath")
        selected = str(selected).strip() if selected else ""
        if selected and any(item["path"] == selected for item in entries):
            self._selected_versions_root = selected

        return entries

    def _save_version_dir_entries(self, entries: list[dict[str, str]]):
        cfg = self.cfg.load()
        self.cfg.save(
            {
                **cfg,
                "VersionDirectoryEntries": entries,
                "SelectedVersionDirectoryPath": self._selected_versions_root,
            }
        )

    def _rebuild_versions_source_options(self):
        if self._versions_source_dd is None:
            return
        self._versions_source_dd.options = [
            ft.dropdown.Option(
                key=item["path"],
                text=item["name"],
            )
            for item in self._version_dir_entries
        ]
        if (
            self._selected_versions_root
            and self._selected_versions_root
            not in [item["path"] for item in self._version_dir_entries]
        ):
            self._selected_versions_root = None
        if self._selected_versions_root is None and self._version_dir_entries:
            self._selected_versions_root = self._version_dir_entries[0]["path"]
        self._versions_source_dd.value = self._selected_versions_root

    def _set_versions_refreshing(self, refreshing: bool):
        if self._versions_refresh_ring is not None:
            self._versions_refresh_ring.visible = refreshing
        if self._versions_refresh_btn is not None:
            self._versions_refresh_btn.disabled = refreshing
            self._versions_refresh_btn.text = "刷新中..." if refreshing else "刷新"

    def _show_message(self, text: str):
        self.page.show_dialog(ft.SnackBar(ft.Text(text)))
        self.page.update()

    def _open_version_directory_manage_page(self):
        async def do_nav():
            await self.page.push_route("/version_dirs")

        self.page.run_task(do_nav)

    def _rename_version_folder(self, old_name: str, new_name: str):
        root = self._versions_root or self._resolve_default_versions_root()
        src = root / old_name
        dst = root / new_name
        if not src.exists():
            raise FileNotFoundError(f"未找到版本目录: {old_name}")
        if dst.exists():
            raise FileExistsError(f"目标文件夹已存在: {new_name}")
        src.rename(dst)

    def _delete_version_folder(self, folder_name: str):
        root = self._versions_root or self._resolve_default_versions_root()
        target = root / folder_name
        if not target.exists():
            raise FileNotFoundError(f"未找到版本目录: {folder_name}")
        shutil.rmtree(target)

    def _open_version_folder(self, folder_name: str):
        root = self._versions_root or self._resolve_default_versions_root()
        target = root / folder_name
        if not target.exists():
            self._show_message(f"目录不存在: {folder_name}")
            return
        try:
            if os.name == "nt":
                os.startfile(target)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.run(["open", str(target)], check=False)
            else:
                subprocess.run(["xdg-open", str(target)], check=False)
        except Exception as ex:
            self.logger.error(f"Open version folder failed: {ex}")
            self._show_message(f"打开目录失败: {ex}")

    def _refresh_versions(self):
        if self._versions_list_view is None or not self._selected_versions_root:
            return

        async def do_reload():
            await self._load_versions_async(
                self._versions_list_view,
                Path(self._selected_versions_root),
            )

        self.page.run_task(do_reload)

    def _show_rename_folder_dialog(self, old_name: str):
        name_field = ft.TextField(label="新名称", value=old_name, autofocus=True)

        def on_cancel(_):
            self.page.pop_dialog()

        def on_confirm(_):
            new_name = (name_field.value or "").strip()
            if not new_name:
                self._show_message("请输入新名称")
                return
            if new_name == old_name:
                self.page.pop_dialog()
                return
            self.page.pop_dialog()

            async def do_rename():
                try:
                    await asyncio.to_thread(
                        self._rename_version_folder, old_name, new_name
                    )
                    self._show_message(f"已重命名: {old_name} -> {new_name}")
                    self._refresh_versions()
                except Exception as ex:
                    self.logger.error(f"Rename version folder failed: {ex}")
                    self._show_message(f"重命名失败: {ex}")

            self.page.run_task(do_rename)

        self.page.show_dialog(
            ft.AlertDialog(
                modal=True,
                title=ft.Text(f"重命名文件夹: {old_name}"),
                content=name_field,
                actions=[
                    ft.TextButton("取消", on_click=on_cancel),
                    ft.FilledButton("保存", on_click=on_confirm),
                ],
            )
        )
        self.page.update()

    def _show_delete_folder_dialog(self, folder_name: str):
        def on_cancel(_):
            self.page.pop_dialog()

        def on_confirm(_):
            self.page.pop_dialog()

            async def do_delete():
                try:
                    await asyncio.to_thread(self._delete_version_folder, folder_name)
                    self._show_message(f"已删除版本文件夹: {folder_name}")
                    self._refresh_versions()
                except Exception as ex:
                    self.logger.error(f"Delete version folder failed: {ex}")
                    self._show_message(f"删除失败: {ex}")

            self.page.run_task(do_delete)

        self.page.show_dialog(
            ft.AlertDialog(
                modal=True,
                title=ft.Text("确认删除"),
                content=ft.Text(
                    f"将永久删除文件夹 {folder_name} 及其全部内容，是否继续？"
                ),
                actions=[
                    ft.TextButton("取消", on_click=on_cancel),
                    ft.FilledButton("删除", on_click=on_confirm),
                ],
            )
        )
        self.page.update()

    def _build_version_card(
        self, folder: str, version: str, tags: list[str]
    ) -> ft.Control:
        subtitle = f"{folder} - {version}" + (f" ({','.join(tags)})" if tags else "")
        return ft.Card(
            content=ft.Container(
                ft.Row(
                    [
                        ft.Text(subtitle, expand=True),
                        ft.Row(
                            [
                                ft.IconButton(
                                    icon=ft.Icons.FOLDER_OPEN,
                                    tooltip="打开目录",
                                    on_click=lambda _,
                                    n=folder: self._open_version_folder(n),
                                ),
                                ft.IconButton(
                                    icon=ft.Icons.DRIVE_FILE_RENAME_OUTLINE,
                                    tooltip="重命名",
                                    on_click=lambda _,
                                    n=folder: self._show_rename_folder_dialog(n),
                                ),
                                ft.IconButton(
                                    icon=ft.Icons.DELETE,
                                    tooltip="删除",
                                    on_click=lambda _,
                                    n=folder: self._show_delete_folder_dialog(n),
                                ),
                            ],
                            spacing=0,
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                padding=10,
            ),
            elevation=2,
        )

    def _load_versions_data(self, root: Path) -> tuple[Path, list[dict], str | None]:
        """在线程池中读取版本信息，UI 控件在主线程中构建。"""
        versions: list[dict] = []

        self.logger.info(f"Checking for versions in: {root}")
        if not root.exists():
            self.logger.warning(f"Versions directory does not exist: {root}")
            return root, [], f"版本目录不存在: {root}"

        try:
            folders = UtilsService.list_dirs(root)
            self.logger.info(f"Found version folders: {folders}")
        except Exception as e:
            print(f"Failed to list directories: {e}")
            self.logger.error(f"Failed to list directories: {e}")
            folders = []

        for folder in folders:
            ver = "未知版本"
            tags = []
            try:
                file_path = root / folder / f"{folder}.json"
                if file_path.exists():
                    data = orjson.loads(file_path.read_bytes())
                    ver = data.get("clientVersion", folder)
                    raw = str(data).lower()
                    if "fabric" in raw:
                        tags.append("Fabric")
                    if "neoforge" in raw:
                        tags.append("NeoForge")
                else:
                    self.logger.warning(f"Version json not found: {file_path}")
            except Exception as e:
                self.logger.error(f"Error reading version {folder}: {e}")
            versions.append({"folder": folder, "version": ver, "tags": tags})

        print(f"Prepared {len(versions)} versions")
        self.logger.info(f"Prepared {len(versions)} versions")
        return root, versions, None

    async def _load_versions_async(self, list_view: ft.ListView, root: Path):
        print("_load_versions_async started")
        try:
            self._set_versions_refreshing(True)
            root, versions, error_text = await asyncio.to_thread(
                self._load_versions_data,
                root,
            )
            self._versions_root = root
            if self._versions_root_text is not None:
                self._versions_root_text.value = f"版本目录: {root}"

            list_view.controls.clear()
            if error_text:
                list_view.controls.append(
                    ft.Card(
                        content=ft.Container(
                            ft.Text(error_text, color=ft.Colors.RED),
                            padding=10,
                        ),
                        elevation=2,
                    )
                )
            elif versions:
                for item in versions:
                    list_view.controls.append(
                        self._build_version_card(
                            item["folder"],
                            item["version"],
                            item["tags"],
                        )
                    )
            else:
                list_view.controls.append(
                    ft.Card(
                        content=ft.Container(
                            ft.Text("未发现本地版本", color=ft.Colors.GREY_600),
                            padding=10,
                        ),
                        elevation=1,
                    )
                )
            self.page.update()
            print("Version list updated on UI")
            self.logger.info("Version list updated on UI")
        except Exception as e:
            print(f"Error in _load_versions_async: {e}")
            self.logger.error(f"Error in _load_versions_async: {e}")
            import traceback

            print(traceback.format_exc())
            self.logger.error(traceback.format_exc())
        finally:
            self._set_versions_refreshing(False)
            self.page.update()

    # ---------- 主页整体 ----------
    def build(self) -> ft.View:
        print("HomePage.build() 被调用")
        # 右侧内容区
        self.content_area = ft.Column(
            [
                self._build_home_content()  # 默认首页
            ],
            expand=True,
        )

        # 导航栏切换
        def on_nav_change(e):
            index = e.control.selected_index
            print(f"Navigation changed to index: {index}")
            self.content_area.controls.clear()
            if index == 0:
                self.content_area.controls.append(self._build_home_content())
            elif index == 1:
                self._version_dir_entries = self._load_version_dir_entries()
                if not self._selected_versions_root and self._version_dir_entries:
                    self._selected_versions_root = self._version_dir_entries[0]["path"]

                def on_source_change(e: ft.ControlEvent):
                    self._selected_versions_root = e.control.value
                    self._save_version_dir_entries(self._version_dir_entries)
                    self._refresh_versions()

                self._versions_root_text = ft.Text("版本目录: 加载中...")
                self._versions_refresh_ring = ft.ProgressRing(
                    width=16,
                    height=16,
                    visible=False,
                )
                self._versions_refresh_btn = ft.OutlinedButton(
                    "刷新",
                    icon=ft.Icons.REFRESH,
                    on_click=lambda _: self._refresh_versions(),
                )
                self._versions_source_dd = ft.Dropdown(
                    label="版本目录",
                    width=520,
                    on_select=on_source_change,
                )
                self._rebuild_versions_source_options()

                toolbar = ft.Row(
                    [
                        ft.Column(
                            [
                                self._versions_source_dd,
                                self._versions_root_text,
                            ],
                            spacing=6,
                        ),
                        ft.Row(
                            [
                                self._versions_refresh_ring,
                                self._versions_refresh_btn,
                                ft.OutlinedButton(
                                    "目录管理",
                                    icon=ft.Icons.FOLDER_OPEN,
                                    on_click=lambda _: self._open_version_directory_manage_page(),
                                ),
                            ]
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                )
                # 将加载态放在同一个列表中，加载完成后整体替换
                self._versions_list_view = ft.ListView(
                    expand=True,
                    spacing=5,
                    controls=[
                        ft.Row(
                            [
                                ft.ProgressRing(width=18, height=18),
                                ft.Text("正在加载版本列表..."),
                            ],
                            spacing=10,
                        )
                    ],
                )
                self.content_area.controls.append(
                    ft.Column([toolbar, self._versions_list_view], expand=True)
                )
                self.content_area.update()
                print("Starting version list load...")

                async def do_load_versions():
                    selected_root = self._selected_versions_root
                    if not selected_root:
                        return
                    await self._load_versions_async(
                        self._versions_list_view,
                        Path(selected_root),
                    )

                self.page.run_task(do_load_versions)
            elif index == 2:
                self.content_area.controls.append(self._build_server_content())
            self.content_area.update()

        view = ft.View(
            route="/",
            controls=[
                ft.AppBar(
                    leading=ft.Image(str(ASSET_DIR / "image" / "icon.png")),
                    title=ft.Text("MineLauncher"),
                    bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
                    actions=[
                        ft.TextButton(
                            self.lang.current.get("home", {})
                            .get("top", {})
                            .get("resource_center", "资源中心"),
                            icon=ft.Icons.SHOPPING_BASKET,
                            on_click=self._create_navigate_handler("/resources"),
                        ),
                        ft.TextButton(
                            self.lang.current.get("home", {})
                            .get("top", {})
                            .get("download_management", "下载管理"),
                            icon=ft.Icons.DOWNLOAD,
                            on_click=self._create_navigate_handler("/download_manager"),
                        ),
                        ft.VerticalDivider(),
                        ft.TextButton(
                            self.lang.current.get("home", {})
                            .get("top", {})
                            .get("settings", "设置"),
                            icon=ft.Icons.SETTINGS,
                            on_click=self._create_navigate_handler("/settings"),
                        ),
                        ft.TextButton(
                            self.lang.current.get("home", {})
                            .get("top", {})
                            .get("about", "关于"),
                            icon=ft.Icons.INFO,
                            on_click=self._create_navigate_handler("/about"),
                        ),
                    ],
                ),
                ft.Row(
                    [
                        ft.NavigationRail(
                            selected_index=0,
                            label_type=ft.NavigationRailLabelType.ALL,
                            min_width=80,
                            destinations=[
                                ft.NavigationRailDestination(
                                    icon=ft.Icons.HOME_OUTLINED,
                                    selected_icon=ft.Icons.HOME,
                                    label=self.lang.current.get("home", {}).get(
                                        "title", "首页"
                                    ),
                                ),
                                ft.NavigationRailDestination(
                                    icon=ft.Icons.VERTICAL_SPLIT_OUTLINED,
                                    selected_icon=ft.Icons.VERTICAL_SPLIT,
                                    label=self.lang.current.get("home", {}).get(
                                        "version_list", "版本列表"
                                    ),
                                ),
                                ft.NavigationRailDestination(
                                    icon=ft.Icons.ASSESSMENT_OUTLINED,
                                    selected_icon=ft.Icons.ASSESSMENT,
                                    label=self.lang.current.get("home", {}).get(
                                        "Server_monitor", "服务器"
                                    ),
                                ),
                            ],
                            on_change=on_nav_change,
                        ),
                        ft.VerticalDivider(width=1),
                        self.content_area,
                    ],
                    expand=True,
                ),
            ],
        )
        print(f"HomePage.build() 返回的视图控件数量: {len(view.controls)}")
        return view

    # ---------- 原来的首页内容 ----------
    def _build_home_content(self) -> ft.Column:
        return ft.Column(
            [
                ft.Column(
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    controls=[
                        ft.Row(
                            [
                                ft.Text(value="MineLauncher", size=45),
                                ft.Column(
                                    controls=[
                                        ft.Row(
                                            controls=[
                                                ft.Placeholder(
                                                    fallback_height=20,
                                                    fallback_width=20,
                                                ),
                                                ft.Text("zs_xiaoshu"),
                                            ]
                                        ),
                                        ft.Button(
                                            icon=ft.Icons.PEOPLE,
                                            content=ft.Text(
                                                self.lang.current.get("home", {}).get(
                                                    "account_settings", "账户设置"
                                                )
                                            ),
                                        ),
                                    ],
                                    horizontal_alignment=ft.CrossAxisAlignment.END,
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        ft.Column(
                            alignment=ft.MainAxisAlignment.CENTER,
                            controls=[
                                ft.Card(
                                    content=ft.Container(
                                        content=ft.Column(
                                            controls=[
                                                ft.Text(
                                                    "新闻",
                                                    size=20,
                                                    weight=ft.FontWeight.BOLD,
                                                ),
                                                ft.Text("标题"),
                                            ]
                                        ),
                                        padding=10,
                                        width=300,
                                        height=100,
                                    )
                                )
                            ],
                            scroll=ft.ScrollMode.AUTO,
                            expand=True,
                        ),
                        ft.Row(
                            controls=[
                                ft.Button(
                                    self.lang.current.get("test", {}).get(
                                        "test", "测试"
                                    ),
                                    ft.Icons.SCIENCE,
                                    on_click=lambda _: print("test clicked"),
                                ),
                                ft.Card(
                                    content=ft.Container(
                                        content=ft.Column(
                                            [
                                                ft.Row(
                                                    [
                                                        ft.Image(
                                                            str(
                                                                ASSET_DIR
                                                                / "image"
                                                                / "grass.png"
                                                            ),
                                                            width=30,
                                                            height=30,
                                                        ),
                                                        ft.Text("MineCraft 1.20.1"),
                                                    ]
                                                ),
                                                ft.Row(
                                                    [
                                                        ft.TextButton(
                                                            self.lang.current.get(
                                                                "home", {}
                                                            )
                                                            .get("game", {})
                                                            .get("config", "配置"),
                                                            icon=ft.Icons.SETTINGS,
                                                            style=ft.ButtonStyle(
                                                                shape=ft.RoundedRectangleBorder(
                                                                    radius=5
                                                                )
                                                            ),
                                                        ),
                                                        ft.FilledButton(
                                                            self.lang.current.get(
                                                                "home", {}
                                                            )
                                                            .get("game", {})
                                                            .get("launch", "启动"),
                                                            icon=ft.Icons.PLAY_ARROW,
                                                            style=ft.ButtonStyle(
                                                                shape=ft.RoundedRectangleBorder(
                                                                    radius=5
                                                                )
                                                            ),
                                                        ),
                                                    ],
                                                    alignment=ft.MainAxisAlignment.END,
                                                ),
                                            ]
                                        ),
                                        width=300,
                                        padding=10,
                                    ),
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            vertical_alignment=ft.CrossAxisAlignment.END,
                        ),
                    ],
                    expand=True,
                ),
            ],
            expand=True,
        )

    def _build_server_content(self):
        # 内容区控件
        self._server_content_area = ft.Column([], expand=True)

        def show_console(_):
            self._server_content_area.controls.clear()
            self._server_content_area.controls.append(
                ft.Card(
                    content=ft.Container(
                        ft.Text("这里是服务器控制台内容，可扩展为日志、命令输入等。"),
                        padding=20,
                        width=500,
                    ),
                    elevation=3,
                )
            )
            self._server_content_area.update()

        def show_core_download(_):
            self._server_content_area.controls.clear()
            self._server_content_area.controls.append(
                ft.Card(
                    content=ft.Container(
                        ft.Text("这里是核心下载区，可集成核心下载功能或列表。"),
                        padding=20,
                        width=500,
                    ),
                    elevation=3,
                )
            )
            self._server_content_area.update()

        def show_player_manage(_):
            self._server_content_area.controls.clear()
            self._server_content_area.controls.append(
                ft.Card(
                    content=ft.Container(
                        ft.Text("这里是玩家管理区，可扩展为玩家列表、操作等。"),
                        padding=20,
                        width=500,
                    ),
                    elevation=3,
                )
            )
            self._server_content_area.update()

        def show_plugin_manage(_):
            self._server_content_area.controls.clear()
            self._server_content_area.controls.append(
                ft.Card(
                    content=ft.Container(
                        ft.Text("这里是插件管理区，可扩展为插件列表、安装等。"),
                        padding=20,
                        width=500,
                    ),
                    elevation=3,
                )
            )
            self._server_content_area.update()

        def show_file_manage(_=None):
            import os

            self._server_content_area.controls.clear()
            server_dir = Path("server")
            if not server_dir.exists():
                self._server_content_area.controls.append(
                    ft.Text("server 文件夹不存在", color=ft.Colors.ERROR)
                )
            else:
                items = []

                def open_file(entry):
                    # 文件内容预览（仅文本文件，其他类型提示不支持预览）
                    try:
                        if entry.is_file():
                            # 简单判断文本文件
                            suffix = entry.suffix.lower()
                            if suffix in [
                                ".txt",
                                ".log",
                                ".json",
                                ".md",
                                ".yaml",
                                ".yml",
                                ".py",
                                ".cfg",
                                "",
                            ]:
                                content = entry.read_text(
                                    encoding="utf-8", errors="ignore"
                                )

                                def close_dialog(e):
                                    dlg.open = False
                                    self.page.update()

                                dlg = ft.AlertDialog(
                                    title=ft.Text(f"预览: {entry.name}"),
                                    content=ft.Text(
                                        content if content else "(空文件)",
                                        selectable=True,
                                        width=500,
                                        height=300,
                                        scroll=ft.ScrollMode.AUTO,
                                    ),
                                    actions=[
                                        ft.TextButton("关闭", on_click=close_dialog)
                                    ],
                                )
                                self.page.show_dialog(dlg)
                                self.page.update()
                            else:
                                self.page.show_dialog(
                                    ft.SnackBar(ft.Text("暂不支持该类型文件预览"))
                                )
                                self.page.update()
                        else:
                            self.page.show_dialog(
                                ft.SnackBar(ft.Text("只能预览文件，不能预览文件夹"))
                            )
                            self.page.update()
                    except Exception as ex:
                        self.page.show_dialog(ft.SnackBar(ft.Text(f"预览失败: {ex}")))
                        self.page.update()

                def delete_file(entry):
                    try:
                        entry.unlink() if entry.is_file() else entry.rmdir()
                        self.page.show_dialog(
                            ft.SnackBar(ft.Text(f"已删除: {entry.name}"))
                        )
                        show_file_manage()
                    except Exception as ex:
                        self.page.show_dialog(ft.SnackBar(ft.Text(f"删除失败: {ex}")))
                        self.page.update()

                def rename_file(entry):
                    def on_submit(e):
                        new_name = e.control.value.strip()
                        if new_name:
                            new_path = entry.parent / new_name
                            try:
                                entry.rename(new_path)
                                self.page.show_dialog(
                                    ft.SnackBar(ft.Text(f"已重命名为: {new_name}"))
                                )
                                show_file_manage()
                            except Exception as ex:
                                self.page.show_dialog(
                                    ft.SnackBar(ft.Text(f"重命名失败: {ex}"))
                                )
                                self.page.update()

                    self._server_content_area.controls.append(
                        ft.Row(
                            [
                                ft.Text(f"重命名 {entry.name} 为:"),
                                ft.TextField(on_submit=on_submit, autofocus=True),
                            ]
                        )
                    )
                    self._server_content_area.update()

                def upload_file(_):
                    self.page.show_dialog(
                        ft.SnackBar(ft.Text("上传功能待实现（可集成文件选择与保存）"))
                    )
                    self.page.update()

                def browse_dir(target_dir):
                    items = []
                    for entry in target_dir.iterdir():

                        def open_action(e, ent=entry):
                            if ent.is_dir():
                                # 打开文件夹，递归浏览
                                show_file_manage(ent)
                            else:
                                open_file(ent)

                        row_items = [
                            ft.Icon(
                                ft.Icons.FOLDER
                                if entry.is_dir()
                                else ft.Icons.DESCRIPTION,
                                color=ft.Colors.AMBER
                                if entry.is_dir()
                                else ft.Colors.BLUE_GREY,
                            ),
                            ft.Text(str(entry.name)),
                            ft.IconButton(
                                icon=ft.Icons.OPEN_IN_NEW,
                                tooltip="打开",
                                on_click=open_action,
                            ),
                            ft.IconButton(
                                icon=ft.Icons.DELETE,
                                tooltip="删除",
                                on_click=lambda e, ent=entry: delete_file(ent),
                            ),
                            ft.IconButton(
                                icon=ft.Icons.DRIVE_FILE_RENAME_OUTLINE,
                                tooltip="重命名",
                                on_click=lambda e, ent=entry: rename_file(ent),
                            ),
                        ]
                        items.append(
                            ft.Row(
                                row_items, alignment=ft.MainAxisAlignment.SPACE_BETWEEN
                            )
                        )
                    return items

                # 支持多级目录浏览
                def show_file_manage(target_dir=server_dir):
                    self._server_content_area.controls.clear()
                    if not target_dir.exists():
                        self._server_content_area.controls.append(
                            ft.Text(f"{target_dir} 文件夹不存在", color=ft.Colors.ERROR)
                        )
                    else:
                        items = browse_dir(target_dir)

                        # 上传按钮
                        def upload_file(_):
                            def on_file_selected(e):
                                files = e.files
                                if files:
                                    import shutil

                                    for f in files:
                                        # f.path 是本地选中文件路径
                                        dest = target_dir / Path(f.name).name
                                        try:
                                            shutil.copy(f.path, dest)
                                        except Exception:
                                            pass
                                    show_file_manage(target_dir)

                            # FilePicker 必须先添加到 page.controls
                            file_picker = ft.FilePicker(on_result=on_file_selected)
                            if file_picker not in self.page.controls:
                                self.page.controls.append(file_picker)
                                self.page.update()
                            file_picker.pick_files(allow_multiple=True)

                        upload_btn = ft.FilledButton(
                            "上传文件", icon=ft.Icons.UPLOAD_FILE, on_click=upload_file
                        )
                        # 刷新按钮
                        refresh_btn = ft.IconButton(
                            icon=ft.Icons.REFRESH,
                            tooltip="刷新",
                            on_click=lambda _: show_file_manage(target_dir),
                        )

                        # 一键清空按钮
                        def clear_server_dir(_):
                            import shutil

                            try:
                                for entry in target_dir.iterdir():
                                    if entry.is_file():
                                        entry.unlink()
                                    elif entry.is_dir():
                                        shutil.rmtree(entry)
                            except Exception:
                                pass
                            show_file_manage(target_dir)

                        clear_btn = ft.IconButton(
                            icon=ft.Icons.DELETE_SWEEP,
                            tooltip="清空全部",
                            on_click=clear_server_dir,
                        )
                        # 返回上级按钮
                        back_btn = None
                        if target_dir != server_dir:
                            back_btn = ft.IconButton(
                                icon=ft.Icons.ARROW_BACK,
                                tooltip="返回上级",
                                on_click=lambda _: show_file_manage(target_dir.parent),
                            )
                        title_row = [
                            ft.Text(
                                f"{target_dir} 内容", size=16, weight=ft.FontWeight.BOLD
                            ),
                            refresh_btn,
                            upload_btn,
                            clear_btn,
                        ]
                        if back_btn:
                            title_row.insert(1, back_btn)
                        self._server_content_area.controls.append(
                            ft.Row(
                                title_row, alignment=ft.MainAxisAlignment.SPACE_BETWEEN
                            )
                        )
                        self._server_content_area.controls.append(
                            ft.Card(
                                content=ft.Container(
                                    ft.Column(items, scroll=ft.ScrollMode.AUTO),
                                    padding=20,
                                    width=500,
                                ),
                                elevation=3,
                            )
                        )
                    self._server_content_area.update()

                # 初始显示 server 文件夹内容
                show_file_manage(server_dir)
                # 上传按钮
                upload_btn = ft.FilledButton(
                    "上传文件", icon=ft.Icons.UPLOAD_FILE, on_click=upload_file
                )
                # 刷新按钮
                refresh_btn = ft.IconButton(
                    icon=ft.Icons.REFRESH,
                    tooltip="刷新",
                    on_click=show_file_manage,
                )
                self._server_content_area.controls.append(
                    ft.Row(
                        [
                            ft.Text(
                                "server 文件夹内容", size=16, weight=ft.FontWeight.BOLD
                            ),
                            refresh_btn,
                            upload_btn,
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    )
                )
                self._server_content_area.controls.append(
                    ft.Card(
                        content=ft.Container(
                            ft.Column(items, scroll=ft.ScrollMode.AUTO),
                            padding=20,
                            width=500,
                        ),
                        elevation=3,
                    )
                )
            self._server_content_area.update()

        top_bar = ft.Row(
            [
                ft.TextButton("控制台", icon=ft.Icons.TERMINAL, on_click=show_console),
                ft.TextButton(
                    "下载核心", icon=ft.Icons.DOWNLOAD, on_click=show_core_download
                ),
                ft.TextButton(
                    "玩家管理", icon=ft.Icons.PEOPLE, on_click=show_player_manage
                ),
                ft.TextButton(
                    "插件管理", icon=ft.Icons.EXTENSION, on_click=show_plugin_manage
                ),
                ft.TextButton(
                    "文件管理", icon=ft.Icons.FOLDER, on_click=show_file_manage
                ),
            ],
            alignment=ft.MainAxisAlignment.START,
            spacing=10,
        )
        return ft.Column(
            [
                top_bar,
                self._server_content_area,
            ],
            expand=True,
        )
