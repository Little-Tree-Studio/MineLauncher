# MineLauncher 主应用
from __future__ import annotations
from pathlib import Path
import flet as ft
from app.services.logger_service import LoggerService
from app.services.config_service import ConfigService
from app.pages.first_run_page import FirstRunPage
from app.pages.home_page import HomePage
from app.pages.about_page import AboutPage
from app.pages.resources_page import ResourcesPage
from app.pages.core_download_page import CoreDownloadPage
from app.pages.mod_download_page import mod_download_page
from app.pages.mod_detail_page import mod_detail_page
from app.pages.settings_page import SettingsPage
from app.pages.version_directory_page import VersionDirectoryPage
from app.pages.download_settings_page import DownloadSettingsPage
from app.pages.versions_page import VersionsPage

ASSET_DIR = Path(__file__).parent.parent / "assets"


class App:
    def __init__(self):
        self.logger = LoggerService().logger
        self.cfg = ConfigService()
        self.first_run = not Path("MineLauncher/config/.inited").exists()

    def run(self):
        ft.run(self.main)

    async def main(self, page: ft.Page):
        page.title = "MineLauncher"
        # flet JSON encoder can't serialize pathlib.Path objects directly,
        # convert to string (file path) so it can be encoded.
        page.fonts = {"Sara": str(ASSET_DIR / "fonts" / "Sarasa UI SC.ttf")}
        page.theme = ft.Theme(font_family="Sara")
        page.theme_mode = (
            ft.ThemeMode.LIGHT
            if self.cfg.load().get("Theme", "light") == "light"
            else ft.ThemeMode.DARK
            if self.cfg.load().get("Theme", "light") == "dark"
            else ft.ThemeMode.SYSTEM
        )

        # 路由变化处理: 根据 page.route 构建对应视图
        def route_change(e: ft.RouteChangeEvent | None = None):
            # 只有在视图栈非空且当前顶视图路由与目标路由不同时，才尝试弹出
            # if page.views and page.views[-1].route != page.route:
            #     try:
            #         page.views.pop()
            #     except IndexError:
            #         pass

            # 仅在当前顶层视图已构建完成时才短路，避免命中 Flet 启动时的默认空视图。
            if page.views:
                top_view = page.views[-1]
                if top_view.route == page.route and len(top_view.controls) > 0:
                    page.update()
                    return

            try:
                # 对于顶层路由（主页、关于等），清空视图栈并重新建立；对于子页面（例如模组详情）则在栈上追加，保留之前的搜索页状态
                if not page.route.startswith("/mod_download/"):
                    page.views.clear()

                self.logger.debug(
                    f"导航至 {page.route}，当前视图栈长度: {len(page.views)}"
                )
                if page.route == "/start":

                    async def go_home():
                        await page.push_route("/")

                    page.views.append(FirstRunPage(go_home).build())
                elif page.route == "/about":
                    page.views.append(AboutPage(page).build())
                elif page.route == "/resources":
                    page.views.append(ResourcesPage(page).build())
                elif page.route == "/core_download":
                    page.views.append(CoreDownloadPage(page).build())
                elif page.route == "/mod_download":
                    page.views.append(mod_download_page(page))
                elif page.route == "/shader_download":
                    from app.pages.shader_download_page import shader_download_page

                    page.views.append(shader_download_page(page))
                elif page.route.startswith("/mod_download/"):
                    page.views.append(mod_detail_page(page))
                elif page.route == "/settings":
                    page.views.append(SettingsPage(page).build())
                elif page.route == "/java_settings":
                    from app.pages.java_settings_page import JavaSettingsPage

                    page.views.append(JavaSettingsPage(page).build())
                elif page.route == "/download_manager":
                    from app.pages.download_manager_page import download_manager_page

                    page.views.append(download_manager_page(page))
                elif page.route == "/download_settings":
                    page.views.append(DownloadSettingsPage(page).build())
                elif page.route == "/version_dirs":
                    page.views.append(VersionDirectoryPage(page).build())
                elif page.route == "/versions":
                    page.views.append(VersionsPage(page).build())
                else:  # 默认主页
                    page.views.clear()
                    home_view = HomePage(page).build()
                    self.logger.debug(f"主页视图控件数量: {len(home_view.controls)}")
                    page.views.append(home_view)

                page.update()
            except Exception:
                self.logger.exception(f"route_change 处理失败，当前路由: {page.route}")
                raise

        # 返回上一视图（例如浏览器后退）
        async def view_pop(e):
            # 安全弹出：仅当有视图时弹出
            if page.views:
                try:
                    page.views.pop()
                except IndexError:
                    pass

            top = page.views[-1] if page.views else None
            await page.push_route(top.route if top else "/")

        page.on_route_change = route_change
        page.on_view_pop = view_pop

        # 初始化路由
        self.logger.debug("初始化路由")
        route_change()
        self.logger.debug(f"路由初始化完成，视图栈长度: {len(page.views)}")

        if self.first_run:
            Path("MineLauncher/config/.inited").touch()
            page.route = "/start"
            route_change()
        else:
            page.route = "/"
            route_change()

        self.logger.debug(f"路由设置完成: {page.route}，视图栈长度: {len(page.views)}")
        page.update()
