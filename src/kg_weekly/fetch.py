from __future__ import annotations

import contextlib
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from .db import Database

if os.name == "nt":  # Windows
    import msvcrt

    def _acquire(handle: Any) -> None:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)

    def _release(handle: Any) -> None:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
else:  # POSIX
    import fcntl

    def _acquire(handle: Any) -> None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)

    def _release(handle: Any) -> None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextlib.contextmanager
def file_lock(path: Path):
    """跨进程文件锁：Windows 用 msvcrt.locking，POSIX 用 fcntl.flock。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write("\n")
            handle.flush()
        _acquire(handle)
        try:
            yield
        finally:
            _release(handle)


class AccessPaused(RuntimeError):
    pass


class RequestBudgetExceeded(RuntimeError):
    pass


class FetchFailed(RuntimeError):
    pass


# 单个响应体上限：防止异常上游返回超大响应耗尽内存。
MAX_BODY_BYTES = 20 * 1024 * 1024


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """不跟随重定向：域名白名单只校验初始 URL，跟随重定向会绕过校验。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _default_opener():
    """与 urlopen 同签名（request, timeout）的可调用 opener，内部不跟随重定向。"""
    director = urllib.request.build_opener(_NoRedirectHandler())

    def open_url(request, timeout=None):
        return director.open(request, timeout=timeout)

    return open_url


# purpose -> 期望的内容类型（异常类型会触发熔断或报错）
_XML_PURPOSES = ("arxiv_query", "daily_feed")
_JSON_PURPOSES = ("openalex_batch",)
_HTML_PURPOSES = ("paper_html",)


class SafeFetcher:
    """白名单、周预算、间隔、跨进程锁、审计与熔断。"""

    def __init__(self, db: Database, config: Dict[str, Any], lock_path: Path,
                 opener: Optional[Any] = None, sleeper: Any = time.sleep):
        self.db = db
        self.config = config
        self.lock_path = lock_path
        self.opener = opener or _default_opener()
        self.sleeper = sleeper

    def fetch(self, url: str, *, mode: str, purpose: str, accept: str,
              optional_404: bool = False) -> Optional[bytes]:
        if mode not in ("automatic", "user"):
            raise ValueError("mode 必须是 automatic 或 user")
        parsed = urlparse(url)
        safety = self.config["safety"]
        if parsed.scheme != "https" or parsed.hostname not in set(safety["allowed_hosts"]):
            raise ValueError("拒绝访问未授权地址：{}".format(url))
        with file_lock(self.lock_path):
            if not self.db.access_enabled():
                raise AccessPaused(self.db.get_setting("site_access_pause_reason", "站点访问已暂停"))
            budget_key = "automatic_requests_per_week" if mode == "automatic" else "user_requests_per_week"
            if self.db.request_count_this_week(mode) >= int(safety[budget_key]):
                raise RequestBudgetExceeded("{} 本周请求预算已用完".format(mode))
            interval = int(safety["minimum_request_interval_seconds"])
            wait = self.db.last_request_time() + interval - int(time.time())
            if wait > 0:
                self.sleeper(wait)
            request_id = self.db.start_request(mode, purpose, parsed.hostname or "")
            request = urllib.request.Request(url, headers={
                "User-Agent": "kg-weekly/0.1 (personal research reader)",
                "Accept": accept,
            })
            try:
                with self.opener(request, timeout=45) as response:
                    status = int(getattr(response, "status", 200))
                    content_type = response.headers.get("Content-Type", "").lower()
                    # 只读上限+1 字节：超过上限立刻中断，内存占用不会超过 20 MB。
                    body = response.read(MAX_BODY_BYTES + 1)
                    if len(body or b"") > MAX_BODY_BYTES:
                        message = "响应体过大（{:,} 字节），已拒绝".format(len(body))
                        self.db.finish_request(request_id, "failed", status, message)
                        raise FetchFailed(message)
                    if purpose in _XML_PURPOSES and not (
                        "xml" in content_type or body.lstrip().startswith(b"<?xml")
                    ):
                        reason = "arXiv 返回了异常内容类型：{}".format(content_type or "unknown")
                        self.db.finish_request(request_id, "blocked", status, reason)
                        self.db.disable_access(reason)
                        raise AccessPaused(reason)
                    if purpose in _JSON_PURPOSES and "json" not in content_type:
                        reason = "OpenAlex 返回了异常内容类型：{}".format(content_type or "unknown")
                        self.db.finish_request(request_id, "blocked", status, reason)
                        self.db.disable_access(reason)
                        raise AccessPaused(reason)
                    if purpose in _HTML_PURPOSES and "html" not in content_type:
                        raise FetchFailed("论文 HTML 返回了异常内容类型：{}".format(content_type or "unknown"))
                    self.db.finish_request(request_id, "success", status)
                    return body
            except urllib.error.HTTPError as exc:
                status = int(exc.code)
                if status == 304:
                    self.db.finish_request(request_id, "not_modified", status)
                    return None
                if status == 404 and optional_404:
                    self.db.finish_request(request_id, "not_found", status)
                    return None
                if status in (301, 302, 303, 307, 308):
                    message = "拒绝跟随重定向（HTTP {}）：{}".format(status, purpose)
                    self.db.finish_request(request_id, "failed", status, message)
                    raise FetchFailed(message)
                message = "HTTP {}: {}".format(status, purpose)
                if status in set(int(x) for x in safety.get("stop_status_codes", [])):
                    self.db.finish_request(request_id, "blocked", status, message)
                    self.db.disable_access(message)
                    raise AccessPaused(message)
                self.db.finish_request(request_id, "failed", status, message)
                raise FetchFailed(message)
            except AccessPaused:
                raise
            except Exception as exc:
                message = "{}: {}".format(type(exc).__name__, str(exc))
                self.db.finish_request(request_id, "failed", None, message)
                raise FetchFailed(message)
