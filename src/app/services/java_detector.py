from __future__ import annotations
import os
import re
import subprocess
import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Set, Dict, Callable


JAVA_KEYWORDS = [
    "java",
    "jdk",
    "jre",
    "jvm",
    "oracle",
    "zulu",
    "corretto",
    "runtime",
    "adoptium",
    "adoptopenjdk",
    "temurin",
    "liberica",
    "graalvm",
    "ojdk",
    "mc",
    "forge",
    "fabric",
    "minecraft",
]

DRIVE_LETTERS = [f"{chr(c)}:\\" for c in range(ord("A"), ord("Z") + 1)]

MAJOR_VERSION_WEIGHTS = {
    21: 100,
    17: 95,
    11: 90,
    8: 85,
    22: 80,
    20: 75,
    19: 70,
    18: 65,
    16: 60,
    15: 55,
    14: 50,
    13: 45,
    12: 40,
    10: 35,
    9: 30,
    7: 25,
    6: 20,
    5: 15,
}


@dataclass
class JavaInfo:
    path: str
    version: str = ""
    major_version: int = 0
    is_64bit: bool = True
    is_jdk: bool = False
    is_mc_related: bool = False
    score: int = 0

    def __post_init__(self):
        self._parse_version()

    def _parse_version(self):
        try:
            result = subprocess.run(
                [self.path, "-version"], capture_output=True, text=True, timeout=5
            )
            output = result.stderr or result.stdout

            match = re.search(r'"(\d+\.\d+\.\d+)[^"]*"', output)
            if match:
                self.version = match.group(1)
                parts = self.version.split(".")
                if len(parts) >= 2:
                    self.major_version = int(parts[1])

            if '"64-Bit"' in output or '"64-bit"' in output:
                self.is_64bit = True
            elif '"32-Bit"' in output or '"32-bit"' in output:
                self.is_64bit = False

            path_lower = self.path.lower()
            self.is_jdk = any(
                k in path_lower for k in ["jdk", "sdk", "bin\\..", "java\\jdk"]
            )
            self.is_mc_related = any(
                k in path_lower for k in ["mc", "forge", "fabric", "minecraft"]
            )

            self._calculate_score()
        except Exception:
            self.version = "Unknown"

    def _calculate_score(self):
        score = 0

        if self.is_mc_related:
            score += 50

        if self.is_64bit:
            score += 30
        else:
            score -= 20

        if self.is_jdk:
            score += 10
        else:
            score += 5

        score += MAJOR_VERSION_WEIGHTS.get(self.major_version, 30)

        self.score = score


class JavaDetector:
    def __init__(self, mc_path: Optional[str] = None):
        self.mc_path = Path(mc_path) if mc_path else None
        self._found_javas: Dict[str, JavaInfo] = {}
        self._user_imported_paths: Set[str] = set()
        self._on_java_found: Callable[[JavaInfo], None] | None = None
        self._scan_task: asyncio.Task | None = None
        self._cancelled = False

    def set_on_java_found(self, callback: Callable[[JavaInfo], None] | None):
        self._on_java_found = callback

    def add_user_import(self, path: str):
        if os.path.exists(path):
            self._user_imported_paths.add(path)

    def get_user_imported(self) -> Set[str]:
        return self._user_imported_paths.copy()

    def cancel(self):
        self._cancelled = True
        if self._scan_task:
            self._scan_task.cancel()

    async def scan_async(self) -> List[JavaInfo]:
        self._found_javas.clear()
        self._cancelled = False

        self._scan_task = asyncio.create_task(self._scan_all())
        await self._scan_task

        results = list(self._found_javas.values())
        results.sort(key=lambda x: x.score, reverse=True)
        return results

    async def _scan_all(self):
        await asyncio.gather(
            self._scan_env_variables(),
            self._scan_special_folders(),
            return_exceptions=True,
        )
        asyncio.create_task(self._scan_disk_drives())

    def scan_sync(self) -> List[JavaInfo]:
        return asyncio.run(self.scan_async())

    async def _scan_env_variables(self):
        await asyncio.to_thread(self._scan_env_variables_sync)

    def _scan_env_variables_sync(self):
        java_paths = set()

        path_env = os.environ.get("PATH", "")
        for p in path_env.split(os.pathsep):
            if self._cancelled:
                return
            exe = os.path.join(p, "java.exe")
            javaw = os.path.join(p, "javaw.exe")
            if os.path.exists(exe):
                java_paths.add(exe)
            if os.path.exists(javaw):
                java_paths.add(javaw)

        java_home = os.environ.get("JAVA_HOME", "")
        if java_home:
            exe = os.path.join(java_home, "java.exe")
            if os.path.exists(exe):
                java_paths.add(exe)

        for path in java_paths:
            if self._cancelled:
                return
            self._add_java(path)

    async def _scan_special_folders(self):
        await asyncio.to_thread(self._scan_special_folders_sync)

    def _scan_special_folders_sync(self):
        special_paths = []

        user_profile = os.environ.get("USERPROFILE", "")
        if user_profile:
            special_paths.extend(
                [
                    os.path.join(user_profile, ".jdks"),
                    os.path.join(user_profile, "jdks"),
                    os.path.join(user_profile, ".sdkman", "candidates", "java"),
                ]
            )

        java_home = os.environ.get("JAVA_HOME", "")
        if java_home:
            special_paths.append(java_home)

        special_paths.extend(
            [
                os.path.join(os.environ.get("ProgramFiles", ""), "Java"),
                os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Java"),
                os.path.join(os.environ.get("ProgramW6432", ""), "Java"),
                os.path.join(
                    os.environ.get("LocalAppData", ""), "Programs", "AdoptOpenJDK"
                ),
                os.path.join(
                    os.environ.get("LocalAppData", ""), "Programs", "Adoptium"
                ),
                os.path.join(
                    os.environ.get("LocalAppData", ""), "Programs", "Eclipse Adoptium"
                ),
            ]
        )

        if self.mc_path:
            special_paths.append(str(self.mc_path))
            special_paths.append(str(self.mc_path.parent))

        current_exe_dir = os.path.dirname(os.path.abspath(__file__))
        special_paths.append(current_exe_dir)

        for base_path in special_paths:
            if self._cancelled:
                return
            if base_path and os.path.exists(base_path):
                self._walk_directory_with_limit(base_path, max_depth=3)

    async def _scan_disk_drives(self):
        await asyncio.to_thread(self._scan_disk_drives_sync)

    def _scan_disk_drives_sync(self):
        for drive in DRIVE_LETTERS:
            if self._cancelled:
                return
            if not os.path.exists(drive):
                continue
            try:
                if not os.path.isdir(drive):
                    continue
            except Exception:
                continue
            self._walk_with_keyword_filter(drive)

    def _walk_with_keyword_filter(
        self, root: str, max_depth: int = 4, current_depth: int = 0
    ):
        if current_depth > max_depth or self._cancelled:
            return

        try:
            entries = os.listdir(root)
        except PermissionError:
            return
        except OSError:
            return

        root_lower = root.lower()

        if any(keyword in root_lower for keyword in JAVA_KEYWORDS):
            self._walk_directory(root)
            return

        for entry in entries:
            if current_depth >= max_depth or self._cancelled:
                break
            try:
                entry_path = os.path.join(root, entry)
                if os.path.isdir(entry_path):
                    self._walk_with_keyword_filter(
                        entry_path, max_depth, current_depth + 1
                    )
            except PermissionError:
                continue
            except OSError:
                continue

    def _walk_directory(self, path: str):
        try:
            for root, dirs, files in os.walk(path):
                if self._cancelled:
                    return
                for file in files:
                    if self._cancelled:
                        return
                    if file.lower() in ("java.exe", "javaw.exe"):
                        java_path = os.path.join(root, file)
                        self._add_java(java_path)
        except PermissionError:
            pass
        except OSError:
            pass

    def _walk_directory_with_limit(self, path: str, max_depth: int = 3):
        try:
            for root, dirs, files in os.walk(path):
                if self._cancelled:
                    return
                depth = root[len(path) :].count(os.sep)
                if depth >= max_depth:
                    dirs.clear()
                    continue
                for file in files:
                    if self._cancelled:
                        return
                    if file.lower() in ("java.exe", "javaw.exe"):
                        java_path = os.path.join(root, file)
                        self._add_java(java_path)
        except PermissionError:
            pass
        except OSError:
            pass

    def _add_java(self, path: str):
        if path in self._found_javas:
            return

        normalized = os.path.normpath(path)
        if normalized in self._found_javas:
            return

        java_info = JavaInfo(path)
        self._found_javas[normalized] = java_info

        if self._on_java_found:
            try:
                self._on_java_found(java_info)
            except Exception:
                pass

    def get_detected_paths(self) -> List[str]:
        return [java.path for java in self._found_javas.values()]
