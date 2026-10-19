# KG 每周前沿（kg-weekly）

一个在 Windows 本地运行的小工具：每周一次，从 arXiv 抓取知识图谱方向的**近 7 天新论文**，用本地规则选出靠谱的文章（知名机构、作者历史影响力、引用数），再让 **deepseek-flash** 把它们变成「能听懂的中文知识」，最后生成一份**单文件静态 HTML 周报**。没有 Web 服务器、没有数据库后台、不需要任何第三方 Python 依赖（纯标准库）。

## 快速开始

环境要求：Windows + Python 3.9+（`python` 命令可用即可）。

1. 设置 DeepSeek API Key（二选一）：

   - 推荐：写入 `local_config.json`（本机私有、已被 .gitignore 忽略，不会进仓库）：

     ```json
     {"llm": {"api_key": "sk-xxxxxxxx"}}
     ```

   - 或设置环境变量：`set DEEPSEEK_API_KEY=sk-xxxxxxxx`

2. 先校验配置（不访问网络、不花钱）：

   ```bat
   run.bat run --dry-run
   ```

3. 跑完整周流水线：

   ```bat
   run.bat run
   ```

4. 打开周报：`out\KG-每周前沿-YYYY-MM-DD.html`

   周报包含：Top 12 AI 精读（白话解读、生活类比、工作意义、靠谱度判断、术语、测验）+ 其余论文的中文卡片 + 可靠度徽章（机构 / 引用 / 评分 / 代码 / 应用型）+ 方法论说明与免责脚注。

## 命令一览

| 命令 | 作用 |
| --- | --- |
| `run.bat run` | 完整周流水线：抓取 arXiv → OpenAlex 增强 → 评分 → 中文卡片 → AI 精读 → 生成 HTML。每一步幂等可重入，中断后重跑会自动跳过已完成部分 |
| `run.bat run --force` | 忽略「本周已抓取」标记，强制重新抓取 |
| `run.bat run --dry-run` | 只校验配置并输出状态，不触网 |
| `run.bat report` | 用已有数据重新生成 HTML，不访问网络 |
| `run.bat status` | 论文数 / LLM 本周用量 / 请求预算 / 访问状态 |
| `run.bat reset-budget` | 手动重置周 token 预算计数 |
| `run.bat enable-access --confirm` | 人工确认熔断原因后重新开启网络访问 |

### 关键词入口（--topic）

默认入口是知识图谱（kg）。想按其他关键词爬取、解读，在 `run` / `report` / `status` / `reset-budget` 上加 `--topic`：

```bat
run.bat run --topic llm        rem 换成 llm 关键词：按 [llm] 爬取 arXiv、评分、AI 解读，输出 LLM-每周前沿-YYYY-MM-DD.html
run.bat report --topic llm     rem 用已有数据重新生成 llm 入口的周报
run.bat status --topic llm     rem 查看 llm 入口的状态
```

- 自定义入口的搜索短语与核心评分关键词都换成输入的关键词；标题自动变为「LLM 每周前沿」
- 每个入口使用**独立数据库** `data\papers-<关键词>.db`（默认入口仍是 `papers.db`），抓取周标记、周 token 预算彼此独立、互不干扰
- AI 卡片与精读的提示词也会按关键词调整（如“与「llm」方向的关系”）
- 提示：arXiv 论文元数据是英文，关键词建议用英文（如 `llm`、`rag`、`multimodal`、`temporal knowledge graph`）

## 每周流水线做了什么

1. **抓取**：一次 arXiv API 查询（cs.AI / cs.CL / cs.DB / cs.IR / cs.LG / cs.SI 分类 + 11 个 KG 相关短语 + 近 7 天 submittedDate 窗口），返回 0 条会报错而不是假成功。
2. **OpenAlex 增强**：只对相关度达标的论文（最多 150 篇）按 DOI 批量查引用数、venue、作者机构、作者历史影响力（免费 API，无需 key；单个批次失败不影响主流程）。
3. **评分**：总分 = 相关性 × 0.7 + 靠谱度 × 0.3。
   - **相关性**：核心关键词（kg / knowledge graph / ai / agent / skill，大小写不敏感、自动匹配复数）每命中一个 +3，标题命中再 +2，命中种类越多有额外加成；应用型信号词 +4；标题/摘要/arxiv comment 里有代码、伪代码、开源、GitHub 线索 +5。
   - **靠谱度**：机构白名单（Google、DeepMind、Meta、清华、北大、阿里、腾讯等 28 个）+ 作者累计被引（对数缩放、封顶）+ 引用数分层 + venue 信息。
4. **中文卡片**：deepseek-flash 批量生成（20 篇/批，严格 JSON + arXiv ID 完整性校验），最多 Top 50 篇。
5. **AI 精读**：对 Top 12 拉取 HTML 全文并缓存，生成白话总结 / 生活类比 / 生活与工作意义 / 靠谱度 / 术语 / 自测题。
6. **周报**：生成单文件 HTML（内联 CSS，无外部资源）。

## 成本控制（重要）

| 项目 | 说明 |
| --- | --- |
| 模型 | `deepseek-flash`（DeepSeek V4.1-Flash） |
| 思考模式 | **已强制关闭**（`thinking: {"type": "disabled"}`）。V4.1 默认开启思考模式且 effort=high，不关会成倍烧 token，这是成本硬前提 |
| 周预算 | 默认 100 万 tokens（`config.json → llm.weekly_token_budget`），每次调用前检查累计用量，触顶自动停止 |
| 用量估算 | 实测完整一周约 5–6 万 tokens（50 卡片 + 12 精读规模）：高峰价约 ¥0.15/周、¥0.6/月；空闲价约 ¥0.08/周、¥0.3/月 |
| 建议 | **在夜间或周末运行**享受空闲半价；`status` 随时查看本周用量 |

deepseek-flash 官方价（2026-10）：输入 ¥2/百万（高峰）、¥1/百万（空闲）；输出 ¥8/百万（高峰）、¥4/百万（空闲）；缓存命中输入仅 ¥0.02–0.04/百万。

## 项目结构

```
kg-weekly/
├── run.bat                  # Windows 入口（设置 PYTHONPATH 后调用 kg_weekly.cli）
├── config.json              # 分类/短语/关键词/白名单/预算/LLM 全部配置
├── README.md / DESIGN.md    # 使用文档与设计说明
├── src/kg_weekly/
│   ├── cli.py               # 命令行入口（run/report/status/reset-budget/enable-access）
│   ├── config.py            # 配置加载与校验（含 --topic 入口、local_config.json 合并）
│   ├── db.py                # SQLite schema 与查询（论文/用量/审计/周标记/熔断）
│   ├── fetch.py             # 跨平台文件锁 + 白名单 + 周请求预算 + 熔断 + 审计
│   ├── arxiv.py             # arXiv API 查询 URL 构造 + Atom 解析（含 comment 字段）
│   ├── openalex.py          # OpenAlex 批量查询（引用/机构/venue/作者影响力）
│   ├── ranking.py           # 相关性/靠谱度评分
│   ├── llm.py               # OpenAI 兼容 LLM 客户端（deepseek-flash，关思考模式）
│   ├── pipeline.py          # 六步周流水线编排（幂等可重入）
│   └── report.py            # 单文件 HTML 周报生成（折叠精读、内联 SVG 图标）
└── 仅本地目录（已被 .gitignore 排除，不入仓库）：
    ├── tests/               # 87 个离线测试（mock，不触网）
    ├── data/                # SQLite 数据库、缓存、锁
    ├── out/                 # 周报输出目录
    └── local_config.json    # 本机私有配置（API Key）
```

## 配置要点（config.json）

- `discovery.categories / search_phrases`：抓取范围，可自行增删 KG 相关短语
- `keywords.core / applied_signals / code_signals`：评分信号词
- `reliability.institution_whitelist`：可信机构白名单
- `llm`：模型、地址、Key、周预算；兼容 OpenAI 格式接口（DeepSeek / 通义 / Kimi 等）。注意 `thinking`（关思考模式）是 DeepSeek 专有字段，换其他服务时请把 `thinking_disabled` 设为 `false`
- `pipeline.top_cards / top_deep`：卡片数量（默认 50）与精读数量（默认 12）
- `local_config.json`（可选，本机私有、已被 .gitignore 忽略）：覆盖 `config.json` 的字段，用于存放 `llm.api_key` 等敏感值，避免把 Key 写进仓库或命令行历史

## 安全与克制设计

- 只允许访问白名单域名（arxiv.org、export.arxiv.org、api.openalex.org），且拒绝跟随重定向（白名单只校验初始 URL，跟随会绕过校验）
- 响应体上限 20 MB，异常上游无法耗尽内存
- 周请求预算（自动 30 次 / 用户 12 次）与最小间隔（默认 10 秒，arXiv 要求 ≥3 秒）
- 内容类型异常或 403/429 自动熔断，人工确认后 `enable-access --confirm` 恢复
- 跨进程文件锁（Windows `msvcrt.locking` / POSIX `fcntl.flock`）
- 删除 AI 账号不丢历史用量审计（provider_usage 保留账号名）
- 每周 LLM 预算自动按自然周重置（跨周自动前滚，无需手动 reset-budget）
- LLM 卡片与精读输出经字段收敛（控制字符过滤、长度截断、枚举校验、结构规范化）

注意事项：

- **单实例运行**：不要同时开两个 `run`，并发进程可能重复花费 LLM 预算（文件锁只串行化网络请求）
- `provider_accounts` 表里的 api_key 明文存于本地 SQLite，介意的话请优先用环境变量（`DEEPSEEK_API_KEY`）
- arXiv 单次查询上限 300 条（`discovery.max_results_per_query`），极端活跃周可能截断最旧的论文

## 运行测试

测试代码仅保留在作者本地（仓库只包含核心源码，`tests/` 已被 .gitignore 排除）：

```bat
python -m unittest discover -s tests -v
```

87 个测试全部离线（mock 网络与 LLM），覆盖 Atom 解析（含 UTF-16 拒绝）、配置校验（含档位乱序/非整数）、数据库（含周预算自动前滚与跨入口请求间隔）、跨平台锁、评分公式（含机构词边界）、LLM 适配器（含「思考模式已关闭」断言与卡片/精读字段收敛）、OpenAlex 解析、周报 HTML 结构（含去重统计）、CLI 命令与完整流水线。

## 常见问题

- **`LLMUnavailable`**：没配 API Key。写入 `local_config.json` 的 `llm.api_key`（推荐，本机私有不落库），或设置 `DEEPSEEK_API_KEY` 环境变量。
- **`BudgetExceeded`**：本周 token 预算用完，`run.bat reset-budget` 可重置；或调大 `llm.weekly_token_budget`。
- **`AccessPaused`**：网络访问被熔断（异常内容类型或 403/429），先检查原因再 `run.bat enable-access --confirm`。
- **`arXiv 返回 0 条结果`**：查询异常（如短语语法问题），检查 `discovery.search_phrases`。
- **新论文引用数很低**：正常现象。刚发布一周的论文普遍 0 引用，此时靠谱度主要由机构白名单与作者历史影响力决定，周报脚注里有同样说明。

## 免责声明

arXiv 页面代表预印本公开，不等于已经同行评审；AI 内容仅依据给定材料总结，可能存在错误，重要结论请核对原文。
