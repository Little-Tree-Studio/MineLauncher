from __future__ import annotations
import threading
import flet as ft
from pathlib import Path
import orjson
from app.services.config_service import ConfigService
from app.services.i18n_service import I18nService
from app.services.utils_service import UtilsService

ASSET_DIR = Path(__file__).parent.parent.parent / "assets"

class HomePage:
    def __init__(self, page: ft.Page):
        self.cfg = ConfigService()
        self.lang = I18nService(self.cfg.load()["Language"])
        self.page = page

    # ---------- 版本列表异步加载 ----------
    def _load_versions_async(self, list_view: ft.ListView):
        def _task():
            versions_card = []
            root = Path(r"E:/###游戏/Minecraft/.minecraft/versions")
            for folder in UtilsService.list_dirs(root):
                ver = "未知版本"
                tags = []
                try:
                    file_path = root / folder / f"{folder}.json"
                    data = orjson.loads(file_path.read_bytes())
                    ver = data.get("clientVersion", folder)
                    raw = str(data).lower()
                    if "fabric" in raw:
                        tags.append("Fabric")
                    if "neoforge" in raw:
                        tags.append("NeoForge")
                except Exception:
                    pass
                txt = f"{folder} - {ver}" + (f" ({','.join(tags)})" if tags else "")
                versions_card.append(
                    ft.Card(
                        content=ft.Container(ft.Text(txt), padding=10),
                        elevation=2,
                    )
                )
            list_view.controls.extend(versions_card)
            list_view.update()

        threading.Thread(target=_task, daemon=True).start()

    # ---------- 主页整体 ----------
    def build(self) -> ft.View:
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
            self.content_area.controls.clear()
            if index == 0:
                self.content_area.controls.append(self._build_home_content())
            elif index == 1:
                lv = ft.ListView(expand=True, spacing=5)
                self.content_area.controls.append(lv)
                self._load_versions_async(lv)
            elif index == 2:
                self.content_area.controls.append(self._build_server_content())
            self.content_area.update()
            

        return ft.View(
            "/",
            [
                ft.AppBar(
                    leading=ft.Image(ASSET_DIR / "image" / "icon.png"),
                    title=ft.Text("MineLauncher"),
                    bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
                    actions=[
                        ft.TextButton(
                            self.lang.current.get("home", {}).get("top", {}).get("resource_center", "资源中心"),
                            icon=ft.Icons.SHOPPING_BASKET,
                            on_click=lambda _: self.page.go("/resources"),
                        ),
                        ft.TextButton(
                            self.lang.current.get("home", {}).get("top", {}).get("download_management", "下载管理"),
                            icon=ft.Icons.DOWNLOAD,
                            on_click=lambda _: self.page.go("/download_manager"),
                        ),
                        ft.VerticalDivider(),
                        ft.TextButton(
                            self.lang.current.get("home", {}).get("top", {}).get("settings", "设置"),
                            icon=ft.Icons.SETTINGS,
                            on_click=lambda _: self.page.go("/settings"),
                        ),
                        ft.TextButton(
                            self.lang.current.get("home", {}).get("top", {}).get("about", "关于"),
                            icon=ft.Icons.INFO,
                            on_click=lambda _: self.page.go("/about"),
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
                                    label=self.lang.current.get("home", {}).get("title", "首页"),
                                ),
                                ft.NavigationRailDestination(
                                    icon=ft.Icons.VERTICAL_SPLIT_OUTLINED,
                                    selected_icon=ft.Icons.VERTICAL_SPLIT,
                                    label=self.lang.current.get("home", {}).get("version_list", "版本列表"),
                                ),
                                ft.NavigationRailDestination(
                                    icon=ft.Icons.ASSESSMENT_OUTLINED,
                                    selected_icon=ft.Icons.ASSESSMENT,
                                    label=self.lang.current.get("home", {}).get("Server_monitor", "服务器"),
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
                                                ft.Placeholder(fallback_height=20, fallback_width=20),
                                                ft.Text("zs_xiaoshu"),
                                            ]
                                        ),
                                        ft.Button(
                                            icon=ft.Icons.PEOPLE,
                                            text=self.lang.current.get("home", {}).get("account_settings", "账户设置"),
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
                                                ft.Text("新闻", size=20, weight=ft.FontWeight.BOLD),
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
                                ft.ElevatedButton(
                                    self.lang.current.get("test", {}).get("test", "测试"),
                                    ft.Icons.SCIENCE,
                                    on_click=lambda _: print("test clicked"),
                                ),
                                ft.Card(
                                    content=ft.Container(
                                        content=ft.Column(
                                            [
                                                ft.Row(
                                                    [
                                                        ft.Image(ASSET_DIR / "image" / "grass.png", width=30, height=30),
                                                        ft.Text("MineCraft 1.20.1"),
                                                    ]
                                                ),
                                                ft.Row(
                                                    [
                                                        ft.TextButton(
                                                            self.lang.current.get("home", {})
                                                            .get("game", {})
                                                            .get("config", "配置"),
                                                            icon=ft.Icons.SETTINGS,
                                                            style=ft.ButtonStyle(
                                                                shape=ft.RoundedRectangleBorder(radius=5)
                                                            ),
                                                        ),
                                                        ft.FilledButton(
                                                            self.lang.current.get("home", {})
                                                            .get("game", {})
                                                            .get("launch", "启动"),
                                                            icon=ft.Icons.PLAY_ARROW,
                                                            style=ft.ButtonStyle(
                                                                shape=ft.RoundedRectangleBorder(radius=5)
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
                            if suffix in [".txt", ".log", ".json", ".md", ".yaml", ".yml", ".py", ".cfg", ""]:
                                content = entry.read_text(encoding="utf-8", errors="ignore")
                                def close_dialog(e):
                                    dlg.open = False
                                    self.page.update()
                                dlg = ft.AlertDialog(
                                    title=ft.Text(f"预览: {entry.name}"),
                                    content=ft.Text(content if content else "(空文件)", selectable=True, width=500, height=300, scroll=ft.ScrollMode.AUTO),
                                    actions=[ft.TextButton("关闭", on_click=close_dialog)],
                                )
                                self.page.show_dialog(dlg)
                                dlg.open = True
                                self.page.update()
                            else:
                                self.page.snack_bar = ft.SnackBar(ft.Text("暂不支持该类型文件预览"))
                                self.page.snack_bar.open = True
                                self.page.update()
                        else:
                            self.page.snack_bar = ft.SnackBar(ft.Text("只能预览文件，不能预览文件夹"))
                            self.page.snack_bar.open = True
                            self.page.update()
                    except Exception as ex:
                        self.page.snack_bar = ft.SnackBar(ft.Text(f"预览失败: {ex}"))
                        self.page.snack_bar.open = True
                        self.page.update()
                def delete_file(entry):
                    try:
                        entry.unlink() if entry.is_file() else entry.rmdir()
                        self.page.snack_bar = ft.SnackBar(ft.Text(f"已删除: {entry.name}"))
                        self.page.snack_bar.open = True
                        show_file_manage()
                    except Exception as ex:
                        self.page.snack_bar = ft.SnackBar(ft.Text(f"删除失败: {ex}"))
                        self.page.snack_bar.open = True
                        self.page.update()
                def rename_file(entry):
                    def on_submit(e):
                        new_name = e.control.value.strip()
                        if new_name:
                            new_path = entry.parent / new_name
                            try:
                                entry.rename(new_path)
                                self.page.snack_bar = ft.SnackBar(ft.Text(f"已重命名为: {new_name}"))
                                self.page.snack_bar.open = True
                                show_file_manage()
                            except Exception as ex:
                                self.page.snack_bar = ft.SnackBar(ft.Text(f"重命名失败: {ex}"))
                                self.page.snack_bar.open = True
                                self.page.update()
                    self._server_content_area.controls.append(
                        ft.Row([
                            ft.Text(f"重命名 {entry.name} 为:"),
                            ft.TextField(on_submit=on_submit, autofocus=True),
                        ])
                    )
                    self._server_content_area.update()
                def upload_file(_):
                    self.page.snack_bar = ft.SnackBar(ft.Text("上传功能待实现（可集成文件选择与保存）"))
                    self.page.snack_bar.open = True
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
                            ft.Icon(ft.Icons.FOLDER if entry.is_dir() else ft.Icons.DESCRIPTION, color=ft.Colors.AMBER if entry.is_dir() else ft.Colors.BLUE_GREY),
                            ft.Text(str(entry.name)),
                            ft.IconButton(icon=ft.Icons.OPEN_IN_NEW, tooltip="打开", on_click=open_action),
                            ft.IconButton(icon=ft.Icons.DELETE, tooltip="删除", on_click=lambda e, ent=entry: delete_file(ent)),
                            ft.IconButton(icon=ft.Icons.DRIVE_FILE_RENAME_OUTLINE, tooltip="重命名", on_click=lambda e, ent=entry: rename_file(ent)),
                        ]
                        items.append(ft.Row(row_items, alignment=ft.MainAxisAlignment.SPACE_BETWEEN))
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
                        upload_btn = ft.FilledButton("上传文件", icon=ft.Icons.UPLOAD_FILE, on_click=upload_file)
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
                            back_btn = ft.IconButton(icon=ft.Icons.ARROW_BACK, tooltip="返回上级", on_click=lambda _: show_file_manage(target_dir.parent))
                        title_row = [ft.Text(f"{target_dir} 内容", size=16, weight=ft.FontWeight.BOLD), refresh_btn, upload_btn, clear_btn]
                        if back_btn:
                            title_row.insert(1, back_btn)
                        self._server_content_area.controls.append(
                            ft.Row(title_row, alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
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
                upload_btn = ft.FilledButton("上传文件", icon=ft.Icons.UPLOAD_FILE, on_click=upload_file)
                # 刷新按钮
                refresh_btn = ft.IconButton(
                    icon=ft.Icons.REFRESH,
                    tooltip="刷新",
                    on_click=show_file_manage,
                )
                self._server_content_area.controls.append(
                    ft.Row([
                        ft.Text("server 文件夹内容", size=16, weight=ft.FontWeight.BOLD),
                        refresh_btn,
                        upload_btn,
                    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
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
                ft.TextButton("下载核心", icon=ft.Icons.DOWNLOAD, on_click=show_core_download),
                ft.TextButton("玩家管理", icon=ft.Icons.PEOPLE, on_click=show_player_manage),
                ft.TextButton("插件管理", icon=ft.Icons.EXTENSION, on_click=show_plugin_manage),
                ft.TextButton("文件管理", icon=ft.Icons.FOLDER, on_click=show_file_manage),
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