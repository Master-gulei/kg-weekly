from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

from .arxiv import split_arxiv_id
from .fetch import SafeFetcher

ARXIV_DOI_PREFIX = "10.48550/arXiv."


def arxiv_doi(arxiv_id: str) -> str:
    return ARXIV_DOI_PREFIX + arxiv_id


def doi_to_arxiv_id(doi: str) -> str:
    """从 OpenAlex DOI 还原 arXiv ID；兼容 URL 形式与大小写变化。"""
    value = str(doi)
    marker = "10.48550/"
    if marker in value.lower():
        value = value.lower().split(marker, 1)[1]
    value = re.sub(r"^arxiv\.", "", value)
    return split_arxiv_id(value)[0]


def _chunks(values: List[str], size: int) -> List[List[str]]:
    return [values[i:i + size] for i in range(0, len(values), size)]


def _mailto_suffix(config: Dict[str, Any]) -> str:
    mailto = str((config.get("openalex") or {}).get("mailto", "")).strip()
    return "&mailto={}".format(quote(mailto)) if mailto else ""


def fetch_works_meta(fetcher: SafeFetcher, config: Dict[str, Any],
                     arxiv_ids: List[str]) -> Tuple[Dict[str, Dict[str, Any]], List[str]]:
    """按 arXiv DOI 批量查询 OpenAlex works。

    返回 ({arxiv_id: {citation_count, venue, institutions, author_ids}}, errors)。
    单个批次失败不影响其他批次。
    """
    openalex = config.get("openalex") or {}
    base = str(openalex.get("base_url", "https://api.openalex.org")).rstrip("/")
    batch_size = max(1, min(int(openalex.get("doi_batch_size", 50)), 50))
    suffix = _mailto_suffix(config)
    result: Dict[str, Dict[str, Any]] = {}
    errors: List[str] = []
    for chunk in _chunks(list(arxiv_ids), batch_size):
        dois = "|".join(arxiv_doi(i) for i in chunk)
        url = "{}/works?filter=doi:{}&per-page={}&select=doi,cited_by_count,primary_location,authorships{}".format(
            base, quote(dois, safe=""), len(chunk), suffix)
        try:
            payload = fetcher.fetch(url, mode="automatic", purpose="openalex_batch",
                                    accept="application/json")
            data = json.loads(payload or b"{}")
            for work in data.get("results", []):
                doi = str(work.get("doi") or "")
                arxiv_id = doi_to_arxiv_id(doi)
                if not arxiv_id or arxiv_id not in chunk:
                    continue
                institutions: List[str] = []
                author_ids: List[str] = []
                for authorship in work.get("authorships") or []:
                    author = authorship.get("author") or {}
                    author_id = str(author.get("id") or "")
                    if author_id:
                        author_ids.append(author_id)
                    for institution in authorship.get("institutions") or []:
                        name = str(institution.get("display_name") or "").strip()
                        if name:
                            institutions.append(name)
                    for raw in authorship.get("raw_affiliation_strings") or []:
                        name = str(raw).strip()
                        if name and name not in institutions:
                            institutions.append(name)
                primary = work.get("primary_location") or {}
                source = primary.get("source") or {}
                venue = str(source.get("display_name") or "") or None
                result[arxiv_id] = {
                    "citation_count": work.get("cited_by_count"),
                    "venue": venue,
                    "institutions": list(dict.fromkeys(institutions))[:8],
                    "author_ids": author_ids,
                }
        except Exception as exc:  # 单批失败不影响主流程
            errors.append("{}: {}".format(type(exc).__name__, exc))
    return result, errors


def fetch_author_impacts(fetcher: SafeFetcher, config: Dict[str, Any],
                         author_ids: List[str]) -> Tuple[Dict[str, int], List[str]]:
    """批量查询作者累计被引次数，返回 {author_openalex_id: cited_by_count}。"""
    openalex = config.get("openalex") or {}
    base = str(openalex.get("base_url", "https://api.openalex.org")).rstrip("/")
    batch_size = max(1, min(int(openalex.get("author_batch_size", 50)), 50))
    suffix = _mailto_suffix(config)
    result: Dict[str, int] = {}
    errors: List[str] = []
    unique_ids = list(dict.fromkeys(aid for aid in author_ids if aid))
    for chunk in _chunks(unique_ids, batch_size):
        ids = "|".join(chunk)
        url = "{}/authors?filter=ids.openalex:{}&per-page={}&select=id,cited_by_count{}".format(
            base, quote(ids, safe=""), len(chunk), suffix)
        try:
            payload = fetcher.fetch(url, mode="automatic", purpose="openalex_batch",
                                    accept="application/json")
            data = json.loads(payload or b"{}")
            for author in data.get("results", []):
                author_id = str(author.get("id") or "")
                count = author.get("cited_by_count")
                if author_id and count is not None:
                    result[author_id] = int(count)
        except Exception as exc:
            errors.append("{}: {}".format(type(exc).__name__, exc))
    return result, errors


def paper_author_impact(author_ids: List[str],
                        impacts: Dict[str, int]) -> Optional[float]:
    """取作者累计被引的最高值作为论文的作者影响力信号。"""
    values = [int(impacts[i]) for i in author_ids if i in impacts and impacts.get(i)]
    return float(max(values)) if values else None
