import flet as ft
from app.services.download_manager import DownloadManager

def download_manager_page(page: ft.Page):
    manager = DownloadManager.instance()
    task_list = ft.Column(spacing=10, expand=True)

    def on_cancel_click(task):
        manager.cancel_task(task.task_id)
        # 删除相关文件
        task.delete_files()
        page.snack_bar = ft.SnackBar(ft.Text(f"已取消并删除: {task.name}"))
        page.snack_bar.open = True
        page.update()

    def refresh():
        task_list.controls.clear()
        for task in manager.get_tasks():
            bar = ft.ProgressBar(width=200, value=task.progress)
            status = ft.Text(task.status, size=12, color=ft.Colors.GREEN if not task.error else ft.Colors.ERROR)
            cancel_btn = ft.IconButton(
                ft.Icons.CANCEL,
                tooltip="取消下载",
                on_click=lambda e, t=task: on_cancel_click(t),
                disabled=task.status in ["已取消", "下载完成", "失败", "已完成"]
            )
            row = ft.Row([
                ft.Text(task.name, size=14, weight="bold"),
                bar,
                status,
                ft.Text(f"{int(task.progress*100)}%", size=12),
                cancel_btn,
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
            task_list.controls.append(row)
        page.update()

    manager.on_change(refresh)
    refresh()

    return ft.View(
        "/download_manager",
        [
            ft.AppBar(title=ft.Text("下载管理"), leading=ft.IconButton(ft.Icons.ARROW_BACK, on_click=lambda e: page.go("/"))),
            ft.Container(task_list, padding=20, expand=True)
        ]
    )
