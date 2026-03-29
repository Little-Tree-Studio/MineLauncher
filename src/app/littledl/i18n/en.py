"""English translations for littledl."""

LOG_MESSAGES = {
    "download_start": "Starting download: {url}",
    "download_complete": "Download complete: {path}",
    "download_failed": "Download failed: {url}",
    "download_cancelled": "Download cancelled",
    "file_exists": "File already exists: {path}",
    "chunk_complete": "Chunk {index} completed",
    "chunk_failed": "Chunk {index} failed: {error}",
    "retry_attempt": "Retry attempt {attempt}/{max_retries}",
    "connection_error": "Connection error: {error}",
    "timeout_error": "Request timed out",
    "server_error": "Server error: {status_code}",
    "auth_required": "Authentication required",
    "proxy_error": "Proxy error: {error}",
    "speed_limited": "Speed limit: {speed}/s",
    "resuming": "Resuming download from {offset} bytes",
    "verifying_ssl": "Verifying SSL certificate",
    "ssl_error": "SSL verification failed: {error}",
    "file_created": "File created: {path}",
    "hash_verified": "Hash verified: {algorithm}={hash}",
    "hash_failed": "Hash verification failed: expected {expected}, got {actual}",
}

ERROR_MESSAGES = {
    "invalid_url": "Invalid URL: {url}",
    "resource_not_found": "Resource not found: {url}",
    "access_forbidden": "Access forbidden: {url}",
    "network_error": "Network error: {error}",
    "connection_refused": "Connection refused",
    "connection_timeout": "Connection timed out",
    "read_timeout": "Read timed out",
    "write_timeout": "Write timed out",
    "range_not_supported": "Server does not support range requests",
    "chunk_error": "Error downloading chunk {index}: {error}",
    "merge_error": "Error merging chunks: {error}",
    "file_error": "File error: {error}",
    "disk_full": "Disk full",
    "permission_denied": "Permission denied: {path}",
    "path_too_long": "Path too long: {path}",
    "resume_error": "Resume error: {error}",
    "config_error": "Configuration error: {error}",
    "auth_error": "Authentication error: {error}",
    "proxy_auth_error": "Proxy authentication error",
    "ssl_error": "SSL error: {error}",
    "too_many_redirects": "Too many redirects",
    "unsupported_scheme": "Unsupported URL scheme: {scheme}",
    "download_incomplete": "Download incomplete",
    "checksum_mismatch": "Checksum mismatch",
    "max_retries_exceeded": "Maximum retries exceeded",
    "cancelled": "Download was cancelled",
}

PROGRESS_MESSAGES = {
    "downloading": "Downloading: {filename}",
    "progress": "Progress: {percent:.1f}%",
    "speed": "Speed: {speed}/s",
    "eta": "ETA: {time}",
    "total": "Total: {downloaded}/{total}",
}

HELP_TEXT = {
    "usage": "Usage: littledl [OPTIONS] URL [SAVE_PATH]",
    "options": "Options:",
    "help_option": "  -h, --help     Show this help message",
    "version_option": "  -v, --version  Show version",
    "config_option": "  -c, --config   Configuration file",
    "output_option": "  -o, --output   Output file",
    "resume_option": "  -r, --resume   Resume download",
    "chunk_option": "  -n, --chunks   Number of chunks",
    "speed_limit_option": "  -s, --speed-limit   Speed limit",
    "proxy_option": "  -p, --proxy    Proxy URL",
    "auth_option": "  -a, --auth     Authentication",
    "examples": "Examples:",
    "example_basic": "  littledl https://example.com/file.zip",
    "example_resume": "  littledl -r https://example.com/file.zip",
    "example_chunks": "  littledl -n 8 https://example.com/file.zip",
}

SECURITY_MESSAGES = {
    "ssrf_warning": "Warning: URL may be attempting SSRF attack",
    "internal_ip_warning": "Warning: URL points to internal IP address",
    "untrusted_cert": "Warning: Using untrusted SSL certificate",
    "auth_stored": "Authentication credentials stored",
    "proxy_auth_required": "Proxy authentication required",
}

SETTINGS_MESSAGES = {
    "config_loaded": "Configuration loaded from {path}",
    "config_saved": "Configuration saved to {path}",
    "invalid_config": "Invalid configuration: {error}",
    "default_config": "Using default configuration",
}

STATUS_MESSAGES = {
    "active": "Active",
    "paused": "Paused",
    "completed": "Completed",
    "failed": "Failed",
    "cancelled": "Cancelled",
    "pending": "Pending",
}

STATUS_CODES = {
    200: "OK",
    206: "Partial Content",
    301: "Moved Permanently",
    302: "Found",
    303: "See Other",
    304: "Not Modified",
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    405: "Method Not Allowed",
    408: "Request Timeout",
    429: "Too Many Requests",
    500: "Internal Server Error",
    502: "Bad Gateway",
    503: "Service Unavailable",
    504: "Gateway Timeout",
}
