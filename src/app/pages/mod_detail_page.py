import flet as ft
import requests
from flet import Text, Row, Column, Image, ProgressBar, ElevatedButton, Icons, IconButton, SnackBar, FilePicker, FilePickerResultEvent
MODRINTH_PROJECT_API = "https://api.modrinth.com/v2/project/"

# 详情页面，路由: /mod_download/{mod_id}
def mod_detail_page(page: ft.Page):
    mod_id = page.route.split("/")[-1]
    mod_info = None
    versions = []
    version_files = []
    version_options = []
    # selected_version not used
    folder_picker = FilePicker()
    page.overlay.append(folder_picker)
    download_params = {}

    # 获取模组详情
    resp = requests.get(MODRINTH_PROJECT_API + mod_id)
    if resp.status_code == 200:
        mod_info = resp.json()
    else:
        return ft.View(
            f"/mod_download/{mod_id}",
            [Text("模组详情获取失败", size=20, color="red")]
        )
    # 获取所有版本
    v_resp = requests.get(MODRINTH_PROJECT_API + f"{mod_id}/version")
    if v_resp.status_code == 200:
        versions = v_resp.json()
        for v in versions:
            v_name = v.get("name", v.get("version_number", "未知版本"))
            if v["files"]:
                file_url = v["files"][0]["url"]
                file_name = v["files"][0]["filename"]
                version_options.append(v_name)
                version_files.append((file_url, file_name))
    version_dd = ft.Dropdown(
        options=[ft.dropdown.Option(text=opt, key=str(idx)) for idx, opt in enumerate(version_options)],
        width=180,
    )
    progress_bar = ProgressBar(width=120, value=0)

    def on_download_click(e, files=version_files, dd=version_dd, pb=progress_bar):
        idx = int(dd.value) if dd.value is not None else 0
        if idx >= len(files):
            page.snack_bar = SnackBar(Text("请选择版本"))
            page.snack_bar.open = True
            page.update()
            return
        file_url, file_name = files[idx]
        pb.value = 0
        page.update()
        download_params.clear()
        download_params["file_url"] = file_url
        download_params["file_name"] = file_name
        download_params["progress_bar"] = pb
        folder_picker.get_directory_path()

    def on_folder_result(e: FilePickerResultEvent):
        if e.path and download_params:
            file_url = download_params.get("file_url")
            file_name = download_params.get("file_name")
            progress_bar = download_params.get("progress_bar")
            # 直接复用主页面下载逻辑
            from .mod_download_page import download_mod_version
            download_mod_version(file_url, file_name, page, progress_bar, e.path)
            download_params.clear()

    folder_picker.on_result = on_folder_result

    # 详情内容参考PCL，展示图标、名称、简介、作者、下载数、版本选择、下载按钮

    # 返回上一视图而不是始终创建一个新的搜索页面
    def on_return_click(e):
        # 如果有视图栈则弹出当前视图并导航至栈顶路由，否则退回到模组列表路由
        if page.views:
            page.views.pop()
            top = page.views[-1] if page.views else None
            # 如果弹出后没有其它视图，回到模组搜索页；否则回到栈顶视图路由
            page.go(top.route if top else "/mod_download")
        else:
            page.go("/mod_download")
    return ft.View(
        f"/mod_download/{mod_id}",
        [
            Row([
                Image(src=mod_info.get("icon_url", ""), width=64, height=64) if mod_info.get("icon_url") else IconButton(icon=Icons.DOWNLOAD),
                Column([
                    Text(mod_info.get("title", "未知模组"), size=22, weight="bold"),
                    Text(mod_info.get("description", "暂无简介"), size=14),
                    Text(f"作者: {', '.join([a.get('name', '') for a in mod_info.get('authors', [])])}", size=12),
                    Text(f"下载数: {mod_info.get('downloads', 0)}", size=12),
                ], expand=True),
            ], alignment="start"),
            Row([
                Text("选择版本:"),
                version_dd,
                ElevatedButton("下载", on_click=lambda e, files=version_files, dd=version_dd, pb=progress_bar: on_download_click(e, files, dd, pb)),
                progress_bar
            ], alignment="start"),
            Row([
                ElevatedButton("返回", on_click=on_return_click)
            ], alignment="start"),
        ]
    )
