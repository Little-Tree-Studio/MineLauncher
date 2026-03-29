"""核心下载页面 - 基于littledl高性能下载"""

from __future__ import annotations
import flet as ft
from pathlib import Path
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from ..services.download_service_v2 import (
    MinecraftDownloader,
    MinecraftDownloadConfig,
    DownloadSource,
    DownloadProgress,
)
from ..services.download_manager import DownloadManager, DownloadTask, TaskStatus
from ..services.config_service import ConfigService
from ..services.logger_service import LoggerService


class CoreDownloadPage:
    """核心下载页面 - 支持版本命名、目录选择、基于littledl下载"""

    def __init__(self, page: ft.Page, mc_root: str | None = None):
        self.page = page
        self.cfg = ConfigService()
        self.logger = LoggerService().logger

        # 获取版本目录列表
        self._version_dirs = self._load_version_dirs()
        self.mc_root = (
            mc_root or self._version_dirs[0]["path"]
            if self._version_dirs
            else "minecraft_versions"
        )

        Path(self.mc_root).mkdir(exist_ok=True, parents=True)

        # UI组件
        self._versions_column = ft.Column(
            spacing=6, tight=False, expand=True, scroll=ft.ScrollMode.AUTO
        )
        self._manifest = None
        self._all_types = ["snapshot", "release", "old_alpha", "old_beta"]
        self._selected_types = set(self._all_types)
        self._render_debounce_timer = None
        self._render_debounce_seconds = 0.08
        self._filter_row = None

        # 线程池
        self._executor = ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="CoreDownload"
        )
        self._render_lock = threading.Lock()
        self._is_rendering = False

        # 目录选择下拉框
        self._dir_dropdown = None

        # 下载管理器
        self._download_manager = DownloadManager.instance()

    def _load_version_dirs(self) -> list[dict]:
        """加载版本目录列表"""
        cfg = self.cfg.load()
        entries = cfg.get("VersionDirectoryEntries", [])
        if not entries:
            default_path = str(Path.home() / ".minecraft" / "versions")
            entries = [{"name": "默认版本目录", "path": default_path}]
            self.cfg.save({**cfg, "VersionDirectoryEntries": entries})
        return entries

    def _on_return_click(self):
        def navigate(route: str):
            async def do_navigate():
                await self.page.push_route(route)

            self.page.run_task(do_navigate)

        if self.page.views:
            self.page.views.pop()
            top_view = self.page.views[-1] if self.page.views else None
            navigate(top_view.route if top_view else "/resources")
        else:
            navigate("/resources")

    async def _navigate_to(self, route: str):
        await self.page.push_route(route)

    def _on_download_manager_click(self):
        self.page.run_task(self._navigate_to, "/download_manager")

    # -------------------- 数据加载 --------------------
    def _load_versions(self):
        """在线程中调用的阻塞函数，返回 manifest 字典"""
        downloader = MinecraftDownloader(self.mc_root)
        return downloader.get_version_manifest()

    def _async_load_versions(self):
        """异步版本加载"""

        def _load_complete(future):
            try:
                manifest = future.result()
                self._dispatch_ui(lambda: self._on_manifest_loaded(manifest))
            except Exception as err:
                self._dispatch_ui(lambda: self._show_error(str(err)))

        future = self._executor.submit(self._load_versions)
        future.add_done_callback(_load_complete)

    def _on_manifest_loaded(self, manifest: dict):
        self._manifest = manifest
        self._render_manifest_async(manifest)

    def _render_manifest_async(self, manifest: dict):
        if self._is_rendering:
            return

        with self._render_lock:
            if self._is_rendering:
                return
            self._is_rendering = True

        def _render_complete(future):
            self._is_rendering = False
            try:
                cards = future.result()
                self._dispatch_ui(lambda: self._update_cards(cards))
            except Exception as err:
                self._dispatch_ui(lambda: self._show_error(f"渲染失败: {err}"))

        future = self._executor.submit(self._build_version_cards, manifest)
        future.add_done_callback(_render_complete)

    def _build_version_cards(self, manifest: dict) -> list[ft.Control]:
        """构建版本卡片"""
        cards: list[ft.Control] = []
        for v in manifest.get("versions", []):
            v_type = v.get("type", "")
            if v_type and v_type not in self._selected_types:
                continue

            tag_text = {
                "snapshot": ("快照版", ft.Colors.ORANGE),
                "release": ("正式版", ft.Colors.GREEN),
                "old_alpha": ("旧 Alpha", ft.Colors.GREY),
                "old_beta": ("旧 Beta", ft.Colors.GREY),
            }.get(v_type, (v_type, ft.Colors.BLUE_GREY))

            cards.append(
                ft.Card(
                    content=ft.Container(
                        padding=10,
                        content=ft.Row(
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            controls=[
                                ft.Column(
                                    spacing=2,
                                    controls=[
                                        ft.Text(
                                            v.get("id", "?"), weight=ft.FontWeight.BOLD
                                        ),
                                        ft.Text(
                                            tag_text[0], size=11, color=tag_text[1]
                                        ),
                                    ],
                                ),
                                ft.Button(
                                    "下载",
                                    icon=ft.Icons.DOWNLOAD,
                                    data=v.get("id"),
                                    on_click=self._on_download_click,
                                ),
                            ],
                        ),
                    )
                )
            )

        if not cards:
            cards = [ft.Text("未获取到版本信息", color=ft.Colors.GREY)]
        return cards

    def _update_cards(self, cards: list[ft.Control]):
        self._versions_column.controls = cards
        self.page.update()

    def _dispatch_ui(self, callback):
        try:
            callback()
        except Exception:
            pass

    def _on_type_toggle(self, v_type: str, value: bool):
        if value:
            self._selected_types.add(v_type)
        else:
            self._selected_types.discard(v_type)
        if self._manifest is not None:
            self._schedule_async_render_manifest()

    def _schedule_async_render_manifest(self, delay: float | None = None):
        if delay is None:
            delay = self._render_debounce_seconds

        if getattr(self, "_render_debounce_timer", None) is not None:
            try:
                self._render_debounce_timer.cancel()
            except Exception:
                pass

        def _on_timer():
            if self._manifest is not None:
                self._render_manifest_async(self._manifest)

        t = threading.Timer(delay, _on_timer)
        t.daemon = True
        self._render_debounce_timer = t
        t.start()

    def _get_filter_row(self) -> ft.Row:
        if self._filter_row is not None:
            return self._filter_row

        checkboxes: list[ft.Control] = []
        label_map = {
            "snapshot": "快照",
            "release": "正式",
            "old_alpha": "旧 Alpha",
            "old_beta": "旧 Beta",
        }
        for t in self._all_types:
            cb = ft.Checkbox(
                label=label_map.get(t, t),
                value=(t in self._selected_types),
                on_change=lambda e, tt=t: self._on_type_toggle(tt, e.control.value),
            )
            checkboxes.append(cb)

        self._filter_row = ft.Row(
            controls=checkboxes, alignment=ft.MainAxisAlignment.START
        )
        return self._filter_row

    def _on_refresh_click(self, e):
        self.page.show_dialog(ft.SnackBar(ft.Text("开始刷新版本列表")))
        self._versions_column.controls = [
            ft.Row(
                controls=[ft.ProgressRing(), ft.Text("正在刷新版本列表...")],
                spacing=10,
            )
        ]
        self.page.update()
        self._async_load_versions()

    def _show_error(self, err: str):
        self._versions_column.controls = [
            ft.Text(f"加载版本失败: {err}", color=ft.Colors.ERROR, selectable=True)
        ]
        self.page.update()

    # -------------------- 下载交互 --------------------
    def _on_download_click(self, e):
        """点击下载按钮 - 显示配置对话框"""
        version_id = e.control.data
        self._show_download_dialog(version_id)

    def _show_download_dialog(self, version_id: str):
        """显示下载配置对话框"""
        # 自定义名称输入
        name_field = ft.TextField(
            label="版本名称 (可选)",
            hint_text=f"留空则使用 {version_id}",
            value="",
            width=300,
        )

        # 目录选择下拉框
        dir_options = [
            ft.dropdown.Option(key=d["path"], text=f"{d['name']} ({d['path']})")
            for d in self._version_dirs
        ]

        selected_dir = ft.Dropdown(
            label="安装目录",
            options=dir_options,
            value=self._version_dirs[0]["path"] if self._version_dirs else "",
            width=400,
        )

        # 下载信息显示
        info_text = ft.Text(
            f"版本: {version_id}\n将使用littledl高性能多线程下载",
            size=12,
        )

        def on_cancel(_):
            self.page.pop_dialog()

        def on_confirm(_):
            self.page.pop_dialog()
            custom_name = name_field.value.strip() or None
            target_dir = selected_dir.value

            if not target_dir:
                self.page.show_dialog(ft.SnackBar(ft.Text("请选择安装目录")))
                return

            self._start_download(version_id, custom_name, target_dir)

        self.page.show_dialog(
            ft.AlertDialog(
                modal=True,
                title=ft.Text(f"下载 Minecraft {version_id}"),
                content=ft.Column(
                    [
                        info_text,
                        ft.Divider(),
                        name_field,
                        selected_dir,
                    ],
                    spacing=10,
                    tight=True,
                ),
                actions=[
                    ft.TextButton("取消", on_click=on_cancel),
                    ft.FilledButton(
                        "开始下载", icon=ft.Icons.DOWNLOAD, on_click=on_confirm
                    ),
                ],
            )
        )
        self.page.update()

    def _start_download(
        self, version_id: str, custom_name: str | None, target_dir: str
    ):
        """开始下载"""
        task_id = f"core_{version_id}_{int(time.time())}"
        display_name = custom_name or version_id

        # 创建下载任务
        task = DownloadTask(
            task_id=task_id,
            name=f"Minecraft {display_name}",
            version_id=version_id,
            target_dir=target_dir,
            custom_name=custom_name or "",
            status=TaskStatus.DOWNLOADING,
        )
        task.started_at = time.time()

        # 添加到管理器
        self._download_manager.add_task(task)

        # 显示提示
        self.page.show_dialog(ft.SnackBar(ft.Text(f"开始下载 {display_name} ...")))
        self.page.update()

        # 进度回调
        def progress_callback(progress: DownloadProgress):
            current_file = progress.current_file or progress.status or task.current_file

            if progress.status and "失败" in progress.status:
                task.update(error=progress.status)

            update_data = {
                "speed": progress.speed,
                "status": TaskStatus.DOWNLOADING,
                "current_file": current_file,
                "connections": progress.connections,
            }

            if progress.total_files > 0:
                update_data["file_count"] = progress.total_files
                update_data["completed_files"] = progress.finished_files
            if progress.total > 0:
                update_data["total"] = progress.total
                update_data["downloaded"] = progress.current
            elif progress.total_files > 0:
                update_data["total"] = progress.total_files
                update_data["downloaded"] = progress.finished_files

            if "total" in update_data:
                task.update(**update_data)
                self._download_manager._notify()

        # 获取下载配置
        download_cfg = self.cfg.get_download_config()

        # 创建下载配置
        config = MinecraftDownloadConfig(
            enable_chunking=download_cfg.get("enable_chunking", True),
            max_chunks=download_cfg.get("max_connections", 16),
            chunk_size=int(download_cfg.get("chunk_size_mb", 4) * 1024 * 1024),
            buffer_size=64 * 1024,
            timeout=download_cfg.get("timeout_seconds", 300),
            resume=download_cfg.get("resume_enabled", True),
            verify_ssl=True,
            speed_limit_enabled=download_cfg.get("speed_limit_kbps", 0) > 0,
            max_speed=download_cfg.get("speed_limit_kbps", 0) * 1024,
            retry_enabled=True,
            max_retries=download_cfg.get("max_retries", 3),
            retry_delay=download_cfg.get("retry_delay_seconds", 1.0),
            proxy_mode="SYSTEM",
            download_source=download_cfg.get("download_source", "mirror_first"),
            verify_hash=download_cfg.get("verify_hash", True),
        )

        # 下载源
        source_map = {
            "mirror_only": DownloadSource.MIRROR_ONLY,
            "mirror_first": DownloadSource.MIRROR_FIRST,
            "official_first": DownloadSource.OFFICIAL_FIRST,
            "official_only": DownloadSource.OFFICIAL_ONLY,
        }
        download_source = source_map.get(
            download_cfg.get("download_source", "mirror_first"),
            DownloadSource.MIRROR_FIRST,
        )

        def do_download():
            try:
                print(f"[下载线程] 开始下载: {version_id}, 目标目录: {target_dir}")

                downloader = MinecraftDownloader(
                    mc_folder=target_dir,
                    config=config,
                    download_source=download_source,
                    progress_callback=progress_callback,
                )

                ok = downloader.download_version(
                    version_id,
                    cancel_event=task._cancel_event,
                    custom_name=custom_name,
                    target_dir=target_dir,
                )

                if ok:
                    msg = f"版本 {display_name} 下载完成"
                    task.update(
                        status=TaskStatus.COMPLETED,
                        completed_at=time.time(),
                        downloaded=task.total,
                    )
                    self._download_manager.archive_task(task.task_id)
                else:
                    detailed_reason = (
                        task.error
                        or getattr(downloader, "last_error", "")
                        or f"版本 {display_name} 下载失败"
                    )
                    msg = f"版本 {display_name} 下载失败"
                    task.update(
                        status=TaskStatus.FAILED,
                        error=detailed_reason,
                        completed_at=time.time(),
                    )
                    self.logger.error(
                        f"版本下载失败: version={version_id}, name={display_name}, reason={detailed_reason}"
                    )
                    self._download_manager.archive_task(task.task_id)

                print(f"[下载线程] 结束: {msg}")
                self._download_manager._notify()

            except Exception as ex:
                import traceback

                tb = traceback.format_exc()
                print(f"[下载线程] 异常: {ex}\n{tb}")
                err_msg = f"下载异常: {ex}"
                task.update(
                    status=TaskStatus.FAILED,
                    error=err_msg,
                    completed_at=time.time(),
                )
                self.logger.exception(
                    f"版本下载线程异常: version={version_id}, name={display_name}"
                )
                self._download_manager.archive_task(task.task_id)
                self._download_manager._notify()

            # 取消时清理文件
            if task.is_cancelled():
                task.delete_files()

        threading.Thread(target=do_download, daemon=True).start()

    # -------------------- 构建视图 --------------------
    def build(self) -> ft.View:
        # 初始加载
        self._versions_column.controls = [
            ft.Row(
                controls=[ft.ProgressRing(), ft.Text("正在获取版本列表...")],
                spacing=10,
            )
        ]
        self._async_load_versions()

        # AppBar
        appbar = ft.AppBar(
            title=ft.Text("核心下载"),
            leading=ft.IconButton(
                ft.Icons.ARROW_BACK, on_click=lambda _: self._on_return_click()
            ),
            actions=[
                ft.IconButton(
                    ft.Icons.REFRESH, on_click=self._on_refresh_click, tooltip="刷新"
                ),
                ft.IconButton(
                    ft.Icons.DOWNLOAD,
                    tooltip="下载管理",
                    on_click=lambda _: self._on_download_manager_click(),
                ),
            ],
            automatically_imply_leading=False,
        )

        # 主体
        body = ft.Column(
            spacing=8,
            expand=True,
            controls=[
                self._get_filter_row(),
                ft.Divider(),
                self._versions_column,
            ],
        )

        return ft.View(
            route="/core_download",
            controls=[
                appbar,
                ft.Container(expand=True, padding=10, content=body),
            ],
        )

    def cleanup(self):
        """清理资源"""
        if hasattr(self, "_executor"):
            self._executor.shutdown(wait=False)

        if (
            hasattr(self, "_render_debounce_timer")
            and self._render_debounce_timer is not None
        ):
            try:
                self._render_debounce_timer.cancel()
            except Exception:
                pass
