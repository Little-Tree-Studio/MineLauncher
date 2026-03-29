"""中文翻译 for littledl."""

LOG_MESSAGES = {
    "download_start": "开始下载: {url}",
    "download_complete": "下载完成: {path}",
    "download_failed": "下载失败: {url}",
    "download_cancelled": "下载已取消",
    "file_exists": "文件已存在: {path}",
    "chunk_complete": "分块 {index} 已完成",
    "chunk_failed": "分块 {index} 失败: {error}",
    "retry_attempt": "重试第 {attempt}/{max_retries} 次",
    "connection_error": "连接错误: {error}",
    "timeout_error": "请求超时",
    "server_error": "服务器错误: {status_code}",
    "auth_required": "需要身份验证",
    "proxy_error": "代理错误: {error}",
    "speed_limited": "限速: {speed}/秒",
    "resuming": "从 {offset} 字节处继续下载",
    "verifying_ssl": "验证 SSL 证书",
    "ssl_error": "SSL 验证失败: {error}",
    "file_created": "文件已创建: {path}",
    "hash_verified": "哈希验证通过: {algorithm}={hash}",
    "hash_failed": "哈希验证失败: 预期 {expected}, 实际 {actual}",
}

ERROR_MESSAGES = {
    "invalid_url": "无效的 URL: {url}",
    "resource_not_found": "资源不存在: {url}",
    "access_forbidden": "访问被拒绝: {url}",
    "network_error": "网络错误: {error}",
    "connection_refused": "连接被拒绝",
    "connection_timeout": "连接超时",
    "read_timeout": "读取超时",
    "write_timeout": "写入超时",
    "range_not_supported": "服务器不支持断点续传",
    "chunk_error": "分块 {index} 下载错误: {error}",
    "merge_error": "分块合并错误: {error}",
    "file_error": "文件错误: {error}",
    "disk_full": "磁盘已满",
    "permission_denied": "权限被拒绝: {path}",
    "path_too_long": "路径过长: {path}",
    "resume_error": "断点续传错误: {error}",
    "config_error": "配置错误: {error}",
    "auth_error": "认证错误: {error}",
    "proxy_auth_error": "代理认证错误",
    "ssl_error": "SSL 错误: {error}",
    "too_many_redirects": "重定向次数过多",
    "unsupported_scheme": "不支持的 URL 协议: {scheme}",
    "download_incomplete": "下载不完整",
    "checksum_mismatch": "校验和不匹配",
    "max_retries_exceeded": "超过最大重试次数",
    "cancelled": "下载已被取消",
}

PROGRESS_MESSAGES = {
    "downloading": "正在下载: {filename}",
    "progress": "进度: {percent:.1f}%",
    "speed": "速度: {speed}/秒",
    "eta": "预计剩余时间: {time}",
    "total": "总计: {downloaded}/{total}",
}

HELP_TEXT = {
    "usage": "用法: littledl [选项] URL [保存路径]",
    "options": "选项:",
    "help_option": "  -h, --help     显示此帮助信息",
    "version_option": "  -v, --version  显示版本信息",
    "config_option": "  -c, --config   配置文件",
    "output_option": "  -o, --output   输出文件",
    "resume_option": "  -r, --resume   继续下载",
    "chunk_option": "  -n, --chunks   分块数量",
    "speed_limit_option": "  -s, --speed-limit   速度限制",
    "proxy_option": "  -p, --proxy    代理 URL",
    "auth_option": "  -a, --auth     身份验证",
    "examples": "示例:",
    "example_basic": "  littledl https://example.com/file.zip",
    "example_resume": "  littledl -r https://example.com/file.zip",
    "example_chunks": "  littledl -n 8 https://example.com/file.zip",
}

SECURITY_MESSAGES = {
    "ssrf_warning": "警告: URL 可能正在尝试 SSRF 攻击",
    "internal_ip_warning": "警告: URL 指向内部 IP 地址",
    "untrusted_cert": "警告: 使用不受信任的 SSL 证书",
    "auth_stored": "认证凭据已存储",
    "proxy_auth_required": "需要代理认证",
}

SETTINGS_MESSAGES = {
    "config_loaded": "配置已从 {path} 加载",
    "config_saved": "配置已保存到 {path}",
    "invalid_config": "无效的配置: {error}",
    "default_config": "使用默认配置",
}

STATUS_MESSAGES = {
    "active": "活动中",
    "paused": "已暂停",
    "completed": "已完成",
    "failed": "失败",
    "cancelled": "已取消",
    "pending": "等待中",
}

STATUS_CODES = {
    200: "成功",
    206: "部分内容",
    301: "永久移动",
    302: "临时移动",
    303: "查看其他",
    304: "未修改",
    400: "错误请求",
    401: "未授权",
    403: "禁止访问",
    404: "未找到",
    405: "方法不允许",
    408: "请求超时",
    429: "请求过多",
    500: "服务器内部错误",
    502: "错误网关",
    503: "服务不可用",
    504: "网关超时",
}
