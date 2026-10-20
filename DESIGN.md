# 设计说明（kg-weekly）

## 产品定位

KG前沿论文解读是 Windows 本机的周报小工具：每周一次从 arXiv 抓取知识图谱方向近 7 天新论文，本地规则评分选出靠谱文章，再由 deepseek-flash 生成中文卡片与 AI 精读，最终输出一份**零外部资源的单文件 HTML 周报**（折叠交互零 JS；「AI 解读」按钮内置一段小脚本，依赖可选的本地服务）。纯 Python 标准库实现，无第三方依赖、无数据库后台；本地服务（双击 `serve.bat` 或 `run.bat serve`）只绑定 127.0.0.1，用于按需精读。

流水线不绑定知识图谱：抓取短语、评分关键词、机构白名单全部可配置，`--topic` 可一键切换到任意 arXiv 领域（LLM、RAG、药物发现……），每个领域独立数据库与周预算，可多领域并行产出周报。

## 六步流水线

```text
抓取 arXiv（6 分类 × 11 短语，近 7 天窗口）
        ↓
OpenAlex 增强（引用 / venue / 机构 / 作者影响力，仅对相关度达标论文）
        ↓
本地评分（相关性 × 0.7 + 靠谱度 × 0.3）
        ↓
中文卡片（deepseek-flash 批量，最多 Top 50）
        ↓
AI 精读（Top 12 拉取 HTML 全文并缓存）
        ↓
单文件 HTML 周报（精读默认折叠，点击展开；其余论文卡片带「AI 解读」按钮）
```

每一步幂等可重入：中断后重跑自动跳过已完成部分；论文内容版本变化才清除派生内容（卡片/精读/全文）。

按需精读不改变周流水线：双击 `serve.bat`（或 `run.bat serve`）起的本地服务在页面点击「AI 解读」时，对指定论文走「拉全文（有缓存用缓存）→ 精读 → 入库」同一条路径。

## 关键设计决策

- **零 JS 折叠 + 可选按需脚本**：精读卡片仍用原生 `<details>/<summary>` 折叠（零 JS）；页面仅内置一段「AI 解读」按钮脚本，通过 fetch 调用本地服务 `/api/deep-read`，双击打开的 file:// 场景自动降级为提示文字，不影响周报阅读。
- **--topic 关键词入口**：`apply_topic` 把搜索短语与核心评分关键词替换为输入关键词；每个入口使用独立 SQLite（`data/papers-<slug>.db`），抓取周标记与周 token 预算彼此隔离，默认 kg 入口不受影响；LLM 提示词按关键词参数化，默认 kg 措辞与历史完全一致。
- **--categories 分类覆盖**：非 CS 领域（如 q-bio）追踪时用 `--categories` 覆盖 arXiv 分类，按入口持久化到 settings（`default` 恢复配置默认），后续 `report`/`status` 自动沿用同一覆盖。
- **多账号故障转移**：LLM 调用按优先级遍历可用账号链（库中账号 → config/env 默认账号），失败自动顺延并记录冷却；单账号限流/网络错误不再导致整批卡片或精读失败。
- **本机密钥**：`local_config.json`（已被 .gitignore 忽略）浅合并覆盖 `config.json`，用于存放 API Key；Key 不进仓库、不出现命令行历史，CLI 输出不回显。
- **按需精读（本地服务中转）**：API Key 绝不能进 HTML，浏览器也无法直连 DeepSeek（CORS + Key 暴露），因此「AI 解读」按钮 POST 到 `run.bat serve` 起的 127.0.0.1 服务，由服务端复用流水线第 5 步代码完成精读并入库；后续再点同一篇直接返回缓存，不重复花 token；同一篇并发点击由 per-paper 锁串行化，锁内二次查库，保证 token 不重复花。
- **跨入口礼貌间隔**：arXiv 最小请求间隔按本机**所有**入口数据库的最新请求时间计算，连续跑多个入口也不会违背间隔保证。
- **LLM 输出收敛**：卡片字段枚举校验、精读结构规范化（`_normalize_detail`），畸形响应被过滤后才入库，渲染永不因模型输出形状崩溃。

## 安全与克制

- 域名白名单（arxiv.org / export.arxiv.org / rss.arxiv.org / api.openalex.org）+ 仅 https + **拒绝跟随重定向**（白名单只校验初始 URL，跟随会绕过校验）。
- 响应体上限 20 MB，读满即中断，异常上游无法耗尽内存。
- LLM 响应体上限 10 MB；`llm.base_url` 必须命中 `llm.allowed_hosts` 白名单（LLM 请求不走站点白名单通道，单独校验）。
- 每次 `run` 前用 SQLite 在线备份 API 把数据库快照到 `data/*.db.bak`，失败不阻塞主流程。
- 周请求预算（自动 30 次 / 用户 12 次）与最小间隔（默认 10 秒，arXiv 要求 ≥3 秒），预算触顶即停。
- 内容类型异常或 403/429 自动熔断，人工确认后 `enable-access --confirm` 恢复。
- 跨进程文件锁（Windows `msvcrt.locking` / POSIX `fcntl.flock`）。
- LLM 周预算按自然周自动前滚，每次调用前检查累计用量。
- 精读数量受 user 模式请求预算约束（top_deep ≤ user_requests_per_week，配置校验强制）。
- `prune` 命令清理过期审计/用量/同步记录（默认保留 90 天），防止审计表无限增长。
- 周报外链只允许 http/https 协议；模型输出 JSON 用 raw_decode 提取首个合法对象，容忍尾部垃圾。
- `serve` 只绑定 127.0.0.1，不监听外网；静态文件解析拒绝路径穿越，只服务 out/ 下的 .html/.htm；POST 请求体上限 64 KB。
- 按需精读与流水线共用同一套保护：周 token 预算、user 请求预算、最小间隔、熔断与白名单全部生效。
- 周报脚注明确：arXiv 预印本不等于同行评审；AI 内容仅依据给定材料，重要结论请核对原文。

## 不做的事情

- 不轮询、不并发抓取、不翻页扫描 arXiv（单次查询，0 条结果报错而不是假成功）。
- 不逐篇访问 PDF；HTML 全文仅对精读 Top N 拉取并缓存。
- 不绕过验证码、限流或站点封锁；不跟随重定向。
- 不把模型生成的解释当作论文原文或事实定论。
- 不部署后台定时任务，不对外网暴露任何服务（`serve` 仅绑定 127.0.0.1，只在本机可达）。

## 数据与模块

- `src/kg_weekly/fetch.py`：白名单、间隔、周请求预算、跨进程锁、审计与熔断。
- `src/kg_weekly/arxiv.py`：arXiv 查询 URL 构造与 Atom 解析（含 comment 字段），以及 HTML 全文提取（未闭合 script 兜底重解析）。
- `src/kg_weekly/openalex.py`：引用数 / venue / 机构 / 作者历史影响力批量查询。
- `src/kg_weekly/ranking.py`：相关性与靠谱度评分（关键词命中、应用型/代码信号、机构白名单、作者影响力、引用分层）。
- `src/kg_weekly/llm.py`：OpenAI 兼容 LLM 客户端（deepseek-flash，强制关思考模式），账号选择与用量记录。
- `src/kg_weekly/pipeline.py`：六步周流水线编排（幂等可重入）。
- `src/kg_weekly/report.py`：单文件 HTML 周报生成（内联 CSS/SVG、零 JS 折叠、按需精读按钮脚本）。
- `src/kg_weekly/server.py`：本地周报浏览与按需精读服务（仅 127.0.0.1，路径穿越防护）。
- `src/kg_weekly/db.py`：SQLite 论文库、用量审计、周标记、熔断状态与请求记录。
- `src/kg_weekly/cli.py` / `config.py`：命令行（含 serve 子命令）与配置加载校验（--topic 入口与 local_config.json 合并）。
