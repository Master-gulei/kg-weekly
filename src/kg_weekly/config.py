from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional


class ConfigError(ValueError):
    pass


def _config_int(data: Dict[str, Any], key: str, default: int, label: str) -> int:
    try:
        return int(data.get(key, default))
    except (TypeError, ValueError):
        raise ConfigError("{} 必须是整数（当前值：{!r}）".format(label, data.get(key)))


def load_config(project: Path) -> Dict[str, Any]:
    path = project / "config.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    # 本机私有配置（local_config.json，已被 gitignore 忽略）：浅合并覆盖，
    # 用于存放 API Key 等敏感值，避免进入版本库或出现在命令行历史里。
    local_path = project / "local_config.json"
    if local_path.exists():
        local = json.loads(local_path.read_text(encoding="utf-8"))
        if not isinstance(local, dict):
            raise ConfigError("local_config.json 必须是 JSON 对象（不能是数组或标量）")
        for key, value in (local or {}).items():
            if isinstance(value, dict) and isinstance(data.get(key), dict):
                data[key] = {**data[key], **value}
            else:
                data[key] = value
    safety = data.get("safety") or {}
    interval = _config_int(safety, "minimum_request_interval_seconds", 0,
                           "safety.minimum_request_interval_seconds")
    if interval < 3:
        raise ConfigError("minimum_request_interval_seconds 不能低于 arXiv 要求的 3 秒")
    if _config_int(safety, "automatic_requests_per_week", 0,
                   "safety.automatic_requests_per_week") < 1:
        raise ConfigError("automatic_requests_per_week 必须至少为 1")
    if _config_int(safety, "user_requests_per_week", 0,
                   "safety.user_requests_per_week") < 1:
        raise ConfigError("user_requests_per_week 必须至少为 1")
    if not safety.get("allowed_hosts"):
        raise ConfigError("必须配置至少一个允许访问的域名")
    discovery = data.get("discovery") or {}
    if not discovery.get("categories"):
        raise ConfigError("至少配置一个 arXiv 分类")
    if not discovery.get("search_phrases"):
        raise ConfigError("至少配置一个搜索短语")
    window = _config_int(data.get("site") or {}, "week_window_days", 7,
                         "site.week_window_days")
    if not 1 <= window <= 31:
        raise ConfigError("week_window_days 必须在 1 到 31 之间")
    keywords = data.get("keywords") or {}
    if not keywords.get("core"):
        raise ConfigError("至少配置一个核心关键词")
    reliability = data.get("reliability") or {}
    if not reliability.get("institution_whitelist"):
        raise ConfigError("至少配置一个可信机构")
    tiers = reliability.get("citation_tiers", [])
    for tier in tiers:
        if len(tier) != 2 or not all(isinstance(x, (int, float)) for x in tier):
            raise ConfigError("citation_tiers 必须是 [阈值, 分数] 列表")
    if tiers:
        thresholds = [tier[0] for tier in tiers]
        if thresholds != sorted(thresholds):
            raise ConfigError("citation_tiers 的阈值必须从小到大排列")
    llm = data.get("llm") or {}
    base_url = str(llm.get("base_url", ""))
    if base_url and not base_url.startswith("https://"):
        raise ConfigError("llm.base_url 必须是 https 地址")
    if _config_int(llm, "weekly_token_budget", 0, "llm.weekly_token_budget") <= 0:
        raise ConfigError("weekly_token_budget 必须大于 0")
    pipeline = data.get("pipeline") or {}
    if _config_int(pipeline, "top_cards", 0, "pipeline.top_cards") < 1:
        raise ConfigError("pipeline.top_cards 必须至少为 1")
    if _config_int(pipeline, "top_deep", 0, "pipeline.top_deep") < 1:
        raise ConfigError("pipeline.top_deep 必须至少为 1")
    # 每篇精读需要拉取一次 HTML 全文（计入 user 模式请求预算），精读数量不能超过该预算。
    if _config_int(pipeline, "top_deep", 0, "pipeline.top_deep") > \
            _config_int(safety, "user_requests_per_week", 0, "safety.user_requests_per_week"):
        raise ConfigError(
            "pipeline.top_deep 不能超过 safety.user_requests_per_week（精读需要拉取 HTML 全文）")
    return data


def project_paths(project: Path) -> Dict[str, Path]:
    project = project.resolve()
    paths = {
        "project": project,
        "data": project / "data",
        "cache": project / "data" / "cache",
        "database": project / "data" / "papers.db",
        "out": project / "out",
    }
    for key in ("data", "cache", "out"):
        paths[key].mkdir(parents=True, exist_ok=True)
    return paths


def apply_topic(config: Dict[str, Any], topic: Optional[str]) -> Dict[str, Any]:
    """入口（主题）切换：默认 kg 保持现状；输入其他关键词则用它爬取、评分与解读。

    注意：会原地修改并返回传入的 config；不要对复用同一个 dict 重复调用。
    """
    topic = str(topic or "").strip() or "kg"
    if len(topic) > 60:
        raise ConfigError("--topic 长度不能超过 60 个字符")
    if re.search(r"[\x00-\x1f]", topic):
        raise ConfigError("--topic 不能包含控制字符")
    if re.search(r'["\\(\\)\\]', topic):
        raise ConfigError("--topic 不能包含引号、括号或反斜杠（会破坏 arXiv 查询）")
    config["_topic"] = topic
    if topic.lower() == "kg":
        return config
    config["discovery"]["search_phrases"] = [topic]
    config["keywords"]["core"] = [topic]
    display = topic.upper() if topic.isascii() else topic
    config["site"]["name"] = "{} 前沿论文解读".format(display)
    return config


# arXiv 分类：主分类（如 cs / math-ph / q-bio）后可选子分类；
# 子分类一般为两位大写，physics.acc-ph 是唯一的 3 位小写例外。
_CATEGORY_RE = re.compile(r"^[a-z-]+(\.[A-Z]{2}|\.acc-ph)?$")


def apply_categories(config: Dict[str, Any], categories: str) -> List[str]:
    """解析 --categories 参数并覆盖 discovery.categories（逗号分隔）。

    分类必须形如 cs.AI / math-ph / q-bio.BM，非法格式抛 ConfigError。
    """
    items = [c.strip() for c in str(categories).split(",") if c.strip()]
    if not items:
        raise ConfigError("--categories 至少需要一个分类（如 cs.AI,cs.LG）")
    for item in items:
        if not _CATEGORY_RE.fullmatch(item):
            raise ConfigError(
                "非法 arXiv 分类：{!r}（形如 cs.AI / math-ph / q-bio.BM）".format(item))
    config["discovery"]["categories"] = items
    return items


def _topic_slug(topic: Optional[str]) -> str:
    topic = str(topic or "").strip() or "kg"
    # 空格与连字符统一归一为连字符；其余字符（如 +、.、冒号）会被丢弃。
    base = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", topic.lower()).strip("-") or "custom"
    # 若关键词含有被丢弃的字符，追加短哈希，防止不同关键词（如 c++ 与 c）撞到同一库名。
    if re.search(r"[^a-z0-9\u4e00-\u9fff\s-]", topic.lower()):
        base += "-" + hashlib.md5(topic.lower().encode("utf-8")).hexdigest()[:8]
    return base


def topic_db_name(topic: Optional[str]) -> str:
    """每个入口使用独立数据库，互不干扰（默认入口仍是 papers.db）。"""
    if str(topic or "").strip().lower() in ("", "kg"):
        return "papers.db"
    return "papers-{}.db".format(_topic_slug(topic))


def topic_file_prefix(topic: Optional[str]) -> str:
    """周报文件名前缀：默认 KG；自定义入口用关键词（ASCII 转大写）。"""
    if str(topic or "").strip().lower() in ("", "kg"):
        return "KG"
    slug = _topic_slug(topic)
    return slug.upper() if slug.isascii() else slug
