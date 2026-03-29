from __future__ import annotations
import re
import zipfile
import orjson
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Optional, List, Dict, Any


class McInstanceState(IntEnum):
    Error = -1
    Unknown = 0
    Original = 1
    Snapshot = 2
    Old = 3
    Fool = 4
    Forge = 5
    NeoForge = 6
    Fabric = 7
    LiteLoader = 8
    OptiFine = 9


@dataclass
class McVersionInfo:
    vanilla_name: str = "Unknown"
    vanilla_version: Optional[Any] = None
    reliable: bool = False
    state: McInstanceState = McInstanceState.Unknown

    has_forge: bool = False
    forge_version: str = ""

    has_neoforge: bool = False
    neoforge_version: str = ""

    has_fabric: bool = False
    fabric_version: str = ""

    has_liteloader: bool = False
    liteloader_version: str = ""

    has_optifine: bool = False
    optifine_version: str = ""

    release_time: Optional[str] = None

    @property
    def display_name(self) -> str:
        parts = []

        state_names = {
            McInstanceState.Original: "正式版",
            McInstanceState.Snapshot: "快照版",
            McInstanceState.Old: "远古版",
            McInstanceState.Fool: "愚人节版",
            McInstanceState.Error: "错误",
            McInstanceState.Forge: "Forge",
            McInstanceState.NeoForge: "NeoForge",
            McInstanceState.Fabric: "Fabric",
            McInstanceState.LiteLoader: "LiteLoader",
            McInstanceState.OptiFine: "OptiFine",
        }

        state_name = state_names.get(self.state, "未知")

        if self.state in (McInstanceState.Error, McInstanceState.Unknown):
            return f"{state_name} ({self.vanilla_name})"

        if self.state == McInstanceState.OptiFine:
            if self.has_optifine and self.optifine_version:
                parts.append(f"OptiFine {self.optifine_version}")
            else:
                parts.append("OptiFine")
            if self.vanilla_name not in ("Unknown", "Old", "pending"):
                parts.append(self.vanilla_name)
            if self.has_fabric and self.fabric_version:
                parts.append(f"Fabric {self.fabric_version}")
        elif self.state == McInstanceState.Fabric:
            if self.has_fabric and self.fabric_version:
                parts.append(f"Fabric {self.fabric_version}")
            else:
                parts.append("Fabric")
            if self.vanilla_name not in ("Unknown", "Old", "pending"):
                parts.append(self.vanilla_name)
            if self.has_optifine and self.optifine_version:
                parts.append(f"OptiFine {self.optifine_version}")
        elif self.state == McInstanceState.Forge:
            if self.has_forge and self.forge_version:
                parts.append(f"Forge {self.forge_version}")
            else:
                parts.append("Forge")
            if self.vanilla_name not in ("Unknown", "Old", "pending"):
                parts.append(self.vanilla_name)
            if self.has_optifine and self.optifine_version:
                parts.append(f"OptiFine {self.optifine_version}")
        elif self.state == McInstanceState.NeoForge:
            if self.has_neoforge and self.neoforge_version:
                parts.append(f"NeoForge {self.neoforge_version}")
            else:
                parts.append("NeoForge")
            if self.vanilla_name not in ("Unknown", "Old", "pending"):
                parts.append(self.vanilla_name)
            if self.has_optifine and self.optifine_version:
                parts.append(f"OptiFine {self.optifine_version}")
        elif self.state == McInstanceState.LiteLoader:
            parts.append("LiteLoader")
            if self.vanilla_name not in ("Unknown", "Old", "pending"):
                parts.append(self.vanilla_name)
        else:
            parts.append(state_name)
            if self.vanilla_name not in ("Unknown", "Old", "pending"):
                parts.append(self.vanilla_name)
            if self.has_forge and self.forge_version:
                parts.append(f"Forge {self.forge_version}")
            if self.has_neoforge and self.neoforge_version:
                parts.append(f"NeoForge {self.neoforge_version}")
            if self.has_fabric and self.fabric_version:
                parts.append(f"Fabric {self.fabric_version}")
            if self.has_liteloader:
                parts.append("LiteLoader")
            if self.has_optifine and self.optifine_version:
                parts.append(f"OptiFine {self.optifine_version}")

        return ", ".join(parts)


def _regex_seek(pattern: str, text: str, group: int = 0) -> Optional[str]:
    match = re.search(pattern, text)
    if match:
        return match.group(group)
    return None


class VersionDetector:
    VERSION_PATTERN = re.compile(
        r"(([1-9][0-9]w[0-9]{2}[a-g])|((1|[2-9][0-9])\.[0-9]+(\.[0-9]+)?(-(pre|rc|snapshot-?)[1-9]*| Pre-Release( [1-9])?)?))(_unobfuscated)?",
        re.IGNORECASE,
    )

    FORGE_VERSION_PATTERN_1 = re.compile(r"forge:[0-9\.]+(_pre[0-9]*)?\-([0-9\.]+)")
    FORGE_VERSION_PATTERN_2 = re.compile(
        r"net\.minecraftforge:minecraftforge:([0-9\.]+)"
    )
    FORGE_VERSION_PATTERN_3 = re.compile(
        r"net\.minecraftforge:fmlloader:[0-9\.]+-([0-9\.]+)"
    )

    FABRIC_VERSION_PATTERN = re.compile(
        r"(?:net\.fabricmc:fabric-loader:|org\.quiltmc:quilt-loader:)([0-9\.]+)(?:\+build\.[0-9]+)?"
    )

    NEOFORGE_VERSION_PATTERN = re.compile(r'--fml\.neoforgeversion",\s*"([0-9.]+)')
    NEOFORGE_FORGE_VERSION_PATTERN = re.compile(r'"forgeVersion"\s*:\s*"([^"]+)"')

    OPTIFINE_VERSION_PATTERN = re.compile(r"hd_u_([a-z0-9_]+)", re.IGNORECASE)

    FORGE_LIB_PATTERN = re.compile(r"net\.minecraftforge:forge:([0-9\.]+)")
    FMLLOADER_LIB_PATTERN = re.compile(r"net\.minecraftforge:fmlloader:([0-9\.]+)")

    INTERMEDIARY_PATTERN = re.compile(r'(?:fabricmc|quiltmc):intermediary:([^"]+)')

    DOWNLOAD_URL_PATTERN = re.compile(r"launcher\.mojang\.com/mc/game/([^/]+)")

    OPTIFINE_LIB_PATTERN = re.compile(r"optifine:OptiFine:([0-9\.]+)")

    def __init__(self, versions_root: Path):
        self.versions_root = versions_root
        self._cache: Dict[str, McVersionInfo] = {}

    def detect(self, folder_name: str, force: bool = False) -> McVersionInfo:
        if not force and folder_name in self._cache:
            return self._cache[folder_name]

        version_path = self.versions_root / folder_name

        if not version_path.is_dir():
            return McVersionInfo(state=McInstanceState.Error)

        json_path = version_path / f"{folder_name}.json"

        json_obj = None
        json_text = ""
        real_json = ""

        if json_path.exists():
            try:
                content = json_path.read_bytes()
                if content:
                    json_obj = orjson.loads(content)
                    json_text = content.decode("utf-8", errors="replace")
                    real_json = json_text.lower()
            except Exception:
                pass

        if json_obj is None:
            for json_file in version_path.glob("*.json"):
                try:
                    content = json_file.read_bytes()
                    if not content:
                        continue
                    temp_obj = orjson.loads(content)
                    if (
                        temp_obj.get("mainClass")
                        and temp_obj.get("type")
                        and temp_obj.get("id")
                    ):
                        json_obj = temp_obj
                        json_text = content.decode("utf-8", errors="replace")
                        real_json = json_text.lower()
                        break
                except Exception:
                    continue

        info = McVersionInfo()

        if json_obj is None:
            self._cache[folder_name] = info
            return info

        self._extract_release_time(json_obj, info)
        self._extract_version_name(json_obj, json_text, folder_name, info)
        self._extract_mod_loaders(real_json, info)
        self._determine_state(json_obj, info)

        self._cache[folder_name] = info
        return info

    def _extract_release_time(self, json_obj: Dict, info: McVersionInfo):
        release_time = json_obj.get("releaseTime")
        if release_time:
            info.release_time = release_time

    def _extract_version_name(
        self, json_obj: Dict, json_text: str, folder_name: str, info: McVersionInfo
    ):
        if info.release_time:
            try:
                year = int(info.release_time[:4])
                if 2000 <= year <= 2012:
                    info.vanilla_name = "Old"
                    return
            except (ValueError, TypeError):
                pass

        vanilla_name = None
        reliable = False

        type_val = json_obj.get("type", "")
        if type_val == "pending":
            vanilla_name = "pending"

        if not vanilla_name and json_obj.get("clientVersion"):
            vanilla_name = json_obj["clientVersion"]

        if not vanilla_name:
            patches = json_obj.get("patches")
            if patches:
                for patch in patches:
                    if isinstance(patch, dict) and patch.get("id") == "game":
                        vanilla_name = patch.get("version")
                        break

        if not vanilla_name:
            arguments = json_obj.get("arguments", {})
            if isinstance(arguments, dict):
                game_args = arguments.get("game", [])
                if isinstance(game_args, list):
                    for i, arg in enumerate(game_args):
                        if str(arg) == "--fml.mcVersion" and i + 1 < len(game_args):
                            vanilla_name = str(game_args[i + 1])
                            break

        inherit_name = json_obj.get("inheritsFrom")
        if not vanilla_name and inherit_name:
            jar = json_obj.get("jar")
            if jar:
                vanilla_name = jar
            else:
                vanilla_name = inherit_name

        if not vanilla_name:
            downloads = json_obj.get("downloads")
            if downloads:
                downloads_str = str(downloads)
                match = self.DOWNLOAD_URL_PATTERN.search(downloads_str)
                if match:
                    vanilla_name = match.group(1)

        if not vanilla_name:
            libraries_str = str(json_obj.get("libraries", []))

            match = self.FORGE_LIB_PATTERN.search(libraries_str)
            if match:
                vanilla_name = match.group(1)
            else:
                match = self.FMLLOADER_LIB_PATTERN.search(libraries_str)
                if match:
                    vanilla_name = match.group(1)

            if not vanilla_name:
                match = self.OPTIFINE_LIB_PATTERN.search(libraries_str)
                if match:
                    vanilla_name = match.group(1)

            if not vanilla_name:
                match = self.INTERMEDIARY_PATTERN.search(libraries_str)
                if match:
                    vanilla_name = match.group(1)

        if not vanilla_name:
            jar = json_obj.get("jar")
            if jar:
                vanilla_name = jar
                reliable = False

        if not vanilla_name:
            version_jar_path = self.versions_root / folder_name / f"{folder_name}.jar"
            if version_jar_path.exists():
                try:
                    with zipfile.ZipFile(version_jar_path, "r") as zf:
                        if "version.json" in zf.namelist():
                            with zf.open("version.json") as vf:
                                version_json = orjson.loads(vf.read())
                                name = version_json.get("name", "")
                                if name and len(name) < 32:
                                    vanilla_name = name
                except Exception:
                    pass

        if not vanilla_name:
            json_id = json_obj.get("id", "")
            if json_id:
                match = self.VERSION_PATTERN.search(json_id)
                if match:
                    vanilla_name = match.group().rstrip("_unobfuscated").rstrip("-")
                    reliable = True

        if not vanilla_name:
            match = self.VERSION_PATTERN.search(folder_name)
            if match:
                vanilla_name = match.group().rstrip("_unobfuscated").rstrip("-")
                reliable = True

        if not vanilla_name:
            json_text_without_libraries = json_text
            if '"libraries"' in json_text_without_libraries:
                libraries_match = re.search(
                    r'"libraries"\s*:\s*\[.*?\]', json_text_without_libraries, re.DOTALL
                )
                if libraries_match:
                    json_text_without_libraries = (
                        json_text_without_libraries[: libraries_match.start()]
                        + json_text_without_libraries[libraries_match.end() :]
                    )

            match = self.VERSION_PATTERN.search(json_text_without_libraries)
            if match:
                vanilla_name = match.group().rstrip("_unobfuscated").rstrip("-")
                reliable = True

        if not vanilla_name:
            vanilla_name = "Unknown"

        vanilla_name = vanilla_name.replace("_", "-")
        while vanilla_name.endswith(".0"):
            vanilla_name = vanilla_name[:-2]

        info.vanilla_name = vanilla_name
        info.reliable = reliable

        if vanilla_name.startswith("1."):
            parts = vanilla_name[2:].split(".")
            try:
                major = int(parts[0]) if len(parts) > 0 else 0
                minor = int(parts[1]) if len(parts) > 1 else 0
                build = int(parts[2]) if len(parts) > 2 else 0
                info.vanilla_version = Version(major, minor, build)
            except (ValueError, IndexError):
                info.vanilla_version = Version(9999, 0, 0)
        elif len(vanilla_name) > 0 and vanilla_name[0].isdigit():
            first_char = int(vanilla_name[0]) if vanilla_name[0].isdigit() else 0
            if 2 <= first_char <= 9:
                try:
                    parts = vanilla_name.split(".")
                    major = int(parts[0]) if parts else 0
                    minor = int(parts[1]) if len(parts) > 1 else 0
                    build = int(parts[2]) if len(parts) > 2 else 0
                    info.vanilla_version = Version(major, minor, build)
                except (ValueError, IndexError):
                    info.vanilla_version = Version(9999, 0, 0)
            else:
                info.vanilla_version = Version(9999, 0, 0)
        else:
            info.vanilla_version = Version(9999, 0, 0)

    def _extract_mod_loaders(self, real_json: str, info: McVersionInfo):
        if "optifine" in real_json:
            info.has_optifine = True
            match = self.OPTIFINE_VERSION_PATTERN.search(real_json)
            info.optifine_version = match.group(1) if match else "未知版本"

        if "liteloader" in real_json:
            info.has_liteloader = True
            info.liteloader_version = "未知版本"

        if (
            "net.fabricmc:fabric-loader" in real_json
            or "org.quiltmc:quilt-loader" in real_json
        ):
            info.has_fabric = True
            match = self.FABRIC_VERSION_PATTERN.search(real_json)
            if match:
                info.fabric_version = match.group(1)
                if "+build" in info.fabric_version:
                    info.fabric_version = info.fabric_version.split("+build")[0]
            else:
                info.fabric_version = "未知版本"

        if "minecraftforge" in real_json and "net.neoforge" not in real_json:
            info.has_forge = True
            match = self.FORGE_VERSION_PATTERN_1.search(real_json)
            if match:
                info.forge_version = match.group(2)
            else:
                match = self.FORGE_VERSION_PATTERN_2.search(real_json)
                if match:
                    info.forge_version = match.group(1)
                else:
                    match = self.FORGE_VERSION_PATTERN_3.search(real_json)
                    if match:
                        info.forge_version = match.group(1)
                    else:
                        info.forge_version = "未知版本"

        if "net.neoforge" in real_json:
            info.has_neoforge = True
            match = self.NEOFORGE_VERSION_PATTERN.search(real_json)
            if not match:
                match = self.NEOFORGE_FORGE_VERSION_PATTERN.search(real_json)
            info.neoforge_version = match.group(1) if match else "未知版本"

    def _determine_state(self, json_obj: Dict, info: McVersionInfo):
        if info.vanilla_name == "Unknown":
            info.state = McInstanceState.Error
            return

        if info.vanilla_name == "Old":
            info.state = McInstanceState.Old
            return

        type_val = json_obj.get("type", "")
        if type_val == "fool":
            info.state = McInstanceState.Fool
            return

        fool_patterns = ["april fools", "april fool", "1.0.0", "0.0.1"]
        for pattern in fool_patterns:
            if pattern in info.vanilla_name.lower():
                info.state = McInstanceState.Fool
                return

        if self._is_snapshot(json_obj, info):
            info.state = McInstanceState.Snapshot
            return

        if info.has_optifine:
            info.state = McInstanceState.OptiFine
            return

        if info.has_liteloader:
            info.state = McInstanceState.LiteLoader
            return

        if info.has_fabric:
            info.state = McInstanceState.Fabric
            return

        if info.has_forge:
            info.state = McInstanceState.Forge
            return

        if info.has_neoforge:
            info.state = McInstanceState.NeoForge
            return

        info.state = McInstanceState.Original

    def _is_snapshot(self, json_obj: Dict, info: McVersionInfo) -> bool:
        vanilla = info.vanilla_name.lower()

        snapshot_indicators = ["w", "snapshot", "rc", "pre", "experimental", "-"]
        for indicator in snapshot_indicators:
            if indicator in vanilla:
                return True

        if "combat" in info.vanilla_name.lower():
            return True

        type_val = json_obj.get("type", "")
        if type_val in ("snapshot", "pending"):
            return True

        return False

    def detect_all(self) -> Dict[str, McVersionInfo]:
        results = {}
        for folder in self._list_dirs(self.versions_root):
            info = self.detect(folder)
            results[folder] = info
        return results

    @staticmethod
    def _list_dirs(path: Path) -> List[str]:
        if not path.is_dir():
            return []
        return [d.name for d in path.iterdir() if d.is_dir()]


class Version:
    def __init__(self, major: int, minor: int = 0, build: int = 0):
        self.major = major
        self.minor = minor
        self.build = build

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.build}"

    def __repr__(self) -> str:
        return f"Version({self.major}, {self.minor}, {self.build})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        return (self.major, self.minor, self.build) == (
            other.major,
            other.minor,
            other.build,
        )

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        return (self.major, self.minor, self.build) < (
            other.major,
            other.minor,
            other.build,
        )

    def __le__(self, other: object) -> bool:
        return self == other or self < other

    def __gt__(self, other: object) -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        return (self.major, self.minor, self.build) > (
            other.major,
            other.minor,
            other.build,
        )

    def __ge__(self, other: object) -> bool:
        return self == other or self > other
