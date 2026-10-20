from __future__ import annotations

import html
from datetime import datetime
from typing import Any, Dict, List

_STYLE = """
:root{--bg:#f4f1e9;--card:#ffffff;--ink:#242130;--muted:#837c92;--line:#e8e2d3;
--accent:#6c4cf1;--accent-2:#8f6fff;--accent-soft:#f1edff;
--gold:#a97e17;--gold-soft:#fbf3dc;--green:#2f7d4f;--green-soft:#e8f5ed;
--blue:#2b62a3;--blue-soft:#e9f2fb;
--shadow:0 12px 32px rgba(36,33,48,.08)}
*{box-sizing:border-box;margin:0;padding:0}
html{scroll-behavior:smooth}
body{font-family:"Segoe UI","PingFang SC","Microsoft YaHei",system-ui,sans-serif;
background:var(--bg);color:var(--ink);line-height:1.7;padding-bottom:72px}
.wrap{max-width:1440px;margin:0 auto;padding:0 48px}
header.hero{margin:0 -48px 10px;padding:56px 48px 36px;border-bottom:1px solid var(--line);
background:radial-gradient(1100px 460px at 12% -12%,rgba(108,76,241,.13),transparent 62%),
radial-gradient(820px 400px at 96% -6%,rgba(169,126,23,.10),transparent 58%)}
@media(max-width:900px){.wrap{padding:0 24px}header.hero{margin:0 -24px 8px;padding:48px 24px 32px}}
@media(max-width:640px){.wrap{padding:0 16px}header.hero{margin:0 -16px 8px;padding:40px 16px 26px}}
.kicker{font-size:11.5px;letter-spacing:.32em;text-transform:uppercase;color:var(--accent);font-weight:700}
.brand{display:flex;align-items:center;gap:18px}
.logo{flex:0 0 auto;width:66px;height:66px;border-radius:18px;
background:linear-gradient(135deg,var(--accent),var(--accent-2));
display:flex;align-items:center;justify-content:center;box-shadow:0 8px 22px rgba(108,76,241,.35)}
.logo svg{width:40px;height:40px;display:block}
.brand-text{min-width:0}
h1{font-size:32px;margin:8px 0 6px}
@media(max-width:640px){.brand{gap:14px}.logo{width:54px;height:54px;border-radius:14px}.logo svg{width:32px;height:32px}}
.sub{color:var(--muted);font-size:13.5px}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:16px;margin:34px 0 6px}
.stat{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px 22px;
transition:transform .18s ease,box-shadow .18s ease}
.stat:hover{transform:translateY(-2px);box-shadow:var(--shadow)}
.stat b{display:block;font-size:24px;color:var(--accent);font-variant-numeric:tabular-nums}
.stat span{color:var(--muted);font-size:12px}
h2.sec{margin:56px 0 4px;font-size:21px;border-left:4px solid var(--accent);border-radius:2px;padding-left:12px}
.sec-note{color:var(--muted);font-size:13px;margin:6px 0 20px}
/* 折叠摘要行上的迷你徽章 */
.chip{display:inline-block;font-size:11px;font-weight:600;border-radius:999px;padding:2px 9px;white-space:nowrap}
.chip.score{background:var(--ink);color:#fff}
.chip.inst{background:var(--accent-soft);color:var(--accent)}
.chip.cite{background:var(--gold-soft);color:var(--gold)}
.chip.code{background:var(--green-soft);color:var(--green)}
.chip.applied{background:var(--blue-soft);color:var(--blue)}
/* 精读：默认折叠，点击展开 */
details.paper{background:var(--card);border:1px solid var(--line);border-radius:16px;margin:16px 0;
overflow:hidden;transition:box-shadow .2s ease,border-color .2s ease}
details.paper:hover{box-shadow:0 6px 22px rgba(36,33,48,.09)}
details.paper[open]{border-color:var(--accent-2);box-shadow:var(--shadow)}
details.paper summary{cursor:pointer;list-style:none;display:grid;grid-template-columns:44px 1fr auto;
column-gap:14px;row-gap:8px;align-items:center;padding:20px 24px}
details.paper summary::-webkit-details-marker{display:none}
.rank{grid-row:1/3;display:flex;align-items:center;justify-content:center;width:40px;height:40px;
border-radius:12px;background:linear-gradient(135deg,var(--accent),var(--accent-2));color:#fff;
font-size:15px;font-weight:700;box-shadow:0 4px 12px rgba(108,76,241,.3)}
.d-head{grid-column:2;min-width:0}
.d-title{font-size:17.5px;font-weight:700;line-height:1.45;transition:color .15s ease}
details.paper summary:hover .d-title{color:var(--accent)}
.d-sub{color:var(--muted);font-size:12.5px;margin-top:3px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.d-one{grid-column:2;font-size:14px;color:#4c4759;line-height:1.6}
.d-meta{grid-column:3;grid-row:1/3;display:flex;flex-direction:column;align-items:flex-end;gap:9px}
.d-meta .chips{display:flex;flex-wrap:wrap;justify-content:flex-end;gap:6px;max-width:420px}
.tg{font-size:12px;color:var(--accent);font-weight:600}
.tg-close{display:none}
details.paper[open] .tg-open{display:none}
details.paper[open] .tg-close{display:inline}
.d-body{padding:6px 24px 28px 82px;animation:rise .22s ease}
@keyframes rise{from{opacity:0;transform:translateY(-5px)}to{opacity:1;transform:none}}
.d-body .orig{color:var(--muted);font-size:13px;padding:12px 0 2px;border-top:1px dashed var(--line);margin-bottom:10px}
@media(max-width:700px){
details.paper summary{grid-template-columns:36px 1fr;padding:16px}
.rank{width:34px;height:34px;font-size:13px;border-radius:10px}
.d-meta{grid-column:2;grid-row:3;flex-direction:row;flex-wrap:wrap;justify-content:flex-start;align-items:center}
.d-body{padding:4px 16px 22px}}
/* 完整徽章（展开区与卡片） */
.badges{margin:12px 0 14px;display:flex;flex-wrap:wrap;gap:6px}
.badge{font-size:12px;border-radius:999px;padding:3px 11px;border:1px solid var(--line);background:#fff;color:#4c4759}
.badge.inst{background:var(--accent-soft);border-color:transparent;color:var(--accent)}
.badge.cite{background:var(--gold-soft);border-color:transparent;color:var(--gold)}
.badge.code{background:var(--green-soft);border-color:transparent;color:var(--green)}
.badge.applied{background:var(--blue-soft);border-color:transparent;color:var(--blue)}
.badge.score{background:var(--ink);color:#fff;border-color:var(--ink)}
/* 展开区内容 */
.section{margin-top:22px}
.section h4{font-size:14px;color:var(--accent);margin-bottom:7px;display:flex;align-items:center;gap:8px}
.section h4::before{content:"";width:6px;height:6px;border-radius:50%;background:var(--accent-2)}
.section p{margin-bottom:10px;font-size:14.5px}
.section li{font-size:14.5px;margin:3px 0 3px 20px}
.callout{background:var(--accent-soft);border-left:3px solid var(--accent);border-radius:10px;padding:12px 15px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:14px}
@media(max-width:640px){.grid2{grid-template-columns:1fr}}
.grid2>div{background:#faf8f3;border:1px solid var(--line);border-radius:12px;padding:14px 18px;font-size:14px}
.grid2 b{display:block;font-size:12px;color:var(--accent);margin-bottom:5px}
.reliability{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px}
.reliability>div{background:#faf8f3;border:1px solid var(--line);border-radius:12px;padding:13px 16px;font-size:13px}
.reliability b{display:block;font-size:12px;color:var(--accent);margin-bottom:4px}
.concept{margin-bottom:10px;font-size:14px;padding:12px 15px;background:#faf8f3;border-radius:10px}
.concept b{color:var(--accent)}
details.quiz{background:#faf8f3;border:1px solid var(--line);border-radius:10px;padding:12px 16px;margin-top:10px}
details.quiz summary{cursor:pointer;font-size:14px;font-weight:600;list-style:none}
details.quiz summary::-webkit-details-marker{display:none}
details.quiz summary::before{content:"✦";color:var(--accent);margin-right:8px}
details.quiz p{font-size:13px;margin-top:8px;color:var(--muted)}
/* 其余论文卡片 */
.paper-list{display:grid;gap:16px}
.paper-list .paper{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px 24px;margin:0;
transition:border-color .15s ease,box-shadow .15s ease}
.paper-list .paper:hover{border-color:var(--accent-2);box-shadow:0 6px 20px rgba(36,33,48,.07)}
.paper-list .paper h3{font-size:15.5px;line-height:1.5}
.paper-list .paper .orig{color:var(--muted);font-size:12.5px;margin:2px 0 8px}
.one-liner{font-size:14px}
.ext{color:var(--accent);font-size:13px;text-decoration:none}
.ext:hover{text-decoration:underline}
footer{margin-top:64px;border-top:1px solid var(--line);padding-top:22px;color:var(--muted);font-size:12.5px}
footer li{margin:4px 0 4px 18px}
"""


def esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


def _safe_url(value: Any) -> str:
    """外链只允许 http/https：防止被污染的 upstream 注入 javascript: 等协议。"""
    url = str(value or "").strip()
    if not url.lower().startswith(("http://", "https://")):
        return ""
    return url


# 内联 SVG 知识图谱拓扑图标：报告是单文件、零外部资源，图标也必须内联。
_LOGO_SVG = (
    '<svg viewBox="0 0 48 48" xmlns="http://www.w3.org/2000/svg" role="img" '
    'aria-label="知识图谱拓扑图">'
    '<g stroke="#ffffff" stroke-opacity=".9" stroke-width="1.6" fill="none">'
    '<path d="M10 14L22 8L34 14L22 20Z"/><path d="M22 20V32"/>'
    '<path d="M22 32L10 40M22 32L34 40M10 40H34"/></g>'
    '<g fill="#ffffff"><circle cx="10" cy="14" r="3.4"/><circle cx="22" cy="8" r="3.4"/>'
    '<circle cx="34" cy="14" r="3.4"/><circle cx="22" cy="20" r="3.4"/>'
    '<circle cx="22" cy="32" r="3.4"/><circle cx="10" cy="40" r="3.4"/>'
    '<circle cx="34" cy="40" r="3.4"/></g>'
    '<circle cx="22" cy="20" r="5.4" fill="none" stroke="#ffd76e" stroke-width="1.4"/>'
    '</svg>'
)
_FAVICON = (
    "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 48 48'%3E"
    "%3Crect width='48' height='48' rx='12' fill='%236c4cf1'/%3E"
    "%3Cg stroke='%23ffffff' stroke-opacity='.85' stroke-width='1.6' fill='none'%3E"
    "%3Cpath d='M10 14L22 8L34 14L22 20Z'/%3E"
    "%3Cpath d='M22 20V32M22 32L10 40M22 32L34 40M10 40H34'/%3E%3C/g%3E"
    "%3Cg fill='%23ffffff'%3E"
    "%3Ccircle cx='10' cy='14' r='3.2'/%3E%3Ccircle cx='22' cy='8' r='3.2'/%3E"
    "%3Ccircle cx='34' cy='14' r='3.2'/%3E%3Ccircle cx='22' cy='20' r='3.2'/%3E"
    "%3Ccircle cx='22' cy='32' r='3.2'/%3E%3Ccircle cx='10' cy='40' r='3.2'/%3E"
    "%3Ccircle cx='34' cy='40' r='3.2'/%3E%3C/g%3E%3C/svg%3E"
)


def _badges(paper: Dict[str, Any]) -> str:
    parts = []
    parts.append('<span class="badge score">相关度 {}</span>'.format(round(float(paper.get("relevance_score") or 0), 1)))
    parts.append('<span class="badge score">靠谱度 {}</span>'.format(round(float(paper.get("reliability_score") or 0), 1)))
    institutions = paper.get("institutions") or []
    if institutions:
        parts.append('<span class="badge inst">机构：{}</span>'.format(esc(institutions[0][:24])))
    cites = paper.get("citation_count")
    if cites is not None:
        parts.append('<span class="badge cite">引用 {}</span>'.format(int(cites)))
    venue = str(paper.get("venue") or "")
    if venue and not venue.lower().startswith("arxiv"):
        parts.append('<span class="badge">venue：{}</span>'.format(esc(venue[:28])))
    card = paper.get("card") or {}
    if str(card.get("code_available", "")).strip() in ("是", "有"):
        parts.append('<span class="badge code">有代码/开源</span>')
    if str(card.get("applied", "")).strip() == "是":
        parts.append('<span class="badge applied">应用型</span>')
    return '<div class="badges">{}</div>'.format("".join(parts))


def _summary_chips(paper: Dict[str, Any]) -> str:
    """折叠行的迷你徽章：评分、机构、引用与加分项，一眼看清重点。"""
    chips = ['<span class="chip score">{}</span>'.format(
        round(float(paper.get("total_score") or 0), 1))]
    institutions = paper.get("institutions") or []
    if institutions:
        chips.append('<span class="chip inst">{}</span>'.format(esc(institutions[0][:18])))
    cites = paper.get("citation_count")
    if cites is not None:
        chips.append('<span class="chip cite">引 {}</span>'.format(int(cites)))
    card = paper.get("card") or {}
    if str(card.get("code_available", "")).strip() in ("是", "有"):
        chips.append('<span class="chip code">开源</span>')
    if str(card.get("applied", "")).strip() == "是":
        chips.append('<span class="chip applied">应用</span>')
    return '<span class="chips">{}</span>'.format("".join(chips))


def _deep_card(paper: Dict[str, Any], rank: int) -> str:
    card = paper.get("card") or {}
    detail = paper.get("detail") or {}
    title_zh = card.get("title_zh") or paper.get("title", "")
    one_liner = str(card.get("one_liner") or "").strip()
    if not one_liner:
        parts = detail.get("plain_summary") or []
        one_liner = (parts[0] if parts else paper.get("abstract", ""))[:160]
    paragraphs = detail.get("plain_summary") or [paper.get("abstract", "")]
    reliability = detail.get("reliability") or {}
    concepts = detail.get("concepts") or []
    quiz = detail.get("quiz") or []
    how_to_apply = detail.get("how_to_apply") or []
    authors = "、".join(paper.get("authors") or [])[:200]
    sections = ['<section class="section"><h4>这篇论文讲了什么</h4>']
    sections += ["<p>{}</p>".format(esc(p)) for p in paragraphs]
    sections.append("</section>")
    if detail.get("life_example"):
        sections.append('<section class="section"><h4>先用生活中的例子理解</h4>'
                        '<p class="callout">{}</p></section>'.format(esc(detail["life_example"])))
    sections.append('<section class="section"><h4>它和你有什么关系</h4>'
                    '<div class="grid2"><div><b>对普通生活</b>{}</div><div><b>对你的工作</b>{}</div></div></section>'
                    .format(esc(detail.get("life_meaning") or "暂无直接意义。"),
                            esc(detail.get("work_meaning") or "暂无明确判断。")))
    if how_to_apply:
        sections.append('<section class="section"><h4>你可以怎么用</h4><ul>{}'
                        "</ul></section>".format("".join("<li>{}</li>".format(esc(x)) for x in how_to_apply)))
    sections.append(
        '<section class="section"><h4>这篇论文靠谱吗</h4><div class="reliability">'
        '<div><b>审核状态</b>{}</div><div><b>论文证据</b>{}</div><div><b>保留怀疑</b>{}</div></div></section>'
        .format(esc(reliability.get("review_status") or "预印本，未确认同行评审"),
                esc(reliability.get("evidence") or "未确认"),
                esc(reliability.get("caution") or "不要把单篇预印本当成定论。")))
    if concepts:
        sections.append('<section class="section"><h4>需要知道的几个词</h4>{}</section>'.format(
            "".join('<div class="concept"><b>{}</b>：{}</div>'.format(esc(c["name"]), esc(c["explanation"]))
                    for c in concepts)))
    if quiz:
        quiz_html = []
        for i, q in enumerate(quiz):
            quiz_html.append(
                "<details class=\"quiz\"><summary>{}. {}</summary>"
                "<p>提示：{}<br>参考答案：{}</p></details>".format(
                    i + 1, esc(q.get("question", "")), esc(q.get("hint") or "先用自己的话回答"),
                    esc(q.get("answer") or "")))
        sections.append('<section class="section"><h4>看看你是否真的理解了</h4>{}</section>'.format("".join(quiz_html)))
    summary = (
        '<summary><span class="rank">{:02d}</span>'
        '<span class="d-head"><span class="d-title">{}</span>'
        '<span class="d-sub">{}</span></span>'
        '<span class="d-one">{}</span>'
        '<span class="d-meta">{}<span class="tg">'
        '<span class="tg-open">展开 ▾</span><span class="tg-close">收起 ▴</span>'
        '</span></span></summary>'
    ).format(rank, esc(title_zh),
             esc("{} · {}".format(authors or "作者信息缺失",
                                  str(paper.get("published_at") or "")[:10])),
             esc(one_liner), _summary_chips(paper))
    return (
        '<details class="paper deep">{}'
        '<div class="d-body"><p class="orig">{} · {} · 依据：{}</p>'
        '{}{}<div class="section"><a class="ext" href="{}" target="_blank" '
        'rel="noopener">打开原论文 ↗</a></div></div></details>'
        .format(summary, esc(authors), esc(paper.get("published_at") or ""),
                esc(detail.get("basis") or "摘要"), _badges(paper), "".join(sections),
                esc(_safe_url(paper.get("abs_url"))))
    )


def _list_card(paper: Dict[str, Any]) -> str:
    card = paper.get("card") or {}
    title_zh = card.get("title_zh") or paper.get("title", "")
    one_liner = card.get("one_liner") or paper.get("abstract", "")[:220]
    return (
        '<article class="paper"><h3>{}</h3><p class="orig">{}</p>'
        '<p class="one-liner">{}</p>{}<div><a class="ext" href="{}" target="_blank" '
        'rel="noopener">打开原论文 ↗</a></div></article>'
        .format(esc(title_zh), esc(paper.get("title", "")), esc(one_liner),
                _badges(paper), esc(_safe_url(paper.get("abs_url"))))
    )


def build_report(site_name: str, label: str, deep_papers: List[Dict[str, Any]],
                 card_papers: List[Dict[str, Any]], stats: Dict[str, Any],
                 config: Dict[str, Any]) -> str:
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")
    # 精读论文通常是卡片子集，取并集避免重复计数。
    unique = len({str(p["arxiv_id"]) for p in card_papers}
                 | {str(p["arxiv_id"]) for p in deep_papers})
    stat_items = [
        ("{}".format(unique), "本周入选论文"),
        ("{}".format(len(deep_papers)), "AI 精读"),
        ("{:,}".format(int(stats.get("llm_tokens_this_week") or 0)), "本周 LLM tokens"),
        ("{:,}".format(int(stats.get("llm_budget_remaining") or 0)), "剩余 token 预算"),
    ]
    stats_html = "".join(
        '<div class="stat"><b>{}</b><span>{}</span></div>'.format(esc(v), esc(label_))
        for v, label_ in stat_items)
    deep_html = "".join(_deep_card(p, i) for i, p in enumerate(deep_papers, 1)) if deep_papers else \
        '<p class="sec-note">本周暂无 AI 精读内容。</p>'
    # 精读过的论文不再出现在下方列表里
    deep_ids = {str(p["arxiv_id"]) for p in deep_papers}
    list_html = "".join(_list_card(p) for p in card_papers if str(p["arxiv_id"]) not in deep_ids)
    if not list_html:
        list_html = '<p class="sec-note">暂无其余论文卡片。</p>'
    whitelist = config.get("reliability", {}).get("institution_whitelist", [])
    core = config.get("keywords", {}).get("core", [])
    return """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="icon" href="{}">
<title>{} · {}</title>
<style>{}</style>
</head>
<body>
<div class="wrap">
<header class="hero">
  <div class="brand">
    <span class="logo" aria-hidden="true">{}</span>
    <div class="brand-text">
      <p class="kicker">KNOWLEDGE GRAPH WEEKLY</p>
      <h1>{}</h1>
      <p class="sub">统计周期：{} · 生成时间：{}</p>
    </div>
  </div>
  <div class="stats">{}</div>
</header>

<h2 class="sec">本周精读</h2>
<p class="sec-note">按综合评分排序的 Top {} 篇：先看一句话摘要，点击任意一篇展开完整解读（白话总结 / 生活类比 / 工作意义 / 靠谱度 / 术语 / 自测题）。</p>
{}

<h2 class="sec">其余论文卡片</h2>
<p class="sec-note">按综合评分排序，卡片由 AI 依据标题与摘要生成。</p>
<div class="paper-list">{}</div>

<footer>
<p>方法论：每周一次查询 arXiv（{} 等分类，近 {} 天），本地按核心关键词（{}）与命中数量加成排序，
再叠加应用型、代码/开源信号加分；通过 OpenAlex 补充引用数与作者机构，按机构白名单、作者历史影响力与引用数计算靠谱度；
综合评分 = 相关性 × 0.7 + 靠谱度 × 0.3。卡片与精读由 {} 生成。</p>
<p>可信机构白名单：{}</p>
<ul>
<li>arXiv 页面代表预印本公开，不等于已经同行评审；有 venue 信息也不代表经过同行评审。</li>
<li>AI 内容仅依据给定材料总结，可能存在错误，重要结论请核对原文。</li>
<li>新发表的论文引用数普遍偏低，靠谱度主要由机构与作者历史影响力决定。</li>
</ul>
</footer>
</div>
</body>
</html>
""".format(_FAVICON, esc(site_name), esc(label), _STYLE, _LOGO_SVG, esc(site_name),
           esc(label), esc(generated), stats_html, len(deep_papers), deep_html, list_html,
           esc("、".join(config.get("discovery", {}).get("categories", []))),
           int(config.get("site", {}).get("week_window_days", 7)),
           esc("、".join(core)),
           esc(str(config.get("llm", {}).get("model", "deepseek-flash"))),
           esc("、".join(whitelist)))
