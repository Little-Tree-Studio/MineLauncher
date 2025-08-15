import flet as ft
import requests
import os
from flet import TextField, ElevatedButton, ListView, Row, Column, Text, Image, ProgressBar, Container, icons, IconButton, SnackBar
MODRINTH_SEARCH_API = "https://api.modrinth.com/v2/search"
MODRINTH_PROJECT_API = "https://api.modrinth.com/v2/project/"

def download_mod(mod_id, page):
    # 获取最新版本文件
    files_api = f"https://api.modrinth.com/v2/project/{mod_id}/version"
    resp = requests.get(files_api)
    if resp.status_code != 200:
        page.snack_bar = SnackBar(Text("获取模组版本失败"))
        page.snack_bar.open = True
        page.update()
        return
    versions = resp.json()
    if not versions:
        page.snack_bar = SnackBar(Text("未找到可用版本"))
        page.snack_bar.open = True
        page.update()
        return
    file_url = versions[0]["files"][0]["url"]
    file_name = versions[0]["files"][0]["filename"]
    save_path = os.path.join("storage", "data", file_name)
    try:
        r = requests.get(file_url, stream=True)
        with open(save_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
        page.snack_bar = SnackBar(Text(f"下载完成: {file_name}"))
    except Exception as e:
        page.snack_bar = SnackBar(Text(f"下载失败: {e}"))
    page.snack_bar.open = True
    page.update()

def mod_download_page(page: ft.Page):
    search_field = TextField(label="搜索模组", width=300)
    search_btn = ElevatedButton("搜索")
    mod_list = ListView(expand=True, spacing=10)

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
                mod_item = Container(
                    content=Row([
                        Image(src=icon_url, width=40, height=40) if icon_url else IconButton(icon=icons.DOWNLOAD),
                        Column([
                            Text(name, size=16, weight="bold"),
                            Text(desc, size=12, overflow="ellipsis"),
                        ], expand=True),
                        ElevatedButton("下载", on_click=lambda e, mod_id=mod_id: download_mod(mod_id, page)),
                    ]),
                    padding=10,
                    bgcolor="#f5f5f5",
                    border_radius=8,
                )
                mod_list.controls.append(mod_item)
        else:
            mod_list.controls.append(Text("搜索失败，请重试。"))
        page.update()

    search_btn.on_click = search_mods
    search_field.on_submit = search_mods

    page.add(
        Row([
            search_field,
            search_btn
        ], alignment="center"),
        mod_list
    )


class ModDownloadPage:
    def __init__(self, page: ft.Page):
        self.page = page

    def build(self) -> ft.View:
        return ft.View("/mod_download", [mod_download_page(self.page)])
