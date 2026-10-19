# 设计说明（kg-weekly）

## 产品定位

KG 每周前沿是 Windows 本机的周报小工具：每周一次从 arXiv 抓取知识图谱方向近 7 天新论文，本地规则评分选出靠谱文章，再由 deepseek-flash 生成中文卡片与 AI 精读，最终输出一份**零 JS、零外部资源的单文件 HTML 周报**。纯 Python 标准库实现，无第三方依赖、无 Web 服务、无数据库后台。

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
单文件 HTML 周报（精读默认折叠，点击展开）
```

每一步幂等可重入：中断后重跑自动跳过已完成部分；论文内容版本变化才清除派生内容（卡片/精读/全文）。

## 关键设计决策

- **零 JS 折叠**：精读卡片用原生 `<details>/<summary>` 折叠，默认只显示一句话摘要，点击展开完整解读。单文件无脚本，安全性与兼容性最好。
- **--topic 关键词入口**：`apply_topic` 把搜索短语与核心评分关键词替换为输入关键词；每个入口使用独立 SQLite（`data/papers-<slug>.db`），抓取周标记与周 token 预算彼此隔离，默认 kg 入口不受影响；LLM 提示词按关键词参数化，默认 kg 措辞与历史完全一致。
- **本机密钥**：`local_config.json`（已被 .gitignore 忽略）浅合并覆盖 `config.json`，用于存放 API Key；Key 不进仓库、不出现命令行历史，CLI 输出不回显。
- **跨入口礼貌间隔**：arXiv 最小请求间隔按本机**所有**入口数据库的最新请求时间计算，连续跑多个入口也不会违背间隔保证。
- **LLM 输出收敛**：卡片字段枚举校验、精读结构规范化（`_normalize_detail`），畸形响应被过滤后才入库，渲染永不因模型输出形状崩溃。

## 安全与克制

- 域名白名单（arxiv.org / export.arxiv.org / rss.arxiv.org / api.openalex.org）+ 仅 https + **拒绝跟随重定向**（白名单只校验初始 URL，跟随会绕过校验）。
- 响应体上限 20 MB，读满即中断，异常上游无法耗尽内存。
- 周请求预算（自动 30 次 / 用户 12 次）与最小间隔（默认 10 秒，arXiv 要求 ≥3 秒），预算触顶即停。
- 内容类型异常或 403/429 自动熔断，人工确认后 `enable-access --confirm` 恢复。
- 跨进程文件锁（Windows `msvcrt.locking` / POSIX `fcntl.flock`）。
- LLM 周预算按自然周自动前滚，每次调用前检查累计用量。
- 周报脚注明确：arXiv 预印本不等于同行评审；AI 内容仅依据给定材料，重要结论请核对原文。

## 不做的事情

- 不轮询、不并发抓取、不翻页扫描 arXiv（单次查询，0 条结果报错而不是假成功）。
- 不逐篇访问 PDF；HTML 全文仅对精读 Top N 拉取并缓存。
- 不绕过验证码、限流或站点封锁；不跟随重定向。
- 不把模型生成的解释当作论文原文或事实定论。
- 不部署后台定时任务，不对外网暴露任何服务。

## 数据与模块

- `src/kg_weekly/fetch.py`：白名单、间隔、周请求预算、跨进程锁、审计与熔断。
- `src/kg_weekly/arxiv.py`：arXiv 查询 URL 构造与 Atom 解析（含 comment 字段）。
- `src/kg_weekly/openalex.py`：引用数 / venue / 机构 / 作者历史影响力批量查询。
- `src/kg_weekly/ranking.py`：相关性与靠谱度评分（关键词命中、应用型/代码信号、机构白名单、作者影响力、引用分层）。
- `src/kg_weekly/llm.py`：OpenAI 兼容 LLM 客户端（deepseek-flash，强制关思考模式），账号选择与用量记录。
- `src/kg_weekly/pipeline.py`：六步周流水线编排（幂等可重入）。
- `src/kg_weekly/report.py`：单文件 HTML 周报生成（内联 CSS/SVG、零 JS 折叠）。
- `src/kg_weekly/db.py`：SQLite 论文库、用量审计、周标记、熔断状态与请求记录。
- `src/kg_weekly/cli.py` / `config.py`：命令行与配置加载校验（含 --topic 入口与 local_config.json 合并）。
