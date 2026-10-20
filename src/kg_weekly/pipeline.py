from __future__ import annotations

import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .arxiv import build_query_url, extract_paper_html, parse_atom
from .config import topic_file_prefix
from .db import Database
from .fetch import SafeFetcher
from .llm import BudgetExceeded, LLMClient, LLMUnavailable
from .openalex import fetch_author_impacts, fetch_works_meta, paper_author_impact
from .ranking import rank_paper, rank_relevance as rank_relevance_of
from .report import build_report


class PipelineError(RuntimeError):
    pass


class WeeklyPipeline:
    """每周流水线：arXiv 查询 → OpenAlex 增强 → 评分 → 中文卡片 → 精读 → HTML 周报。

    每一步幂等可重入：已有结果的论文会被跳过。
    """

    def __init__(self, project: Path, db: Database, config: Dict[str, Any],
                 fetcher: SafeFetcher, llm: LLMClient):
        self.project = project
        self.db = db
        self.config = config
        self.fetcher = fetcher
        self.llm = llm
        self.out_dir = project / "out"
        self.out_dir.mkdir(parents=True, exist_ok=True)
        window_days = int(config.get("site", {}).get("week_window_days", 7))
        self.window_end = datetime.now()
        self.window_start = self.window_end - timedelta(days=window_days)
        self.window_start_ts = int(time.mktime(self.window_start.timetuple()))
        self.label = "{} ~ {}".format(
            self.window_start.strftime("%Y-%m-%d"), self.window_end.strftime("%Y-%m-%d"))

    # ---------- 步骤 1：arXiv 查询 ----------

    def fetch_arxiv(self, force: bool = False) -> Dict[str, Any]:
        week_key = "last_arxiv_fetch_week"
        # 用 ISO 年（跨年时日历年与 ISO 周不同步，如 2027-01-01 属于 2026-W53）
        iso = self.window_end.isocalendar()
        current_week = "{}-W{:02d}".format(iso[0], iso[1])
        if not force and self.db.get_setting(week_key) == current_week:
            return {"status": "skipped", "reason": "本周已经抓取过；可用 --force 重新抓取"}
        run_id = self.db.begin_sync()
        discovery = self.config["discovery"]
        url = build_query_url(
            discovery["categories"], discovery["search_phrases"],
            self.window_start, self.window_end, discovery.get("max_results_per_query", 300),
        )
        try:
            payload = self.fetcher.fetch(
                url, mode="automatic", purpose="arxiv_query",
                accept="application/atom+xml, application/xml;q=0.9",
            )
            papers = parse_atom(payload or b"")
            if not papers:
                self.db.finish_sync(run_id, "failed", error="arXiv 返回 0 条结果，疑似查询异常")
                raise PipelineError("arXiv 返回 0 条结果，请检查 search_phrases 配置")
            inserted = updated = 0
            for paper in papers:
                paper["comment"] = paper.get("comment", "")
                event = self.db.upsert_paper(paper)
                inserted += int(event == "inserted")
                updated += int(event == "updated")
                relevance, reason = rank_relevance_of(paper, self.config)
                self.db.set_relevance(str(paper["arxiv_id"]), relevance, reason)
            self.db.finish_sync(run_id, "success", len(papers), inserted, updated)
            self.db.set_setting(week_key, current_week)
            return {"status": "success", "fetched": len(papers),
                    "inserted": inserted, "updated": updated}
        except Exception as exc:
            self.db.finish_sync(run_id, "failed", error="{}: {}".format(type(exc).__name__, exc))
            raise

    # ---------- 步骤 2：OpenAlex 增强 ----------

    def enrich_openalex(self) -> Dict[str, Any]:
        pipeline_cfg = self.config.get("pipeline") or {}
        candidates = self.db.papers_need_openalex(
            self.window_start_ts,
            float(pipeline_cfg.get("enrich_min_relevance", 3)),
            int(pipeline_cfg.get("enrich_limit", 150)),
        )
        if not candidates:
            return {"status": "skipped", "reason": "没有需要增强的论文"}
        arxiv_ids = [str(paper["arxiv_id"]) for paper in candidates]
        meta, errors = fetch_works_meta(self.fetcher, self.config, arxiv_ids)
        author_ids: List[str] = []
        for entry in meta.values():
            author_ids.extend(entry.get("author_ids") or [])
        impacts, author_errors = fetch_author_impacts(self.fetcher, self.config, author_ids)
        errors.extend(author_errors)
        enriched = 0
        for arxiv_id in arxiv_ids:
            entry = meta.get(arxiv_id)
            if entry is None:
                continue
            impact = paper_author_impact(entry.get("author_ids") or [], impacts)
            self.db.set_openalex_meta(
                arxiv_id,
                entry.get("citation_count"),
                entry.get("venue"),
                entry.get("institutions") or [],
                impact,
            )
            enriched += 1
        return {"status": "success", "selected": len(arxiv_ids), "enriched": enriched,
                "errors": errors[:5]}

    # ---------- 步骤 3：评分 ----------

    def score_papers(self) -> Dict[str, Any]:
        papers = self.db.papers_in_window(self.window_start_ts)
        scored = 0
        for paper in papers:
            relevance, relevance_reason, reliability, reliability_reason, total = rank_paper(
                paper, self.config)
            self.db.set_relevance(str(paper["arxiv_id"]), relevance, relevance_reason)
            self.db.set_scores(str(paper["arxiv_id"]), reliability, reliability_reason, total)
            scored += 1
        return {"status": "success", "scored": scored}

    # ---------- 步骤 4：中文卡片 ----------

    def make_cards(self) -> Dict[str, Any]:
        pipeline_cfg = self.config.get("pipeline") or {}
        llm_cfg = self.config.get("llm") or {}
        limit = int(pipeline_cfg.get("top_cards", 50))
        batch_size = max(1, min(int(llm_cfg.get("batch_size", 20)), 20))
        papers = self.db.papers_need_cards(self.window_start_ts, limit)
        if not papers:
            return {"status": "skipped", "reason": "没有需要生成卡片的论文"}
        done = failed = 0
        failures: List[str] = []
        for index in range(0, len(papers), batch_size):
            chunk = papers[index:index + batch_size]
            try:
                cards = self.llm.batch_cards(chunk)
                for paper, card in zip(chunk, cards):
                    self.db.set_card(str(paper["arxiv_id"]), card)
                done += len(cards)
            except (LLMUnavailable, BudgetExceeded) as exc:
                return {"status": "stopped", "done": done, "failed": failed,
                        "failures": failures[:5],
                        "error": "{}: {}".format(type(exc).__name__, exc)}
            except Exception as exc:
                failed += len(chunk)
                failures.append("{}: {}".format(type(exc).__name__, str(exc)[:300]))
        return {"status": "success" if failed == 0 else "partial",
                "selected": len(papers), "done": done, "failed": failed,
                "failures": failures[:5]}

    # ---------- 步骤 5：AI 精读 ----------

    def ensure_full_text(self, paper: Dict[str, Any]) -> Tuple[str, str]:
        """返回 (全文, 来源)；本地服务按需精读与流水线共用（跨模块公开契约）。"""
        arxiv_id = str(paper["arxiv_id"])
        full_text = self.db.full_text(arxiv_id)
        source = paper.get("full_text_source") or "摘要"
        if not full_text:
            payload = self.fetcher.fetch(
                paper["html_url"], mode="user", purpose="paper_html",
                accept="text/html,application/xhtml+xml", optional_404=True,
            )
            if payload:
                full_text = extract_paper_html(payload)
                source = "HTML全文"
                self.db.set_full_text(arxiv_id, full_text, source, int(paper["version"]))
            else:
                full_text = ""
                source = "摘要"
        return full_text, str(source)

    def deep_read(self) -> Dict[str, Any]:
        pipeline_cfg = self.config.get("pipeline") or {}
        limit = int(pipeline_cfg.get("top_deep", 12))
        papers = self.db.papers_need_deep(self.window_start_ts, limit)
        if not papers:
            return {"status": "skipped", "reason": "没有需要精读的论文"}
        done = failed = 0
        failures: List[str] = []
        for paper in papers:
            try:
                full_text, source = self.ensure_full_text(paper)
                detail = self.llm.deep_read(paper, full_text, source)
                self.db.set_detail(str(paper["arxiv_id"]), detail)
                done += 1
            except (LLMUnavailable, BudgetExceeded) as exc:
                return {"status": "stopped", "done": done, "failed": failed,
                        "failures": failures[:5],
                        "error": "{}: {}".format(type(exc).__name__, exc)}
            except Exception as exc:
                failed += 1
                failures.append("{}: {}".format(type(exc).__name__, str(exc)[:300]))
        return {"status": "success" if failed == 0 else "partial",
                "selected": len(papers), "done": done, "failed": failed,
                "failures": failures[:5]}

    # ---------- 步骤 6：周报 ----------

    def build_report(self) -> Dict[str, Any]:
        deep_papers = self.db.papers_with_detail(self.window_start_ts)
        card_papers = self.db.papers_with_cards(self.window_start_ts)
        stats = self.db.status()
        html = build_report(
            self.config.get("site", {}).get("name", "KG前沿论文解读"),
            self.label, deep_papers, card_papers, stats, self.config,
        )
        path = self.out_dir / "{}-前沿论文解读-{}.html".format(
            topic_file_prefix(self.config.get("_topic") or "kg"),
            self.window_end.strftime("%Y-%m-%d"))
        path.write_text(html, encoding="utf-8")
        return {"status": "success", "path": str(path),
                "deep_count": len(deep_papers), "card_count": len(card_papers)}

    # ---------- 总入口 ----------

    def _backup_db(self) -> Dict[str, Any]:
        """运行前把数据库快照到 data\papers.db.bak；失败不阻塞主流程。"""
        try:
            self.db.backup(self.db.path.with_suffix(".db.bak"))
            return {"status": "success"}
        except Exception as exc:
            return {"status": "failed", "error": "{}: {}".format(type(exc).__name__, exc)}

    def run(self, force: bool = False) -> Dict[str, Any]:
        steps: Dict[str, Any] = {}
        steps["backup"] = self._backup_db()
        steps["fetch"] = self.fetch_arxiv(force=force)
        steps["openalex"] = self.enrich_openalex()
        steps["score"] = self.score_papers()
        steps["cards"] = self.make_cards()
        steps["deep"] = self.deep_read()
        steps["report"] = self.build_report()
        return steps
