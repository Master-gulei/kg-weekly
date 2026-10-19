from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Tuple


def _contains(text: str, keyword: str) -> bool:
    """大小写不敏感匹配；单词型关键词按词边界匹配并自动兼容复数（如 kg/kgs）。"""
    keyword = keyword.lower().strip()
    text = text.lower()
    if not keyword:
        return False
    if re.fullmatch(r"[a-z0-9_-]+", keyword):
        return re.search(r"\b{}(?:s)?\b".format(re.escape(keyword)), text) is not None
    return keyword in text


def rank_relevance(paper: Dict[str, Any], config: Dict[str, Any]) -> Tuple[float, str]:
    """相关性打分：核心关键词命中 + 多命中加成 + 应用型加成 + 代码/开源加成。"""
    keywords = config.get("keywords") or {}
    title = paper.get("title", "").lower()
    abstract = paper.get("abstract", "").lower()
    comment = paper.get("comment", "").lower()
    combined = title + "\n" + abstract
    score = 0.0
    reasons: List[str] = []

    hits = {word: _contains(combined, word) for word in keywords.get("core", [])}
    hit_words = [word for word, matched in hits.items() if matched]
    if hit_words:
        score += len(hit_words) * 3.0
        title_hits = [word for word in hit_words if _contains(title, word)]
        score += len(title_hits) * 2.0
        if len(hit_words) >= 2:
            score += (len(hit_words) - 1) * 2.0
        reasons.append("命中关键词 {} 种：{}".format(len(hit_words), "、".join(hit_words)))

    applied = [word for word in keywords.get("applied_signals", []) if _contains(combined, word)]
    if applied:
        score += 4.0
        reasons.append("应用型信号：{}".format("、".join(applied[:3])))

    code_hits = [word for word in keywords.get("code_signals", [])
                 if _contains(combined + "\n" + comment, word)]
    if code_hits:
        score += 5.0
        reasons.append("代码/开源信号：{}".format("、".join(code_hits[:3])))

    negatives = [word for word in keywords.get("negative", []) if _contains(combined, word)]
    if negatives:
        score -= 10.0
        reasons.append("负向降权：{}".format("、".join(negatives[:3])))

    return round(score, 2), "；".join(reasons) or "未命中核心关键词"


def rank_reliability(paper: Dict[str, Any], config: Dict[str, Any]) -> Tuple[float, str]:
    """靠谱度打分：机构白名单 + 作者历史影响力 + 引用数分层 + venue 信息。"""
    reliability = config.get("reliability") or {}
    score = 0.0
    reasons: List[str] = []

    whitelist = [str(item).lower() for item in reliability.get("institution_whitelist", [])]
    institutions = " ".join(str(item) for item in paper.get("institutions") or []).lower()
    # 词边界匹配，避免 "nec" 命中 Connecti**cut**、"meta" 命中 **Meta**data 之类的子串误报。
    matched = [item for item in whitelist
               if item and re.search(r"\b{}\b".format(re.escape(item)), institutions)]
    if matched:
        score += min(6.0, 2.0 * len(matched))
        reasons.append("知名机构：{}".format("、".join(matched[:3])))

    impact = float(paper.get("author_impact") or 0)
    if impact > 0:
        cap = float(reliability.get("author_impact_bonus_cap", 6))
        bonus = min(cap, 1.5 * math.log10(impact + 1))
        score += bonus
        reasons.append("作者影响力：累计被引 {:,}".format(int(impact)))

    cites = paper.get("citation_count")
    if cites is not None:
        points = 0
        for threshold, tier_points in reliability.get("citation_tiers", []):
            if cites >= float(threshold):
                points = tier_points
        score += float(points)
        if cites > 0:
            reasons.append("引用 {} 次".format(cites))

    venue = str(paper.get("venue") or "").strip()
    # arXiv 本身是预印本仓库，不是同行评审 venue，不能加分。
    if venue and not venue.lower().startswith("arxiv"):
        score += 2.0
        reasons.append("venue：{}".format(venue[:60]))

    return round(score, 2), "；".join(reasons) or "暂无外部可靠度信号"


def rank_paper(paper: Dict[str, Any], config: Dict[str, Any]) -> Tuple[float, float, str, float, str]:
    """综合评分：总分 = 相关性 * 0.7 + 靠谱度 * 0.3。"""
    relevance, relevance_reason = rank_relevance(paper, config)
    reliability, reliability_reason = rank_reliability(paper, config)
    total = round(relevance * 0.7 + reliability * 0.3, 2)
    return relevance, relevance_reason, reliability, reliability_reason, total
