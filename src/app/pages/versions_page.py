from __future__ import annotations
import time
import flet as ft
from pathlib import Path
from app.services.utils_service import UtilsService
from app.services.version_detector import VersionDetector, McInstanceState, Version


class VersionsPage:
    def __init__(self, page: ft.Page):
        self.page = page
        self.root = Path(r"E:/###游戏/Minecraft/.minecraft/versions")
        self.detector = VersionDetector(self.root)

    def build(self) -> ft.View:
        versions_card = []
        start_time = time.time()

        all_versions = self.detector.detect_all()

        for folder, info in sorted(
            all_versions.items(),
            key=lambda x: x[1].vanilla_version or Version(0, 0, 0),
            reverse=True,
        ):
            state_icons = {
                McInstanceState.Original: "🌿",
                McInstanceState.Snapshot: "📦",
                McInstanceState.Old: "🏛️",
                McInstanceState.Fool: "🎃",
                McInstanceState.Forge: "⚒️",
                McInstanceState.NeoForge: "🔨",
                McInstanceState.Fabric: "🧵",
                McInstanceState.LiteLoader: "🥚",
                McInstanceState.OptiFine: "✨",
                McInstanceState.Error: "❌",
                McInstanceState.Unknown: "❓",
            }

            icon = state_icons.get(info.state, "❓")

            loader_info = self._get_loader_info(info)
            if loader_info:
                main_text = f"{icon} {folder} - {info.vanilla_name} ({loader_info})"
            else:
                main_text = f"{icon} {folder} - {info.vanilla_name}"

            tooltip_text = ""
            if info.release_time:
                tooltip_text += f"发布时间: {info.release_time}"
            if info.has_forge and info.forge_version:
                tooltip_text += (
                    f"\nForge: {info.forge_version}"
                    if tooltip_text
                    else f"Forge: {info.forge_version}"
                )
            if info.has_neoforge and info.neoforge_version:
                tooltip_text += (
                    f"\nNeoForge: {info.neoforge_version}"
                    if tooltip_text
                    else f"NeoForge: {info.neoforge_version}"
                )
            if info.has_fabric and info.fabric_version:
                tooltip_text += (
                    f"\nFabric: {info.fabric_version}"
                    if tooltip_text
                    else f"Fabric: {info.fabric_version}"
                )
            if (
                info.has_optifine
                and info.optifine_version
                and info.optifine_version != "未知版本"
            ):
                tooltip_text += (
                    f"\nOptiFine: {info.optifine_version}"
                    if tooltip_text
                    else f"OptiFine: {info.optifine_version}"
                )

            versions_card.append(
                ft.Card(
                    content=ft.Container(
                        ft.Text(main_text, size=14),
                        padding=10,
                        tooltip=tooltip_text if tooltip_text else None,
                    ),
                    elevation=2,
                )
            )

        end_time = time.time()
        print(f"读取版本列表耗时: {end_time - start_time:.2f} 秒")

        return ft.View(
            "/versions",
            [
                ft.Text("版本管理", size=30, weight=ft.FontWeight.BOLD),
                *versions_card,
            ],
            scroll=ft.ScrollMode.AUTO,
        )

    def _get_loader_info(self, info) -> str:
        if info.state == McInstanceState.Forge and info.forge_version:
            return f"Forge {info.forge_version}"
        if info.state == McInstanceState.NeoForge and info.neoforge_version:
            return f"NeoForge {info.neoforge_version}"
        if info.state == McInstanceState.Fabric and info.fabric_version:
            return f"Fabric {info.fabric_version}"
        if info.state == McInstanceState.OptiFine:
            parts = []
            if info.optifine_version and info.optifine_version != "未知版本":
                parts.append(f"OptiFine {info.optifine_version}")
            if info.has_fabric and info.fabric_version:
                parts.append(f"Fabric {info.fabric_version}")
            return " + ".join(parts) if parts else ""
        if info.state == McInstanceState.LiteLoader:
            return "LiteLoader"
        return ""
