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
    "안녕하세요",  # 韩语
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


def create_file(file_name):
    if not os.path.exists(file_name):
        with open(file_name, "w", encoding="utf-8") as f:
            f.write("")

def list_files_in_folder(folder_path):
    if os.path.exists(folder_path) and os.path.isdir(folder_path):
        files = os.listdir(folder_path)
        return files
    else:
        logging.ERROR(
            f"[函数-列出文件夹下文件]路径 {folder_path} 不存在或不是一个文件夹"
        )
        return []


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

if os.path.exists("lang") is not True:
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
except Exception as e:
    logging.error(f"文件夹和文件初始化失败：{e}")
    messagebox.showerror("Fatal error", "Failed to initialize folder and file")
    exit(1)

logging.info("文件夹和文件初始化成功")
def get_lang(lang):
    try:
        with open(f"lang/{lang}.yaml", encoding="utf-8") as f:
            lang_data = yaml.safe_load(f)
    except Exception as e:
        logging.error(f"语言文件加载失败：{e}")
    return lang_data
lang_data = get_lang("zh-cn")

logging.info("语言文件加载成功")


def start(e):
    print(e)

flag_hello = True
def change_hello_text(text_controls):
    while flag_hello:
        for i in HELLO:
            time.sleep(1)
            text_controls.value = i
            text_controls.update()


def main(page: ft.Page):
    page.title = "MineLauncher"
    page.fonts = {
        "Sarasa UI SC": "assets/fonts/Sarasa UI SC.ttf",
    }
    page.theme = ft.Theme(font_family="Sarasa UI SC")

    # 关于对话框
    dlg_about = ft.AlertDialog(
        modal=True,
        title=ft.Text("关于"),
        content=ft.Text(f"这是测试 ， 测试 ，测试\n V1111111 \n {VER}"),
        actions=[
            ft.TextButton("关闭", on_click=lambda e: page.close(dlg_about)),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )

    # 语言选择页面
    def change_language(e):
        global lang_data
        lang_data = get_lang(e.data)
        
        logging.info(f"切换语言为 {e.data}")
        set_language_label.value = lang_data["start"]["set_language"]
        page.update()


    def change_page(index):
        tabs.selected_index = index
        tabs.update()
    set_language_label = ft.Text(lang_data["start"]["set_language"], size=30)
    language_page = ft.Column(
        controls=[
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
        ],
        alignment=ft.MainAxisAlignment.CENTER,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
    )

    # 主页面
    hello = ft.Text(value="你好", size=40)
    main_page = ft.Column(
        spacing=400,
        controls=[
            ft.Row([hello], ft.MainAxisAlignment.CENTER),
            ft.Row(
                controls=[
                    ft.IconButton(ft.Icons.NAVIGATE_NEXT, icon_size=50, on_click=lambda e: change_page(1)),
                ],
                alignment=ft.MainAxisAlignment.END,  # 水平靠右
                run_spacing=1000,
            ),
        ],
        expand=True,
    )

    # 分页
    tabs = ft.Tabs(
        selected_index=0,
        tabs=[
            ft.Tab(text="主页", content=main_page),
            ft.Tab(text="语言", content=language_page),
        ],
        expand=True,
    )



    page.add(tabs)
    page.update()

    # 启动后台线程更新文本
    threading.Thread(target=change_hello_text, args=(hello,), daemon=True).start()

ft.app(main)