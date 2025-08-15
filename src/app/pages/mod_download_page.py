import flet as ft
import requests
import os
from flet import TextField, ElevatedButton, ListView, Row, Column, Text, Image, ProgressBar, Container, icons, IconButton, SnackBar, FilePicker, FilePickerResultEvent
MODRINTH_SEARCH_API = "https://api.modrinth.com/v2/search"
MODRINTH_PROJECT_API = "https://api.modrinth.com/v2/project/"


# 下载指定版本并显示进度条

# 下载指定版本并显示进度条，支持自定义保存路径
def download_mod_version(file_url, file_name, page, progress_bar, save_folder):
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



def mod_download_page(page: ft.Page):
    search_field = TextField(label="搜索模组", width=300)
    search_btn = ElevatedButton("搜索")
    mod_list = ListView(expand=True, spacing=10)
    folder_picker = FilePicker()
    page.overlay.append(folder_picker)
    # 用于存储当前下载参数
    download_params = {}

    def search_mods(e=None):
        query = search_field.value.strip()
        if not query:
            page.snack_bar = SnackBar(Text("请输入关键词"))
            page.snack_bar.open = True
            page.update()
            return
        params = {"query": query, "limit": 20}
        resp = requests.get(MODRINTH_SEARCH_API, params=params)
        mod_list.controls.clear()
        if resp.status_code == 200:
            results = resp.json().get("hits", [])
            for mod in results:
                mod_id = mod["project_id"]
                name = mod["title"]
                desc = mod.get("description", "")
                icon_url = mod.get("icon_url", "")
                # 获取所有版本
                files_api = f"https://api.modrinth.com/v2/project/{mod_id}/version"
                v_resp = requests.get(files_api)
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
                    # 记录参数，弹出文件夹选择
                    download_params.clear()
                    download_params["file_url"] = file_url
                    download_params["file_name"] = file_name
                    download_params["progress_bar"] = pb
                    folder_picker.get_directory_path()

                mod_item = Container(
                    content=Row([
                        Image(src=icon_url, width=40, height=40) if icon_url else IconButton(icon=icons.DOWNLOAD),
                        Column([
                            Text(name, size=16, weight="bold"),
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
                mod_list.controls.append(mod_item)
        else:
            mod_list.controls.append(Text("搜索失败，请重试。"))
        page.update()

    def on_folder_result(e: FilePickerResultEvent):
        if e.path and download_params:
            file_url = download_params.get("file_url")
            file_name = download_params.get("file_name")
            progress_bar = download_params.get("progress_bar")
            download_mod_version(file_url, file_name, page, progress_bar, e.path)
            download_params.clear()

    folder_picker.on_result = on_folder_result
    search_btn.on_click = search_mods
    search_field.on_submit = search_mods

    page.add(
        Row([
            search_field,
            search_btn
        ], alignment="center"),
        mod_list
    )

# 入口函数
def main(page: ft.Page):
    mod_download_page(page)

if __name__ == "__main__":
    ft.app(target=main)


class ModDownloadPage:
    def __init__(self, page: ft.Page):
        self.page = page

    def build(self) -> ft.View:
        return ft.View("/mod_download", [])
