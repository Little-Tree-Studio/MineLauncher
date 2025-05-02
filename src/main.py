import flet as ft
import yaml

VER = "0.1.0"

lang = "en-us"

with open(f"lang/{lang}.yaml", encoding="utf-8") as f:
    lang_data = yaml.safe_load(f)

def start(e):
    print(e)
def main(page: ft.Page):
    page.title = "MineLauncher"
    page.fonts = {
        "Sarasa UI SC": "assets/fonts/Sarasa UI SC.ttf",
    }
    page.theme = ft.Theme(font_family="Sarasa UI SC")
    dlg_about = ft.AlertDialog(
        modal=True,
        title=ft.Text("关于"),
        content=ft.Text(f"这是测试 ， 测试 ，测试\n V1111111 \n {VER}"),
        actions=[
            ft.TextButton("关闭", on_click=lambda e: page.close(dlg_about)),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )

    page.appbar = ft.AppBar(
        leading=ft.Icon(ft.Icons.HOME),
        leading_width=40,
        title=ft.Text("MineLauncher"),
        center_title=False,
        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
        actions=[
            ft.IconButton(ft.Icons.INFO,on_click=lambda e: page.open(dlg_about)),

        ],
    )

    t = ft.Text(value=lang_data["start"]["hello"], size=20)
    page.controls.append(t)


    page.add(
    ft.Row(controls=[
        ft.ElevatedButton(text=lang_data["start"]["start"],on_click=start)
    ])
)
    page.update()

ft.app(main)