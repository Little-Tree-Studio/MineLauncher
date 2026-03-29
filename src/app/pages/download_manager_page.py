"""下载管理页面 - 任务队列、进度、历史记录"""

from __future__ import annotations
import flet as ft
from datetime import datetime
from ..services.download_manager import (
    DownloadManager,
    DownloadTask,
    TaskStatus,
    DownloadHistory,
)


def format_size(size: int) -> str:
    """格式化文件大小"""
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def format_speed(speed: float) -> str:
    """格式化速度"""
    if speed <= 0:
        return "-"
    return format_size(int(speed)) + "/s"


def format_eta(seconds: float) -> str:
    """格式化预计时间"""
    if seconds <= 0:
        return "-"
    if seconds < 60:
        return f"{seconds:.0f}秒"
    elif seconds < 3600:
        minutes = seconds // 60
        secs = seconds % 60
        return f"{minutes:.0f}分{secs:.0f}秒"
    else:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"{hours:.0f}时{minutes:.0f}分"


def format_duration(seconds: float) -> str:
    """格式化时长"""
    if seconds < 60:
        return f"{seconds:.0f}秒"
    elif seconds < 3600:
        minutes = seconds // 60
        secs = seconds % 60
        return f"{minutes:.0f}分{secs:.0f}秒"
    else:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"{hours:.0f}时{minutes:.0f}分"


def format_time(timestamp: float) -> str:
    """格式化时间戳"""
    if timestamp <= 0:
        return "-"
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")


def download_manager_page(page: ft.Page):
    manager = DownloadManager.instance()

    # 当前选中的标签页索引
    current_tab_index = [0]

    # 任务队列容器
    task_list_container = ft.Column(spacing=5, expand=True, scroll=ft.ScrollMode.AUTO)

    # 历史记录容器
    history_list_container = ft.Column(
        spacing=5, expand=True, scroll=ft.ScrollMode.AUTO
    )

    def navigate(route: str):
        async def do_navigate():
            await page.push_route(route)

        page.run_task(do_navigate)

    def get_status_color(status: TaskStatus) -> str:
        colors = {
            TaskStatus.WAITING: ft.Colors.BLUE,
            TaskStatus.DOWNLOADING: ft.Colors.GREEN,
            TaskStatus.PAUSED: ft.Colors.ORANGE,
            TaskStatus.COMPLETED: ft.Colors.GREEN,
            TaskStatus.FAILED: ft.Colors.RED,
            TaskStatus.CANCELLED: ft.Colors.GREY,
            TaskStatus.VERIFYING: ft.Colors.PURPLE,
        }
        return colors.get(status, ft.Colors.GREY)

    def get_status_icon(status: TaskStatus) -> ft.IconData:
        icons = {
            TaskStatus.WAITING: ft.Icons.HOURGLASS_EMPTY,
            TaskStatus.DOWNLOADING: ft.Icons.DOWNLOAD,
            TaskStatus.PAUSED: ft.Icons.PAUSE,
            TaskStatus.COMPLETED: ft.Icons.CHECK_CIRCLE,
            TaskStatus.FAILED: ft.Icons.ERROR,
            TaskStatus.CANCELLED: ft.Icons.CANCEL,
            TaskStatus.VERIFYING: ft.Icons.VERIFIED,
        }
        return icons.get(status, ft.Icons.HELP)

    def build_task_card(task: DownloadTask) -> ft.Card:
        """构建任务卡片"""
        status_color = get_status_color(task.status)
        status_icon = get_status_icon(task.status)

        # 进度条
        progress_bar = ft.ProgressBar(
            value=task.progress,
            color=status_color,
            bgcolor=ft.Colors.GREY_300,
        )

        # 操作按钮
        action_buttons = []

        if task.status == TaskStatus.DOWNLOADING:
            action_buttons.append(
                ft.IconButton(
                    icon=ft.Icons.PAUSE,
                    tooltip="暂停",
                    on_click=lambda e, tid=task.task_id: pause_task(tid),
                )
            )
        elif task.status == TaskStatus.PAUSED:
            action_buttons.append(
                ft.IconButton(
                    icon=ft.Icons.PLAY_ARROW,
                    tooltip="继续",
                    on_click=lambda e, tid=task.task_id: resume_task(tid),
                )
            )

        if task.status in [
            TaskStatus.DOWNLOADING,
            TaskStatus.WAITING,
            TaskStatus.PAUSED,
        ]:
            action_buttons.append(
                ft.IconButton(
                    icon=ft.Icons.CANCEL,
                    tooltip="取消",
                    on_click=lambda e, tid=task.task_id: cancel_task(tid),
                )
            )
        elif task.status in [
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        ]:
            action_buttons.append(
                ft.IconButton(
                    icon=ft.Icons.DELETE,
                    tooltip="删除",
                    on_click=lambda e, tid=task.task_id: remove_task(tid),
                )
            )

        # 详细信息
        is_mc_download = bool(task.version_id)

        details = ft.Column(
            [
                ft.Row(
                    [
                        ft.Icon(status_icon, color=status_color, size=20),
                        ft.Text(
                            task.name, size=14, weight=ft.FontWeight.BOLD, expand=True
                        ),
                        ft.Text(task.status.value, color=status_color, size=12),
                    ]
                ),
                ft.Row(
                    [
                        ft.Text(
                            f"{format_size(task.downloaded)} / {format_size(task.total)}",
                            size=12,
                        )
                        if not is_mc_download
                        else ft.Container(),
                        ft.Text("|", size=12, color=ft.Colors.GREY)
                        if not is_mc_download
                        else ft.Container(),
                        ft.Text(f"速度: {format_speed(task.speed)}", size=12),
                        ft.Text("|", size=12, color=ft.Colors.GREY),
                        ft.Text(f"剩余: {format_eta(task.eta)}", size=12),
                    ]
                ),
                ft.Row(
                    [
                        ft.Text(
                            f"文件: {task.completed_files}/{task.file_count}", size=12
                        ),
                        ft.Text("|", size=12, color=ft.Colors.GREY),
                        ft.Text(f"连接: {task.connections}", size=12),
                        ft.Text("|", size=12, color=ft.Colors.GREY),
                        ft.Text(f"进度: {task.progress * 100:.1f}%", size=12),
                    ]
                ),
                progress_bar,
                ft.Row(
                    action_buttons,
                    alignment=ft.MainAxisAlignment.END,
                ),
            ],
            spacing=5,
        )

        return ft.Card(
            content=ft.Container(
                content=details,
                padding=10,
            ),
            margin=ft.margin.Margin.only(bottom=5),
        )

    def build_history_card(history: DownloadHistory) -> ft.Card:
        """构建历史记录卡片"""
        status_color = (
            ft.Colors.GREEN
            if history.status == "已完成"
            else ft.Colors.RED
            if history.status == "失败"
            else ft.Colors.GREY
        )

        error_control = None
        if history.status == "失败" and history.error:
            error_control = ft.Text(
                f"失败原因: {history.error}",
                size=12,
                color=ft.Colors.RED_700,
                selectable=True,
            )

        return ft.Card(
            content=ft.Container(
                content=ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Text(
                                    history.name,
                                    size=14,
                                    weight=ft.FontWeight.BOLD,
                                    expand=True,
                                ),
                                ft.Text(history.status, color=status_color, size=12),
                            ]
                        ),
                        ft.Row(
                            [
                                ft.Text(
                                    f"大小: {format_size(history.downloaded)}", size=12
                                ),
                                ft.Text("|", size=12, color=ft.Colors.GREY),
                                ft.Text(
                                    f"耗时: {format_duration(history.duration)}",
                                    size=12,
                                ),
                                ft.Text("|", size=12, color=ft.Colors.GREY),
                                ft.Text(
                                    f"平均速度: {format_speed(history.average_speed)}",
                                    size=12,
                                ),
                            ]
                        ),
                        ft.Row(
                            [
                                ft.Text(
                                    f"文件: {history.completed_files}/{history.file_count}",
                                    size=12,
                                ),
                                ft.Text("|", size=12, color=ft.Colors.GREY),
                                ft.Text(
                                    f"完成时间: {format_time(history.completed_at or 0)}",
                                    size=12,
                                ),
                            ]
                        ),
                        error_control if error_control else ft.Container(),
                    ],
                    spacing=5,
                ),
                padding=10,
            ),
            margin=ft.margin.Margin.only(bottom=5),
        )

    def build_statistics() -> ft.Card:
        """构建统计卡片"""
        stats = manager.get_statistics()

        return ft.Card(
            content=ft.Container(
                content=ft.Column(
                    [
                        ft.Text("下载统计", size=16, weight=ft.FontWeight.BOLD),
                        ft.Row(
                            [
                                ft.Column(
                                    [
                                        ft.Text(
                                            "总下载次数", size=12, color=ft.Colors.GREY
                                        ),
                                        ft.Text(
                                            str(stats["total_downloads"]),
                                            size=20,
                                            weight=ft.FontWeight.BOLD,
                                        ),
                                    ],
                                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                                ),
                                ft.VerticalDivider(),
                                ft.Column(
                                    [
                                        ft.Text("成功", size=12, color=ft.Colors.GREY),
                                        ft.Text(
                                            str(stats["completed"]),
                                            size=20,
                                            color=ft.Colors.GREEN,
                                        ),
                                    ],
                                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                                ),
                                ft.VerticalDivider(),
                                ft.Column(
                                    [
                                        ft.Text("失败", size=12, color=ft.Colors.GREY),
                                        ft.Text(
                                            str(stats["failed"]),
                                            size=20,
                                            color=ft.Colors.RED,
                                        ),
                                    ],
                                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                                ),
                                ft.VerticalDivider(),
                                ft.Column(
                                    [
                                        ft.Text(
                                            "总大小", size=12, color=ft.Colors.GREY
                                        ),
                                        ft.Text(
                                            format_size(stats["total_size"]), size=16
                                        ),
                                    ],
                                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_AROUND,
                        ),
                    ],
                    spacing=10,
                ),
                padding=15,
            ),
            margin=ft.margin.Margin.only(bottom=10),
        )

    def refresh():
        """刷新界面"""
        # 任务列表
        task_list_container.controls.clear()
        active_tasks = manager.get_active_tasks()
        completed_tasks = manager.get_completed_tasks()

        if active_tasks:
            task_list_container.controls.append(
                ft.Text("进行中", size=16, weight=ft.FontWeight.BOLD)
            )
            for task in active_tasks:
                task_list_container.controls.append(build_task_card(task))

        if completed_tasks:
            task_list_container.controls.append(
                ft.Text("已完成", size=16, weight=ft.FontWeight.BOLD)
            )
            for task in completed_tasks:
                task_list_container.controls.append(build_task_card(task))

        if not active_tasks and not completed_tasks:
            task_list_container.controls.append(
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Icon(
                                ft.Icons.DOWNLOAD, size=64, color=ft.Colors.GREY_400
                            ),
                            ft.Text("暂无下载任务", size=16, color=ft.Colors.GREY),
                        ],
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    expand=True,
                )
            )

        # 历史记录
        history_list_container.controls.clear()
        history_items = manager.get_history()

        if history_items:
            history_list_container.controls.append(build_statistics())
            for history in history_items[:50]:  # 显示最近50条
                history_list_container.controls.append(build_history_card(history))
        else:
            history_list_container.controls.append(
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Icon(
                                ft.Icons.HISTORY, size=64, color=ft.Colors.GREY_400
                            ),
                            ft.Text("暂无下载历史", size=16, color=ft.Colors.GREY),
                        ],
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    expand=True,
                )
            )

        if page.views:
            page.update()

    def pause_task(task_id: str):
        manager.pause_task(task_id)

    def resume_task(task_id: str):
        manager.resume_task(task_id)

    def cancel_task(task_id: str):
        task = manager.get_task(task_id)
        if task:
            task.cancel()
            task.delete_files()
            page.show_dialog(ft.SnackBar(ft.Text(f"已取消: {task.name}")))
            page.update()

    def remove_task(task_id: str):
        manager.remove_task(task_id)
        page.show_dialog(ft.SnackBar(ft.Text("已移除任务")))
        page.update()

    def clear_completed(_):
        manager.clear_completed_tasks()
        page.show_dialog(ft.SnackBar(ft.Text("已清除已完成任务")))
        page.update()

    def clear_history(_):
        manager.clear_history()
        page.show_dialog(ft.SnackBar(ft.Text("已清空历史记录")))
        page.update()

    # 注册监听器
    manager.on_change(refresh)

    # 初始刷新
    refresh()

    # 创建标签页内容
    tab_queue_content = ft.Container(
        content=task_list_container,
        padding=10,
        expand=True,
    )

    tab_history_content = ft.Container(
        content=history_list_container,
        padding=10,
        expand=True,
    )

    # 当前显示的内容
    content_area = ft.Container(expand=True, content=tab_queue_content)

    def on_tab_change(e):
        current_tab_index[0] = e.control.selected_index
        if e.control.selected_index == 0:
            content_area.content = tab_queue_content
        else:
            content_area.content = tab_history_content
        page.update()

    # 使用Column和按钮模拟Tabs
    tab_buttons = ft.Row(
        [
            ft.TextButton(
                "下载队列",
                icon=ft.Icons.DOWNLOAD,
                style=ft.ButtonStyle(
                    bgcolor=ft.Colors.BLUE_100 if current_tab_index[0] == 0 else None,
                ),
                on_click=lambda e: switch_tab(0),
            ),
            ft.TextButton(
                "下载历史",
                icon=ft.Icons.HISTORY,
                style=ft.ButtonStyle(
                    bgcolor=ft.Colors.BLUE_100 if current_tab_index[0] == 1 else None,
                ),
                on_click=lambda e: switch_tab(1),
            ),
        ]
    )

    def switch_tab(index):
        current_tab_index[0] = index
        if index == 0:
            content_area.content = tab_queue_content
            tab_buttons.controls[0].style = ft.ButtonStyle(bgcolor=ft.Colors.BLUE_100)
            tab_buttons.controls[1].style = ft.ButtonStyle(bgcolor=None)
        else:
            content_area.content = tab_history_content
            tab_buttons.controls[0].style = ft.ButtonStyle(bgcolor=None)
            tab_buttons.controls[1].style = ft.ButtonStyle(bgcolor=ft.Colors.BLUE_100)
        page.update()

    return ft.View(
        route="/download_manager",
        controls=[
            ft.AppBar(
                title=ft.Text("下载管理"),
                leading=ft.IconButton(
                    ft.Icons.ARROW_BACK, on_click=lambda e: navigate("/")
                ),
                actions=[
                    ft.PopupMenuButton(
                        items=[
                            ft.PopupMenuItem(
                                content=ft.Text("清除已完成任务"),
                                icon=ft.Icons.DELETE_SWEEP,
                                on_click=clear_completed,
                            ),
                            ft.PopupMenuItem(
                                content=ft.Text("清空历史记录"),
                                icon=ft.Icons.HISTORY_TOGGLE_OFF,
                                on_click=clear_history,
                            ),
                        ],
                    ),
                ],
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
