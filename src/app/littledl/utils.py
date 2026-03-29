import contextlib
import hashlib
import mimetypes
import re
import time
import uuid
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

MIME_SIGNATURES: dict[bytes, str] = {
    b"\x89PNG\r\n\x1a\n": ".png",
    b"\xff\xd8\xff": ".jpg",
    b"GIF87a": ".gif",
    b"GIF89a": ".gif",
    b"PK\x03\x04": ".zip",
    b"%PDF": ".pdf",
    b"Rar!\x1a\x07": ".rar",
    b"\x1f\x8b\x08": ".gz",
    b"BZh": ".bz2",
    b"\xfd7zXZ\x00": ".xz",
    b"\x50\x4b\x03\x04\x14\x00\x06\x00": ".docx",
    b"\x50\x4b\x03\x04\x14\x00\x08\x00": ".xlsx",
    b"\x50\x4b\x03\x04\x14\x00\x00\x00": ".pptx",
}

INVALID_FILENAME_CHARS = re.compile(r'[<>:"|?*\x00-\x1f]')
PATH_TRAVERSAL_PATTERN = re.compile(r"(^|/)\.\.(/|$)")


def safe_filename(filename: str | None, default: str = "download") -> str:
    if not filename:
        return default
    filename = filename.strip()
    if not filename or filename in (".", ".."):
        return default
    filename = INVALID_FILENAME_CHARS.sub("_", filename)
    filename = PATH_TRAVERSAL_PATTERN.sub("_", filename)
    if filename.startswith("."):
        filename = "_" + filename[1:]
    return filename[:255] or default


OFFICE_MIME_MAP: dict[str, str] = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/msword": ".doc",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.ms-powerpoint": ".ppt",
}


def format_size(size_bytes: int) -> str:
    size = float(size_bytes)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024.0:
            return f"{size:.2f} {unit}" if unit != "B" else f"{int(size)} {unit}"
        size /= 1024.0
    return f"{size:.2f} PB"


def format_speed(bytes_per_second: float) -> str:
    return f"{format_size(int(bytes_per_second))}/s"


def format_time(seconds: float) -> str:
    if seconds < 0:
        return "Unknown"
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}m {secs}s"
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    return f"{hours}h {minutes}m"


def generate_download_id(url: str) -> str:
    url_hash = hashlib.sha256(url.encode()).hexdigest()[:12]
    return f"dl_{url_hash}"


def generate_chunk_id() -> str:
    return str(uuid.uuid4())[:8]


def generate_temp_filename(download_id: str, chunk_index: int | None = None) -> str:
    if chunk_index is not None:
        return f".{download_id}_chunk_{chunk_index}.tmp"
    return f".{download_id}.tmp"


def generate_meta_filename(download_id: str) -> str:
    return f".{download_id}.meta"


def parse_content_range(content_range: str) -> tuple[int, int, int] | None:
    match = re.match(r"bytes\s+(\d+)-(\d+)/(\d+|\*)", content_range, re.IGNORECASE)
    if not match:
        return None
    start = int(match.group(1))
    end = int(match.group(2))
    total = int(match.group(3)) if match.group(3) != "*" else -1
    return (start, end, total)


def parse_content_length(content_length: str | None) -> int:
    if not content_length:
        return -1
    try:
        return int(content_length)
    except ValueError:
        return -1


def parse_content_disposition(content_disposition: str | None) -> str | None:
    if not content_disposition:
        return None
    match_star = re.findall(r"filename\*\s*=\s*([^;]+)", content_disposition, re.IGNORECASE)
    if match_star:
        value = match_star[-1].strip().strip('"').strip("'")
        if "''" in value:
            _, value = value.split("''", 1)
        return safe_filename(unquote(value))
    match = re.findall(r"filename\s*=\s*([^;]+)", content_disposition, re.IGNORECASE)
    if match:
        return safe_filename(match[-1].strip().strip('"').strip("'"))
    return None


def guess_extension_from_mime(mime_type: str) -> str | None:
    if not mime_type:
        return None
    mime_type = mime_type.split(";")[0].strip().lower()
    ext = mimetypes.guess_extension(mime_type)
    if ext:
        return ext
    return OFFICE_MIME_MAP.get(mime_type)


def guess_extension_from_signature(data: bytes) -> str | None:
    for signature, ext in MIME_SIGNATURES.items():
        if data.startswith(signature):
            return ext
    return None


def extract_filename_from_url(url: str) -> str | None:
    parsed = urlparse(url)
    path = unquote(parsed.path)
    filename = Path(path).name
    return safe_filename(filename) if filename else None


def extract_filename_from_query(url: str) -> str | None:
    parsed = urlparse(url)
    query_params = parse_qs(parsed.query)
    rcd_values = query_params.get("response-content-disposition", [])
    if rcd_values:
        decoded = unquote(rcd_values[-1])
        return parse_content_disposition(decoded)
    return None


def determine_filename(
    url: str,
    content_disposition: str | None = None,
    content_type: str | None = None,
    custom_filename: str | None = None,
    file_signature: bytes | None = None,
) -> str:
    if custom_filename:
        return custom_filename
    filename: str | None = None
    ext: str | None = None
    filename = parse_content_disposition(content_disposition)
    if filename:
        ext = Path(filename).suffix.lower() or None
    if not filename:
        filename = extract_filename_from_query(url)
        if filename:
            ext = Path(filename).suffix.lower() or None
    if not filename:
        filename = extract_filename_from_url(url)
        if filename:
            ext = Path(filename).suffix.lower() or None
    if not ext and content_type:
        ext = guess_extension_from_mime(content_type)
    if not ext and file_signature:
        ext = guess_extension_from_signature(file_signature)
    if not filename:
        timestamp = int(time.time())
        ext = ext or ".bin"
        filename = f"download_{timestamp}{ext}"
    elif ext and not filename.lower().endswith(ext.lower()):
        stem = Path(filename).stem
        filename = f"{stem}{ext}"
    return filename


def exponential_backoff(attempt: int, base_delay: float = 1.0, max_delay: float = 30.0, jitter: bool = True) -> float:
    delay = min(base_delay * (2**attempt), max_delay)
    if jitter:
        import random

        delay = delay * (0.5 + random.random())
    return delay


def calculate_eta(downloaded: int, total: int, speed: float) -> float:
    if speed <= 0:
        return -1
    remaining = total - downloaded
    return remaining / speed


def normalize_url(url: str) -> str:
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


def validate_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        return bool(parsed.scheme and parsed.netloc)
    except Exception:
        return False


def merge_chunks(
    chunk_files: list[Path],
    output_path: Path,
    chunk_size: int = 64 * 1024 * 1024,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sorted_files = sorted(chunk_files, key=lambda p: extract_chunk_index(p.name))
    with open(output_path, "wb") as outfile:
        for chunk_file in sorted_files:
            with open(chunk_file, "rb") as infile:
                while True:
                    data = infile.read(chunk_size)
                    if not data:
                        break
                    outfile.write(data)


def extract_chunk_index(filename: str) -> int:
    match = re.search(r"_chunk_(\d+)\.tmp$", filename)
    if match:
        return int(match.group(1))
    return 0


def safe_move(src: Path, dst: Path) -> None:
    import shutil

    dst.parent.mkdir(parents=True, exist_ok=True)
    temp_dst = dst.with_suffix(dst.suffix + ".tmp_move")
    shutil.move(str(src), str(temp_dst))
    temp_dst.rename(dst)


def clean_temp_files(directory: Path, download_id: str | None = None) -> None:
    if not directory.exists():
        return
    pattern = f".{'*' if download_id is None else download_id}*.tmp"
    for temp_file in directory.glob(pattern):
        with contextlib.suppress(Exception):
            temp_file.unlink(missing_ok=True)
    if download_id:
        meta_pattern = f".{download_id}*.meta"
        for meta_file in directory.glob(meta_pattern):
            with contextlib.suppress(Exception):
                meta_file.unlink(missing_ok=True)


class SpeedCalculator:
    def __init__(self, window_size: int = 10) -> None:
        self.window_size = window_size
        self.samples: list[tuple[float, int]] = []
        self._last_speed: float = 0.0

    def add_sample(self, bytes_downloaded: int) -> None:
        now = time.time()
        self.samples.append((now, bytes_downloaded))
        while len(self.samples) > self.window_size:
            self.samples.pop(0)

    def get_speed(self) -> float:
        if len(self.samples) < 2:
            return self._last_speed
        time_diff = self.samples[-1][0] - self.samples[0][0]
        if time_diff <= 0:
            return self._last_speed
        total_bytes = sum(bytes_count for _, bytes_count in self.samples[1:])
        speed = total_bytes / time_diff
        self._last_speed = speed
        return speed

    def get_average_speed(self) -> float:
        return self._last_speed

    def reset(self) -> None:
        self.samples.clear()
        self._last_speed = 0.0


class MovingAverage:
    def __init__(self, window_size: int = 5) -> None:
        self.window_size = window_size
        self.values: list[float] = []
        self._weighted_multiplier: float = 0.7

    def add(self, value: float) -> None:
        self.values.append(value)
        if len(self.values) > self.window_size:
            self.values.pop(0)

    def get_average(self) -> float:
        if not self.values:
            return 0.0
        return sum(self.values) / len(self.values)

    def get_weighted_average(self) -> float:
        if not self.values:
            return 0.0
        weights = [self._weighted_multiplier ** (len(self.values) - i - 1) for i in range(len(self.values))]
        total_weight = sum(weights)
        return sum(v * w for v, w in zip(self.values, weights)) / total_weight

    def get_median(self) -> float:
        if not self.values:
            return 0.0
        sorted_vals = sorted(self.values)
        n = len(sorted_vals)
        if n % 2 == 0:
            return (sorted_vals[n // 2 - 1] + sorted_vals[n // 2]) / 2
        return sorted_vals[n // 2]

    def get_smoothed_average(self, smoothing_factor: float = 0.3) -> float:
        if not self.values:
            return 0.0
        if len(self.values) == 1:
            return self.values[0]
        smoothed = self.values[0]
        for val in self.values[1:]:
            smoothed = smoothing_factor * val + (1 - smoothing_factor) * smoothed
        return smoothed

    def get_trend(self) -> float:
        if len(self.values) < 2:
            return 0.0
        recent = self.values[-min(3, len(self.values)) :]
        older = self.values[: -min(3, len(self.values))] if len(self.values) > 3 else self.values[:-1]
        if not older:
            return 0.0
        recent_avg = sum(recent) / len(recent)
        older_avg = sum(older) / len(older)
        if older_avg == 0:
            return 0.0
        return (recent_avg - older_avg) / older_avg

    def get_stability(self) -> float:
        if len(self.values) < 2:
            return 1.0
        avg = self.get_average()
        if avg == 0:
            return 0.0
        variance = sum((v - avg) ** 2 for v in self.values) / len(self.values)
        std_dev = variance**0.5
        return max(0.0, 1.0 - (std_dev / avg))

    def is_stable(self, threshold: float = 0.3) -> bool:
        return self.get_stability() >= threshold


def is_path_safe(save_path: Path, final_path: Path, allowed_dir: Path) -> bool:
    try:
        resolved = final_path.resolve()
        allowed = allowed_dir.resolve()
        return str(resolved).startswith(str(allowed))
    except Exception:
        return False


def resolve_download_path(save_path: Path, filename: str | None, allowed_dir: Path | None = None) -> tuple[Path, Path]:
    save_path = save_path.expanduser().resolve()
    if filename:
        filename = safe_filename(filename, "download")
    if save_path.is_dir():
        if not filename:
            filename = "download.bin"
        final_path = save_path / filename
    else:
        final_path = save_path
        save_path = final_path.parent
    if allowed_dir:
        resolved_final = final_path.resolve()
        resolved_allowed = allowed_dir.resolve()
        if not str(resolved_final).startswith(str(resolved_allowed)):
            raise ValueError(f"Path {resolved_final} is outside allowed directory {resolved_allowed}")
    return save_path, final_path


def calculate_file_hash(file_path: Path, algorithm: str = "md5") -> str:
    """计算文件哈希值"""
    hash_func = hashlib.new(algorithm)
    with open(file_path, "rb") as f:
        while True:
            data = f.read(1024 * 1024)
            if not data:
                break
            hash_func.update(data)
    return hash_func.hexdigest()
