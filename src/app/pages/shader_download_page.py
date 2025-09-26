
import flet as ft
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import os
from flet import TextField, ElevatedButton, ListView, Row, Column, Text, Image, ProgressBar, Container, Icons, IconButton, SnackBar, FilePicker, FilePickerResultEvent, AppBar


MODRINTH_SEARCH_API = "https://api.modrinth.com/v2/search"
MODRINTH_PROJECT_API = "https://api.modrinth.com/v2/project/"

# 下载指定光影包并显示进度条，支持自定义保存路径
def download_shader(file_url, file_name, page, progress_bar, save_folder):
    save_path = os.path.join(save_folder, file_name)
    try:
        r = requests.get(file_url, stream=True)
        total = int(r.headers.get('content-length', 0))
        downloaded = 0
        with open(save_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total > 0:
                        progress_bar.value = downloaded / total
                        page.update()
        page.snack_bar = SnackBar(Text(f"下载完成: {file_name}"))
    except Exception as e:
        page.snack_bar = SnackBar(Text(f"下载失败: {e}"))
    progress_bar.value = 0
    page.snack_bar.open = True
    page.update()


def shader_download_page(page: ft.Page):
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=0.5)
    session.mount('https://', HTTPAdapter(max_retries=retries))
    search_field = TextField(label="搜索光影包", width=600, border=ft.InputBorder.UNDERLINE)
    search_btn = ElevatedButton("搜索",icon=ft.Icons.SEARCH, style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=5)),height=40)
    shader_list = ListView(expand=True, spacing=10)
    folder_picker = FilePicker()
    download_params = {}

    def show_shader_intro(shader_name, shader_desc):
        page.dialog = ft.AlertDialog(
            title=Text(f"{shader_name} 简介"),
            content=Text(shader_desc or "暂无简介"),
            actions=[ft.TextButton("关闭", on_click=lambda e: setattr(page.dialog, "open", False))],
        )
        page.open(page.dialog)
        page.update()

    def search_shaders(e=None):
        query = search_field.value.strip()
        if not query:
            page.snack_bar = SnackBar(Text("请输入关键词"))
            page.open(page.snack_bar)
            page.update()
            return
        # 显示加载动画
        shader_list.controls.clear()
        loading = ft.Row([
            ft.ProgressRing(width=40, height=40),
            ft.Text("正在搜索光影，请稍候...", theme_style="bodyMedium")
        ], alignment=ft.MainAxisAlignment.CENTER)
        shader_list.controls.append(loading)
        page.update()
        # 使用modrinth API搜索光影（project_type=shader）
        params = {"query": query, "limit": 20, "facets": "[[\"project_type:shader\"]]"}
        try:
            resp = session.get(MODRINTH_SEARCH_API, params=params, timeout=10)
        except Exception as ex:
            shader_list.controls.clear()
            shader_list.controls.append(Text(f"网络连接失败: {ex}"))
            page.update()
            return
        shader_list.controls.clear()
        if resp.status_code == 200:
            for shader in resp.json()["hits"]:
                shader_id = shader["project_id"]
                name = shader["title"]
                desc = shader.get("description", "")
                icon_url = shader.get("icon_url", "")
                files_api = f"https://api.modrinth.com/v2/project/{shader_id}/version"
                try:
                    v_resp = session.get(files_api, timeout=10)
                except Exception as ex:
                    shader_list.controls.append(Text(f"获取版本信息失败: {ex}"))
                    continue
                version_options = []
                version_files = []
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

                shader_item = Container(
                    content=Row([
                        Image(src=icon_url, width=40, height=40) if icon_url else IconButton(icon=Icons.DOWNLOAD),
                        Column([
                            Row([
                                Text(name, size=16, weight="bold"),
                                IconButton(icon=Icons.INFO_OUTLINED, tooltip="简介", on_click=(lambda n=name, d=desc: lambda e: show_shader_intro(n, d))()),
                            ]),
                            Text(desc, size=12, overflow="ellipsis"),
                            Row([
                                Text("选择版本:"),
                                version_dd,
                                ElevatedButton("下载", on_click=lambda e, files=version_files, dd=version_dd, pb=progress_bar: on_download_click(e, files, dd, pb)),
                                progress_bar
                            ])
                        ], expand=True),
                    ]),
                    padding=10,
                    bgcolor="#f5f5f5",
                    border_radius=8,
                )
                shader_list.controls.append(shader_item)
            page.update()
        else:
            shader_list.controls.append(Text("搜索失败，请重试。"))
            page.update()

    def on_folder_result(e: FilePickerResultEvent):
        if e.path and download_params:
            file_url = download_params.get("file_url")
            file_name = download_params.get("file_name")
            progress_bar = download_params.get("progress_bar")
            download_shader(file_url, file_name, page, progress_bar, e.path)
            download_params.clear()

    folder_picker.on_result = on_folder_result
    search_btn.on_click = search_shaders
    search_field.on_submit = search_shaders

    return ft.View(
        "/shader_download",
        [
            folder_picker,
            AppBar(title=Text("光影下载"), leading=IconButton(icon=Icons.ARROW_BACK, on_click=lambda e: page.go("/resources"))),
            Row([
                search_field,
                search_btn
            ], alignment=ft.MainAxisAlignment.START),
            shader_list
        ]
    )
