from __future__ import annotations
import os
import re
import shutil
import subprocess
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Callable
import orjson
from app.services.logger_service import LoggerService
from enum import IntEnum


class ModLoaderType(IntEnum):
    VANILLA = 0
    FORGE = 1
    NEOFORGE = 2
    FABRIC = 3
    QUILT = 4
    LITE = 5
    OPTIFINE = 6
    FORGE_OPTIFINE = 7


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
    mod_loader: ModLoaderType = ModLoaderType.VANILLA
    mod_loader_version: str = ""
    server_ip: str = ""
    server_port: int = 0
    xmx: str = "2G"
    xms: str = "512M"
    wrapper_path: str = ""
    env_vars: dict = field(default_factory=dict)
    close_launcher: bool = False


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

    @staticmethod
    def detect_mod_loader(version_json_str: str) -> tuple[ModLoaderType, str]:
        real_json_lower = version_json_str.lower()

        has_optifine = "optifine" in real_json_lower
        has_liteloader = "liteloader" in real_json_lower
        has_fabric = (
            "net.fabricmc:fabric-loader" in version_json_str
            or "org.quiltmc:quilt-loader" in version_json_str
        )
        has_neoforge = "net.neoforge" in version_json_str
        has_forge = "minecraftforge" in real_json_lower and not has_neoforge

        if has_fabric and "quilt" in real_json_lower:
            return ModLoaderType.QUILT, LaunchService._extract_quilt_version(
                version_json_str
            )
        elif has_fabric:
            return ModLoaderType.FABRIC, LaunchService._extract_fabric_version(
                version_json_str
            )
        elif has_neoforge:
            return ModLoaderType.NEOFORGE, LaunchService._extract_neoforge_version(
                version_json_str
            )
        elif has_forge:
            return ModLoaderType.FORGE, LaunchService._extract_forge_version(
                version_json_str
            )
        elif has_liteloader:
            return ModLoaderType.LITE, LaunchService._extract_liteloader_version(
                version_json_str
            )
        elif has_optifine and has_forge:
            return ModLoaderType.FORGE_OPTIFINE, LaunchService._extract_forge_version(
                version_json_str
            )
        elif has_optifine:
            return ModLoaderType.OPTIFINE, LaunchService._extract_optifine_version(
                version_json_str
            )
        else:
            return ModLoaderType.VANILLA, ""

    @staticmethod
    def _extract_fabric_version(json_str: str) -> str:
        patterns = [
            r"(?<=net\.fabricmc:fabric-loader:)[0-9.]+(\+build\.[0-9]+)?",
            r"(?<=org\.quiltmc:quilt-loader:)[0-9.]+(\+build\.[0-9]+)?",
        ]
        for pattern in patterns:
            match = re.search(pattern, json_str)
            if match:
                return match.group(0)
        return ""

    @staticmethod
    def _extract_forge_version(json_str: str) -> str:
        patterns = [
            r"(?<=forge:[0-9.]+(_pre[0-9]*)?\-)[[0-9.]+",
            r'"forgeVersion"\s*,\s*"([^"]+)"',
            r"forge-([0-9.]+)-",
        ]
        for pattern in patterns:
            match = re.search(pattern, json_str)
            if match:
                return match.group(1)
        return ""

    @staticmethod
    def _extract_neoforge_version(json_str: str) -> str:
        match = re.search(r'"neoforgeVersion"\s*,\s*"([^"]+)"', json_str)
        if match:
            return match.group(1)
        match = re.search(r'net\.neoforge:neoforge:[0-9.]+[-_]([^"\\]+)', json_str)
        if match:
            return match.group(1)
        return ""

    @staticmethod
    def _extract_optifine_version(json_str: str) -> str:
        match = re.search(r'(?<=HD_U_)[^":/]+', json_str)
        if match:
            return match.group(0)
        return ""

    @staticmethod
    def _extract_liteloader_version(json_str: str) -> str:
        match = re.search(r"1\.\d+\.\d+", json_str)
        return match.group(0) if match else ""

    @staticmethod
    def _extract_quilt_version(json_str: str) -> str:
        return LaunchService._extract_fabric_version(json_str)

    @staticmethod
    def get_required_java_version(mc_version: str) -> int:
        version_parts = mc_version.split(".")
        if len(version_parts) < 2:
            return 8

        major = int(version_parts[0])
        minor = int(version_parts[1])

        if major == 1:
            if minor >= 20:
                patch = (
                    int(version_parts[2].split("-")[0])
                    if len(version_parts) > 2 and version_parts[2]
                    else 0
                )
                if minor == 20 and patch >= 5:
                    return 21
                return 17
            elif minor >= 18:
                return 17
            elif minor >= 17 or (
                minor >= 12
                and LaunchService._is_snapshot_or_later(mc_version, "21w19a")
            ):
                return 16
            else:
                return 8
        return 8

    @staticmethod
    def _is_snapshot_or_later(version: str, snapshot_name: str) -> bool:
        try:
            parts = version.split("w")
            if len(parts) >= 2:
                version_num = int(parts[0].split(".")[-1])
                snapshot_num = int(snapshot_name.split("w")[0].split(".")[-1])
                return version_num > snapshot_num
        except:
            pass
        return False

    @staticmethod
    def get_mod_loader_java_requirement(
        mod_loader: ModLoaderType, mc_version: str, mod_loader_version: str = ""
    ) -> int:
        if mod_loader == ModLoaderType.FABRIC:
            version_parts = mc_version.split(".")
            if len(version_parts) >= 2:
                minor = int(version_parts[1])
                if minor >= 18:
                    return 17
                return 8
        elif mod_loader == ModLoaderType.FORGE:
            if mod_loader_version:
                if "1.6.1" <= mc_version <= "1.7.2":
                    return 7
                elif mc_version.startswith("1.13") or mc_version.startswith("1.14"):
                    return 10
            return 8
        elif mod_loader == ModLoaderType.OPTIFINE:
            version_parts = mc_version.split(".")
            if len(version_parts) >= 2:
                minor = int(version_parts[1])
                if minor in (8, 9, 10, 11):
                    return 8
        return LaunchService.get_required_java_version(mc_version)

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

    def _check_rules(self, rules: list) -> bool:
        if not rules:
            return True
        import platform
        os_name_map = {
            "windows": "windows",
            "darwin": "osx",
            "linux": "linux",
        }
        os_name = os_name_map.get(platform.system().lower(), "unknown")
        
        is_allowed = False
        for rule in rules:
            action = rule.get("action")
            
            # Check features
            if "features" in rule:
                features = rule.get("features", {})
                if features.get("is_demo_user") and action == "allow":
                    return False
                if features.get("has_custom_resolution") and action == "allow":
                    is_allowed = True
                continue

            # Check OS
            os_rule = rule.get("os", {})
            if not os_rule:
                is_allowed = action == "allow"
            elif os_rule.get("name") == os_name:
                is_allowed = action == "allow"
        return is_allowed

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
            if not self._check_rules(lib.get("rules", [])):
                continue

            if not lib.get("downloads"):
                continue

            native_info = lib.get("downloads", {}).get("classifiers")
            if not native_info:
                # Some native jars are directly in artifact
                jar_path = lib.get("downloads", {}).get("artifact", {}).get("path")
                if not jar_path:
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
            if not self._check_rules(lib.get("rules", [])):
                continue

            jar_path = None
            if "downloads" in lib:
                if "artifact" in lib["downloads"]:
                    jar_path = lib["downloads"]["artifact"].get("path")
                if not jar_path:
                    jar_path = lib["downloads"].get("jar")
            
            if not jar_path and "name" in lib:
                parts = lib["name"].split(":")
                if len(parts) >= 3:
                    group, name, version = parts[0].replace(".", "/"), parts[1], parts[2]
                    jar_path = f"{group}/{name}/{version}/{name}-{version}.jar"

            if not jar_path:
                continue

            lib_file = versions_dir / jar_path
            if lib_file.exists() and str(lib_file) not in classpath:
                classpath.append(str(lib_file))

        version_jar = versions_root / folder_name / f"{folder_name}.jar"
        if version_jar.exists() and str(version_jar) not in classpath:
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

        raw_args = []
        for arg in jvm_args:
            if isinstance(arg, dict):
                if not self._check_rules(arg.get("rules", [])):
                    continue
                arg_value = arg.get("value", "")
                if isinstance(arg_value, list):
                    raw_args.extend(str(v) for v in arg_value)
                elif arg_value:
                    raw_args.append(str(arg_value))
            else:
                raw_args.append(str(arg))
        
        processed_args = []
        cp_sep = ";" if os.name == "nt" else ":"
        for arg in raw_args:
            arg = arg.replace("${natives_directory}", str(native_path))
            arg = arg.replace("${library_directory}", str(library_path))
            arg = arg.replace("${classpath_separator}", cp_sep)
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
        width: int = 854,
        height: int = 480,
    ) -> list[str]:
        game_args_raw = version_data.get("arguments", {}).get("game", [])
        
        raw_args = []
        if game_args_raw:
            for arg in game_args_raw:
                if isinstance(arg, dict):
                    if not self._check_rules(arg.get("rules", [])):
                        continue
                    val = arg.get("value", "")
                    if isinstance(val, list):
                        raw_args.extend(str(v) for v in val)
                    elif val:
                        raw_args.append(str(val))
                else:
                    raw_args.append(str(arg))
        else:
            minecraft_args = version_data.get("minecraftArguments", "")
            if minecraft_args:
                raw_args = minecraft_args.split()

        asset_index_obj = version_data.get("assetIndex", {})
        if isinstance(asset_index_obj, dict) and "id" in asset_index_obj:
            asset_index = asset_index_obj.get("id")
        else:
            asset_index = version_data.get("assets", "legacy")
            if isinstance(asset_index, dict) and "id" in asset_index:
                asset_index = asset_index.get("id")

        version_id = version_folder if version_folder else version_data.get("id", "")

        processed_args = []
        for arg in raw_args:
            arg = str(arg)

            arg = arg.replace("${auth_player_name}", username)
            arg = arg.replace("${auth_uuid}", uuid)
            arg = arg.replace("${auth_access_token}", access_token)
            arg = arg.replace("${client_token}", "pc_launcher")
            arg = arg.replace("${game_directory}", str(game_directory))
            arg = arg.replace("${game_dir}", str(game_directory))
            arg = arg.replace("${game_assets}", str(assets_directory))
            arg = arg.replace("${assets_root}", str(assets_directory))
            arg = arg.replace("${assetsDir}", str(assets_directory))
            arg = arg.replace("${assets_index_name}", str(asset_index))
            arg = arg.replace("${version_name}", version_id)
            arg = arg.replace("${version_type}", version_data.get("type", "release"))
            arg = arg.replace("${clientid}", "1")
            arg = arg.replace("${auth_xuid}", "0")
            arg = arg.replace("${user_type}", "mojang")
            arg = arg.replace("${user_properties}", "{}")
            arg = arg.replace("${auth_session}", access_token)
            arg = arg.replace("${resolution_width}", str(width))
            arg = arg.replace("${resolution_height}", str(height))

            if arg.startswith("--") and "${" in arg:
                continue

            if arg.strip():
                processed_args.append(arg)

        return processed_args

    def _get_main_class(
        self,
        version_data: dict,
        folder_name: str,
        mod_loader: ModLoaderType = ModLoaderType.VANILLA,
    ) -> str:
        main_class = version_data.get("mainClass", "net.minecraft.client.main.Main")
        json_str = str(version_data)

        if mod_loader == ModLoaderType.FABRIC and "KnotClient" not in main_class:
            main_class = "net.fabricmc.loader.launch.knot.KnotClient"
        elif mod_loader == ModLoaderType.QUILT and "KnotClient" not in main_class:
            main_class = "net.fabricmc.loader.launch.knot.KnotClient"
        elif mod_loader == ModLoaderType.LITE and "LiteLoaderTweaker" not in main_class:
            pass

        return main_class

    def _apply_mod_loader_game_args(
        self, game_args: list, mod_loader: ModLoaderType, version_data: dict
    ) -> list:
        json_str = str(version_data)

        if (
            mod_loader == ModLoaderType.FORGE
            or mod_loader == ModLoaderType.FORGE_OPTIFINE
        ):
            if "--fml" not in " ".join(game_args):
                pass
        elif (
            mod_loader == ModLoaderType.OPTIFINE
            or mod_loader == ModLoaderType.FORGE_OPTIFINE
        ):
            if "OptiFineForgeTweaker" not in " ".join(game_args):
                game_args.append("--tweakClass")
                game_args.append("optifine.OptiFineForgeTweaker")

        return game_args

    def build_launch_config(
        self,
        version_folder: str,
        versions_root: Path,
        java_path: str,
        username: str,
        access_token: str = "offline",
        width: int = 854,
        height: int = 480,
        xmx: str = "2G",
        xms: str = "512M",
        server_ip: str = "",
        server_port: int = 0,
        wrapper_path: str = "",
        env_vars: Optional[dict] = None,
        close_launcher: bool = False,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> LaunchConfig | None:
        if progress_callback:
            progress_callback("检测版本数据...")
        version_path = versions_root / version_folder
        json_path = version_path / f"{version_folder}.json"

        if not json_path.exists():
            return None

        try:
            version_data_bytes = json_path.read_bytes()
            version_data = orjson.loads(version_data_bytes)
        except Exception:
            return None

        version_json_str = version_data_bytes.decode("utf-8", errors="ignore")
        mod_loader, mod_loader_version = self.detect_mod_loader(version_json_str)

        if progress_callback:
            progress_callback("解析版本继承关系...")
        inherits_from = version_data.get("inheritsFrom")
        if inherits_from:
            parent_json = self._resolve_version_json(versions_root, inherits_from)
            if parent_json:
                version_data = self._merge_version_json(version_data, parent_json)

        game_directory = versions_root.parent
        assets_directory = game_directory / "assets"
        libraries_directory = game_directory / "libraries"
        natives_path = version_path / "natives"
        if progress_callback:
            progress_callback("解压 Natives 文件...")
        self._extract_natives(version_data, version_path, natives_path, versions_root)

        if progress_callback:
            progress_callback("构建类路径 (Classpath)...")

        classpath = self._build_classpath(version_data, versions_root, version_folder)

        self.logger.info(f"Classpath built with {len(classpath)} entries")

        if not classpath:
            self.logger.error("Classpath is empty")
            return None

        if progress_callback:
            progress_callback("处理启动参数...")
        main_class = self._get_main_class(version_data, version_folder, mod_loader)

        jvm_args = self._parse_jvm_arguments(version_data, natives_path, libraries_directory)

        uuid = self.uuid if self.uuid else self.generate_legacy_uuid(username)

        game_args = self._parse_game_arguments(
            version_data,
            game_directory,
            assets_directory,
            username,
            uuid,
            access_token,
            version_folder,
            width,
            height,
        )

        game_args = self._apply_mod_loader_game_args(
            game_args, mod_loader, version_data
        )

        if server_ip:
            game_args.append("--server")
            game_args.append(server_ip)
            if server_port:
                game_args.append("--port")
                game_args.append(str(server_port))

        game_args.extend(
            [
                "--width",
                str(width),
                "--height",
                str(height),
            ]
        )

        if progress_callback:
            progress_callback("启动环境准备完毕，即将启动游戏...")

        self.logger.info(
            f"Launch config built: main_class={main_class}, mod_loader={mod_loader.name}, game_args count={len(game_args)}"
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
            mod_loader=mod_loader,
            mod_loader_version=mod_loader_version,
            server_ip=server_ip,
            server_port=server_port,
            xmx=xmx,
            xms=xms,
            wrapper_path=wrapper_path,
            env_vars=env_vars or {},
            close_launcher=close_launcher,
        )

    def launch(self, config: LaunchConfig) -> subprocess.Popen | None:
        java_cmd = [config.java_path]

        java_cmd.extend([f"-Xmx{config.xmx}"])
        java_cmd.extend([f"-Xms{config.xms}"])

        java_cmd.extend(config.jvm_arguments)

        java_cmd.extend(
            [
                f"-Djava.library.path={config.native_path}",
                f"-Djna.tmpdir={config.native_path}",
                f"-Dorg.lwjgl.system.SharedLibraryExtractPath={config.native_path}",
                f"-Dio.netty.native.workdir={config.native_path}",
                "-Dminecraft.launcher.brand=MineLauncher",
                "-Dminecraft.launcher.version=1.0",
            ]
        )

        if (
            config.mod_loader == ModLoaderType.FORGE
            or config.mod_loader == ModLoaderType.NEOFORGE
        ):
            java_cmd.extend(
                [
                    "--add-exports",
                    "cpw.mods.bootstraplauncher/cpw.mods.bootstraplauncher=ALL-UNNAMED",
                ]
            )

        cp_sep = ";" if os.name == "nt" else ":"
        java_cmd.extend(["-cp", cp_sep.join(config.classpath)])

        if config.wrapper_path and os.path.exists(config.wrapper_path):
            # If a wrapper is used, some wrappers might replace main class or need -javaagent.
            # Assuming -javaagent for log4j wrappers here if appropriate, or maybe prepend wrapper to cp.
            # We'll just insert it as a javaagent if it contains 'log4j' and 'agent', otherwise maybe generic.
            if "agent" in config.wrapper_path.lower() or "log4j" in config.wrapper_path.lower():
                java_cmd.insert(1, f"-javaagent:{config.wrapper_path}")
            else:
                pass # If it's another kind of wrapper, maybe handle accordingly.

        java_cmd.append(config.main_class)
        java_cmd.extend(config.game_arguments)

        self.logger.info(f"Launch command: {' '.join(java_cmd)}")

        try:
            env = os.environ.copy()
            env.update(config.env_vars)

            if os.name == "nt":
                DETACHED_PROCESS = 0x00000008
                proc = subprocess.Popen(
                    java_cmd,
                    cwd=str(config.game_directory),
                    creationflags=DETACHED_PROCESS,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=env,
                )
            else:
                proc = subprocess.Popen(
                    java_cmd,
                    cwd=str(config.game_directory),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env=env,
                )
            return proc
        except Exception as e:
            self.logger.error(f"Failed to launch: {e}")
            return None

    def __init__(self):
        self.logger = LoggerService().logger
        self.uuid: str | None = None
