import argparse
import asyncio
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any, TextIO

import httpx

from . import DownloadConfig, download_file
from .batch import BatchDownloader, FileTaskStatus
from .i18n import gettext as _
from .strategy import DownloadStyle, StrategySelector
from .utils import determine_filename, validate_url


def parse_args(args: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="littledl",
        description=_(
            "High-performance download library with multi-threaded segmented downloading, intelligent strategy selection, and adaptive optimization."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_(
            "Exit codes:\n"
            "  0 - Success\n"
            "  1 - General error\n"
            "  2 - URL error or invalid argument\n"
            "  3 - Download failed after retries\n"
            "  4 - Cancelled by user\n"
        ),
    )
    parser.add_argument(
        "urls",
        nargs="*",
        help=_("URL(s) to download. Single URL for single file, multiple URLs or -F for batch download"),
    )
    parser.add_argument(
        "-F", "--batch-file", dest="batch_file", help=_("File containing URLs to download (one per line)")
    )
    parser.add_argument("-o", "--output", dest="output", help=_("Output directory or file path"))
    parser.add_argument("-f", "--filename", dest="filename", help=_("Specify output filename"))
    parser.add_argument(
        "-s",
        "--style",
        dest="style",
        choices=["single", "multi", "adaptive", "hybrid", "hybrid_turbo", "auto"],
        default="hybrid_turbo",
        help=_(
            "Download style: single (单线程), multi (多线程分段), adaptive (传统自适应), hybrid_turbo (极速稳态), auto (自动分析)"
        ),
    )
    parser.add_argument("-i", "--info", dest="info_only", action="store_true", help=_("Show file info and exit"))
    parser.add_argument("--no-resume", dest="resume", action="store_false", default=True, help=_("Disable resume"))
    parser.add_argument(
        "-c",
        "--max-chunks",
        dest="max_chunks",
        type=int,
        default=16,
        help=_("Maximum number of chunks for multi-threaded download"),
    )
    parser.add_argument("-t", "--timeout", dest="timeout", type=int, default=300, help=_("Timeout in seconds"))
    parser.add_argument("--proxy", dest="proxy", help=_("HTTP proxy (e.g., http://proxy:8080)"))
    parser.add_argument("--user-agent", dest="user_agent", help=_("Custom User-Agent"))
    parser.add_argument(
        "--verify-ssl", dest="verify_ssl", action="store_true", default=True, help=_("Verify SSL certificates")
    )
    parser.add_argument("--no-verify-ssl", dest="verify_ssl", action="store_false", help=_("Skip SSL verification"))
    parser.add_argument("--speed-limit", dest="speed_limit", type=int, help=_("Speed limit in bytes per second"))
    parser.add_argument("--retry", dest="retry", type=int, default=3, help=_("Maximum retry attempts"))
    parser.add_argument("-v", "--verbose", action="store_true", help=_("Verbose output"))
    parser.add_argument(
        "--max-concurrent",
        dest="max_concurrent",
        type=int,
        default=3,
        help=_("Maximum concurrent downloads for batch mode"),
    )
    parser.add_argument("--quiet", "-q", dest="quiet", action="store_true", help=_("Quiet mode (minimal output)"))
    parser.add_argument("--force", dest="force", action="store_true", help=_("Force download even if file exists"))
    parser.add_argument(
        "--temp-dir",
        dest="temp_dir",
        type=str,
        default=None,
        help=_("Temporary directory for download temp files"),
    )
    parser.add_argument(
        "--output-format",
        dest="output_format",
        choices=["auto", "json", "text"],
        default="auto",
        help=_("Output format: auto (根据环境), json (结构化), text (纯文本)"),
    )
    parser.add_argument("--version", action="version", version="%(prog)s 0.7.0")
    return parser.parse_args(args)


class OutputMode:
    """Handles output mode selection based on environment and user preference."""

    def __init__(self, format_pref: str = "auto", quiet: bool = False, is_tty: bool | None = None) -> None:
        self.format_pref = format_pref
        self.quiet = quiet
        self._is_tty = is_tty if is_tty is not None else sys.stdout.isatty()
        self._json_mode = format_pref == "json" or (format_pref == "auto" and not self._is_tty)

    @property
    def use_json(self) -> bool:
        return self._json_mode

    @property
    def use_progress_bar(self) -> bool:
        return not self.quiet and self._is_tty and not self._json_mode

    def print(self, *args: Any, **kwargs: Any) -> None:
        if self.quiet and self._json_mode:
            return
        print(*args, **kwargs)

    def print_json(self, data: dict[str, Any]) -> None:
        if self.use_json:
            print(json.dumps(data, ensure_ascii=False, indent=2))
        else:
            self._print_dict_as_text(data)

    def _print_dict_as_text(self, data: dict[str, Any], prefix: str = "") -> None:
        for key, value in data.items():
            if isinstance(value, dict):
                self.print(f"{prefix}{key}:")
                self._print_dict_as_text(value, prefix + "  ")
            elif isinstance(value, list):
                for i, item in enumerate(value):
                    if isinstance(item, dict):
                        self.print(f"{prefix}{key}[{i}]:")
                        self._print_dict_as_text(item, prefix + "  ")
                    else:
                        self.print(f"{prefix}{key}[{i}]: {item}")
            else:
                self.print(f"{prefix}{key}: {value}")


def style_to_enum(style_str: str) -> DownloadStyle:
    """Convert CLI style string to DownloadStyle enum"""
    mapping = {
        "single": DownloadStyle.SINGLE,
        "multi": DownloadStyle.MULTI,
        "adaptive": DownloadStyle.ADAPTIVE,
        "hybrid": DownloadStyle.HYBRID_TURBO,
        "hybrid_turbo": DownloadStyle.HYBRID_TURBO,
        "auto": DownloadStyle.HYBRID_TURBO,
    }
    return mapping.get(style_str.lower(), DownloadStyle.HYBRID_TURBO)


def read_urls_from_file(file_path: str) -> list[tuple[int, str]]:
    """Read URLs from a file, ignoring empty lines and comments.

    Returns:
        List of (line_number, url) tuples for valid URLs.
    """
    urls = []
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Batch file not found: {file_path}")

    with open(path, encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if not validate_url(line):
                continue
            urls.append((line_num, line))
    return urls


async def probe_url(url: str, config: DownloadConfig) -> dict[str, Any]:
    timeout = httpx.Timeout(
        connect=config.connect_timeout,
        read=config.read_timeout,
        write=config.write_timeout,
        pool=config.write_timeout,
    )

    async with httpx.AsyncClient(verify=config.verify_ssl) as client:
        headers = config.get_headers(url)
        response = await client.head(url, headers=headers, follow_redirects=True, timeout=timeout)

        content_disposition = response.headers.get("Content-Disposition")
        content_type = response.headers.get("Content-Type")
        content_length = response.headers.get("Content-Length")
        accept_ranges = response.headers.get("Accept-Ranges", "").lower()

        file_size = int(content_length) if content_length else -1
        supports_range = accept_ranges == "bytes"
        supports_resume = supports_range and file_size > 0

        filename = determine_filename(url, content_disposition, content_type)

        return {
            "url": url,
            "filename": filename,
            "size": file_size,
            "supports_range": supports_range,
            "supports_resume": supports_resume,
            "content_type": content_type,
            "etag": response.headers.get("ETag"),
            "last_modified": response.headers.get("Last-Modified"),
        }


def format_size(bytes_num: float) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if bytes_num < 1024:
            return f"{bytes_num:6.1f}{unit}" if bytes_num >= 100 else f"{bytes_num:5.2f}{unit}"
        bytes_num /= 1024
    return f"{bytes_num:6.1f}PB"


def format_time(seconds: float) -> str:
    if seconds < 0:
        return "--:--"
    if seconds < 60:
        return f"{seconds:5.1f}s"
    if seconds < 3600:
        mins = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{mins:02d}m {secs:02d}s"
    hours = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    return f"{hours}h {mins:02d}m"


class ProgressDisplay:
    def __init__(self, output: TextIO = sys.stdout) -> None:
        self.last_len = 0
        self._output = output

    def clear(self) -> None:
        if self.last_len > 0:
            self._output.write("\r" + " " * self.last_len)
            self._output.write("\r")
            self._output.flush()
            self.last_len = 0

    def update(self, downloaded: int, total: int, speed: float, eta: int) -> None:
        if total <= 0:
            return

        downloaded_str = format_size(downloaded)
        total_str = format_size(total)
        speed_str = f"{format_size(speed)}/s"

        progress = downloaded / total
        bar_len = min(40, shutil.get_terminal_size().columns - 70)
        filled = int(bar_len * progress)
        bar = "[" + "=" * filled + " " * (bar_len - filled) + "]"

        if eta > 0:
            eta_str = format_time(eta)
            line = f"{bar} {progress * 100:5.1f}% | {downloaded_str:>8} / {total_str:<8} | {speed_str:>10} | ETA: {eta_str}"
        else:
            line = f"{bar} {progress * 100:5.1f}% | {downloaded_str:>8} / {total_str:<8} | {speed_str:>10}"

        self.clear()
        self._output.write(line)
        self._output.flush()
        self.last_len = len(line)

    def finish(self) -> None:
        self.clear()


class BatchProgressDisplay:
    """Progress display for batch downloads with multiple files."""

    def __init__(self, total_tasks: int, quiet: bool = False) -> None:
        self.total_tasks = total_tasks
        self.quiet = quiet
        self.tasks: dict[str, dict] = {}
        self.completed = 0
        self.failed = 0
        self.cancelled = 0
        self.total_bytes = 0
        self.downloaded_bytes = 0
        self.total_speed = 0.0
        self.start_time = time.time()
        self._last_update = 0.0
        self._update_interval = 0.3
        self._closed = False
        self._prev_len = 0

    def add_task(self, task_id: str, filename: str, url: str, size: int = -1) -> None:
        self.tasks[task_id] = {
            "filename": filename,
            "url": url,
            "size": size,
            "downloaded": 0,
            "speed": 0.0,
            "status": FileTaskStatus.PENDING.value,
            "error": None,
        }
        if size > 0:
            self.total_bytes += size

    def update_task(self, task_id: str, downloaded: int, speed: float, status: FileTaskStatus) -> None:
        if task_id not in self.tasks:
            return
        self.tasks[task_id]["downloaded"] = downloaded
        self.tasks[task_id]["speed"] = speed
        self.tasks[task_id]["status"] = status.value
        self.downloaded_bytes = sum(t["downloaded"] for t in self.tasks.values())
        self.total_speed = sum(
            t["speed"] for t in self.tasks.values() if t["status"] == FileTaskStatus.DOWNLOADING.value
        )
        self._maybe_display()

    def complete_task(self, task_id: str, success: bool, error: str | None = None) -> None:
        if task_id not in self.tasks:
            return
        self.tasks[task_id]["status"] = FileTaskStatus.COMPLETED.value if success else FileTaskStatus.FAILED.value
        self.tasks[task_id]["error"] = error
        if success:
            self.completed += 1
        else:
            self.failed += 1
        self.total_speed = sum(
            t["speed"] for t in self.tasks.values() if t["status"] == FileTaskStatus.DOWNLOADING.value
        )
        self._maybe_display()

    def _maybe_display(self) -> None:
        if self.quiet or self._closed:
            return
        now = time.time()
        if now - self._last_update < self._update_interval:
            return
        self._last_update = now
        self._display()

    def _display(self) -> None:
        if self._closed:
            return

        elapsed = time.time() - self.start_time
        lines = []

        header = f"\r[_('Batch Download')]: {self.completed}/{self.total_tasks} completed, {self.failed} failed"
        if self.total_bytes > 0:
            overall_progress = self.downloaded_bytes / self.total_bytes * 100
            header += (
                f" | {overall_progress:5.1f}% | {format_size(self.downloaded_bytes)}/{format_size(self.total_bytes)}"
            )
        if self.total_speed > 0:
            header += f" | {format_size(self.total_speed)}/s"
        if elapsed > 0:
            header += f" | {format_time(elapsed)}"
        lines.append(header)

        active_tasks = [(tid, t) for tid, t in self.tasks.items() if t["status"] == FileTaskStatus.DOWNLOADING.value]
        for _tid, task in active_tasks[:3]:
            filename = task["filename"][:30]
            if task["size"] > 0:
                pct = task["downloaded"] / task["size"] * 100
                prog = f"{pct:5.1f}%"
                size_str = f"{format_size(task['downloaded'])}/{format_size(task['size'])}"
            else:
                prog = "---.-%"
                size_str = format_size(task["downloaded"])
            lines.append(f"  [{prog}] {filename}: {size_str} ({format_size(task['speed'])}/s)")

        if len(active_tasks) > 3:
            lines.append(f"  ... and {len(active_tasks) - 3} more")

        line_len = 0
        for line in lines:
            line_len = max(line_len, len(line))

        output = "\r" + "\n".join(lines)
        output += " " * max(0, self._prev_len - line_len)
        self._prev_len = line_len
        output += "\r"

        sys.stdout.write(output)
        for _i in lines[:-1]:
            sys.stdout.write("\033[1A")
        sys.stdout.flush()

    def finish(self) -> None:
        self._closed = True
        if self.quiet:
            return
        elapsed = time.time() - self.start_time
        print()
        print(f"{'=' * 50}")
        print(f"{_('Batch Download Summary')}:")
        print(f"  {_('Total')}: {self.total_tasks}")
        print(f"  {_('Completed')}: {self.completed}")
        print(f"  {_('Failed')}: {self.failed}")
        print(f"  {_('Total downloaded')}: {format_size(self.downloaded_bytes)}")
        print(f"  {_('Time elapsed')}: {format_time(elapsed)}")
        if elapsed > 0:
            print(f"  {_('Average speed')}: {format_size(self.downloaded_bytes / elapsed)}/s")

    def get_results(self) -> dict[str, Any]:
        """Get structured results for JSON output."""
        elapsed = time.time() - self.start_time
        return {
            "total": self.total_tasks,
            "completed": self.completed,
            "failed": self.failed,
            "cancelled": self.cancelled,
            "total_bytes": self.downloaded_bytes,
            "elapsed_seconds": elapsed,
            "average_speed": self.downloaded_bytes / elapsed if elapsed > 0 else 0,
            "tasks": [
                {
                    "filename": t["filename"],
                    "url": t["url"],
                    "status": t["status"],
                    "size": t["size"],
                    "downloaded": t["downloaded"],
                    "error": t["error"],
                }
                for t in self.tasks.values()
            ],
        }


async def run_analyze(url: str, config: DownloadConfig, output: OutputMode) -> int:
    try:
        recommendation = await analyze_and_recommend(url, config)
        if output.use_json:
            output.print_json(
                {
                    "type": "analysis",
                    "success": True,
                    "data": {
                        "file": recommendation["file_info"],
                        "style": recommendation["style"].value,
                        "recommended_chunks": recommendation["recommended_chunks"],
                        "estimated_speedup": recommendation["estimated_speedup"],
                        "reason": recommendation["reason"],
                    },
                }
            )
        else:
            print_file_info(recommendation["file_info"], output)
            print_strategy_recommendation(recommendation, output)
        return 0
    except Exception as e:
        if output.use_json:
            output.print_json({"type": "analysis", "success": False, "error": str(e)})
        else:
            print(f"\n{_('Failed to analyze URL')}: {e}")
        return 1


async def run_probe(url: str, config: DownloadConfig, output: OutputMode) -> int:
    try:
        info = await probe_url(url, config)
        if output.use_json:
            output.print_json({"type": "probe", "success": True, "data": info})
        else:
            print_file_info(info, output)
        return 0
    except Exception as e:
        if output.use_json:
            output.print_json({"type": "probe", "success": False, "error": str(e)})
        else:
            print(f"\n{_('Failed to probe URL')}: {e}")
        return 1


async def run_download(
    url: str,
    config: DownloadConfig,
    save_path: Path,
    output: OutputMode,
    args: argparse.Namespace,
    style: DownloadStyle,
) -> int:
    """Run single file download."""
    probe_info = await probe_url(url, config)

    if output.use_progress_bar:
        print(f"{_('Starting download')}: {url}")
        print(f"{_('Style')}: {style.value.upper()}")
        print(f"{_('Output')}: {save_path}")

    if args.style == "auto":
        selector = StrategySelector(enable_single=True, enable_multi=True)
        profile = selector.analyze_file(
            url,
            probe_info["size"],
            probe_info["supports_range"],
            probe_info.get("content_type", ""),
        )
        decision = selector.select_style(profile)
        config.apply_style(decision.style)
        if output.use_progress_bar and args.verbose:
            print(f"{_('Auto-selected style')}: {decision.style.value.upper()} ({decision.reason})")

    progress = ProgressDisplay() if output.use_progress_bar else None

    def progress_callback(downloaded: int, total: int, speed: float, eta: int) -> None:
        if progress:
            progress.update(downloaded, total, speed, eta)

    try:
        path = await download_file(
            url=url,
            save_path=str(save_path.parent),
            filename=save_path.name,
            config=config,
            progress_callback=progress_callback,
            resume=args.resume,
        )
        if progress:
            progress.finish()

        if output.use_json:
            output.print_json(
                {
                    "type": "download",
                    "success": True,
                    "path": str(path),
                    "size": path.stat().st_size if path.exists() else 0,
                }
            )
        else:
            print(f"\n{_('Download complete')}: {path}")
        return 0
    except KeyboardInterrupt:
        if progress:
            progress.finish()
        if output.use_json:
            output.print_json({"type": "download", "success": False, "error": "Cancelled by user", "cancelled": True})
        else:
            print(f"\n{_('Download cancelled')}")
        return 4
    except Exception as e:
        if progress:
            progress.finish()
        if output.use_json:
            output.print_json({"type": "download", "success": False, "error": str(e)})
        else:
            print(f"\n{_('Download failed')}: {e}")
        return 1


async def run_batch_download(
    urls: list[tuple[int, str]],
    config: DownloadConfig,
    output_path: Path,
    max_concurrent: int,
    output: OutputMode,
    args: argparse.Namespace,
) -> int:
    """Run batch download using BatchDownloader."""
    if not urls:
        if output.use_json:
            output.print_json({"type": "batch", "success": True, "completed": 0, "failed": 0, "tasks": []})
        else:
            print(f"{_('No URLs to download')}")
        return 0

    if output.use_progress_bar:
        print(f"{_('Starting batch download')}: {len(urls)} {_('URLs')}")
        print(f"{_('Output directory')}: {output_path}")
        print(f"{_('Max concurrent')}: {max_concurrent}")

    display = BatchProgressDisplay(total_tasks=len(urls), quiet=output.quiet or not output.use_progress_bar)

    batch = BatchDownloader(
        config=config,
        max_concurrent_files=max_concurrent,
        max_concurrent_chunks_per_file=config.max_chunks,
        enable_adaptive_concurrency=True,
        enable_small_file_priority=True,
    )

    def on_progress(task_id: str, downloaded: int, total: int, speed: float) -> None:
        if task_id in display.tasks:
            display.update_task(task_id, downloaded, speed, FileTaskStatus.DOWNLOADING)

    def on_complete(task_id: str, path: str, error: str | None = None) -> None:
        display.complete_task(task_id, error is None, error)
        if output.use_progress_bar and args.verbose:
            task = display.tasks.get(task_id, {})
            filename = task.get("filename", "unknown")
            if error:
                print(f"\n{_('Failed')}: {filename}: {error}")
            else:
                print(f"\n{_('Completed')}: {filename} -> {path}")

    batch.set_progress_callback(on_progress)
    batch.set_file_complete_callback(on_complete)

    for line_num, url in urls:
        try:
            task_id = await batch.add_url(url, output_path)
            display.add_task(task_id, Path(url).name, url)
        except Exception as e:
            if not output.use_json:
                print(f"\n{_('Warning')}: {_('Failed to add URL (line')} {line_num}): {url}: {e}")

    try:
        await batch.start()
    except KeyboardInterrupt:
        if output.use_json:
            results = display.get_results()
            results["type"] = "batch"
            results["success"] = False
            results["cancelled"] = True
            output.print_json(results)
        elif output.use_progress_bar:
            print(f"\n{_('Batch download cancelled by user')}")
        return 4
    except Exception as e:
        if output.use_json:
            output.print_json({"type": "batch", "success": False, "error": str(e)})
        elif output.use_progress_bar:
            print(f"\n{_('Batch download error')}: {e}")
        return 1
    finally:
        display.finish()

    if output.use_json:
        results = display.get_results()
        results["type"] = "batch"
        results["success"] = results["failed"] == 0
        output.print_json(results)
    elif not output.use_progress_bar:
        print(f"Batch download: {display.completed} completed, {display.failed} failed")

    return 0 if display.failed == 0 else 1


def get_unique_path(path: Path) -> Path:
    if not path.exists():
        return path

    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    counter = 1

    while True:
        new_name = f"{stem} ({counter}){suffix}"
        new_path = parent / new_name
        if not new_path.exists():
            return new_path
        counter += 1


def print_file_info(info: dict, output: OutputMode) -> None:
    output.print(f"\n{_('File Info')}:")
    output.print(f"  {_('Filename')}: {info['filename']}")
    if info["size"] > 0:
        output.print(f"  {_('Size')}: {format_size(info['size'])}")
    else:
        output.print(f"  {_('Size')}: {_('Unknown')}")
    output.print(f"  {_('Content-Type')}: {info['content_type'] or _('Unknown')}")
    output.print(f"  {_('Resume Support')}: {_('Yes') if info['supports_resume'] else _('No')}")


async def analyze_and_recommend(url: str, config: DownloadConfig) -> dict:
    """Analyze URL and recommend download strategy"""
    info = await probe_url(url, config)

    selector = StrategySelector(
        default_style=DownloadStyle.HYBRID_TURBO,
        enable_single=True,
        enable_multi=True,
    )

    profile = selector.analyze_file(
        url=url,
        size=info["size"],
        supports_range=info["supports_range"],
        content_type=info.get("content_type", ""),
    )

    decision = selector.select_style(profile)

    return {
        "file_info": info,
        "style": decision.style,
        "recommended_chunks": decision.recommended_chunks,
        "estimated_speedup": decision.estimated_speedup,
        "reason": decision.reason,
    }


def print_strategy_recommendation(recommendation: dict, output: OutputMode) -> None:
    """Print strategy recommendation"""
    info = recommendation["file_info"]
    style = recommendation["style"]
    chunks = recommendation["recommended_chunks"]
    speedup = recommendation["estimated_speedup"]
    reason = recommendation["reason"]

    output.print(f"\n{_('Strategy Analysis')}:")
    output.print(f"  {_('File')}: {info['filename']}")
    if info["size"] > 0:
        output.print(f"  {_('Size')}: {format_size(info['size'])}")
    output.print(f"  {_('Recommended Style')}: {style.value.upper()}")
    output.print(f"  {_('Recommended Chunks')}: {chunks}")
    output.print(f"  {_('Estimated Speedup')}: {speedup:.1f}x")
    output.print(f"  {_('Reason')}: {reason}")

    if info["size"] > 0:
        if info["size"] < 5 * 1024 * 1024:
            size_category = "small (< 5MB)"
        elif info["size"] < 100 * 1024 * 1024:
            size_category = "medium (5MB - 100MB)"
        else:
            size_category = "large (> 100MB)"
        output.print(f"  {_('Size Category')}: {size_category}")

    output.print(f"  {_('Range Support')}: {_('Yes') if info['supports_range'] else _('No')}")


def build_config_from_args(args: argparse.Namespace) -> DownloadConfig:
    """Build DownloadConfig from parsed arguments."""
    config = DownloadConfig(
        resume=args.resume,
        max_chunks=args.max_chunks,
        timeout=args.timeout,
        verify_ssl=args.verify_ssl,
        temp_dir=args.temp_dir,
    )

    if args.proxy:
        from . import ProxyConfig, ProxyMode

        config.proxy = ProxyConfig(mode=ProxyMode.CUSTOM, http_proxy=args.proxy, https_proxy=args.proxy)

    if args.user_agent:
        config.user_agent = args.user_agent

    if args.speed_limit:
        from . import SpeedLimitConfig, SpeedLimitMode

        config.speed_limit = SpeedLimitConfig(enabled=True, mode=SpeedLimitMode.GLOBAL, max_speed=args.speed_limit)

    if args.retry:
        from . import RetryConfig

        config.retry = RetryConfig(max_retries=args.retry)

    return config


def main() -> int:
    args = parse_args()
    output = OutputMode(format_pref=args.output_format, quiet=args.quiet)

    if not args.urls and not args.batch_file:
        if output.use_json:
            output.print_json(
                {
                    "type": "error",
                    "success": False,
                    "error": "URL or batch file required",
                    "exit_code": 2,
                }
            )
        else:
            print(f"{_('Error')}: {_('URL or batch file required')}")
            print(f"{_('Usage')}: littledl <URL>")
            print(f"{_('   or')}: littledl <URL1> <URL2> <URL3> ...")
            print(f"{_('   or')}: littledl -F <batch_file>")
        return 2

    if args.batch_file or len(args.urls) > 1:
        return asyncio.run(run_batch_main(args, output))

    single_url = args.urls[0]

    config = build_config_from_args(args)
    style = style_to_enum(args.style)
    if args.style != "auto":
        config.apply_style(style)

    if args.info_only:
        if args.style != "auto":
            return asyncio.run(run_probe(single_url, config, output))
        else:
            return asyncio.run(run_analyze(single_url, config, output))

    output_path = Path(args.output or "./downloads").expanduser().resolve()

    final_filename = args.filename
    probe_info = None
    if output_path.is_dir() and not final_filename:
        probe_info = asyncio.run(probe_url(single_url, config))
        final_filename = probe_info["filename"]

    save_path = output_path / final_filename if output_path.is_dir() else output_path
    if not args.force:
        save_path = get_unique_path(save_path)

    if output.use_progress_bar and args.verbose and save_path.name != (final_filename or ""):
        print(f"{_('Auto-renamed to')}: {save_path.name}")

    return asyncio.run(run_download(single_url, config, save_path, output, args, style))


async def run_batch_main(args: argparse.Namespace, output: OutputMode) -> int:
    """Run batch download from file or direct URLs."""
    if args.batch_file:
        try:
            urls = read_urls_from_file(args.batch_file)
        except FileNotFoundError as e:
            if output.use_json:
                output.print_json({"type": "batch", "success": False, "error": str(e), "exit_code": 2})
            else:
                print(f"{_('Error')}: {e}")
            return 2

        if not urls:
            if output.use_json:
                output.print_json({"type": "batch", "success": True, "completed": 0, "failed": 0, "tasks": []})
            else:
                print(f"{_('No valid URLs found in file')}")
            return 0
    else:
        urls = [(i + 1, url) for i, url in enumerate(args.urls)]
        if not urls:
            if output.use_json:
                output.print_json({"type": "batch", "success": True, "completed": 0, "failed": 0, "tasks": []})
            else:
                print(f"{_('No URLs to download')}")
            return 0

    config = build_config_from_args(args)
    config.overwrite = args.force

    style = style_to_enum(args.style)
    if args.style != "auto":
        config.apply_style(style)

    output_path = Path(args.output or "./downloads").expanduser().resolve()
    output_path.mkdir(parents=True, exist_ok=True)

    return await run_batch_download(
        urls=urls,
        config=config,
        output_path=output_path,
        max_concurrent=args.max_concurrent,
        output=output,
        args=args,
    )


if __name__ == "__main__":
    sys.exit(main())
