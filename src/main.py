import flet as ft
import yaml
import json
import os
import logging
import datetime
import time
import threading
from tkinter import messagebox

VER = "0.1.0"
HELLO = [
    "你好",  # 汉语
    "Hello",  # 英语
    "Bonjour",  # 法语
    "Guten Tag",  # 德语
    "こんにちは",  # 日语
    "안녕하세요",  # 朝鲜语
    "Hola",  # 西班牙语
    "Olá",  # 葡萄牙语
    "Ciao",  # 意大利语
    "Здравствуйте",  # 俄语
    "สวัสดี",  # 泰语
    "Halo",  # 印尼语
    "Hai",  # 马来语
    "Hallo",  # 荷兰语
    "Γεια σας",  # 希腊语
    "Merhaba",  # 土耳其语
    "مرحبا",  # 阿拉伯语
    "Hej",  # 瑞典/丹麦语
    "Szia",  # 匈牙利语
    "Witają",  # 波兰语
    "Привіт",  # 乌克兰语
    "नमस्ते",  # 印地语
    "ہیلو",  # 乌尔都语
    "Sawubona",  # 祖鲁语
]


start_time = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


def create_folder(folder_name):
    if not os.path.exists(folder_name):
        os.makedirs(folder_name)


def cleanup_file(file_name):
    if os.path.exists(file_name):
        with open(file_name, "w", encoding="utf-8") as f:
            f.write("")


def create_file(file_name):
    if not os.path.exists(file_name):
        with open(file_name, "w", encoding="utf-8") as f:
            f.write("")


def list_files_in_folder(folder_path):
    if os.path.exists(folder_path) and os.path.isdir(folder_path):
        files = os.listdir(folder_path)
        return files
    else:
        logging.error(
            f"[函数-列出文件夹下文件]路径 {folder_path} 不存在或不是一个文件夹"
        )
        return []


if os.path.exists("MineLauncher") is not True:
    first_run = True
else:
    first_run = False

if os.path.exists("assets/lang") is not True:
    logging.error("语言文件夹不存在")
    messagebox.showerror("Fatal error", "The language folder does not exist")
    exit(1)
try:
    create_folder(".minecraft")
    create_folder("MineLauncher")
    create_folder("MineLauncher/log")
    create_folder("MineLauncher/temp")
    create_folder("MineLauncher/download")
    create_folder("MineLauncher/config")

    create_file("MineLauncher/config/config.json")
    create_file("MineLauncher/log/latest.log")
    create_file(f"MineLauncher/log/log_{start_time}.log")

    cleanup_file("MineLauncher/log/latest.log")
except Exception as e:
    logging.error(f"文件夹和文件初始化失败：{e}")
    messagebox.showerror("Fatal error", "Failed to initialize folder and file")
    exit(1)

# 日志初始化
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("MineLauncher/log/latest.log", encoding="utf-8"),
        logging.FileHandler(f"MineLauncher/log/log_{start_time}.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)

logging.info("日志初始化成功")
logging.info("文件夹和文件初始化成功")


def get_lang(lang):
    try:
        with open(f"assets/lang/{lang}.yaml", encoding="utf-8") as f:
            lang_data = yaml.safe_load(f)
    except Exception as e:
        logging.error(f"语言文件加载失败：{e}")
    return lang_data


logging.info("语言文件加载成功")


def save_config(config):
    with open("MineLauncher/config/config.json", "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4)
        logging.info("配置文件保存成功")


def read_config():
    try:
        with open("MineLauncher/config/config.json", "r", encoding="utf-8") as f:
            config = json.load(f)
            logging.info("配置文件读取成功")
            return config
    except Exception as e:
        logging.error(f"配置文件读取失败：{e}")


def generate_config():
    try:
        with open("MineLauncher/config/config.json", "w", encoding="utf-8") as f:
            config = {
                "Language": "zh-cn",
            }
            json.dump(config, f, ensure_ascii=False, indent=4)
            logging.info("配置文件生成成功")
            return config
    except Exception as e:
        logging.error(f"配置文件生成失败：{e}")
        return None


config = read_config()
if config is None:
    logging.warning("配置文件为空或读取错误，即将重新生成配置文件")
    config = generate_config()
    if config is None:
        logging.error("配置文件生成失败，请检查权限和路径")
        messagebox.showerror("错误", "配置文件生成失败，请检查权限和路径")
        exit()

lang_data = get_lang(config["Language"])


def change_hello_text(text_controls):
    while 1:
        for i in HELLO:
            time.sleep(1)
            try:
                text_controls.value = i
                text_controls.update()
            except AssertionError:
                break


def main(page: ft.Page):
    page.title = "MineLauncher"
    page.fonts = {
        "Sarasa UI SC": "assets/fonts/Sarasa UI SC.ttf",
    }
    page.theme = ft.Theme(font_family="Sarasa UI SC")

    def route_change(e):
        page.views.clear()
        page.views.append(
            ft.View(
                "/",
                [
                    ft.Column(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        controls=[
                            ft.Row(
                                [
                                    # ft.IconButton(icon=ft.Icons.INFO),
                                    ft.Text(value="MineLauncher", size=45),
                                    ft.Column(
                                        controls=[
                                            ft.Row(
                                                controls=[
                                                    ft.Placeholder(
                                                        fallback_height=20,
                                                        fallback_width=20,
                                                    ),
                                                    ft.Text("zs_xiaoshu"),
                                                ]
                                            ),
                                            ft.Button(
                                                icon=ft.Icons.PEOPLE,
                                                text=lang_data["home"][
                                                    "account_settings"
                                                ],
                                            ),
                                        ],
                                        horizontal_alignment=ft.CrossAxisAlignment.END,
                                    ),
                                ],
                                ft.MainAxisAlignment.SPACE_BETWEEN,
                            ),
                            ft.Column(
                                alignment=ft.MainAxisAlignment.CENTER,
                                controls=[
                                    ft.Card(
                                        content=ft.Container(
                                            content=ft.Column(
                                                controls=[
                                                    ft.Text(
                                                        "新闻",
                                                        size=20,
                                                        weight=ft.FontWeight.BOLD,
                                                    ),
                                                    ft.Text(
                                                        "标题",
                                                    ),
                                                ]
                                            ),
                                            padding=10,
                                            width=300,
                                            height=100,
                                        )
                                    )
                                ],
                                scroll=ft.ScrollMode.AUTO,
                                expand=True,
                            ),
                            ft.Row(
                                controls=[
                                    ft.Row(
                                        controls=[
                                            ft.Button(
                                                lang_data["home"]["version_list"],
                                                icon=ft.Icons.LIST,
                                            )
                                        ]
                                    ),
                                    ft.ElevatedButton(
                                        lang_data["test"]["test"],
                                        ft.Icons.SCIENCE,
                                        on_click=lambda _: page.go("/test"),
                                    ),
                                    ft.Card(
                                        content=ft.Container(
                                            content=ft.Column(
                                                [
                                                    ft.Row(
                                                        [
                                                            ft.Image(
                                                                "assets/image/grass.png",
                                                                width=30,
                                                                height=30,
                                                            ),
                                                            ft.Text("MineCraft 1.20.1"),
                                                        ]
                                                    ),
                                                    ft.Row(
                                                        [
                                                            ft.TextButton(
                                                                lang_data["home"][
                                                                    "game"
                                                                ]["config"],
                                                                icon=ft.Icons.SETTINGS,
                                                                style=ft.ButtonStyle(
                                                                    shape=ft.RoundedRectangleBorder(
                                                                        radius=5
                                                                    )
                                                                ),
                                                            ),
                                                            ft.FilledButton(
                                                                lang_data["home"][
                                                                    "game"
                                                                ]["launch"],
                                                                icon=ft.Icons.PLAY_ARROW,
                                                                style=ft.ButtonStyle(
                                                                    shape=ft.RoundedRectangleBorder(
                                                                        radius=5
                                                                    )
                                                                ),
                                                            ),
                                                        ],
                                                        alignment=ft.MainAxisAlignment.END,
                                                    ),
                                                ]
                                            ),
                                            width=300,
                                            padding=10,
                                        ),
                                    ),
                                ],
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                vertical_alignment=ft.CrossAxisAlignment.END,
                            ),
                        ],
                        expand=True,
                    ),
                    ft.AppBar(
                        leading=ft.Image("assets/image/icon.png"),
                        title=ft.Text("MineLauncher"),
                        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
                        actions=[
                            ft.TextButton(
                                lang_data["home"]["top"]["resource_center"],
                                icon=ft.Icons.SHOPPING_BASKET,
                            ),
                            ft.TextButton(
                                lang_data["home"]["top"]["download_management"],
                                icon=ft.Icons.DOWNLOAD,
                            ),
                            ft.VerticalDivider(),
                            ft.TextButton(
                                lang_data["home"]["top"]["settings"],
                                icon=ft.Icons.SETTINGS,
                            ),
                            ft.TextButton(
                                lang_data["home"]["top"]["about"],
                                icon=ft.Icons.INFO,
                                on_click=lambda _: page.go("/about"),
                            ),
                        ],
                    ),
                ],
            )
        )

        if page.route == "/start":
            page.views.append(
                ft.View(
                    "/start",
                    [tabs],
                )
            )
        elif page.route == "/OOBE":
            page.views.append(
                ft.View(
                    "/OOBE",
                    [
                        ft.Tabs(
                            [
                                ft.Tab(
                                    text=lang_data["OOBE"]["tab1"],
                                    icon=ft.Icons.NETWORK_WIFI,
                                    content=ft.Row(
                                        controls=[
                                            ft.Text("OOBE"),
                                            ft.IconButton(
                                                ft.Icons.DONE,
                                                on_click=lambda _: page.go("/"),
                                            ),
                                        ]
                                    ),
                                ),
                            ],
                            selected_index=0,
                            expand=True,
                        ),
                    ],
                )
            )
        elif page.route == "/test":
            page.views.append(
                ft.View(
                    "/",
                    [
                        ft.AppBar(
                            leading=ft.Image("assets/image/icon.png"),
                            title=ft.Text("MineLauncher"),
                            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
                        ),
                        ft.ElevatedButton(
                            lang_data["test"]["test1"],
                            ft.Icons.SCIENCE,
                            on_click=lambda _: page.go("/start"),
                        ),
                        ft.ElevatedButton(
                            lang_data["test"]["test2"],
                            ft.Icons.SCIENCE,
                            on_click=lambda _: page.go("/OOBE"),
                        ),
                        ft.IconButton(
                            ft.Icons.HOME, icon_size=50, on_click=lambda _: page.go("/")
                        ),
                    ],
                )
            )
        elif page.route == "/about":
            page.views.append(
                ft.View(
                    "/about",
                    [
                        ft.ElevatedButton(
                            "返回", on_click=lambda _: page.go("/"), icon=ft.Icons.HOME
                        ),
                        ft.Text(lang_data["about"]["title"], size=30),
                        ft.Text(
                            lang_data["about"]["description"],
                        ),
                    ],
                )
            )
        page.update()

    # 语言选择页面
    def change_language(e):
        global lang_data
        lang_data = get_lang(e.data)

        config["Language"] = e.data
        save_config(config)

        logging.info(f"切换语言为 {e.data}")
        set_language_label.value = lang_data["start"]["set_language"]

        page.update()

    def change_page(index):
        tabs.selected_index = index
        tabs.update()

    set_language_label = ft.Text(lang_data["start"]["set_language"], size=30)
    language_page = ft.Column(
        controls=[
            ft.Icon(name=ft.Icons.LANGUAGE, size=100, grade=1),
            set_language_label,
            ft.Dropdown(
                options=[
                    ft.dropdown.Option("zh-cn", "中文"),
                    ft.dropdown.Option("en", "English"),
                    ft.dropdown.Option("ja", "日本語"),
                    ft.dropdown.Option("ko", "한국어"),
                ],
                on_change=change_language,
                value="zh-cn",
            ),
            ft.Row(
                controls=[
                    ft.IconButton(
                        ft.Icons.DONE, icon_size=50, on_click=lambda e: page.go("/OOBE")
                    ),
                ],
                alignment=ft.MainAxisAlignment.END,
            ),
        ],
        spacing=30,
        alignment=ft.MainAxisAlignment.CENTER,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
    )

    hello = ft.Text(value="你好", size=35)
    main_page = ft.Column(
        alignment=ft.MainAxisAlignment.SPACE_AROUND,
        controls=[
            ft.Row(
                [ft.Text(value="MineLauncher", size=45)], ft.MainAxisAlignment.CENTER
            ),
            ft.Row(
                [ft.Icon(ft.Icons.WAVING_HAND, size=45), hello],
                ft.MainAxisAlignment.CENTER,
            ),
            ft.Row(
                controls=[
                    ft.IconButton(
                        ft.Icons.NAVIGATE_NEXT,
                        icon_size=50,
                        on_click=lambda e: change_page(1),
                    ),
                ],
                alignment=ft.MainAxisAlignment.END,
            ),
        ],
        expand=True,
    )

    # 分页
    tabs = ft.Tabs(
        selected_index=0,
        tabs=[
            ft.Tab(content=main_page, icon=ft.Icons.HOME),
            ft.Tab(content=language_page, icon=ft.Icons.LANGUAGE),
        ],
        expand=True,
    )

    def view_pop(e):
        page.views.pop()
        top_view = page.views[-1]
        page.go(top_view.route)

    page.on_route_change = route_change
    page.on_view_pop = view_pop

    page.update()
    if first_run:
        page.go("/start")
    else:
        page.go("/")
    threading.Thread(target=change_hello_text, args=(hello,), daemon=True).start()


ft.app(main)
