# 🧠 KG前沿论文解读（kg-weekly）

> 一个在 Windows 本地运行的小工具：每周一次，从 arXiv 抓取指定方向的**近 7 天新论文**
> （默认知识图谱方向，可换成任意关键词），用本地规则选出靠谱的文章（知名机构、作者历史
> 影响力、引用数），再让 **deepseek-flash** 把它们变成「能听懂的中文知识」，最后生成一份
> **单文件静态 HTML 周报**。没有数据库后台、不需要任何第三方 Python 依赖；可选本地服务
> （`run.bat serve`，仅 127.0.0.1）用于「AI 解读」按钮的按需精读。

**🪟 Windows 本地** · **🐍 纯 Python 标准库（零依赖）** · **📄 单文件 HTML 周报（内联 CSS/SVG 图标）** · **💸 周成本约 ¥0.15**

## ✨ 特性一览

| 特性 | 说明 |
| --- | --- |
| 🎯 任意方向追踪 | 默认知识图谱（KG），`--topic` 一键切换到 llm / rag / 多模态等任意领域；多方向并行、数据库与预算彼此独立 |
| 🏅 本地规则评分 | 总分 = 相关性 ×0.7 + 靠谱度 ×0.3（机构白名单、作者历史影响力、引用数分层） |
| 🤖 AI 中文解读 | Top 12 拉取全文精读：白话总结、生活类比、生活与工作意义、靠谱度、术语、自测题；多账号失败自动切换 |
| 🎖️ 可靠度徽章 | 每篇论文标注 机构 / 引用 / 评分 / 代码 / 应用型，一眼判断成色 |
| 📊 单文件周报 | 内联 CSS + SVG 图标，零外部资源，浏览器直接打开即可分享 |
| 🔍 按需精读 | 其余论文卡片带「AI 解读」按钮：本地起个服务，点击即生成与 Top 12 同款的深度解读，结果入库缓存 |
| 🛡️ 克制联网 | 域名白名单、周请求预算、最小间隔、熔断保护、跨平台文件锁 |

## 目录

- [🚀 快速开始](#🚀-快速开始)
- [📋 命令一览](#📋-命令一览)
- [🔄 每周流水线做了什么](#🔄-每周流水线做了什么)
- [💰 成本控制（重要）](#💰-成本控制)
- [📁 项目结构](#📁-项目结构)
- [⚙️ 配置要点（config.json）](#⚙️-配置要点)
- [🛡️ 安全与克制设计](#🛡️-安全与克制设计)
- [🧪 运行测试](#🧪-运行测试)
- [❓ 常见问题](#❓-常见问题)
- [⚠️ 免责声明](#⚠️-免责声明)

## 🚀 快速开始

环境要求：Windows + Python 3.9+（`python` 命令可用即可）。

1. 🔑 **设置 DeepSeek API Key**（二选一）：

   - 推荐：写入 `local_config.json`（本机私有、已被 .gitignore 忽略，不会进仓库）：

     ```json
     {"llm": {"api_key": "sk-xxxxxxxx"}}
     ```

   - 或设置环境变量：`set DEEPSEEK_API_KEY=sk-xxxxxxxx`

2. 🔍 **先校验配置**（不访问网络、不花钱）：

   ```bat
   run.bat run --dry-run
   ```

3. ▶️ **跑完整周流水线**：

   ```bat
   run.bat run
   ```

4. 📖 **打开周报**：`out\KG-前沿论文解读-YYYY-MM-DD.html`

   周报包含：Top 12 AI 精读（白话解读、生活类比、工作意义、靠谱度判断、术语、测验）+ 其余论文的中文卡片 + 可靠度徽章（机构 / 引用 / 评分 / 代码 / 应用型）+ 方法论说明与免责脚注。

5. 🔍 **按需精读（可选）**：其余论文卡片上有「AI 解读」按钮，点一下就能为任意一篇生成与 Top 12 同款的深度解读：

   ```bat
   serve.bat
   ```

   双击 `serve.bat`（或直接双击 `run.bat`——无参数时默认启动解读服务，等价命令 `run.bat serve`）会启动服务并自动用浏览器打开 `http://127.0.0.1:8000`，在页面里点「AI 解读」即可。服务只监听本机（不对外网开放），API Key 只留在本机进程，不会写入任何 HTML 文件。

   注意：必须通过 `http://127.0.0.1:8000` 打开周报，「AI 解读」按钮才可用——直接双击 `out\` 里的 HTML 文件（file://）时按钮会提示先启动服务。

## 📋 命令一览

| 命令 | 作用 |
| --- | --- |
| `run.bat run` | 完整周流水线：抓取 arXiv → OpenAlex 增强 → 评分 → 中文卡片 → AI 精读 → 生成 HTML。每一步幂等可重入，中断后重跑会自动跳过已完成部分 |
| `run.bat run --force` | 忽略「本周已抓取」标记，强制重新抓取 |
| `run.bat run --dry-run` | 只校验配置并输出状态，不触网 |
| `run.bat report` | 用已有数据重新生成 HTML，不访问网络 |
| `run.bat serve` | 本地起周报浏览 + 按需精读服务（仅监听 127.0.0.1），默认端口 8000；可 `--port` 换端口、`--topic` 指定入口 |
| 双击 `serve.bat` | 同 `run.bat serve`（固定 8000 端口与默认入口），并自动用浏览器打开 127.0.0.1:8000；自定义端口/入口请用命令行 `run.bat serve --port N --topic X`；服务异常退出时窗口会停住显示错误 |
| 双击 `run.bat`（无参数） | 同 `run.bat serve`（默认启动解读服务并自动开浏览器）；带子命令时行为不变（`run` / `status` / `prune` …） |
| `run.bat status` | 论文数 / LLM 本周用量 / 请求预算 / 访问状态 |
| `run.bat reset-budget` | 手动重置周 token 预算计数 |
| `run.bat prune --days 90` | 清理过期审计/用量/同步记录（默认保留 90 天；可加 `--topic` 清理指定入口） |
| `run.bat enable-access --confirm` | 人工确认熔断原因后重新开启网络访问 |

### 🔑 关键词入口（--topic）

默认入口是知识图谱（kg）。想按其他关键词爬取、解读，在 `run` / `report` / `serve` / `status` / `reset-budget` / `prune` / `enable-access` 上加 `--topic`：

```bat
run.bat run --topic llm        rem 换成 llm 关键词：按 [llm] 爬取 arXiv、评分、AI 解读，输出 LLM-前沿论文解读-YYYY-MM-DD.html
run.bat report --topic llm     rem 用已有数据重新生成 llm 入口的周报
run.bat serve --topic llm      rem 本地服务默认打开 llm 入口的最新周报
run.bat status --topic llm     rem 查看 llm 入口的状态
```

- 自定义入口的搜索短语与核心评分关键词都换成输入的关键词；标题自动变为「LLM 前沿论文解读」
- 每个入口使用**独立数据库** `data\papers-<关键词>.db`（默认入口仍是 `papers.db`），抓取周标记、周 token 预算彼此独立、互不干扰
- AI 卡片与精读的提示词也会按关键词调整（如“与「llm」方向的关系”）
- 提示：arXiv 论文元数据是英文，关键词建议用英文（如 `llm`、`rag`、`multimodal`、`temporal knowledge graph`）
- **换非 CS 领域要加 `--categories`**：默认抓取 6 个 `cs.*` 分类，追踪生物/物理等方向时用 `run.bat run --topic bio --categories q-bio.BM,q-bio.GN` 覆盖分类（会持久化到该入口，`default` 恢复配置默认；换分类后需 `--force` 重新抓取）

### 🌍 不止知识图谱：任何领域的前沿追踪

这条流水线本身不绑定知识图谱，`--topic` 是最快捷的切换方式，深度定制则改 `config.json`：

- **一键换领域**：`run.bat run --topic "large language model"` 会把抓取短语与核心评分关键词换成该方向，周报标题、独立数据库、LLM 提示词全部跟随，输出 `LARGE-LANGUAGE-MODEL-前沿论文解读-YYYY-MM-DD.html`。
- **多领域并行**：每个入口有独立的数据库与周 token 预算，每周可同时产出多个方向的周报，互不干扰（arXiv 礼貌间隔按所有入口共享）。
- **深度定制**：改 `config.json` 的 `discovery.categories` / `search_phrases`（抓取范围）、`keywords.core`（评分关键词）、`reliability.institution_whitelist`（靠谱机构），就能追踪任意 arXiv 领域——药物发现、自动驾驶、AI4Science……把机构白名单换成对应领域的顶级机构后评分更准。

## 🔄 每周流水线做了什么

0. 💾 **备份**：运行前把数据库快照到 `data\papers.db.bak`（SQLite 在线备份 API），失败不阻塞主流程。
1. 📡 **抓取**：一次 arXiv API 查询（cs.AI / cs.CL / cs.DB / cs.IR / cs.LG / cs.SI 分类 + 11 个 KG 相关短语 + 近 7 天 submittedDate 窗口），返回 0 条会报错而不是假成功。
2. 🔎 **OpenAlex 增强**：只对相关度达标的论文（最多 150 篇）按 DOI 批量查引用数、venue、作者机构、作者历史影响力（免费 API，无需 key；单个批次失败不影响主流程）。
3. 🏅 **评分**：总分 = 相关性 × 0.7 + 靠谱度 × 0.3。
   - **相关性**：核心关键词（kg / knowledge graph / ai / agent / skill，大小写不敏感、自动匹配复数）每命中一个 +3，标题命中再 +2，命中种类越多有额外加成；应用型信号词 +4；标题/摘要/arxiv comment 里有代码、伪代码、开源、GitHub 线索 +5。
   - **靠谱度**：机构白名单（Google、DeepMind、Meta、清华、北大、阿里、腾讯等 28 个）+ 作者累计被引（对数缩放、封顶）+ 引用数分层 + venue 信息。
4. 💬 **中文卡片**：deepseek-flash 批量生成（20 篇/批，严格 JSON + arXiv ID 完整性校验），最多 Top 50 篇。
5. 🧠 **AI 精读**：对 Top 12 拉取 HTML 全文并缓存，生成白话总结 / 生活类比 / 生活与工作意义 / 靠谱度 / 术语 / 自测题。
6. 📊 **周报**：生成单文件 HTML（内联 CSS，无外部资源；其余论文卡片带「AI 解读」按钮，配合 `run.bat serve` 可按需精读任意论文）。

## 💰 成本控制

| 项目 | 说明 |
| --- | --- |
| 模型 | `deepseek-flash`（DeepSeek V4.1-Flash） |
| 思考模式 | **已强制关闭**（`thinking: {"type": "disabled"}`）。V4.1 默认开启思考模式且 effort=high，不关会成倍烧 token，这是成本硬前提 |
| 周预算 | 默认 100 万 tokens（`config.json → llm.weekly_token_budget`），每次调用前检查累计用量，触顶自动停止 |
| 用量估算 | 实测完整一周约 5–6 万 tokens（50 卡片 + 12 精读规模）：高峰价约 ¥0.15/周、¥0.6/月；空闲价约 ¥0.08/周、¥0.3/月 |
| 建议 | **在夜间或周末运行**享受空闲半价；`status` 随时查看本周用量 |

deepseek-flash 官方价（2026-10）：输入 ¥2/百万（高峰）、¥1/百万（空闲）；输出 ¥8/百万（高峰）、¥4/百万（空闲）；缓存命中输入仅 ¥0.02–0.04/百万。

## 📁 项目结构

```
kg-weekly/
├── run.bat                  # Windows 入口（设置 PYTHONPATH 后调用 kg_weekly.cli；双击无参数时默认启动解读服务）
├── serve.bat                # 解读服务入口（双击启动 + 服务就绪后自动开浏览器）
├── config.json              # 分类/短语/关键词/白名单/预算/LLM 全部配置
├── README.md / DESIGN.md    # 使用文档与设计说明
├── src/kg_weekly/
│   ├── __init__.py          # 包信息（名称与版本）
│   ├── cli.py               # 命令行入口（run/report/serve/status/reset-budget/enable-access/prune）
│   ├── config.py            # 配置加载与校验（含 --topic/--categories 入口、local_config.json 合并）
│   ├── db.py                # SQLite schema 与查询（论文/用量/审计/周标记/熔断）
│   ├── fetch.py             # 跨平台文件锁 + 白名单 + 周请求预算 + 熔断 + 审计
│   ├── arxiv.py             # arXiv API 查询 URL 构造 + Atom 解析（含 comment 字段）+ HTML 全文提取
│   ├── openalex.py          # OpenAlex 批量查询（引用/机构/venue/作者影响力）
│   ├── ranking.py           # 相关性/靠谱度评分
│   ├── llm.py               # OpenAI 兼容 LLM 客户端（deepseek-flash，关思考模式，多账号故障转移）
│   ├── pipeline.py          # 六步周流水线编排（幂等可重入）
│   ├── report.py            # 单文件 HTML 周报生成（折叠精读、内联 SVG 图标、按需精读按钮）
│   └── server.py            # 本地周报浏览与按需精读服务（仅 127.0.0.1）
└── 仅本地目录（已被 .gitignore 排除，不入仓库）：
    ├── tests/               # 118 个离线测试（mock，不触网）
    ├── data/                # SQLite 数据库、自动备份（.bak）与锁
    ├── out/                 # 周报输出目录
    └── local_config.json    # 本机私有配置（API Key）
```

## ⚙️ 配置要点

- `safety.allowed_hosts / *_requests_per_week / minimum_request_interval_seconds`：域名白名单、周请求预算与最小间隔（克制联网的核心开关）
- `discovery.categories / search_phrases`：抓取范围，可自行增删 KG 相关短语
- `keywords.core / applied_signals / code_signals`：评分信号词
- `reliability.institution_whitelist`：可信机构白名单
- `llm`：模型、地址（须在 `allowed_hosts` 白名单内）、Key、周预算；兼容 OpenAI 格式接口（DeepSeek / 通义 / Kimi 等）。注意 `thinking`（关思考模式）是 DeepSeek 专有字段，换其他服务时请把 `thinking_disabled` 设为 `false`
- `pipeline.top_cards / top_deep`：卡片数量（默认 50）与精读数量（默认 12）
- `local_config.json`（可选，本机私有、已被 .gitignore 忽略）：覆盖 `config.json` 的字段，用于存放 `llm.api_key` 等敏感值，避免把 Key 写进仓库或命令行历史

## 🛡️ 安全与克制设计

- 只允许访问白名单域名（arxiv.org、export.arxiv.org、rss.arxiv.org、api.openalex.org），且拒绝跟随重定向（白名单只校验初始 URL，跟随会绕过校验）
- 响应体上限 20 MB，异常上游无法耗尽内存
- LLM 响应体上限 10 MB；`llm.base_url` 必须命中 `llm.allowed_hosts` 白名单（LLM 请求不走站点白名单通道，单独校验）
- 每次 `run` 前自动用 SQLite 在线备份 API 快照数据库到 `data\*.db.bak`，失败不阻塞主流程
- 周请求预算（自动 30 次 / 用户 12 次）与最小间隔（默认 10 秒，arXiv 要求 ≥3 秒）
- 内容类型异常或 403/429 自动熔断，人工确认后 `enable-access --confirm` 恢复
- 跨进程文件锁（Windows `msvcrt.locking` / POSIX `fcntl.flock`）
- 删除 AI 账号不丢历史用量审计（provider_usage 保留账号名）
- LLM 调用按优先级遍历可用账号，失败自动顺延到下一个并进入冷却（多账号故障转移）
- 每周 LLM 预算自动按自然周重置（跨周自动前滚，无需手动 reset-budget）
- LLM 卡片与精读输出经字段收敛（控制字符过滤、长度截断、枚举校验、结构规范化）
- 精读数量受 user 请求预算约束（`top_deep ≤ user_requests_per_week`，配置校验强制）
- `run.bat prune` 清理过期审计/用量/同步记录（默认保留 90 天），防止审计表无限增长
- 周报外链只允许 http/https 协议（防污染链接注入 `javascript:` 等）
- `run.bat serve` 只绑定 127.0.0.1（不监听外网）；静态文件解析拒绝路径穿越、只服务 out/ 下的 HTML；API 请求体上限 64 KB
- 按需精读复用流水线同一套保护（周 token 预算、user 请求预算、最小间隔、熔断），API Key 只留在本机进程，永不写入 HTML 文件

注意事项：

- ⚠️ **单实例运行**：不要同时开两个 `run`，并发进程可能重复花费 LLM 预算（文件锁只串行化网络请求）
- ⚠️ `provider_accounts` 表里的 api_key 明文存于本地 SQLite，介意的话请优先用环境变量（`DEEPSEEK_API_KEY`）
- ⚠️ arXiv 单次查询上限 300 条（`discovery.max_results_per_query`），极端活跃周可能截断最旧的论文

## 🧪 运行测试

测试代码仅保留在作者本地（仓库只包含核心源码，`tests/` 已被 .gitignore 排除）：

```bat
python -m unittest discover -s tests -v
```

118 个测试全部离线（mock 网络与 LLM），覆盖 Atom 解析（含 UTF-16 拒绝与未闭合 script 恢复）、配置校验（含档位乱序/非整数/精读超预算/LLM 地址白名单）、数据库（含周预算自动前滚、跨入口请求间隔、审计清理与在线备份）、跨平台锁、评分公式（含机构词边界）、LLM 适配器（含「思考模式已关闭」断言、卡片/精读字段收敛、多账号故障转移、尾部垃圾 JSON 容忍、响应体上限、地址白名单、提示词去重）、OpenAlex 解析、周报 HTML 结构（含去重统计、外链协议白名单与按需解读按钮）、CLI 命令（含 --categories 持久化、prune 与 serve --topic 透传）、本地服务（含路径穿越防护、按需精读 API、缓存复用、同篇并发去重与非法 Content-Length 拒绝）与完整流水线（含运行前自动备份）。

## ❓ 常见问题

- 🔑 **`LLMUnavailable`**：没配 API Key。写入 `local_config.json` 的 `llm.api_key`（推荐，本机私有不落库），或设置 `DEEPSEEK_API_KEY` 环境变量。
- 💸 **`BudgetExceeded`**：本周 token 预算用完，`run.bat reset-budget` 可重置；或调大 `llm.weekly_token_budget`。
- ⛔ **`AccessPaused`**：网络访问被熔断（异常内容类型或 403/429），先检查原因再 `run.bat enable-access --confirm`。
- ⚙️ **`pipeline.top_deep 不能超过 safety.user_requests_per_week`**：每篇精读要拉一次 HTML 全文（计入 user 请求预算），调大精读数量时需同步调大 `safety.user_requests_per_week`。
- 📭 **`arXiv 返回 0 条结果`**：查询异常（如短语语法问题），检查 `discovery.search_phrases`。
- 🆕 **新论文引用数很低**：正常现象。刚发布一周的论文普遍 0 引用，此时靠谱度主要由机构白名单与作者历史影响力决定，周报脚注里有同样说明。
- 🔍 **点「AI 解读」提示无法连接本地服务**：按需精读需要本地服务中转 API Key。双击 `serve.bat` 启动服务，再通过它自动打开的 `http://127.0.0.1:8000` 浏览周报（直接双击 HTML 文件时该按钮不可用）。
- 🪟 **双击 `run.bat` 一闪而过（已修复）**：无参数双击现在默认启动解读服务（等价 `run.bat serve`），窗口会保持打开并自动开浏览器；带子命令时（如 `run.bat run`、`run.bat status`）行为不变，请在命令行里运行。
- 🔁 **服务已在运行时再次双击 `run.bat`/`serve.bat` 提示端口占用**：此时服务本来就在运行，浏览器也会照常打开周报，那个报错窗口直接关掉即可（不要多开服务）。

## ⚠️ 免责声明

arXiv 页面代表预印本公开，不等于已经同行评审；AI 内容仅依据给定材料总结，可能存在错误，重要结论请核对原文。
