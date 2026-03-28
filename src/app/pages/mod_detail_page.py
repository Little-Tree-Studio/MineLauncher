import flet as ft
import requests

MODRINTH_PROJECT_API = "https://api.modrinth.com/v2/project/"


# 详情页面，路由: /mod_download/{mod_id}
def mod_detail_page(page: ft.Page):
    mod_id = page.route.split("/")[-1]
    mod_info = None
    versions = []
    version_files = []
    version_options = []
    # selected_version not used
    folder_picker = ft.FilePicker()
    download_params = {}

    def navigate(route: str):
        async def do_navigate():
            await page.push_route(route)

        page.run_task(do_navigate)

    # 获取模组详情
    try:
        resp = requests.get(MODRINTH_PROJECT_API + mod_id, proxies={})
    except requests.exceptions.ProxyError as ex:
        return ft.View(
            route=f"/mod_download/{mod_id}",
            controls=[ft.Text(f"网络/代理错误: {ex}", size=20, color="red")],
        )
    except Exception as ex:
        return ft.View(
            route=f"/mod_download/{mod_id}",
            controls=[ft.Text(f"模组详情获取失败: {ex}", size=20, color="red")],
        )
    if resp.status_code == 200:
        mod_info = resp.json()
    else:
        return ft.View(
            route=f"/mod_download/{mod_id}",
            controls=[ft.Text("模组详情获取失败", size=20, color="red")],
        )
    # 获取所有版本
    try:
        v_resp = requests.get(MODRINTH_PROJECT_API + f"{mod_id}/version", proxies={})
    except requests.exceptions.ProxyError as ex:
        return ft.View(
            route=f"/mod_download/{mod_id}",
            controls=[ft.Text(f"网络/代理错误: {ex}", size=20, color="red")],
        )
    except Exception as ex:
        return ft.View(
            route=f"/mod_download/{mod_id}",
            controls=[ft.Text(f"模组版本获取失败: {ex}", size=20, color="red")],
        )
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

    async def on_download_click(e, files=version_files, dd=version_dd, pb=progress_bar):
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
            # 直接复用主页面下载逻辑
            from .mod_download_page import download_mod_version

            download_mod_version(file_url, file_name, page, pb, folder_path)
            download_params.clear()

    # 详情内容参考PCL，展示更多MODRINTH信息
    def on_return_click(e):
        if page.views:
            page.views.pop()
            top = page.views[-1] if page.views else None
            navigate(top.route if top else "/mod_download")
        else:
            navigate("/mod_download")

    # 分类
    categories = mod_info.get("categories", [])
    categories_str = ", ".join(categories) if categories else "无"
    # 支持的游戏版本
    game_versions = set()
    for v in versions:
        for gv in v.get("game_versions", []):
            game_versions.add(gv)
    game_versions_str = ", ".join(sorted(game_versions)) if game_versions else "未知"
    # 最新更新时间
    latest_update = mod_info.get("updated", "")
    # 项目网址
    project_url = mod_info.get("project_url", "")
    # 许可证
    license_str = mod_info.get("license", {}).get("name", "未知")
    # 依赖
    dependencies = mod_info.get("dependencies", [])
    dependencies_str = (
        ", ".join([d.get("version_id", "") for d in dependencies])
        if dependencies
        else "无"
    )

    return ft.View(
        route=f"/mod_download/{mod_id}",
        controls=[
            ft.Row(
                [
                    ft.Image(src=mod_info.get("icon_url", ""), width=64, height=64)
                    if mod_info.get("icon_url")
                    else ft.IconButton(icon=ft.Icons.DOWNLOAD),
                    ft.Column(
                        [
                            ft.Text(
                                mod_info.get("title", "未知模组"),
                                size=22,
                                weight="bold",
                            ),
                            ft.Text(mod_info.get("description", "暂无简介"), size=14),
                            ft.Text(
                                f"作者: {', '.join([a.get('name', '') for a in mod_info.get('authors', [])])}",
                                size=12,
                            ),
                            ft.Text(f"下载数: {mod_info.get('downloads', 0)}", size=12),
                            ft.Text(f"分类: {categories_str}", size=12),
                            ft.Text(f"支持游戏版本: {game_versions_str}", size=12),
                            ft.Text(f"最新更新时间: {latest_update}", size=12),
                            ft.Text(f"许可证: {license_str}", size=12),
                            ft.Text(f"依赖: {dependencies_str}", size=12),
                            ft.Text(f"项目网址: {project_url}", size=12, color="blue"),
                        ],
                        expand=True,
                    ),
                ],
                alignment=ft.MainAxisAlignment.START,
            ),
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
                ],
                alignment=ft.MainAxisAlignment.START,
            ),
            ft.Row(
                [ft.Button("返回", on_click=on_return_click)],
                alignment=ft.MainAxisAlignment.START,
            ),
        ],
    )
