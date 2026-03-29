from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import flet as ft

from app.services.config_service import ConfigService


class VersionDirectoryPage:
    def __init__(self, page: ft.Page):
        self.page = page
        self.cfg = ConfigService()
        self.entries: list[dict[str, str]] = []
        self.selected_path: str | None = None
        self.list_view = ft.ListView(expand=True, spacing=8)
        self._file_picker = ft.FilePicker()

    def _navigate(self, route: str):
        async def do_navigate():
            await self.page.push_route(route)

        self.page.run_task(do_navigate)

    def _show_message(self, text: str):
        self.page.show_dialog(ft.SnackBar(ft.Text(text)))
        self.page.update()

    def _resolve_default_versions_root(self) -> Path:
        root = Path.home() / ".minecraft" / "versions"
        if not root.exists():
            candidates = [
                Path(r"E:/###游戏/Minecraft/.minecraft/versions"),
                Path(
                    r"C:/Users/%s/AppData/Roaming/.minecraft/versions"
                    % os.getenv("USERNAME", "")
                ),
                Path(r"D:/Minecraft/.minecraft/versions"),
            ]
            for p in candidates:
                if p.exists():
                    return p
        return root

    def _load_entries(self):
        cfg = self.cfg.load()
        raw_entries = cfg.get("VersionDirectoryEntries", [])
        entries: list[dict[str, str]] = []
        seen: set[str] = set()

        if isinstance(raw_entries, list):
            for item in raw_entries:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name", "")).strip()
                path = str(item.get("path", "")).strip()
                if not path:
                    continue
                norm = str(Path(path).expanduser())
                key = norm.lower()
                if key in seen:
                    continue
                seen.add(key)
                entries.append({"name": name or Path(norm).name or norm, "path": norm})

        if not entries:
            default_root = str(self._resolve_default_versions_root())
            entries = [{"name": "默认版本目录", "path": default_root}]

        self.entries = entries
        selected = cfg.get("SelectedVersionDirectoryPath")
        selected = str(selected).strip() if selected else ""
        exists = any(item["path"] == selected for item in self.entries)
        self.selected_path = selected if exists else self.entries[0]["path"]
        self._save_entries()

    def _save_entries(self):
        cfg = self.cfg.load()
        self.cfg.save(
            {
                **cfg,
                "VersionDirectoryEntries": self.entries,
                "SelectedVersionDirectoryPath": self.selected_path,
            }
        )

    def _open_path(self, path_value: str):
        target = Path(path_value)
        if not target.exists():
            self._show_message(f"目录不存在: {target}")
            return
        try:
            if os.name == "nt":
                os.startfile(target)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.run(["open", str(target)], check=False)
            else:
                subprocess.run(["xdg-open", str(target)], check=False)
        except Exception as ex:
            self._show_message(f"打开目录失败: {ex}")

    def _add_entry(self, path_value: str):
        norm = str(Path(path_value).expanduser())
        key = norm.lower()
        for item in self.entries:
            if item["path"].lower() == key:
                self._show_message("该目录已存在")
                return
        self.entries.append({"name": Path(norm).name or norm, "path": norm})
        self.selected_path = norm
        self._save_entries()
        self._rebuild_list()
        self._show_message(f"已添加目录: {norm}")

    async def _pick_directory(
        self,
        dialog_title: str,
        initial_directory: str | None = None,
    ) -> str | None:
        try:
            return await self._file_picker.get_directory_path(
                dialog_title=dialog_title,
                initial_directory=initial_directory,
            )
        except Exception as ex:
            self._show_message(f"无法打开系统目录选择器: {ex}")
            return None

    def _on_add_directory_click(self):
        async def do_pick():
            selected = await self._pick_directory("选择要添加的版本目录")
            if selected:
                self._add_entry(selected)

        self.page.run_task(do_pick)

    def _on_create_directory_click(self):
        async def do_create():
            parent = await self._pick_directory("选择新版本目录的父目录")
            if not parent:
                return

            name_field = ft.TextField(label="新目录名称", autofocus=True)

            def on_cancel(_):
                self.page.pop_dialog()

            def on_confirm(_):
                folder_name = (name_field.value or "").strip()
                if not folder_name:
                    self._show_message("请输入目录名称")
                    return
                self.page.pop_dialog()
                try:
                    target = Path(parent) / folder_name
                    target.mkdir(parents=True, exist_ok=False)
                    self._add_entry(str(target))
                    self._show_message(f"已新建版本目录: {target}")
                except FileExistsError:
                    self._show_message("目录已存在")
                except Exception as ex:
                    self._show_message(f"新建目录失败: {ex}")

            self.page.show_dialog(
                ft.AlertDialog(
                    modal=True,
                    title=ft.Text("新建版本目录"),
                    content=ft.Column(
                        [
                            ft.Text(f"父目录: {parent}", selectable=True),
                            name_field,
                        ],
                        tight=True,
                    ),
                    actions=[
                        ft.TextButton("取消", on_click=on_cancel),
                        ft.FilledButton("创建", on_click=on_confirm),
                    ],
                )
            )
            self.page.update()

        self.page.run_task(do_create)

    def _show_rename_dialog(self, path_value: str):
        item = next((x for x in self.entries if x["path"] == path_value), None)
        if item is None:
            self._show_message("目录配置不存在")
            return

        name_field = ft.TextField(label="目录名称", value=item["name"], autofocus=True)

        def on_cancel(_):
            self.page.pop_dialog()

        def on_confirm(_):
            new_name = (name_field.value or "").strip()
            if not new_name:
                self._show_message("请输入名称")
                return
            item["name"] = new_name
            self._save_entries()
            self._rebuild_list()
            self.page.pop_dialog()
            self._show_message("目录名称已更新")

        self.page.show_dialog(
            ft.AlertDialog(
                modal=True,
                title=ft.Text("命名目录"),
                content=name_field,
                actions=[
                    ft.TextButton("取消", on_click=on_cancel),
                    ft.FilledButton("保存", on_click=on_confirm),
                ],
            )
        )
        self.page.update()

    def _show_delete_dialog(self, path_value: str):
        item = next((x for x in self.entries if x["path"] == path_value), None)
        if item is None:
            self._show_message("目录配置不存在")
            return

        def on_cancel(_):
            self.page.pop_dialog()

        def on_confirm(_):
            self.page.pop_dialog()
            self.entries = [x for x in self.entries if x["path"] != path_value]
            if not self.entries:
                default_root = str(self._resolve_default_versions_root())
                self.entries = [{"name": "默认版本目录", "path": default_root}]
            if self.selected_path == path_value:
                self.selected_path = self.entries[0]["path"]
            self._save_entries()
            self._rebuild_list()
            self._show_message("目录配置已删除")

        self.page.show_dialog(
            ft.AlertDialog(
                modal=True,
                title=ft.Text("删除目录配置"),
                content=ft.Text("仅删除配置，不删除磁盘目录。是否继续？"),
                actions=[
                    ft.TextButton("取消", on_click=on_cancel),
                    ft.FilledButton("删除", on_click=on_confirm),
                ],
            )
        )
        self.page.update()

    def _set_current(self, path_value: str):
        self.selected_path = path_value
        self._save_entries()
        self._rebuild_list()
        self._show_message("已设置为当前版本目录")

    def _rebuild_list(self):
        self.list_view.controls.clear()
        for item in self.entries:
            is_current = item["path"] == self.selected_path
            self.list_view.controls.append(
                ft.Card(
                    content=ft.Container(
                        ft.Column(
                            [
                                ft.Row(
                                    [
                                        ft.Text(
                                            item["name"],
                                            size=18,
                                            weight=ft.FontWeight.BOLD,
                                        ),
                                        ft.Text(
                                            "当前",
                                            color=ft.Colors.GREEN_700,
                                            visible=is_current,
                                        ),
                                    ],
                                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                ),
                                ft.Text(item["path"], selectable=True),
                                ft.Row(
                                    [
                                        ft.OutlinedButton(
                                            "设为当前",
                                            icon=ft.Icons.CHECK,
                                            on_click=lambda _,
                                            p=item["path"]: self._set_current(p),
                                        ),
                                        ft.OutlinedButton(
                                            "打开",
                                            icon=ft.Icons.FOLDER_OPEN,
                                            on_click=lambda _,
                                            p=item["path"]: self._open_path(p),
                                        ),
                                        ft.OutlinedButton(
                                            "命名",
                                            icon=ft.Icons.DRIVE_FILE_RENAME_OUTLINE,
                                            on_click=lambda _,
                                            p=item["path"]: self._show_rename_dialog(p),
                                        ),
                                        ft.OutlinedButton(
                                            "删除",
                                            icon=ft.Icons.DELETE_OUTLINE,
                                            on_click=lambda _,
                                            p=item["path"]: self._show_delete_dialog(p),
                                        ),
                                    ],
                                    spacing=8,
                                ),
                            ],
                            spacing=8,
                        ),
                        padding=12,
                    )
                )
            )

        self.page.update()

    def build(self) -> ft.View:
        self._load_entries()
        self._rebuild_list()
        return ft.View(
            route="/version_dirs",
            controls=[
                self._file_picker,
                ft.AppBar(
                    title=ft.Text("版本目录管理"),
                    leading=ft.IconButton(
                        ft.Icons.ARROW_BACK,
                        on_click=lambda _: self._navigate("/"),
                    ),
                ),
                ft.Row(
                    [
                        ft.FilledButton(
                            "添加目录",
                            icon=ft.Icons.ADD_LINK,
                            on_click=lambda _: self._on_add_directory_click(),
                        ),
                        ft.FilledButton(
                            "新建版本目录",
                            icon=ft.Icons.CREATE_NEW_FOLDER,
                            on_click=lambda _: self._on_create_directory_click(),
                        ),
                        ft.OutlinedButton(
                            "查看版本列表",
                            icon=ft.Icons.LIST,
                            on_click=lambda _: self._navigate("/versions"),
                        ),
                    ],
                    spacing=10,
                ),
                self.list_view,
            ],
            scroll=ft.ScrollMode.AUTO,
        )
