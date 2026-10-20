from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from .config import ConfigError, load_config, topic_file_prefix
from .fetch import AccessPaused, RequestBudgetExceeded
from .llm import BudgetExceeded, LLMCallFailed, LLMUnavailable

# POST 请求体上限：按需精读只传 arxiv_id 与 topic，几百字节足够。
MAX_BODY_BYTES = 64 * 1024

# 进程内按 arxiv_id 去重锁：并发请求同一篇论文时只发一次 LLM 调用，
# 其余请求拿到锁后命中缓存结果，避免重复拉全文与重复消耗 token 预算。
# 每篇被点击的论文仅占一个锁对象（几百字节），服务存续期内不回收：量级可忽略，
# 且回收需引用计数防与等待者竞争，刻意不做。
_DEEP_LOCKS: Dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _deep_lock(arxiv_id: str) -> threading.Lock:
    with _LOCKS_GUARD:
        return _DEEP_LOCKS.setdefault(arxiv_id, threading.Lock())


def deep_read_paper(project: Path, topic: Optional[str], arxiv_id: str) -> Tuple[int, Dict[str, Any]]:
    """对指定论文执行一次按需精读：全文（有缓存用缓存）→ LLM 生成 → 入库。

    与流水线第 5 步共用同一套代码路径，请求预算、周 token 预算、
    熔断与白名单保护全部生效；已有精读的论文直接返回缓存结果。
    返回 (http_status, payload)，status 200 时 payload 含 detail。
    """
    from .cli import build  # 局部导入避免 cli ↔ server 循环依赖

    arxiv_id = str(arxiv_id or "").strip()
    if not arxiv_id:
        return 400, {"error": "缺少 arxiv_id"}
    try:
        config, _paths, db, pipeline = build(project, topic)
    except ConfigError as exc:
        return 400, {"error": "配置错误：{}".format(exc)}
    try:
        paper = db.paper(arxiv_id)
        if paper is None:
            return 404, {"error": "论文不存在：{}".format(arxiv_id)}
        existing = paper.get("detail")
        if existing:
            return 200, {"arxiv_id": arxiv_id, "detail": existing, "cached": True}
        # 并发点击同一篇去重：等待锁期间其他请求可能已完成精读并入库，
        # 拿到锁后二次检查缓存，避免重复拉全文与重复花费 token。
        with _deep_lock(arxiv_id):
            paper = db.paper(arxiv_id)
            existing = paper.get("detail")
            if existing:
                return 200, {"arxiv_id": arxiv_id, "detail": existing, "cached": True}
            full_text, source = pipeline.ensure_full_text(paper)
            detail = pipeline.llm.deep_read(paper, full_text, source)
            db.set_detail(arxiv_id, detail)
            return 200, {"arxiv_id": arxiv_id, "detail": detail, "cached": False}
    except BudgetExceeded as exc:
        return 402, {"error": str(exc)}
    except LLMUnavailable as exc:
        return 503, {"error": str(exc)}
    except LLMCallFailed as exc:
        return 502, {"error": str(exc)}
    except AccessPaused as exc:
        return 403, {"error": "站点访问已暂停：{}".format(exc)}
    except RequestBudgetExceeded as exc:
        return 429, {"error": str(exc)}
    except Exception as exc:
        return 500, {"error": "{}: {}".format(type(exc).__name__, str(exc)[:400])}
    finally:
        db.close()


def latest_report_path(project: Path, topic: Optional[str]) -> Optional[Path]:
    """返回该入口最新一份周报路径（按修改时间）。"""
    out_dir = Path(project) / "out"
    if not out_dir.is_dir():
        return None
    prefix = topic_file_prefix(topic)
    candidates = sorted(
        out_dir.glob("{}-前沿论文解读-*.html".format(prefix)),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def resolve_report_file(project: Path, name: str) -> Optional[Path]:
    """把 URL 文件名解析到 out/ 目录内，拒绝路径穿越与非 HTML 文件。"""
    name = str(name or "").strip().strip("/")
    if not name:
        return None
    out_dir = (Path(project) / "out").resolve()
    candidate = (out_dir / name).resolve()
    if candidate.parent != out_dir or not candidate.is_file():
        return None
    if candidate.suffix.lower() not in (".html", ".htm"):
        return None
    return candidate


class _Handler(BaseHTTPRequestHandler):
    """本地服务处理器：仅服务 out/ 下的 HTML 周报与 /api/deep-read 接口。"""

    project: Path = Path(".")
    topic: Optional[str] = None  # 服务默认入口（首页未带 ?topic= 时使用）
    server_version = "kg-weekly-serve/0.1"

    def _json(self, status: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(path.stat().st_size))
        self.end_headers()
        with path.open("rb") as handle:
            self.wfile.write(handle.read())

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/index.html"):
            topic = (parse_qs(parsed.query).get("topic") or [None])[0] or self.topic
            report = latest_report_path(self.project, topic)
            if report is None:
                self._json(404, {"error": "还没有生成周报：请先运行 run.bat run"})
                return
            self._send_file(report)
            return
        if parsed.path == "/api/health":
            self._json(200, {"ok": True})
            return
        target = resolve_report_file(self.project, parsed.path)
        if target is None:
            self._json(404, {"error": "文件不存在"})
            return
        self._send_file(target)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/deep-read":
            self._json(404, {"error": "接口不存在"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._json(400, {"error": "Content-Length 非法"})
            return
        if length < 0:
            self._json(400, {"error": "Content-Length 非法"})
            return
        if length > MAX_BODY_BYTES:
            self._json(413, {"error": "请求体过大"})
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._json(400, {"error": "请求体不是合法 JSON"})
            return
        if not isinstance(payload, dict):
            self._json(400, {"error": "请求体必须是 JSON 对象"})
            return
        status, body = deep_read_paper(self.project, payload.get("topic"), payload.get("arxiv_id", ""))
        self._json(status, body)


def make_server(project: Path, port: int = 8000, topic: Optional[str] = None) -> ThreadingHTTPServer:
    """构造绑定 127.0.0.1 的服务（port=0 时由系统分配，测试用）。"""
    handler = type("_BoundHandler", (_Handler,), {
        "project": Path(project).resolve(), "topic": topic})
    return ThreadingHTTPServer(("127.0.0.1", int(port)), handler)


def run_server(project: Path, port: int = 8000, topic: Optional[str] = None) -> None:
    """启动本地周报浏览与按需精读服务，阻塞直到 Ctrl+C。

    topic 为服务默认入口（首页不带 ?topic= 参数时生效），None 表示默认 kg。
    """
    project = Path(project).resolve()
    load_config(project)  # 启动前先校验配置，尽早暴露错误
    httpd = make_server(project, port, topic)
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # Windows 控制台默认 GBK
    except (AttributeError, OSError):
        pass
    host, bound_port = httpd.server_address[:2]
    print("KG 周报服务已启动：http://{}:{}".format(host, bound_port))
    print("按 Ctrl+C 停止。API Key 只保存在本机，不会写入任何 HTML 文件。")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
