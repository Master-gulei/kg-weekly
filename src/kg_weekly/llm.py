from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from .db import Database

CARD_SYSTEM = """你是一个严格、节制的中文论文筛选编辑。读者是«READER_CARD»。
你会收到若干篇论文的本地元信息（标题与摘要），不读取或假装读过全文。逐篇生成简短中文筛选卡，忠实说明论文内容；与读者方向没有关系时直说，不要硬凑。
只输出严格 JSON 对象，不要 Markdown，格式为：
{"papers":[{"arxiv_id":"原样返回","title_zh":"准确中文标题","one_liner":"一句话说明论文做了什么","why_related":"与«DIRECTION»方向的真实关系","applied":"应用型判断：是/否/不确定","code_available":"是否有代码、伪代码或开源实现线索：是/否/不确定","worth":"A|B|C","basis":"仅依据标题和摘要"}]}
必须返回输入中的每一个 arxiv_id，且不得添加不存在的 ID。"""

DETAIL_SYSTEM = """你是耐心、诚实的中文论文老师。读者是«READER_DETAIL»，但对论文主题按小白处理。
目标是让他真正知道论文讲了什么、与生活或工作有什么关系，而不是复述学术术语。
只依据提供的论文内容；不确定就说不确定。arXiv 默认是预印本，除非元信息明确给出期刊信息，否则不要声称经过同行评审。
只输出严格 JSON，不要 Markdown：
{
  "plain_summary": ["3到5段短说明，每段只讲一个意思"],
  "life_example": "一个生活化类比",
  "life_meaning": "对普通生活的意义；没有直接意义要明说",
  "work_meaning": "对«WORK_AREA»工作的意义",
  "how_to_apply": ["0到3条现实可行的应用；不适合应用就给空数组"],
  "reliability": {
    "review_status": "是否能确认经过同行评审",
    "evidence": "论文用了什么证据",
    "caution": "最需要保留的怀疑"
  },
  "concepts": [{"name":"术语", "explanation":"一句白话解释"}],
  "quiz": [
    {"question":"理解题", "hint":"提示", "answer":"参考答案"},
    {"question":"应用题", "hint":"提示", "answer":"参考答案"}
  ],
  "basis": "摘要|HTML全文"
}
禁止在 JSON 字符串内使用英文双引号。"""


def _topic_prompts(config: Dict[str, Any]) -> Tuple[str, str]:
    """按入口关键词生成卡片/精读提示词；默认 kg 与历史措辞完全一致。"""
    topic = str(config.get("_topic") or "kg").strip() or "kg"
    if topic.lower() == "kg":
        reader_card = "知识图谱/图算法工程师，关注知识图谱、图神经网络、图数据库、RAG、AI Agent、Skill 等方向"
        direction = "知识图谱/图/AI/Agent/Skill"
        reader_detail = "知识图谱/图算法工程师（做图谱检索、图数据库、RAG 与 AI Agent 方向）"
        work_area = "知识图谱、图数据库、RAG 或 AI Agent"
    else:
        reader_card = "关注「{}」方向的工程师，需要筛出与该方向最相关的论文".format(topic)
        direction = "「{}」".format(topic)
        reader_detail = "关注「{}」方向的工程师".format(topic)
        work_area = "「{}」".format(topic)
    card = CARD_SYSTEM.replace("«READER_CARD»", reader_card).replace("«DIRECTION»", direction)
    detail = DETAIL_SYSTEM.replace("«READER_DETAIL»", reader_detail).replace("«WORK_AREA»", work_area)
    return card, detail


class LLMUnavailable(RuntimeError):
    pass


class LLMCallFailed(RuntimeError):
    pass


class BudgetExceeded(RuntimeError):
    pass


# 卡片字段的合法取值，用于收敛模型输出的异常内容。
ALLOWED_YES_NO = ("是", "否", "不确定")
ALLOWED_WORTH = ("A", "B", "C")


def _clean_text(value: Any, limit: int) -> str:
    """去掉控制字符并截断，防止异常内容进入卡片与报告。"""
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", str(value or ""))
    return text.strip()[:limit]


def _normalize_detail(value: Dict[str, Any]) -> Dict[str, Any]:
    """规范模型输出的精读：过滤控制字符、截断长度、收敛结构。

    模型可能返回畸形结构（如 quiz 里是字符串而非对象），直接入库会在渲染时报错；
    这里把每个字段收敛到渲染器期望的形状，无效条目直接丢弃。
    """

    def _list_of_str(x: Any, limit: int) -> List[str]:
        if not isinstance(x, list):
            return []
        return [_clean_text(v, limit) for v in x if isinstance(v, (str, int, float))]

    def _list_of_dict(x: Any, fields: Tuple[str, ...], limit: int) -> List[Dict[str, str]]:
        out: List[Dict[str, str]] = []
        if isinstance(x, list):
            for item in x:
                if isinstance(item, dict):
                    out.append({f: _clean_text(item.get(f), limit) for f in fields})
        return out

    reliability = value.get("reliability")
    reliability = reliability if isinstance(reliability, dict) else {}
    return {
        "plain_summary": _list_of_str(value.get("plain_summary"), 800),
        "life_example": _clean_text(value.get("life_example"), 400),
        "life_meaning": _clean_text(value.get("life_meaning"), 400),
        "work_meaning": _clean_text(value.get("work_meaning"), 400),
        "how_to_apply": _list_of_str(value.get("how_to_apply"), 400),
        "reliability": {
            "review_status": _clean_text(reliability.get("review_status"), 200),
            "evidence": _clean_text(reliability.get("evidence"), 300),
            "caution": _clean_text(reliability.get("caution"), 300),
        },
        "concepts": _list_of_dict(value.get("concepts"), ("name", "explanation"), 200),
        "quiz": _list_of_dict(value.get("quiz"), ("question", "hint", "answer"), 300),
        "basis": _clean_text(value.get("basis"), 40),
        "model": _clean_text(value.get("model"), 40),
    }


def _extract_json(text: str) -> Dict[str, Any]:
    match = re.search(r"\{.*\}", text.strip(), re.S)
    if not match:
        raise LLMCallFailed("模型响应中没有 JSON")
    return json.loads(match.group(0))


def _paper_material(paper: Dict[str, Any]) -> str:
    return "\n".join([
        "标题：{}".format(paper.get("title", "")),
        "作者：{}".format("、".join(paper.get("authors", []))),
        "分类：{}".format("、".join(paper.get("categories", []))),
        "期刊信息：{}".format(paper.get("journal_ref") or "未提供"),
        "摘要：{}".format(paper.get("abstract", "")),
    ])


class LLMClient:
    """OpenAI 兼容接口的 LLM 客户端，默认 DeepSeek（deepseek-flash，关闭思考模式）。

    账号优先级：provider_accounts 表中的可用账号 > config/env 的默认账号。
    每次调用记录真实 usage，周预算触顶即抛 BudgetExceeded。
    """

    def __init__(self, db: Database, config: Dict[str, Any]):
        self.db = db
        self.config = config
        self.card_system, self.detail_system = _topic_prompts(config)
        llm = config.get("llm") or {}
        self.provider = str(llm.get("provider", "deepseek")).lower()
        self.base_url = str(llm.get("base_url", "https://api.deepseek.com")).rstrip("/")
        self.model = str(llm.get("model", "deepseek-flash"))
        env_name = str(llm.get("api_key_env", "DEEPSEEK_API_KEY"))
        self.api_key = str(llm.get("api_key", "")).strip() or os.environ.get(env_name, "")
        self.timeout = int(llm.get("timeout_seconds", 600))
        self.thinking_disabled = bool(llm.get("thinking_disabled", True))
        self.budget = int(llm.get("weekly_token_budget", 1000000))
        self.failure_cooldown_seconds = 300

    # ---------- 账号与预算 ----------

    def _pick_account(self) -> Optional[Dict[str, Any]]:
        self.db.reset_due_provider_quotas()
        now = int(time.time())
        eligible = []
        for account in self.db.provider_accounts(include_credentials=True):
            if not account.get("enabled"):
                continue
            if int(account.get("cooldown_until") or 0) > now:
                continue
            total = account.get("quota_total")
            if total is not None and float(total) - float(account.get("quota_used") or 0) <= 0:
                continue
            eligible.append(account)
        if eligible:
            return eligible[0]
        if self.api_key:
            return None  # 使用 config/env 默认账号
        raise LLMUnavailable(
            "没有可用的 AI 账号；请配置 llm.api_key 或设置环境变量 {}".format(
                self.config.get("llm", {}).get("api_key_env", "DEEPSEEK_API_KEY"))
        )

    def _check_budget(self) -> None:
        used = self.db.llm_usage_this_week()
        if used >= self.budget:
            raise BudgetExceeded(
                "本周 LLM 用量已达预算上限（{:,}/{:,} tokens）；可运行 reset-budget 重置后继续"
                .format(used, self.budget)
            )

    # ---------- 底层调用 ----------

    def chat(self, system: str, prompt: str, task_type: str) -> str:
        self._check_budget()
        account = self._pick_account()
        if account is not None:
            credentials = account.get("credentials") or {}
            provider = str(account.get("provider", "")).lower()
            api_key = str(credentials.get("api_key", "")).strip()
            base_url = str(credentials.get("base_url", self.base_url)).rstrip("/")
            model = str(credentials.get("model", self.model))
            account_id: Optional[int] = int(account["id"])
            label = "{}:{}".format(account.get("provider"), account.get("account_name"))
        else:
            provider, api_key, base_url, model = self.provider, self.api_key, self.base_url, self.model
            account_id, label = None, "default"
        if provider == "mock":
            return self._mock_chat(task_type, prompt)
        if not api_key:
            raise LLMUnavailable("账号缺少 api_key 凭据")
        body: Dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "response_format": {"type": "json_object"},
            "stream": False,
        }
        if self.thinking_disabled and provider == "deepseek":
            # DeepSeek V4.x 默认开启思考模式（effort=high），必须显式关闭以控制成本。
            # 该字段是 DeepSeek 专有参数，其他 OpenAI 兼容服务可能拒绝，因此按 provider 判断。
            body["thinking"] = {"type": "disabled"}
        request = urllib.request.Request(
            base_url + "/chat/completions",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": "Bearer " + api_key,
                "Content-Type": "application/json",
                "User-Agent": "kg-weekly/0.1",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                value = json.loads(response.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as exc:
            message = "HTTP {}: {}".format(exc.code, exc.read().decode("utf-8", errors="replace")[:300])
            cooldown = 3600 if exc.code in (429, 402) or "limit" in message.lower() else self.failure_cooldown_seconds
            self.db.record_provider_result(account_id, label, task_type, 0, False, message, cooldown)
            raise LLMCallFailed(message)
        except urllib.error.URLError as exc:
            message = "网络错误：{}".format(exc.reason)
            self.db.record_provider_result(account_id, label, task_type, 0, False, message)
            raise LLMCallFailed(message)
        output = str(value.get("choices", [{}])[0].get("message", {}).get("content", ""))
        if not output:
            message = "模型返回了空内容"
            self.db.record_provider_result(account_id, label, task_type, 0, False, message)
            raise LLMCallFailed(message)
        usage = value.get("usage") or {}
        units = int(usage.get("prompt_tokens") or 0) + int(usage.get("completion_tokens") or 0)
        if units == 0:
            units = int(len(system + prompt) * 0.3 + len(output) * 0.6)  # 本地估算兜底
        self.db.record_provider_result(account_id, label, task_type, units, True)
        return output

    @staticmethod
    def _mock_chat(task_type: str, prompt: str) -> str:
        """测试用 mock：cards 按输入 ID 回显模板卡，detail 返回固定结构。"""
        if task_type == "cards":
            ids = re.findall(r"arxiv_id：(\S+)", prompt)
            cards = [{
                "arxiv_id": i, "title_zh": "中文标题({})".format(i),
                "one_liner": "一句话摘要({})".format(i),
                "why_related": "与知识图谱方向相关", "applied": "否",
                "code_available": "否", "worth": "B", "basis": "仅依据标题和摘要",
            } for i in ids]
            return json.dumps({"papers": cards}, ensure_ascii=False)
        return json.dumps({
            "plain_summary": ["一段白话总结", "第二段说明"],
            "life_example": "生活化类比",
            "life_meaning": "对普通生活意义有限",
            "work_meaning": "对知识图谱工程有参考价值",
            "how_to_apply": ["可以作为检索模块的基线"],
            "reliability": {"review_status": "预印本，未确认同行评审", "evidence": "实验与消融", "caution": "数据规模有限"},
            "concepts": [{"name": "知识图谱嵌入", "explanation": "把实体和关系变成向量"}],
            "quiz": [
                {"question": "这篇论文核心思路是什么？", "hint": "一句话", "answer": "参考答案"},
                {"question": "如何应用？", "hint": "结合工作", "answer": "参考答案"},
            ],
            "basis": "HTML全文",
        }, ensure_ascii=False)

    # ---------- 业务方法 ----------

    def batch_cards(self, papers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not papers:
            return []
        materials = []
        expected = []
        for paper in papers:
            arxiv_id = str(paper.get("arxiv_id", ""))
            expected.append(arxiv_id)
            materials.append("\n".join([
                "arxiv_id：{}".format(arxiv_id),
                _paper_material(paper),
            ]))
        prompt = self.card_system + "\n\n=== 论文（共 {} 篇）===\n".format(len(papers))
        prompt += "\n\n---\n\n".join(materials)
        output = self.chat(self.card_system, prompt, "cards")
        value = _extract_json(output)
        raw_cards = value.get("papers")
        if not isinstance(raw_cards, list):
            raise LLMCallFailed("模型响应缺少 papers 数组")
        cards_by_id = {
            str(card.get("arxiv_id")): card for card in raw_cards if isinstance(card, dict)
        }
        if set(cards_by_id) != set(expected):
            missing = sorted(set(expected) - set(cards_by_id))
            extra = sorted(set(cards_by_id) - set(expected))
            raise LLMCallFailed("模型返回的论文 ID 不完整；缺少={}，多出={}".format(missing, extra))
        result = []
        for arxiv_id in expected:
            card = dict(cards_by_id[arxiv_id])
            card.pop("arxiv_id", None)
            result.append(self._normalize_card(card))
        return result

    def _normalize_card(self, card: Dict[str, Any]) -> Dict[str, Any]:
        """规范模型输出的卡片：过滤控制字符、截断长度、枚举值收敛。"""
        applied = str(card.get("applied", "")).strip()
        code_available = str(card.get("code_available", "")).strip()
        worth = str(card.get("worth", "")).strip().upper()
        if applied not in ALLOWED_YES_NO:
            applied = "不确定"
        if code_available not in ALLOWED_YES_NO:
            code_available = "不确定"
        if worth not in ALLOWED_WORTH:
            worth = "B"
        return {
            "title_zh": _clean_text(card.get("title_zh"), 120),
            "one_liner": _clean_text(card.get("one_liner"), 200),
            "why_related": _clean_text(card.get("why_related"), 300),
            "applied": applied,
            "code_available": code_available,
            "worth": worth,
            "basis": "仅依据标题和摘要",
            "model": self.model,
        }

    def deep_read(self, paper: Dict[str, Any], full_text: str, source: str) -> Dict[str, Any]:
        max_chars = int(self.config.get("pipeline", {}).get("fulltext_max_characters", 40000))
        material = _paper_material(paper)
        if full_text:
            material += "\n\n=== {} ===\n{}".format(source, full_text[:max_chars])
        prompt = self.detail_system + "\n\n=== 材料 ===\n" + material
        output = self.chat(self.detail_system, prompt, "deep_read")
        value = _extract_json(output)
        value["model"] = self.model
        value["basis"] = source
        return _normalize_detail(value)
