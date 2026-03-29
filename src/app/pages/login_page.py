from __future__ import annotations
from typing import Callable, Optional
import flet as ft
from app.services.account_service import (
    AccountService,
    LOGIN_LEGACY,
    LOGIN_NIDE,
    LOGIN_AUTHLIB,
    LOGIN_MICROSOFT,
)
from app.services.auth_service import AuthService
from app.services.i18n_service import I18nService
from app.services.logger_service import LoggerService


class LoginPage:
    def __init__(
        self, page: ft.Page, on_login_success: Optional[Callable[..., None]] = None
    ):
        self.page = page
        self.lang = I18nService("zh-cn")
        self.logger = LoggerService().logger
        self.account_service = AccountService()
        self.auth_service = AuthService()
        self.on_login_success = on_login_success
        self._selected_login_type = LOGIN_MICROSOFT
        self._loading = False
        self._accounts = self.account_service.get_accounts()

    def build(self) -> ft.View:
        self._account_list = ft.ListView(
            expand=True,
            spacing=10,
            controls=self._build_account_cards(),
        )

        self._login_content = ft.Container(
            content=self._build_microsoft_content(),
            border=ft.Border.all(1, ft.Colors.OUTLINE),
            border_radius=5,
            padding=15,
        )

        self._message_text = ft.Text("", color=ft.Colors.RED)

        self._tab_buttons = ft.Row(
            [
                ft.Button("Microsoft", on_click=self._show_microsoft_tab),
                ft.Button("离线登录", on_click=self._show_legacy_tab),
                ft.Button("服务器", on_click=self._show_server_tab),
            ],
        )

        return ft.View(
            route="/login",
            controls=[
                ft.AppBar(
                    leading=ft.IconButton(
                        icon=ft.Icons.ARROW_BACK,
                        on_click=self._go_back,
                    ),
                    title=ft.Text("登录账户"),
                ),
                ft.Column(
                    [
                        ft.Text("已保存的账户", size=16, weight=ft.FontWeight.BOLD),
                        ft.Container(
                            self._account_list,
                            height=200,
                            border=ft.Border.all(1, ft.Colors.OUTLINE),
                            border_radius=5,
                            padding=10,
                        ),
                        ft.Divider(),
                        ft.Text("添加新账户", size=16, weight=ft.FontWeight.BOLD),
                        self._tab_buttons,
                        self._login_content,
                        self._message_text,
                    ],
                    expand=True,
                    scroll=ft.ScrollMode.AUTO,
                ),
            ],
        )

    def _go_back(self, e):
        self.page.views.pop()
        self.page.update()

    def _build_account_cards(self) -> list:
        cards = []
        for account in self._accounts:
            type_names = {
                LOGIN_LEGACY: "离线",
                LOGIN_MICROSOFT: "Microsoft",
                LOGIN_NIDE: "Nide8",
                LOGIN_AUTHLIB: "Authlib",
            }
            type_name = type_names.get(account.type, "未知")

            def on_select(e, acc=account):
                self._login_with_account(acc)

            def on_delete(e, acc=account):
                self._confirm_delete_account(acc)

            card = ft.Card(
                content=ft.Container(
                    ft.Row(
                        [
                            ft.Column(
                                [
                                    ft.Text(
                                        account.username, weight=ft.FontWeight.BOLD
                                    ),
                                    ft.Text(
                                        f"{type_name} - {account.uuid[:8]}...",
                                        size=12,
                                        color=ft.Colors.GREY_600,
                                    ),
                                ],
                                expand=True,
                            ),
                            ft.IconButton(
                                icon=ft.Icons.LOGIN,
                                tooltip="登录",
                                on_click=on_select,
                            ),
                            ft.IconButton(
                                icon=ft.Icons.DELETE,
                                tooltip="删除",
                                on_click=on_delete,
                            ),
                        ],
                    ),
                    padding=10,
                ),
            )
            cards.append(card)

        if not cards:
            cards.append(
                ft.Card(
                    content=ft.Container(
                        ft.Text("暂无保存的账户", color=ft.Colors.GREY_600),
                        padding=10,
                    ),
                )
            )
        return cards

    def _build_microsoft_content(self) -> ft.Control:
        return ft.Column(
            [
                ft.Text("使用 Microsoft 账户登录 Minecraft"),
                ft.Text(
                    "将打开浏览器进行身份验证",
                    size=12,
                    color=ft.Colors.GREY_600,
                ),
                ft.FilledButton(
                    "使用 Microsoft 登录",
                    icon=ft.Icons.LOGIN,
                    on_click=lambda _: self._do_microsoft_login(),
                ),
            ],
        )

    def _build_legacy_content(self) -> ft.Control:
        self._legacy_username = ft.TextField(
            label="用户名",
            hint_text="输入游戏昵称",
            autofocus=True,
        )
        self._legacy_skin_slim = ft.Checkbox(label="纤细皮肤 (Alex)", value=False)

        return ft.Column(
            [
                self._legacy_username,
                self._legacy_skin_slim,
                ft.FilledButton(
                    "离线登录",
                    icon=ft.Icons.PLAY_CIRCLE,
                    on_click=self._do_legacy_login,
                ),
            ],
            spacing=10,
        )

    def _build_server_content(self) -> ft.Control:
        self._server_username = ft.TextField(
            label="用户名/邮箱",
            hint_text="输入用户名或邮箱",
        )
        self._server_password = ft.TextField(
            label="密码",
            hint_text="输入密码",
            password=True,
        )
        self._server_url = ft.TextField(
            label="服务器地址",
            hint_text="例如: https://auth.mc-user.com:233",
        )
        self._server_id = ft.TextField(
            label="服务器ID (Nide8)",
            hint_text="服务器标识符",
        )
        self._server_type_dd = ft.Dropdown(
            label="服务器类型",
            options=[
                ft.dropdown.Option("nide", "Nide8"),
                ft.dropdown.Option("authlib", "Authlib"),
            ],
            value="nide",
        )

        return ft.Column(
            [
                self._server_type_dd,
                self._server_url,
                self._server_id,
                self._server_username,
                self._server_password,
                ft.FilledButton(
                    "服务器登录",
                    icon=ft.Icons.DNS,
                    on_click=self._do_server_login,
                ),
            ],
            spacing=10,
        )

    def _show_microsoft_tab(self, e):
        self._login_content.content = self._build_microsoft_content()
        self._login_content.update()

    def _show_legacy_tab(self, e):
        self._login_content.content = self._build_legacy_content()
        self._login_content.update()

    def _show_server_tab(self, e):
        self._login_content.content = self._build_server_content()
        self._login_content.update()

    def _show_message(self, text: str, is_error: bool = True):
        self._message_text.value = text
        self._message_text.color = ft.Colors.RED if is_error else ft.Colors.GREEN
        self.page.show_dialog(ft.SnackBar(ft.Text(text)))
        self.page.update()

    def _set_loading(self, loading: bool):
        self._loading = loading
        self.page.update()

    def _invoke_login_success(self, result):
        callback = self.on_login_success
        if callback is not None:

            async def run_callback():
                assert callback is not None
                await callback(result)

            self.page.run_task(run_callback)

    def _do_legacy_login(self, e):
        username = self._legacy_username.value or ""
        if not username.strip():
            self._show_message("请输入用户名")
            return

        skin_type = "slim" if self._legacy_skin_slim.value else "classic"

        try:
            result = self.auth_service.legacy_login(username, skin_type)
            self._show_message(f"登录成功: {result.username}", is_error=False)
            self._accounts = self.account_service.get_accounts()
            self._invoke_login_success(result)
        except Exception as ex:
            self.logger.error(f"Legacy login failed: {ex}")
            self._show_message(f"登录失败: {ex}")

    def _do_microsoft_login(self):
        try:
            self._set_loading(True)
            self._show_message("正在打开浏览器进行验证...", is_error=False)
            result = self.auth_service.microsoft_login()
            self._show_message(f"登录成功: {result.username}", is_error=False)
            self._accounts = self.account_service.get_accounts()
            self._invoke_login_success(result)
        except Exception as ex:
            self.logger.error(f"Microsoft login failed: {ex}")
            self._show_message(f"登录失败: {ex}")
        finally:
            self._set_loading(False)

    def _do_server_login(self, e):
        username = self._server_username.value or ""
        password = self._server_password.value or ""
        base_url = self._server_url.value or ""
        server_id = self._server_id.value or ""

        if not all([username, password, base_url]):
            self._show_message("请填写所有必填字段")
            return

        login_type = (
            LOGIN_NIDE if self._server_type_dd.value == "nide" else LOGIN_AUTHLIB
        )

        try:
            self._set_loading(True)
            result = self.auth_service.server_login(
                username, password, base_url, server_id, login_type
            )
            self._show_message(f"登录成功: {result.username}", is_error=False)
            self._accounts = self.account_service.get_accounts()
            self._invoke_login_success(result)
        except Exception as ex:
            self.logger.error(f"Server login failed: {ex}")
            self._show_message(f"登录失败: {ex}")
        finally:
            self._set_loading(False)

    def _login_with_account(self, account):
        try:
            self._set_loading(True)
            result = self.auth_service.login_with_account(account)
            self._show_message(f"登录成功: {result.username}", is_error=False)
            self.account_service.set_last_account(account.account_id)
            self._invoke_login_success(result)
        except Exception as ex:
            self.logger.error(f"Account login failed: {ex}")
            self._show_message(f"登录失败: {ex}")
        finally:
            self._set_loading(False)

    def _confirm_delete_account(self, account):
        def on_confirm(e):
            self.page.views.pop()
            self.account_service.remove_account(account.account_id)
            self._accounts = self.account_service.get_accounts()
            self._account_list.controls = self._build_account_cards()
            self.page.update()

        def on_cancel(e):
            self.page.pop_dialog()

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("确认删除"),
            content=ft.Text(f"确定要删除账户 {account.username} 吗？"),
            actions=[
                ft.TextButton("取消", on_click=on_cancel),
                ft.FilledButton("删除", on_click=on_confirm),
            ],
        )
        self.page.show_dialog(dlg)
