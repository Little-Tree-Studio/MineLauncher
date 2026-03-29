from __future__ import annotations
import os
import re
import shutil
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import orjson
from app.services.logger_service import LoggerService


@dataclass
class LaunchConfig:
    java_path: str
    game_directory: Path
    assets_directory: Path
    versions_directory: Path
    username: str
    uuid: str
    access_token: str
    native_path: Path
    classpath: list[str]
    main_class: str
    game_arguments: list[str]
    jvm_arguments: list[str]
    client_token: str = "pc_launcher"
    width: int = 854
    height: int = 480


class LaunchService:
    @staticmethod
    def generate_legacy_uuid(username: str) -> str:
        name_bytes = username.encode("utf-8")
        name_hash = 0
        for byte in name_bytes:
            name_hash = ((name_hash << 8) - name_hash) & 0xFFFFFFFFFFFFFFFF
            name_hash ^= byte
            name_hash &= 0xFFFFFFFFFFFFFFFF

        hash_str = format(name_hash & 0xFFFFFFFFFFFFFFFF, "016x")
        full_uuid = f"{len(username):02x}{hash_str}"

        uuid_chars = list(full_uuid)
        uuid_chars[12] = "3"
        uuid_chars[16] = "9"

        return "".join(uuid_chars)[:32]

    def _merge_version_json(
        self, base_json: dict, inherit_json: dict | None = None
    ) -> dict:
        if inherit_json is None:
            return base_json

        merged = inherit_json.copy()

        for key, value in base_json.items():
            if key == "libraries":
                existing_names = {
                    lib.get("name", "") for lib in merged.get("libraries", [])
                }
                for lib in value:
                    if lib.get("name", "") not in existing_names:
                        merged.setdefault("libraries", []).append(lib)
            elif key == "arguments":
                if isinstance(value, dict) and isinstance(
                    merged.get("arguments"), dict
                ):
                    for arg_type in ["jvm", "game"]:
                        if arg_type in value:
                            existing = {
                                str(a) for a in merged["arguments"].get(arg_type, [])
                            }
                            for arg in value[arg_type]:
                                if str(arg) not in existing:
                                    merged["arguments"].setdefault(arg_type, []).append(
                                        arg
                                    )
                else:
                    merged[key] = value
            elif key not in merged:
                merged[key] = value
            elif isinstance(value, dict) and isinstance(merged[key], dict):
                merged[key] = {**merged[key], **value}

        return merged

    def _resolve_inheritance(self, version_path: Path, folder_name: str) -> dict | None:
        json_path = version_path / f"{folder_name}.json"
        if not json_path.exists():
            return None

        try:
            base_json = orjson.loads(json_path.read_bytes())
        except Exception:
            return None

        inherits_from = base_json.get("inheritsFrom")
        if not inherits_from:
            return base_json

        parent_json = self._resolve_version_json(version_path.parent, inherits_from)
        if parent_json:
            return self._merge_version_json(base_json, parent_json)

        return base_json

    def _resolve_version_json(
        self, versions_root: Path, version_id: str
    ) -> dict | None:
        version_path = versions_root / version_id
        json_path = version_path / f"{version_id}.json"

        if not json_path.exists():
            return None

        try:
            return orjson.loads(json_path.read_bytes())
        except Exception:
            return None

    def _extract_natives(
        self,
        version_data: dict,
        version_path: Path,
        natives_path: Path,
        versions_root: Path,
    ) -> list[str]:
        natives_path.mkdir(parents=True, exist_ok=True)

        native_extensions = [".dll", ".so", ".dylib", ".dylib"]
        if os.name == "nt":
            native_extensions = [".dll"]
        elif sys.platform == "darwin":
            native_extensions = [".dylib", ".so"]
        else:
            native_extensions = [".so"]

        extracted = []
        libraries_root = versions_root.parent / "libraries"

        for lib in version_data.get("libraries", []):
            if not lib.get("downloads"):
                continue

            native_info = lib.get("downloads", {}).get("classifiers")
            if not native_info:
                jar_path = lib.get("downloads", {}).get("jar")
                if jar_path:
                    jar_file = libraries_root / jar_path
                    if jar_file.exists():
                        extracted.extend(
                            self._extract_from_jar(
                                jar_file, natives_path, native_extensions
                            )
                        )
                continue

            for classifier, artifact in native_info.items():
                if not any(ext in classifier.lower() for ext in native_extensions):
                    continue

                jar_path = artifact.get("path")
                if not jar_path:
                    continue

                jar_file = libraries_root / jar_path
                if jar_file.exists():
                    extracted.extend(
                        self._extract_from_jar(
                            jar_file, natives_path, native_extensions
                        )
                    )

        return extracted

    def _extract_from_jar(
        self, jar_path: Path, natives_path: Path, extensions: list[str]
    ) -> list[str]:
        extracted = []

        try:
            with zipfile.ZipFile(jar_path, "r") as zf:
                for name in zf.namelist():
                    if any(name.endswith(ext) for ext in extensions):
                        basename = os.path.basename(name)
                        dest = natives_path / basename
                        try:
                            with zf.open(name) as src, open(dest, "wb") as dst:
                                shutil.copyfileobj(src, dst)
                            extracted.append(str(dest))
                        except Exception:
                            pass
        except Exception:
            pass

        return extracted

    def _build_classpath(
        self, version_data: dict, versions_root: Path, folder_name: str
    ) -> list[str]:
        classpath = []
        versions_dir = versions_root.parent / "libraries"

        for lib in version_data.get("libraries", []):
            if not lib.get("downloads"):
                continue

            jar_path = lib.get("downloads", {}).get("jar")
            if not jar_path:
                continue

            lib_file = versions_dir / jar_path
            if lib_file.exists():
                classpath.append(str(lib_file))

        version_jar = versions_root / folder_name / f"{folder_name}.jar"
        if version_jar.exists():
            classpath.append(str(version_jar))

        return classpath

    def _parse_jvm_arguments(
        self, version_data: dict, native_path: Path, library_path: Path
    ) -> list[str]:
        jvm_args = version_data.get("arguments", {}).get("jvm", [])

        if not jvm_args or (
            len(jvm_args) == 1
            and isinstance(jvm_args[0], str)
            and jvm_args[0] == "-DF=0"
        ):
            jvm_args = [
                "-XX:+UseG1GC",
                "-XX:G1NewSizePercent=20",
                "-XX:G1ReservePercent=20",
                "-XX:MaxGCPauseMillis=50",
                "-XX:+UseStringDeduplication",
            ]

        processed_args = []
        for arg in jvm_args:
            if isinstance(arg, dict):
                rules = arg.get("rules", [])
                if rules:
                    allowed = False
                    for rule in rules:
                        action = rule.get("action", "")
                        os_info = rule.get("os", {})
                        if os_info:
                            os_name = os_info.get("name", "")
                            if action == "allow":
                                if os_name == "windows" and os.name != "nt":
                                    allowed = False
                                    break
                                elif os_name == "osx" and sys.platform != "darwin":
                                    allowed = False
                                    break
                                elif os_name == "linux" and sys.platform != "linux":
                                    allowed = False
                                    break
                            elif action == "disallow":
                                if os_name == "windows" and os.name == "nt":
                                    allowed = False
                                    break
                        else:
                            allowed = True
                    if not allowed:
                        continue

                arg_value = arg.get("value", "")
                if isinstance(arg_value, list):
                    processed_args.extend(str(v) for v in arg_value)
                    continue
                elif not arg_value:
                    continue
                arg = str(arg_value)
            else:
                arg = str(arg)

            arg = arg.replace("${natives_directory}", str(native_path))
            arg = arg.replace("${library_directory}", str(library_path))
            arg = arg.replace("${cwd}", str(Path.cwd()))
            arg = arg.replace("${workdir}", str(Path.cwd()))
            arg = arg.replace("${launcher_name}", "MineLauncher")
            arg = arg.replace("${launcher_version}", "1.0")

            if arg.startswith("-cp") or arg.startswith("${classpath}"):
                continue

            if arg.strip():
                processed_args.append(arg)

        return processed_args

    def _parse_game_arguments(
        self,
        version_data: dict,
        game_directory: Path,
        assets_directory: Path,
        username: str,
        uuid: str,
        access_token: str,
        version_folder: str = "",
    ) -> list[str]:
        game_args = version_data.get("arguments", {}).get("game", [])

        if not game_args:
            minecraft_args = version_data.get("minecraftArguments", "")
            if minecraft_args:
                parts = minecraft_args.split()
                game_args = []
                i = 0
                while i < len(parts):
                    part = parts[i]
                    if part.startswith("--"):
                        game_args.append(part)
                        if i + 1 < len(parts) and not parts[i + 1].startswith("--"):
                            game_args.append(parts[i + 1])
                            i += 1
                    i += 1

        asset_index = version_data.get("assets", "")
        if isinstance(asset_index, dict):
            asset_index = asset_index.get("id", "legacy")

        version_id = version_folder if version_folder else version_data.get("id", "")

        processed_args = []
        for arg in game_args:
            if isinstance(arg, dict):
                continue

            arg = str(arg)

            arg = arg.replace("${auth_player_name}", username)
            arg = arg.replace("${auth_uuid}", uuid)
            arg = arg.replace("${auth_access_token}", access_token)
            arg = arg.replace("${client_token}", "pc_launcher")
            arg = arg.replace("${game_directory}", str(game_directory))
            arg = arg.replace("${game_dir}", str(game_directory))
            arg = arg.replace("${assets_root}", str(assets_directory))
            arg = arg.replace("${assetsDir}", str(assets_directory))
            arg = arg.replace("${assets_index_name}", str(asset_index))
            arg = arg.replace("${version_name}", version_id)
            arg = arg.replace("${version_type}", version_data.get("type", "release"))

            if arg.startswith("--") and "${" in arg:
                continue

            processed_args.append(arg)

        return processed_args

    def _get_main_class(self, version_data: dict, folder_name: str) -> str:
        main_class = version_data.get("mainClass", "net.minecraft.client.main.Main")

        if "fabric" in str(version_data).lower() and "net.fabricmc" not in main_class:
            if "KnotClient" not in main_class:
                main_class = "net.fabricmc.loader.launch.knot.KnotClient"

        if (
            "neoforge" in str(version_data).lower()
            or "net.neoforge" in str(version_data).lower()
        ):
            pass

        if (
            "minecraftforge" in str(version_data).lower()
            and "net.neoforge" not in str(version_data).lower()
        ):
            pass

        return main_class

    def build_launch_config(
        self,
        version_folder: str,
        versions_root: Path,
        java_path: str,
        username: str,
        access_token: str = "offline",
        width: int = 854,
        height: int = 480,
    ) -> LaunchConfig | None:
        version_path = versions_root / version_folder
        json_path = version_path / f"{version_folder}.json"

        if not json_path.exists():
            return None

        try:
            version_data = orjson.loads(json_path.read_bytes())
        except Exception:
            return None

        inherits_from = version_data.get("inheritsFrom")
        if inherits_from:
            parent_json = self._resolve_version_json(versions_root, inherits_from)
            if parent_json:
                version_data = self._merge_version_json(version_data, parent_json)

        game_directory = versions_root.parent
        assets_directory = game_directory / "assets"
        natives_path = version_path / "natives"
        library_path = game_directory / "libraries"

        self._extract_natives(version_data, version_path, natives_path, versions_root)

        classpath = self._build_classpath(version_data, versions_root, version_folder)

        self.logger.info(f"Classpath built with {len(classpath)} entries")

        if not classpath:
            self.logger.error("Classpath is empty")
            return None

        main_class = self._get_main_class(version_data, version_folder)

        jvm_args = self._parse_jvm_arguments(version_data, natives_path, library_path)

        uuid = self.uuid if self.uuid else self.generate_legacy_uuid(username)

        game_args = self._parse_game_arguments(
            version_data,
            game_directory,
            assets_directory,
            username,
            uuid,
            access_token,
            version_folder,
        )

        game_args.extend(
            [
                "--width",
                str(width),
                "--height",
                str(height),
            ]
        )

        self.logger.info(
            f"Launch config built: main_class={main_class}, game_args count={len(game_args)}"
        )

        return LaunchConfig(
            java_path=java_path,
            game_directory=game_directory,
            assets_directory=assets_directory,
            versions_directory=versions_root,
            username=username,
            uuid=uuid,
            access_token=access_token,
            native_path=natives_path,
            classpath=classpath,
            main_class=main_class,
            game_arguments=game_args,
            jvm_arguments=jvm_args,
            width=width,
            height=height,
        )

    def launch(self, config: LaunchConfig) -> subprocess.Popen | None:
        java_cmd = [config.java_path]

        java_cmd.extend(config.jvm_arguments)

        java_cmd.extend(
            [
                f"-Djava.library.path={config.native_path}",
                f"-Djna.tmpdir={config.native_path}",
                f"-Dorg.lwjgl.system.SharedLibraryExtractPath={config.native_path}",
                f"-Dio.netty.native.workdir={config.native_path}",
                "-Dminecraft.launcher.brand=MineLauncher",
                "-Dminecraft.launcher.version=1.0",
                "--add-exports",
                "cpw.mods.bootstraplauncher/cpw.mods.bootstraplauncher=ALL-UNNAMED",
            ]
        )

        java_cmd.extend(
            [
                "-cp",
                ";".join(config.classpath),
            ]
        )

        java_cmd.append(config.main_class)
        java_cmd.extend(config.game_arguments)

        self.logger.info(f"Launch command: {' '.join(java_cmd)}")

        try:
            if os.name == "nt":
                DETACHED_PROCESS = 0x00000008
                proc = subprocess.Popen(
                    java_cmd,
                    cwd=str(config.game_directory),
                    creationflags=DETACHED_PROCESS,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
            else:
                proc = subprocess.Popen(
                    java_cmd,
                    cwd=str(config.game_directory),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            return proc
        except Exception as e:
            self.logger.error(f"Failed to launch: {e}")
            return None

    def __init__(self):
        self.logger = LoggerService().logger
        self.uuid: str | None = None
