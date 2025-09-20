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

ASSET_DIR = Path(__file__).parent.parent / "assets"


class App:
    def __init__(self):
        self.logger = LoggerService().logger
        self.cfg = ConfigService()
        self.first_run = not Path("MineLauncher/config/.inited").exists()

    def run(self):
        ft.app(target=self.main)

    def main(self, page: ft.Page):
        page.title = "MineLauncher"
        # flet JSON encoder can't serialize pathlib.Path objects directly,
        # convert to string (file path) so it can be encoded.
        page.fonts = {"Sara": str(ASSET_DIR / "fonts" / "Sarasa UI SC.ttf")}
        page.theme = ft.Theme(font_family="Sara")
        # 路由变化处理: 根据 page.route 构建对应视图
        def route_change(e: ft.RouteChangeEvent):
            # 只有在视图栈非空且当前顶视图路由与目标路由不同时，才尝试弹出
            if page.views and page.views[-1].route != page.route:
                try:
                    page.views.pop()
                except IndexError:
                    pass

            # 如果视图栈中已存在目标路由，直接更新即可（避免重建导致状态丢失）
            for v in page.views:
                if v.route == page.route:
                    page.update()
                    return


            # 对于顶层路由（主页、关于等），清空视图栈并重新建立；对于子页面（例如模组详情）则在栈上追加，保留之前的搜索页状态
            # if not page.route.startswith("/mod_download/"):
            #     page.views.clear()
            
            
            print(f"导航至 {page.route}，当前视图栈长度: {len(page.views)}")
            if page.route == "/start":
                page.views.append(FirstRunPage(lambda: page.go("/")).build())
            elif page.route == "/about":
                page.views.append(AboutPage(page).build())
            elif page.route == "/resources":
                page.views.append(ResourcesPage(page).build())
            elif page.route == "/core_download":
                page.views.append(CoreDownloadPage(page).build())
            elif page.route == "/mod_download":
                page.views.append(mod_download_page(page))
            elif page.route.startswith("/mod_download/"):
                page.views.append(mod_detail_page(page))
            elif page.route == "/settings":
                page.views.append(SettingsPage(page).build())
            else:  # 默认主页
                page.views.clear()
                page.views.append(HomePage(page).build())

            page.update()

        # 返回上一视图（例如浏览器后退）
        def view_pop(e: ft.ViewPopEvent):
            # 安全弹出：仅当有视图时弹出
            if page.views:
                try:
                    page.views.pop()
                except IndexError:
                    pass

            top = page.views[-1] if page.views else None
            page.go(top.route if top else "/")

        page.on_route_change = route_change
        page.on_view_pop = view_pop

        if self.first_run:
            Path("MineLauncher/config/.inited").touch()
            page.go("/start")
        else:
            page.go("/")
