from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .config import (ConfigError, apply_categories, apply_topic, load_config,
                      project_paths, topic_db_name)
from .db import Database
from .fetch import SafeFetcher
from .llm import LLMClient
from .pipeline import WeeklyPipeline
from .server import run_server


def _open_database(project: Path, topic: Optional[str],
                  config: Dict[str, Any]) -> Tuple[Database, Dict[str, Path]]:
    """按入口打开独立数据库并初始化安全设置；build() 与 dry-run 共用。"""
    paths = project_paths(project)
    # 每个入口独立数据库：默认 kg 用 papers.db，自定义关键词用 papers-<slug>.db
    paths["database"] = paths["data"] / topic_db_name(topic)
    db = Database(paths["database"])
    db.initialize_safety(bool(config["safety"].get("site_access_enabled", True)))
    # 每次启动把 config 里的周预算同步到 settings，供 status 展示与审计。
    db.set_setting("weekly_token_budget", config["llm"]["weekly_token_budget"])
    return db, paths


def _restore_categories(db: Database, config: Dict[str, Any]) -> None:
    """恢复该入口上次 --categories 保存的分类覆盖（存在时覆盖配置默认值）。"""
    saved = db.get_setting("topic_categories")
    if saved:
        config["discovery"]["categories"] = [c for c in saved.split(",") if c]


def _apply_cli_categories(project: Path, db: Database, config: Dict[str, Any],
                          raw: Optional[str]) -> None:
    """应用 --categories：default 恢复 config.json 默认，其余校验后覆盖并持久化。"""
    raw = str(raw or "").strip()
    if not raw:
        return
    if raw.lower() == "default":
        config["discovery"]["categories"] = load_config(project)["discovery"]["categories"]
        db.set_setting("topic_categories", "")
    else:
        items = apply_categories(config, raw)
        db.set_setting("topic_categories", ",".join(items))


def build(project: Path, topic: Optional[str] = None) -> Tuple[Dict[str, Any], Dict[str, Path], Database, WeeklyPipeline]:
    config = apply_topic(load_config(project), topic)
    db, paths = _open_database(project, topic, config)
    _restore_categories(db, config)
    fetcher = SafeFetcher(db, config, paths["data"] / "network.lock")
    llm = LLMClient(db, config)
    pipeline = WeeklyPipeline(project, db, config, fetcher, llm)
    return config, paths, db, pipeline


def output(value: Any) -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # Windows 控制台默认 GBK，避免中文 JSON 乱码
    except (AttributeError, OSError):
        pass
    print(json.dumps(value, ensure_ascii=False, indent=2), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="KG前沿论文解读：arXiv 知识图谱方向论文周报生成器")
    parser.add_argument("--project", type=Path, default=Path.cwd(),
                        help="项目根目录（默认当前目录）")
    topic_help = "入口关键词：默认 kg（知识图谱入口）；输入其他关键词则按它爬取、解读并出独立周报"
    commands = parser.add_subparsers(dest="command", required=True)
    run_cmd = commands.add_parser("run", help="运行完整周流水线（抓取→增强→评分→卡片→精读→周报）")
    run_cmd.add_argument("--force", action="store_true", help="忽略本周已抓取标记，强制重新抓取 arXiv")
    run_cmd.add_argument("--dry-run", action="store_true", help="仅校验配置并输出状态，不访问网络/LLM")
    run_cmd.add_argument("--topic", type=str, default=None, help=topic_help)
    run_cmd.add_argument(
        "--categories", type=str, default=None,
        help="覆盖 arXiv 分类（逗号分隔，如 cs.AI,q-bio.BM）；default 恢复配置默认值。非默认值会持久化到该入口",
    )
    report_cmd = commands.add_parser("report", help="仅用已有数据重新生成 HTML 周报（不访问网络）")
    report_cmd.add_argument("--topic", type=str, default=None, help=topic_help)
    status_cmd = commands.add_parser("status", help="查看论文数、预算用量与访问状态")
    status_cmd.add_argument("--topic", type=str, default=None, help=topic_help)
    reset_cmd = commands.add_parser("reset-budget", help="手动重置周 token 预算计数（从当前时刻重新累计）")
    reset_cmd.add_argument("--topic", type=str, default=None, help=topic_help)
    enable = commands.add_parser("enable-access", help="人工确认熔断原因后重新开启网络访问")
    enable.add_argument("--confirm", action="store_true", help="确认已检查熔断原因")
    enable.add_argument("--topic", type=str, default=None, help=topic_help)
    prune_cmd = commands.add_parser("prune", help="清理过期的审计/用量/同步记录（默认保留 90 天）")
    prune_cmd.add_argument("--days", type=int, default=90, help="保留天数（默认 90，最小 1）")
    prune_cmd.add_argument("--topic", type=str, default=None, help=topic_help)
    serve_cmd = commands.add_parser("serve", help="启动本地周报浏览与按需精读服务（仅监听 127.0.0.1）")
    serve_cmd.add_argument("--port", type=int, default=8000, help="监听端口（默认 8000）")
    serve_cmd.add_argument("--topic", type=str, default=None, help=topic_help)
    args = parser.parse_args()

    project = args.project.expanduser().resolve()
    try:
        if args.command == "run" and args.dry_run:
            config = apply_topic(load_config(project), args.topic)  # 校验配置本身
            db, paths = _open_database(project, args.topic, config)
            _restore_categories(db, config)
            _apply_cli_categories(project, db, config, getattr(args, "categories", None))
            output({"status": "config_ok",
                    "topic": config["_topic"],
                    "site": config["site"],
                    "discovery": {
                        "categories": config["discovery"]["categories"],
                        "search_phrases_count": len(config["discovery"]["search_phrases"]),
                    },
                    "llm": {key: config["llm"][key] for key in
                            ("provider", "base_url", "model", "weekly_token_budget")},
                    **db.status()})
            db.close()
            return
        if args.command == "serve":
            # 服务按请求惰性打开对应入口数据库，不在这里 build。
            run_server(project, args.port, args.topic)
            return
        config, paths, db, pipeline = build(project, args.topic)
        try:
            if args.command == "run":
                _apply_cli_categories(project, db, config, getattr(args, "categories", None))
                output(pipeline.run(force=args.force))
            elif args.command == "report":
                output(pipeline.build_report())
            elif args.command == "status":
                output({**db.status(), "database": str(paths["database"]),
                        "out_dir": str(paths["out"])})
            elif args.command == "reset-budget":
                output({"ok": True, "budget_week_start": db.reset_budget_week(),
                        "llm_tokens_this_week": db.llm_usage_this_week()})
            elif args.command == "enable-access":
                if not args.confirm:
                    parser.error("必须检查熔断原因后显式添加 --confirm")
                db.enable_access()
                output({"ok": True, "access_enabled": db.access_enabled()})
            elif args.command == "prune":
                days = max(1, int(args.days))
                output({"ok": True, "retention_days": days,
                        "pruned": db.prune_audit(days)})
        finally:
            db.close()
    except ConfigError as exc:
        output({"error": "配置错误：{}".format(exc)})
        sys.exit(1)
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:
        output({"error": "{}: {}".format(type(exc).__name__, exc)})
        sys.exit(1)


if __name__ == "__main__":
    main()
