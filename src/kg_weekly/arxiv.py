from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode


ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV = "{http://arxiv.org/schemas/atom}"


def _text(node: Optional[ET.Element], default: str = "") -> str:
    if node is None:
        return default
    return re.sub(r"\s+", " ", "".join(node.itertext())).strip()


def split_arxiv_id(url_or_id: str) -> Tuple[str, int]:
    value = url_or_id.rstrip("/").split("/")[-1]
    match = re.match(r"(.+?)(?:v(\d+))?$", value)
    if not match:
        return value, 1
    return match.group(1), int(match.group(2) or 1)


def build_query_url(categories: List[str], phrases: List[str], start_date,
                    end_date, max_results: int = 300) -> str:
    """构造 arXiv API 查询 URL：分类 + 短语（all: 字段，匹配标题与摘要）+ 时间窗。"""
    cat_part = " OR ".join("cat:{}".format(item) for item in categories)
    phrase_part = " OR ".join('all:"{}"'.format(item) for item in phrases)
    query = "({}) AND ({}) AND submittedDate:[{} TO {}]".format(
        cat_part, phrase_part,
        start_date.strftime("%Y%m%d%H%M"), end_date.strftime("%Y%m%d%H%M"),
    )
    params = urlencode({
        "search_query": query,
        "start": 0,
        "max_results": max(1, min(max_results, 1000)),
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    })
    return "https://export.arxiv.org/api/query?" + params


def parse_atom(payload: bytes) -> List[Dict[str, Any]]:
    # 拒绝 DOCTYPE/实体声明（防实体扩展）；拒绝带 NUL 字节的负载——UTF-16 等编码会
    # 绕过字节级匹配，直接交给 expat 解析可能展开内部实体。
    if re.search(rb"<!DOCTYPE|<!ENTITY", payload, re.I) or b"\x00" in payload[:512]:
        raise ValueError("XML 中的 DOCTYPE/实体声明被拒绝")
    root = ET.fromstring(payload)
    papers = []
    for entry in root.findall(ATOM + "entry"):
        entry_id = _text(entry.find(ATOM + "id"))
        arxiv_id, version = split_arxiv_id(entry_id)
        title = _text(entry.find(ATOM + "title"))
        abstract = _text(entry.find(ATOM + "summary"))
        authors = [_text(a.find(ATOM + "name")) for a in entry.findall(ATOM + "author")]
        categories = [node.attrib.get("term", "") for node in entry.findall(ATOM + "category")]
        primary_node = entry.find(ARXIV + "primary_category")
        primary = primary_node.attrib.get("term") if primary_node is not None else (categories[0] if categories else "")
        links = {node.attrib.get("title") or node.attrib.get("rel", ""): node.attrib.get("href", "")
                 for node in entry.findall(ATOM + "link")}
        abs_url = next((node.attrib.get("href", "") for node in entry.findall(ATOM + "link")
                        if node.attrib.get("rel") == "alternate"), "https://arxiv.org/abs/" + arxiv_id)
        papers.append({
            "arxiv_id": arxiv_id,
            "version": version,
            "title": title,
            "authors": [a for a in authors if a],
            "abstract": abstract,
            "comment": _text(entry.find(ARXIV + "comment")),
            "published_at": _text(entry.find(ATOM + "published")),
            "updated_at": _text(entry.find(ATOM + "updated")),
            "primary_category": primary,
            "categories": [c for c in categories if c],
            "abs_url": abs_url.replace("http://", "https://"),
            "html_url": "https://arxiv.org/html/{}v{}".format(arxiv_id, version),
            "pdf_url": (links.get("pdf") or "https://arxiv.org/pdf/{}v{}".format(arxiv_id, version)).replace("http://", "https://"),
            "journal_ref": _text(entry.find(ARXIV + "journal_ref")),
            "doi": _text(entry.find(ARXIV + "doi")),
        })
    return papers


class PaperHTMLParser(HTMLParser):
    SKIP = {"script", "style", "nav", "footer", "noscript"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth_skip = 0
        self.parts: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if tag in self.SKIP:
            self.depth_skip += 1
        if self.depth_skip == 0 and tag in ("h1", "h2", "h3", "h4", "p", "li", "figcaption", "tr"):
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP and self.depth_skip:
            self.depth_skip -= 1
        if self.depth_skip == 0 and tag in ("p", "li", "figcaption", "tr", "section"):
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.depth_skip == 0:
            cleaned = re.sub(r"\s+", " ", data).strip()
            if cleaned:
                self.parts.append(cleaned + " ")

    def text(self) -> str:
        value = html.unescape("".join(self.parts))
        value = re.sub(r"[ \t]+\n", "\n", value)
        value = re.sub(r"\n{3,}", "\n\n", value)
        return value.strip()


def extract_paper_html(payload: bytes) -> str:
    text = payload.decode("utf-8", errors="replace")
    parser = PaperHTMLParser()
    parser.feed(text)
    if parser.depth_skip:
        # HTMLParser 对 script/style 启用 CDATA 模式：只找对应的闭合标签，未闭合时
        # 其后所有内容（含正文标签）都会整体变成一次 handle_data，全部被跳过。
        # 此时剔除 script/style 标签后重解析，让正文容器重新可见；残留的少量
        # 脚本文本进入正文无害，远好于整篇正文丢失。
        cleaned = re.sub(r"(?is)<(script|style)\b[^>]*>.*?</\1\s*>", "", text)
        cleaned = re.sub(r"(?is)<(script|style)\b[^>]*>", "", cleaned)
        parser = PaperHTMLParser()
        parser.feed(cleaned)
    return parser.text()
