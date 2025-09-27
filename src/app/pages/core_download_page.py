from __future__ import annotations
import flet as ft
from pathlib import Path
import threading
from concurrent.futures import ThreadPoolExecutor
from app.services.download_service import MinecraftDownloader


class CoreDownloadPage:
    """核心下载页面（使用线程后台加载避免协程环境问题）"""

    def __init__(self, page: ft.Page, mc_root: str | None = None):
        self.page = page
        self.mc_root = mc_root or "minecraft_versions"
        Path(self.mc_root).mkdir(exist_ok=True, parents=True)
        # 让版本列表占满剩余空间并可滚动
        self._versions_column = ft.Column(spacing=6, tight=False, expand=True, scroll=ft.ScrollMode.AUTO)
        # 当前获取到的 manifest（用于切换筛选时重绘）
        self._manifest = None
        # 默认选中所有类型
        self._all_types = ["snapshot", "release", "old_alpha", "old_beta"]
        self._selected_types = set(self._all_types)
        # 防抖计时器：批量切换复选框时合并重绘，减少频繁 rebuild 导致的卡顿
        self._render_debounce_timer = None
        # 防抖延迟（秒） — 可根据 UI 响应调整，太大将降低交互感
        self._render_debounce_seconds = 0.08

        # 顶部筛选控件占位（在 build 中创建）
        self._filter_row = None
        
        # 线程池用于异步处理耗时操作
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="CoreDownload")
        
        # 控制渲染任务的锁，防止同时进行多个渲染任务
        self._render_lock = threading.Lock()
        self._is_rendering = False

    def _on_return_click(self):
        # 如果有视图栈则弹出当前视图并导航至栈顶路由，否则退回到模组列表路由
        if self.page.views:
            self.page.views.pop()
            top_view = self.page.views[-1] if self.page.views else None
            self.page.go(top_view.route if top_view else "/resources")
        else:
            self.page.go("/resources")
    # -------------------- 数据加载（异步优化） --------------------
    def _load_versions(self):
        """在线程中调用的阻塞函数，返回 manifest 字典。"""
        downloader = MinecraftDownloader(self.mc_root)
        return downloader.get_version_manifest()

    def _async_load_versions(self):
        """异步版本加载，使用线程池避免阻塞UI"""
        def _load_complete(future):
            """加载完成回调"""
            try:
                manifest = future.result()
                self._dispatch_ui(lambda: self._on_manifest_loaded(manifest))
            except Exception as err:
                self._dispatch_ui(lambda err=err: self._show_error(err))
        
        # 提交到线程池异步执行
        future = self._executor.submit(self._load_versions)
        future.add_done_callback(_load_complete)

    def _on_manifest_loaded(self, manifest: dict):
        """manifest加载完成后的UI更新"""
        self._manifest = manifest
        self._render_manifest_async(manifest)

    def _render_manifest_async(self, manifest: dict):
        """异步渲染manifest，避免大数据量时UI卡顿"""
        # 防止同时进行多个渲染任务
        if self._is_rendering:
            return
            
        with self._render_lock:
            if self._is_rendering:
                return
            self._is_rendering = True
            
        def _render_complete(future):
            """渲染完成回调"""
            self._is_rendering = False
            try:
                cards = future.result()
                self._dispatch_ui(lambda: self._update_cards(cards))
            except Exception as err:
                self._dispatch_ui(lambda err=err: self._show_error(f"渲染失败: {err}"))
        
        # 提交卡片构建任务到线程池
        future = self._executor.submit(self._build_version_cards, manifest)
        future.add_done_callback(_render_complete)

    def _build_version_cards(self, manifest: dict) -> list[ft.Control]:
        """在后台线程构建版本卡片（CPU密集型操作）"""
        cards: list[ft.Control] = []
        for v in manifest.get("versions", []):
            v_type = v.get("type", "")
            # 根据当前选中的类型过滤
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
                                        ft.Text(v.get("id", "?"), weight=ft.FontWeight.BOLD),
                                        ft.Text(tag_text[0], size=11, color=tag_text[1]),
                                    ],
                                ),
                                ft.ElevatedButton(
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
        """更新UI卡片（在UI线程执行）"""
        self._versions_column.controls = cards
        self.page.update()

    def _render_manifest(self, manifest: dict):
        # 如果有防抖计时器，说明可能有未完成的合并请求，取消它以确保立即生效
        if getattr(self, "_render_debounce_timer", None) is not None:
            try:
                self._render_debounce_timer.cancel()
            except Exception:
                pass
            self._render_debounce_timer = None

        cards: list[ft.Control] = []
        for v in manifest.get("versions", []):
            v_type = v.get("type", "")
            # 根据当前选中的类型过滤
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
                                        ft.Text(v.get("id", "?"), weight=ft.FontWeight.BOLD),
                                        ft.Text(tag_text[0], size=11, color=tag_text[1]),
                                    ],
                                ),
                                ft.ElevatedButton(
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
        self._versions_column.controls = cards
        self.page.update()

    def _dispatch_ui(self, callback):
        """统一的UI线程调度方法"""
        try:
            # 新版 Flet
            if hasattr(self.page, "invoke_later"):
                self.page.invoke_later(callback)
            else:
                # 无调度 API 时直接调用（某些版本允许跨线程简单更新）
                callback()
        except Exception:
            callback()

    def _on_type_toggle(self, v_type: str, value: bool):
        """复选框切换回调：更新选中集合并重绘当前 manifest。"""
        if value:
            self._selected_types.add(v_type)
        else:
            self._selected_types.discard(v_type)
        # 使用防抖合并多次切换引发的重绘请求，并使用异步渲染
        if self._manifest is not None:
            self._schedule_async_render_manifest()

    def _schedule_async_render_manifest(self, delay: float | None = None):
        """调度异步渲染当前manifest，使用防抖避免频繁操作"""
        if delay is None:
            delay = self._render_debounce_seconds

        # cancel previous timer
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
        """返回包含多选筛选和刷新按钮的行。"""
        # 如果已创建，直接返回（保持复用以保留控件状态）
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
            cb = ft.Checkbox(label=label_map.get(t, t), value=(t in self._selected_types), on_change=lambda e, tt=t: self._on_type_toggle(tt, e.control.value))
            checkboxes.append(cb)

        self._filter_row = ft.Row(controls=checkboxes, alignment=ft.MainAxisAlignment.START)
        return self._filter_row

    def _on_refresh_click(self, e: ft.ControlEvent):
        """用户点击刷新：重新启动异步加载并提示"""
        # 显示顶部提示并把列表替换成加载动画
        self.page.open(ft.SnackBar(ft.Text("开始刷新版本列表")))
        # 将版本列表替换为加载占位（保证用户看到加载状态）
        self._versions_column.controls = [
            ft.Row(
                controls=[ft.ProgressRing(), ft.Text("正在刷新版本列表...")],
                spacing=10,
            )
        ]
        self.page.update()
        # 使用异步加载
        self._async_load_versions()

    def _show_error(self, err: Exception | str):
        self._versions_column.controls = [
            ft.Text(f"加载版本失败: {err}", color=ft.Colors.ERROR, selectable=True)
        ]
        self.page.update()

    # -------------------- 交互 --------------------
    def _on_download_click(self, e: ft.ControlEvent):
        from app.services.download_manager import DownloadManager, DownloadTask
        version_id = e.control.data
        task_id = f"core_{version_id}"
        task = DownloadTask(task_id=task_id, name=f"核心版本 {version_id}")
        manager = DownloadManager.instance()
        manager.add_task(task)
        self.page.snack_bar = ft.SnackBar(ft.Text(f"正在下载 {version_id} ... (已加入下载管理)"))
        self.page.snack_bar.open = True
        self.page.update()

        def progress_callback(progress):
            # 实时更新全局任务进度（支持大文件）
            downloaded = getattr(progress, 'finished_files', 0)
            total = getattr(progress, 'total_files', 1)
            percent = getattr(progress, 'total_percentage', 0)
            status = getattr(progress, 'status', "下载中")
            # 让 DownloadTask 的 progress 实时反映 percent
            with task._lock:
                task.downloaded = downloaded
                task.total = total
                task.progress = percent / 100
                task.status = status
            # 通知刷新
            manager._notify()
            # 兼容原有进度条和snackbar
            if hasattr(self, '_download_progress_bar'):
                self._download_progress_bar.value = percent / 100
            self.page.snack_bar = ft.SnackBar(ft.Text(f"{status} ({downloaded}/{total})"))
            self.page.snack_bar.open = True
            self.page.update()

        def do_download():
            file_paths = set()
            def file_paths_cb(file_path, temp_path):
                if file_path:
                    file_paths.add(file_path)
                if temp_path:
                    file_paths.add(temp_path)
            try:
                print(f"[下载线程] 开始下载: {version_id}, 路径: {self.mc_root}")
                downloader = MinecraftDownloader(self.mc_root, progress_callback=progress_callback)
                ok = downloader.download_version(version_id, cancel_event=task._cancel_event, file_paths_cb=file_paths_cb)
                if ok:
                    msg = f"版本 {version_id} 下载完成"
                    task.update(downloaded=task.total, status=msg)
                else:
                    msg = f"版本 {version_id} 下载失败"
                    task.update(status=msg, error=msg)
                print(f"[下载线程] 结束: {msg}")
                self.page.snack_bar = ft.SnackBar(ft.Text(msg))
                self.page.snack_bar.open = True
                self.page.update()
            except Exception as ex:
                import traceback
                tb = traceback.format_exc()
                print(f"[下载线程] 异常: {ex}\n{tb}")
                err_msg = f"下载异常: {ex}"
                task.update(status=err_msg, error=str(ex))
                self.page.snack_bar = ft.SnackBar(ft.Text(err_msg))
                self.page.snack_bar.open = True
                self.page.update()
            # 取消时清理所有已下载文件
            if task.is_cancelled():
                import os
                for fp in file_paths:
                    try:
                        if os.path.exists(fp):
                            os.remove(fp)
                    except Exception:
                        pass
        threading.Thread(target=do_download, daemon=True).start()

    # -------------------- 构建视图 --------------------
    def build(self) -> ft.View:
        # 初始加载占位
        self._versions_column.controls = [
            ft.Row(
                controls=[ft.ProgressRing(), ft.Text("正在获取版本列表...")],
                spacing=10,
            )
        ]
        # 启动异步加载
        self._async_load_versions()
        # 构建包含返回、刷新按钮与筛选行的视图
        appbar = ft.AppBar(
            title=ft.Text("核心下载"),
            leading=ft.IconButton(ft.Icons.ARROW_BACK, on_click=lambda _: self._on_return_click()),
            actions=[
                ft.IconButton(ft.Icons.REFRESH, on_click=self._on_refresh_click, tooltip="刷新"),
            ],
            automatically_imply_leading=False,
        )

        # 在列表上方显示筛选行
        body = ft.Column(spacing=8, expand=True, controls=[self._get_filter_row(), self._versions_column])

        return ft.View(
            "/core_download",
            [
                appbar,
                ft.Container(expand=True, padding=10, content=body),
            ],
        )

    def cleanup(self):
        """清理资源，页面销毁时调用"""
        if hasattr(self, '_executor'):
            self._executor.shutdown(wait=False)
        
        if hasattr(self, '_render_debounce_timer') and self._render_debounce_timer is not None:
            try:
                self._render_debounce_timer.cancel()
            except Exception:
                pass
