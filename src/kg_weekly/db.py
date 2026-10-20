from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS papers (
  arxiv_id TEXT PRIMARY KEY,
  version INTEGER NOT NULL DEFAULT 1,
  title TEXT NOT NULL,
  authors_json TEXT NOT NULL DEFAULT '[]',
  abstract TEXT NOT NULL DEFAULT '',
  comment TEXT NOT NULL DEFAULT '',
  published_at TEXT,
  updated_at TEXT,
  primary_category TEXT,
  categories_json TEXT NOT NULL DEFAULT '[]',
  abs_url TEXT NOT NULL,
  html_url TEXT,
  pdf_url TEXT,
  journal_ref TEXT,
  doi TEXT,
  citation_count INTEGER,
  venue TEXT,
  institutions_json TEXT,
  author_impact REAL,
  relevance_score REAL NOT NULL DEFAULT 0,
  relevance_reason TEXT NOT NULL DEFAULT '',
  reliability_score REAL NOT NULL DEFAULT 0,
  reliability_reason TEXT NOT NULL DEFAULT '',
  total_score REAL NOT NULL DEFAULT 0,
  card_json TEXT,
  detail_json TEXT,
  full_text TEXT,
  full_text_source TEXT,
  content_version INTEGER,
  discovered_at INTEGER NOT NULL,
  last_seen_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_papers_total ON papers(total_score DESC);
CREATE INDEX IF NOT EXISTS idx_papers_discovered ON papers(discovered_at DESC);

CREATE TABLE IF NOT EXISTS provider_accounts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  capability TEXT NOT NULL CHECK(capability IN ('ai')),
  provider TEXT NOT NULL,
  account_name TEXT NOT NULL,
  credential_json TEXT NOT NULL DEFAULT '{}',
  priority INTEGER NOT NULL DEFAULT 100,
  quota_total REAL,
  quota_used REAL NOT NULL DEFAULT 0,
  quota_reset_at INTEGER,
  quota_period_seconds INTEGER NOT NULL DEFAULT 2592000,
  enabled INTEGER NOT NULL DEFAULT 1,
  cooldown_until INTEGER,
  consecutive_failures INTEGER NOT NULL DEFAULT 0,
  last_used_at INTEGER,
  last_success_at INTEGER,
  last_error TEXT,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  UNIQUE(capability,provider,account_name)
);

CREATE TABLE IF NOT EXISTS provider_usage (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  account_id INTEGER REFERENCES provider_accounts(id) ON DELETE SET NULL,
  account_label TEXT NOT NULL DEFAULT '',
  task_type TEXT NOT NULL,
  units REAL NOT NULL DEFAULT 0,
  success INTEGER NOT NULL,
  error TEXT,
  created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_provider_usage_created ON provider_usage(created_at);

CREATE TABLE IF NOT EXISTS network_requests (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  requested_at INTEGER NOT NULL,
  finished_at INTEGER,
  mode TEXT NOT NULL,
  purpose TEXT NOT NULL,
  host TEXT NOT NULL,
  status_code INTEGER,
  outcome TEXT NOT NULL DEFAULT 'started',
  error TEXT
);
CREATE INDEX IF NOT EXISTS idx_network_requested ON network_requests(requested_at);

CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS sync_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at INTEGER NOT NULL,
  finished_at INTEGER,
  status TEXT NOT NULL DEFAULT 'running',
  fetched_count INTEGER NOT NULL DEFAULT 0,
  inserted_count INTEGER NOT NULL DEFAULT 0,
  updated_count INTEGER NOT NULL DEFAULT 0,
  error TEXT
);
"""


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(str(self.path), timeout=30, check_same_thread=False)
        self.con.row_factory = sqlite3.Row
        self.con.executescript(SCHEMA)
        self.con.execute("PRAGMA busy_timeout=30000")

    def close(self) -> None:
        self.con.close()

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    # ---------- settings ----------

    def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        row = self.con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: Any) -> None:
        now = int(time.time())
        self.con.execute(
            "INSERT INTO settings(key,value,updated_at) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",
            (key, str(value), now),
        )
        self.con.commit()

    # ---------- 站点访问熔断 ----------

    def initialize_safety(self, enabled: bool) -> None:
        if self.get_setting("site_access_enabled") is None:
            self.set_setting("site_access_enabled", "1" if enabled else "0")

    def disable_access(self, reason: str) -> None:
        self.set_setting("site_access_enabled", "0")
        self.set_setting("site_access_pause_reason", reason[:500])

    def enable_access(self) -> None:
        self.set_setting("site_access_enabled", "1")
        self.set_setting("site_access_pause_reason", "")

    def access_enabled(self) -> bool:
        return self.get_setting("site_access_enabled", "0") == "1"

    # ---------- 时间与预算 ----------

    def local_week_start(self, now: Optional[datetime] = None) -> int:
        value = now or datetime.now()
        monday = datetime(value.year, value.month, value.day) - timedelta(days=value.weekday())
        return int(time.mktime(monday.timetuple()))

    def budget_week_start(self) -> int:
        """本周预算起点：进入新的一周自动前滚，无需手动 reset-budget。"""
        current = self.local_week_start()
        raw = self.get_setting("budget_week_start")
        try:
            stored = int(raw) if raw else 0
        except ValueError:
            stored = 0
        if stored >= current:
            return stored
        self.set_setting("budget_week_start", current)
        return current

    def reset_budget_week(self) -> int:
        value = int(time.time())
        self.set_setting("budget_week_start", value)
        return value

    def llm_usage_this_week(self) -> int:
        row = self.con.execute(
            "SELECT COALESCE(SUM(units),0) n FROM provider_usage WHERE success=1 AND created_at>=?",
            (self.budget_week_start(),),
        ).fetchone()
        return int(row["n"])

    def request_count_this_week(self, mode: str) -> int:
        row = self.con.execute(
            "SELECT COUNT(*) n FROM network_requests WHERE mode=? AND requested_at>=?",
            (mode, self.local_week_start()),
        ).fetchone()
        return int(row["n"])

    def last_request_time(self) -> int:
        """本机所有入口数据库中最晚的网络请求时间。

        各入口（--topic）使用独立数据库，但 arXiv 礼貌间隔必须跨入口共享：
        连续跑两个入口时，只查当前库会得到很小的等待时间，违背间隔保证。
        """
        latest = 0
        for path in self.path.parent.glob("papers*.db"):
            try:
                con = sqlite3.connect(str(path), timeout=5)
                try:
                    row = con.execute(
                        "SELECT COALESCE(MAX(requested_at),0) t FROM network_requests"
                    ).fetchone()
                    if row and row[0] is not None and int(row[0]) > latest:
                        latest = int(row[0])
                finally:
                    con.close()
            except sqlite3.Error:
                continue  # 其他入口的库损坏/被占用不影响本入口
        return latest

    # ---------- 请求审计 ----------

    def start_request(self, mode: str, purpose: str, host: str) -> int:
        cur = self.con.execute(
            "INSERT INTO network_requests(requested_at,mode,purpose,host) VALUES(?,?,?,?)",
            (int(time.time()), mode, purpose, host),
        )
        self.con.commit()
        return int(cur.lastrowid)

    def finish_request(self, request_id: int, outcome: str, status_code: Optional[int] = None,
                       error: str = "") -> None:
        self.con.execute(
            "UPDATE network_requests SET finished_at=?,outcome=?,status_code=?,error=? WHERE id=?",
            (int(time.time()), outcome, status_code, error[:500], request_id),
        )
        self.con.commit()

    # ---------- 同步记录 ----------

    def begin_sync(self) -> int:
        cur = self.con.execute("INSERT INTO sync_runs(started_at) VALUES(?)", (int(time.time()),))
        self.con.commit()
        return int(cur.lastrowid)

    def finish_sync(self, run_id: int, status: str, fetched: int = 0, inserted: int = 0,
                    updated: int = 0, error: str = "") -> None:
        self.con.execute(
            "UPDATE sync_runs SET finished_at=?,status=?,fetched_count=?,inserted_count=?,updated_count=?,error=? WHERE id=?",
            (int(time.time()), status, fetched, inserted, updated, error[:500], run_id),
        )
        self.con.commit()

    # ---------- 审计清理 ----------

    def prune_audit(self, retention_days: int = 90) -> Dict[str, int]:
        """清理超过保留期的审计记录（默认 90 天），防止审计表无限增长。

        只清理审计/用量/同步记录，论文数据不动。
        """
        days = max(1, int(retention_days))
        cutoff = int(time.time()) - days * 86400
        pruned: Dict[str, int] = {}
        for table, column in (("network_requests", "requested_at"),
                              ("provider_usage", "created_at"),
                              ("sync_runs", "started_at")):
            cur = self.con.execute(
                "DELETE FROM {} WHERE {}<?".format(table, column), (cutoff,))
            pruned[table] = cur.rowcount
        self.con.commit()
        return pruned

    def backup(self, target: Path) -> Path:
        """在线备份当前数据库到指定路径（SQLite backup API，写库时仍可安全调用）。"""
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        backup_con = sqlite3.connect(str(target))
        try:
            self.con.backup(backup_con)
        finally:
            # with 块只提交/回滚事务，不关闭连接；Windows 上必须显式关闭才能释放文件锁
            backup_con.close()
        return target

    # ---------- 论文 ----------

    def upsert_paper(self, paper: Dict[str, Any]) -> str:
        now = int(time.time())
        old = self.con.execute(
            "SELECT version FROM papers WHERE arxiv_id=?", (paper["arxiv_id"],)
        ).fetchone()
        values = (
            paper["arxiv_id"], paper.get("version", 1), paper["title"],
            json.dumps(paper.get("authors", []), ensure_ascii=False), paper.get("abstract", ""),
            paper.get("comment", ""), paper.get("published_at"), paper.get("updated_at"),
            paper.get("primary_category"),
            json.dumps(paper.get("categories", []), ensure_ascii=False), paper["abs_url"],
            paper.get("html_url"), paper.get("pdf_url"), paper.get("journal_ref"), paper.get("doi"),
        )
        if old is None:
            self.con.execute(
                """INSERT INTO papers(
                arxiv_id,version,title,authors_json,abstract,comment,published_at,updated_at,
                primary_category,categories_json,abs_url,html_url,pdf_url,journal_ref,doi,
                discovered_at,last_seen_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                values + (now, now),
            )
            event = "inserted"
        else:
            version_changed = int(paper.get("version", 1)) > int(old["version"])
            self.con.execute(
                """UPDATE papers SET version=?,title=?,authors_json=?,abstract=?,comment=?,
                published_at=?,updated_at=?,primary_category=?,categories_json=?,abs_url=?,
                html_url=?,pdf_url=?,journal_ref=?,doi=?,last_seen_at=? WHERE arxiv_id=?""",
                values[1:] + (now, paper["arxiv_id"]),
            )
            if version_changed:
                self.con.execute(
                    "UPDATE papers SET card_json=NULL,detail_json=NULL,full_text=NULL,"
                    "full_text_source=NULL,content_version=NULL,citation_count=NULL,venue=NULL,"
                    "institutions_json=NULL,author_impact=NULL WHERE arxiv_id=?",
                    (paper["arxiv_id"],),
                )
            event = "updated"
        self.con.commit()
        return event

    @staticmethod
    def _paper_dict(row: sqlite3.Row) -> Dict[str, Any]:
        item = dict(row)
        for source, target, empty in (
            ("authors_json", "authors", []), ("categories_json", "categories", []),
            ("institutions_json", "institutions", []), ("card_json", "card", {}),
            ("detail_json", "detail", {}),
        ):
            raw = item.pop(source, None)
            try:
                item[target] = json.loads(raw) if raw else empty
            except json.JSONDecodeError:
                item[target] = empty
        item.pop("full_text", None)
        return item

    def paper(self, arxiv_id: str) -> Optional[Dict[str, Any]]:
        row = self.con.execute("SELECT * FROM papers WHERE arxiv_id=?", (arxiv_id,)).fetchone()
        return self._paper_dict(row) if row else None

    def papers_in_window(self, window_start: int) -> List[Dict[str, Any]]:
        rows = self.con.execute(
            "SELECT * FROM papers WHERE discovered_at>=? ORDER BY total_score DESC,arxiv_id DESC",
            (window_start,),
        ).fetchall()
        return [self._paper_dict(row) for row in rows]

    def papers_need_openalex(self, window_start: int, min_relevance: float,
                             limit: int) -> List[Dict[str, Any]]:
        rows = self.con.execute(
            """SELECT * FROM papers WHERE discovered_at>=? AND citation_count IS NULL
               AND relevance_score>=? ORDER BY relevance_score DESC,arxiv_id DESC LIMIT ?""",
            (window_start, float(min_relevance), max(1, int(limit))),
        ).fetchall()
        return [self._paper_dict(row) for row in rows]

    def papers_need_cards(self, window_start: int, limit: int) -> List[Dict[str, Any]]:
        # 只在总分最高的 top N 里找还没生成卡片的，不向排名 N 之后蔓延。
        rows = self.con.execute(
            """SELECT * FROM (
                 SELECT * FROM papers WHERE discovered_at>=?
                 ORDER BY total_score DESC,arxiv_id DESC LIMIT ?
               ) WHERE card_json IS NULL""",
            (window_start, max(1, int(limit))),
        ).fetchall()
        return [self._paper_dict(row) for row in rows]

    def papers_need_deep(self, window_start: int, limit: int) -> List[Dict[str, Any]]:
        # 精读只针对 top N；已精读的跳过，但不顺延到 top N 之外。
        rows = self.con.execute(
            """SELECT * FROM (
                 SELECT * FROM papers WHERE discovered_at>=?
                 ORDER BY total_score DESC,arxiv_id DESC LIMIT ?
               ) WHERE detail_json IS NULL""",
            (window_start, max(1, int(limit))),
        ).fetchall()
        return [self._paper_dict(row) for row in rows]

    def papers_with_cards(self, window_start: int) -> List[Dict[str, Any]]:
        rows = self.con.execute(
            "SELECT * FROM papers WHERE discovered_at>=? AND card_json IS NOT NULL "
            "ORDER BY total_score DESC,arxiv_id DESC",
            (window_start,),
        ).fetchall()
        return [self._paper_dict(row) for row in rows]

    def papers_with_detail(self, window_start: int) -> List[Dict[str, Any]]:
        rows = self.con.execute(
            "SELECT * FROM papers WHERE discovered_at>=? AND detail_json IS NOT NULL "
            "ORDER BY total_score DESC,arxiv_id DESC",
            (window_start,),
        ).fetchall()
        return [self._paper_dict(row) for row in rows]

    # ---------- OpenAlex 元数据与评分 ----------

    def set_openalex_meta(self, arxiv_id: str, citation_count: Optional[int],
                          venue: Optional[str], institutions: List[str],
                          author_impact: Optional[float]) -> None:
        self.con.execute(
            """UPDATE papers SET citation_count=?,venue=?,institutions_json=?,author_impact=?
               WHERE arxiv_id=?""",
            (citation_count, venue, json.dumps(institutions or [], ensure_ascii=False),
             author_impact, arxiv_id),
        )
        self.con.commit()

    def set_relevance(self, arxiv_id: str, score: float, reason: str) -> None:
        self.con.execute(
            "UPDATE papers SET relevance_score=?,relevance_reason=? WHERE arxiv_id=?",
            (score, reason, arxiv_id),
        )
        self.con.commit()

    def set_scores(self, arxiv_id: str, reliability_score: float, reliability_reason: str,
                   total_score: float) -> None:
        self.con.execute(
            "UPDATE papers SET reliability_score=?,reliability_reason=?,total_score=? WHERE arxiv_id=?",
            (reliability_score, reliability_reason, total_score, arxiv_id),
        )
        self.con.commit()

    def set_card(self, arxiv_id: str, card: Dict[str, Any]) -> None:
        self.con.execute(
            "UPDATE papers SET card_json=? WHERE arxiv_id=?",
            (json.dumps(card, ensure_ascii=False), arxiv_id),
        )
        self.con.commit()

    def set_detail(self, arxiv_id: str, detail: Dict[str, Any]) -> None:
        self.con.execute(
            "UPDATE papers SET detail_json=? WHERE arxiv_id=?",
            (json.dumps(detail, ensure_ascii=False), arxiv_id),
        )
        self.con.commit()

    def set_full_text(self, arxiv_id: str, text: str, source: str, version: int) -> None:
        self.con.execute(
            "UPDATE papers SET full_text=?,full_text_source=?,content_version=? WHERE arxiv_id=?",
            (text, source, version, arxiv_id),
        )
        self.con.commit()

    def full_text(self, arxiv_id: str) -> Optional[str]:
        row = self.con.execute("SELECT full_text FROM papers WHERE arxiv_id=?", (arxiv_id,)).fetchone()
        return row["full_text"] if row and row["full_text"] else None

    # ---------- AI 账号 ----------

    def add_provider_account(self, provider: str, account_name: str,
                             credentials: Dict[str, Any], priority: int = 100,
                             quota_total: Optional[float] = None, quota_used: float = 0,
                             quota_reset_at: Optional[int] = None,
                             quota_period_seconds: int = 2592000) -> int:
        provider = provider.strip().lower()
        account_name = account_name.strip()
        if not provider or not account_name:
            raise ValueError("provider 和 account_name 不能为空")
        if quota_total is not None and quota_total <= 0:
            raise ValueError("quota_total 必须大于 0")
        if quota_used < 0:
            raise ValueError("quota_used 不能小于 0")
        now = int(time.time())
        period_seconds = max(1, int(quota_period_seconds))
        if quota_total is not None and quota_reset_at is None:
            quota_reset_at = now + period_seconds
        self.con.execute(
            """INSERT INTO provider_accounts(
                 capability,provider,account_name,credential_json,priority,quota_total,quota_used,
                 quota_reset_at,quota_period_seconds,created_at,updated_at)
               VALUES('ai',?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(capability,provider,account_name) DO UPDATE SET
                 credential_json=excluded.credential_json,priority=excluded.priority,
                 quota_total=excluded.quota_total,quota_used=excluded.quota_used,
                 quota_reset_at=excluded.quota_reset_at,
                 quota_period_seconds=excluded.quota_period_seconds,enabled=1,
                 cooldown_until=NULL,consecutive_failures=0,last_error=NULL,
                 updated_at=excluded.updated_at""",
            (provider, account_name, json.dumps(credentials, ensure_ascii=False),
             int(priority), quota_total, float(quota_used), quota_reset_at,
             period_seconds, now, now),
        )
        self.con.commit()
        row = self.con.execute(
            "SELECT id FROM provider_accounts WHERE capability='ai' AND provider=? AND account_name=?",
            (provider, account_name),
        ).fetchone()
        return int(row["id"])

    def provider_accounts(self, include_credentials: bool = False) -> List[Dict[str, Any]]:
        rows = self.con.execute(
            "SELECT * FROM provider_accounts ORDER BY priority,id"
        ).fetchall()
        result: List[Dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            raw = item.pop("credential_json", "{}")
            try:
                credentials = json.loads(raw)
            except json.JSONDecodeError:
                credentials = {}
            if include_credentials:
                item["credentials"] = credentials
            else:
                item["credential_keys"] = sorted(credentials.keys()) if isinstance(credentials, dict) else []
            total = item.get("quota_total")
            used = float(item.get("quota_used") or 0)
            item["remaining_ratio"] = None if total is None else max(0.0, (float(total) - used) / float(total))
            result.append(item)
        return result

    def set_provider_enabled(self, account_id: int, enabled: bool) -> None:
        cur = self.con.execute(
            "UPDATE provider_accounts SET enabled=?,updated_at=? WHERE id=?",
            (int(enabled), int(time.time()), int(account_id)),
        )
        self.con.commit()
        if cur.rowcount == 0:
            raise KeyError(account_id)

    def delete_provider_account(self, account_id: int) -> None:
        # provider_usage 的 account_id 为 ON DELETE SET NULL，且保留 account_label，
        # 删除账号不会连带丢失历史用量审计。
        cur = self.con.execute("DELETE FROM provider_accounts WHERE id=?", (int(account_id),))
        self.con.commit()
        if cur.rowcount == 0:
            raise KeyError(account_id)

    def reset_due_provider_quotas(self, now: Optional[int] = None) -> int:
        now = int(now or time.time())
        rows = self.con.execute(
            """SELECT id,quota_reset_at,quota_period_seconds FROM provider_accounts
               WHERE quota_reset_at IS NOT NULL AND quota_reset_at<=?""", (now,)
        ).fetchall()
        for row in rows:
            reset_at = int(row["quota_reset_at"])
            period = max(1, int(row["quota_period_seconds"]))
            while reset_at <= now:
                reset_at += period
            self.con.execute(
                """UPDATE provider_accounts SET quota_used=0,quota_reset_at=?,cooldown_until=NULL,
                   consecutive_failures=0,last_error=NULL,updated_at=? WHERE id=?""",
                (reset_at, now, int(row["id"])),
            )
        if rows:
            self.con.commit()
        return len(rows)

    def record_provider_result(self, account_id: Optional[int], account_label: str,
                               task_type: str, units: float, success: bool, error: str = "",
                               cooldown_seconds: int = 300) -> None:
        now = int(time.time())
        safe_error = error[:500]
        safe_label = (account_label or "")[:80]
        with self.con:
            self.con.execute(
                "INSERT INTO provider_usage(account_id,account_label,task_type,units,success,error,created_at) "
                "VALUES(?,?,?,?,?,?,?)",
                (account_id, safe_label, task_type, float(units), int(success), safe_error, now),
            )
            if account_id is not None:
                if success:
                    self.con.execute(
                        """UPDATE provider_accounts SET quota_used=quota_used+?,last_used_at=?,
                           last_success_at=?,consecutive_failures=0,cooldown_until=NULL,
                           last_error=NULL,updated_at=? WHERE id=?""",
                        (float(units), now, now, now, int(account_id)),
                    )
                else:
                    self.con.execute(
                        """UPDATE provider_accounts SET last_used_at=?,consecutive_failures=consecutive_failures+1,
                           cooldown_until=?,last_error=?,updated_at=? WHERE id=?""",
                        (now, now + max(0, int(cooldown_seconds)), safe_error, now, int(account_id)),
                    )

    # ---------- 状态 ----------

    def status(self) -> Dict[str, Any]:
        paper_count = self.con.execute("SELECT COUNT(*) n FROM papers").fetchone()
        card_count = self.con.execute(
            "SELECT COUNT(*) n FROM papers WHERE card_json IS NOT NULL"
        ).fetchone()
        detail_count = self.con.execute(
            "SELECT COUNT(*) n FROM papers WHERE detail_json IS NOT NULL"
        ).fetchone()
        used_tokens = self.llm_usage_this_week()
        budget = int(self.get_setting("weekly_token_budget", "0") or 0)
        last_sync = self.con.execute("SELECT * FROM sync_runs ORDER BY id DESC LIMIT 1").fetchone()
        accounts = self.provider_accounts()
        return {
            "access_enabled": self.access_enabled(),
            "pause_reason": self.get_setting("site_access_pause_reason", ""),
            "papers": int(paper_count["n"]),
            "with_cards": int(card_count["n"]),
            "with_details": int(detail_count["n"]),
            "requests_this_week": {
                "automatic": self.request_count_this_week("automatic"),
                "user": self.request_count_this_week("user"),
            },
            "llm_tokens_this_week": used_tokens,
            "llm_budget": budget,
            "llm_budget_remaining": max(0, budget - used_tokens) if budget else None,
            "provider_accounts": [{
                "id": item["id"], "provider": item["provider"],
                "account_name": item["account_name"],
                "enabled": bool(item["enabled"]), "remaining_ratio": item["remaining_ratio"],
                "cooldown_until": item["cooldown_until"],
            } for item in accounts],
            "last_sync": dict(last_sync) if last_sync else None,
        }
