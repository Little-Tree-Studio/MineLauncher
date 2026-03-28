import flet as ft
import requests
import os

MODRINTH_SEARCH_API = "https://api.modrinth.com/v2/search"
MODRINTH_PROJECT_API = "https://api.modrinth.com/v2/project/"


def download_mod_version(file_url, file_name, page, progress_bar, save_folder):
    save_path = os.path.join(save_folder, file_name)
    try:
        r = requests.get(file_url, stream=True)
        total = int(r.headers.get("content-length", 0))
        downloaded = 0
        with open(save_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total > 0:
                        progress_bar.value = downloaded / total
                        page.update()
        page.show_dialog(ft.SnackBar(ft.Text(f"下载完成: {file_name}")))
    except Exception as e:
        page.show_dialog(ft.SnackBar(ft.Text(f"下载失败: {e}")))
        progress_bar.value = 0
        page.update()


def mod_download_page(page: ft.Page):
    search_field = ft.TextField(
        label="搜索模组", width=600, border=ft.InputBorder.UNDERLINE
    )
    search_btn = ft.Button(
        "搜索",
        icon=ft.Icons.SEARCH,
        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=5)),
        height=40,
    )
    mod_list = ft.ListView(expand=True, spacing=10)
    folder_picker = ft.FilePicker()

    download_params = {}

    def navigate(route: str):
        async def do_navigate():
            await page.push_route(route)

        page.run_task(do_navigate)

    def show_mod_intro(mod_name, mod_desc):
        dlg = ft.AlertDialog(
            title=ft.Text(f"{mod_name} 简介"),
            content=ft.Text(mod_desc or "暂无简介"),
            actions=[ft.TextButton("关闭", on_click=lambda e: page.pop_dialog())],
        )
        page.show_dialog(dlg)
        page.update()

    def goto_mod_download(mod_id):
        # 跳转到模组下载详情页面，路由为 /mod_download/{mod_id}
        navigate(f"/mod_download/{mod_id}")

    def search_mods(e=None):
        query = search_field.value.strip()
        if not query:
            page.show_dialog(ft.SnackBar(ft.Text("请输入关键词")))
            page.update()
            return
        # 显示加载动画
        mod_list.controls.clear()
        loading = ft.Row(
            [
                ft.ProgressRing(width=40, height=40),
                ft.Text("正在搜索模组，请稍候...", theme_style="bodyMedium"),
            ],
            alignment=ft.MainAxisAlignment.CENTER,
        )
        mod_list.controls.append(loading)
        page.update()
        params = {"query": query, "limit": 20}
        resp = requests.get(MODRINTH_SEARCH_API, params=params)
        mod_list.controls.clear()
        if resp.status_code == 200:
            for mod in resp.json()["hits"]:
                mod_id = mod["project_id"]
                name = mod["title"]
                desc = mod.get("description", "")
                icon_url = mod.get("icon_url", "")
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
                    options=[
                        ft.dropdown.Option(text=opt, key=str(idx))
                        for idx, opt in enumerate(version_options)
                    ],
                    width=180,
                )
                progress_bar = ft.ProgressBar(width=120, value=0)

                async def on_download_click(
                    e, files=version_files, dd=version_dd, pb=progress_bar
                ):
                    idx = int(dd.value) if dd.value is not None else 0
                    if idx >= len(files):
                        page.show_dialog(ft.SnackBar(ft.Text("请选择版本")))
                        page.update()
                        return
                    file_url, file_name = files[idx]
                    pb.value = 0
                    page.update()
                    download_params.clear()
                    download_params["file_url"] = file_url
                    download_params["file_name"] = file_name
                    download_params["progress_bar"] = pb
                    # 使用异步方法获取目录路径
                    folder_path = await folder_picker.get_directory_path()
                    if folder_path:
                        download_mod_version(file_url, file_name, page, pb, folder_path)

                mod_item = ft.Container(
                    content=ft.Row(
                        [
                            ft.Image(src=icon_url, width=40, height=40)
                            if icon_url
                            else ft.IconButton(icon=ft.Icons.DOWNLOAD),
                            ft.Column(
                                [
                                    ft.Row(
                                        [
                                            ft.Text(name, size=16, weight="bold"),
                                            ft.IconButton(
                                                icon=ft.Icons.INFO_OUTLINED,
                                                tooltip="简介",
                                                on_click=(
                                                    lambda n=name,
                                                    d=desc: lambda e: show_mod_intro(
                                                        n, d
                                                    )
                                                )(),
                                            ),
                                        ]
                                    ),
                                    ft.Text(desc, size=12, overflow="ellipsis"),
                                    ft.Row(
                                        [
                                            ft.Text("选择版本:"),
                                            version_dd,
                                            ft.Button(
                                                "下载",
                                                on_click=lambda e,
                                                files=version_files,
                                                dd=version_dd,
                                                pb=progress_bar: page.run_task(
                                                    on_download_click, e, files, dd, pb
                                                ),
                                            ),
                                            progress_bar,
                                        ]
                                    ),
                                ],
                                expand=True,
                            ),
                        ]
                    ),
                    padding=10,
                    bgcolor="#f5f5f5",
                    border_radius=8,
                    on_click=lambda e, mid=mod_id: goto_mod_download(mid),
                )
                mod_list.controls.append(mod_item)
            page.update()
        else:
            mod_list.controls.append(ft.Text("搜索失败，请重试。"))
            page.update()

    search_btn.on_click = search_mods
    search_field.on_submit = search_mods

    return ft.View(
        route="/mod_download",
        controls=[
            ft.AppBar(
                title=ft.Text("Mod下载"),
                leading=ft.IconButton(
                    icon=ft.Icons.ARROW_BACK, on_click=lambda e: navigate("/resources")
                ),
            ),
            ft.Row([search_field, search_btn], alignment=ft.MainAxisAlignment.START),
            mod_list,
        ],
    )
