from __future__ import annotations
import flet as ft
from pathlib import Path
import threading
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

    # -------------------- 数据加载（线程） --------------------
    def _load_versions(self):
        """在线程中调用的阻塞函数，返回 manifest 字典。"""
        downloader = MinecraftDownloader(self.mc_root)
        return downloader.get_version_manifest()

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

    def _on_type_toggle(self, v_type: str, value: bool):
        """复选框切换回调：更新选中集合并重绘当前 manifest。"""
        if value:
            self._selected_types.add(v_type)
        else:
            self._selected_types.discard(v_type)
        # 使用防抖合并多次切换引发的重绘请求
        if self._manifest is not None:
            self._schedule_render_manifest()

    def _schedule_render_manifest(self, delay: float | None = None):
        """Schedule a debounced render of the current manifest on the UI thread.

        Cancel any existing timer and create a new one. The timer callback uses
        page.invoke_later to ensure UI updates run on the main thread.
        """
        if delay is None:
            delay = self._render_debounce_seconds

        # cancel previous timer
        if getattr(self, "_render_debounce_timer", None) is not None:
            try:
                self._render_debounce_timer.cancel()
            except Exception:
                pass

        def _on_timer():
            try:
                if hasattr(self.page, "invoke_later"):
                    self.page.invoke_later(lambda: self._render_manifest(self._manifest))
                else:
                    # 直接调用也可能在某些 Flet 版本工作
                    self._render_manifest(self._manifest)
            except Exception:
                # 最后兜底：直接尝试渲染
                try:
                    self._render_manifest(self._manifest)
                except Exception:
                    pass

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

        # 只保留筛选复选框，刷新按钮在 AppBar 中已有一个
        self._filter_row = ft.Row(controls=checkboxes, alignment=ft.MainAxisAlignment.START)
        return self._filter_row

    def _on_refresh_click(self, e: ft.ControlEvent):
        """用户点击刷新：重新启动后台加载并提示"""
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
        self._start_background_load()

    def _show_error(self, err: Exception | str):
        self._versions_column.controls = [
            ft.Text(f"加载版本失败: {err}", color=ft.Colors.ERROR, selectable=True)
        ]
        self.page.update()

    def _start_background_load(self):
        import threading

        # 统一 UI 线程调度（兼容旧版本 Flet 没有 invoke_later 情况）
        def _dispatch_ui(cb):
            try:
                # 新版 Flet
                if hasattr(self.page, "invoke_later"):
                    self.page.invoke_later(cb)
                else:
                    # 无调度 API 时直接调用（某些版本允许跨线程简单更新）
                    cb()
            except Exception:
                cb()

        def worker():
            try:
                manifest = self._load_versions()

                def _ui_update(m=manifest):
                    # 保存 manifest 以便筛选时重绘
                    self._manifest = m
                    self._render_manifest(m)

                _dispatch_ui(_ui_update)
            except Exception as e:  # noqa
                _dispatch_ui(lambda err=e: self._show_error(err))

        threading.Thread(target=worker, daemon=True).start()

    # -------------------- 交互 --------------------
    def _on_download_click(self, e: ft.ControlEvent):
        version_id = e.control.data
        self.page.open(ft.SnackBar(ft.Text(f"TODO: 下载版本 {version_id}")))
        self.page.update()

    # -------------------- 构建视图 --------------------
    def build(self) -> ft.View:
        # 初始加载占位
        self._versions_column.controls = [
            ft.Row(
                controls=[ft.ProgressRing(), ft.Text("正在获取版本列表...")],
                spacing=10,
            )
        ]
        # 启动后台线程加载
        self._start_background_load()
        # 构建包含返回、刷新按钮与筛选行的视图
        appbar = ft.AppBar(
            title=ft.Text("核心下载"),
            leading=ft.IconButton(ft.Icons.ARROW_BACK, on_click=lambda _: self.page.go("/")),
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
