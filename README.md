# Interview Copilot Agent

一个面向面试准备场景的后端 MVP。

变更记录见 [CHANGELOG.md](CHANGELOG.md)。

它不是普通的问答机器人，而是把 `JD`、`简历`、`题目 + 用户作答` 统一入库，做短板诊断，再生成当天的准备任务，形成最小闭环。

## 当前能力

- 入库 `resume`、`jd`、`questions`
- 用 `documents` / `document_chunks` 维护可追溯证据链
- 用 `SQLite + Chroma + SQLite FTS5` 做结构化存储、混合检索和证据召回
- 做一次 `Gap Analysis`
- 生成当天计划与任务
- 提供 `TickTick` dry-run 同步接口
- 提供一个 `Vue 3 + TypeScript` 的 workbench 前端
- 提供一个复用同一套前端的 `Electron` 桌面壳

## 技术栈

- `FastAPI`
- `SQLAlchemy`
- `SQLite`
- `SQLite FTS5`
- `Chroma`
- `Pydantic Settings`
- `PyPDF`

## 项目结构

```text
interview_agent/
  app/          FastAPI 入口、配置、schema、LLM provider
  actions/      外部动作适配层，当前包含 TickTick stub
  core/         应用容器
  diagnosis/    Gap Analysis
  ingestion/    文本抽取、切块、题目解析、入库
  planning/     计划和任务生成
  retrieval/    source-aware 检索
  storage/      SQLAlchemy model、repository、Chroma 封装
frontend/       Vue 3 workbench + Electron shell
tests/          单测和服务层集成测试
```

## 数据设计

核心思想是把“原始文档”和“下游结构化记录”分开。

- `documents`
  存原始文档本体，比如简历、JD、题库文本
- `document_chunks`
  存切块结果，并和 Chroma 的 `vector_id` 对齐
- `questions` / `answer_records`
  存题目、参考答案、用户作答评估
- `gap_records`
  存诊断结果和证据摘要
- `plans` / `tasks`
  存当天计划和任务

其中 `questions` 现在同时承担“结构化题库记录”和“RAG 检索主索引”的角色，支持：

- `normalized_text`
- `question_fingerprint`
- `source_scope`
- `is_active`
- `superseded_by`

这样每条诊断结论都可以回溯到：

```json
{
  "source_type": "resume",
  "document_id": "doc_xxx",
  "chunk_id": "chunk_xxx",
  "text": "..."
}
```

## 文档版本策略

同一用户重复上传同类文档时，当前策略是：

- 新上传文档创建新的 `document` 和 `document_chunks`
- 旧版本文档会被标记为 `inactive`
- 默认检索只查 `active` 文档
- 历史证据仍然保留，可继续追溯

对于 `question` 类型，除了 `document` 版本管理外，还额外支持题目级别的增量治理：

- 先按 `source_scope` 确定一批题的逻辑来源
- 再按 `question_fingerprint` 判定是否为同一道题
- 未变化题目会跳过，不重复建索引
- 已变化题目会生成新版本，并让旧版本 `inactive`
- 旧题库里本轮未出现的题，也会被标记为 `inactive`

## RAG / Retrieval 逻辑

当前题库与证据检索采用一套混合 RAG 管线。

### 1. 入库阶段

- `resume` / `jd` / `questions` 原文先进入 `documents`
- 原文粗粒度切块后进入 `document_chunks`
- `questions` 会优先走真实 LLM 做结构化抽取
- 如果 LLM 不可用、返回坏结构或抽取失败，会自动退回规则解析 fallback

结构化题目字段包括：

- `question`
- `answer`
- `source_company`
- `source_role`
- `dimension`
- `topics`
- `reference_answer`

### 2. 索引阶段

系统维护两条检索 lane：

- dense lane：`Chroma`
- lexical lane：`SQLite FTS5`

具体索引内容是：

- `question_bank`
  存题干、参考答案要点、topics、来源信息的向量表示
- `interview_chunks`
  存原始 chunk 证据，主要用于追溯和诊断引用
- `retrieval_fts`
  统一的 FTS5 检索表，索引 active 的题目和必要证据块

这意味着系统既能做语义召回，也能做精确术语召回。

### 3. 检索阶段

查询时会先做 query rewrite，再并行走两条召回链路：

- dense retrieval：从 `question_bank` / `interview_chunks` / `gap_memory` 做向量检索
- lexical retrieval：从 `retrieval_fts` 做 `MATCH + bm25()` 全文检索

随后在 service 层做：

- metadata filter
- 去重合并
- question 优先于其 source chunk
- rerank 排序

默认只返回 `active` 的题和文档，避免旧版本污染结果。

### 4. 重排阶段

当前重排会综合这些信号：

- dense score
- lexical score
- dimension match
- source_type match
- query lexical overlap

因此它不是“只有向量检索”的简单 RAG，而是一套面向题库问答和短板诊断的 hybrid retrieval。

## LLM 策略

系统提供统一的 OpenAI-compatible provider。

- 如果配置了 `LLM_BASE_URL` 和 `LLM_API_KEY`，会走真实模型接口
- 如果额外配置了 `EMBEDDING_BASE_URL` 和 `EMBEDDING_API_KEY`，embedding 可以单独走专用模型
- 如果没有配置，会退化到本地 deterministic fallback

这意味着：

- 你现在可以不接模型，先把全流程跑通
- 接入真实模型后，不需要改 API 形状

## 本地运行

### 1. 创建虚拟环境

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
```

### 2. 配置环境变量

```bash
cp .env.example .env
```

默认配置已经可以本地运行。

关键项：

- `INTERVIEW_AGENT_WORKSPACE_DIR`
- `INTERVIEW_AGENT_DATABASE_URL`
- `INTERVIEW_AGENT_CHROMA_DIR`
- `INTERVIEW_AGENT_LLM_BASE_URL`
- `INTERVIEW_AGENT_LLM_API_KEY`
- `INTERVIEW_AGENT_CORS_ALLOW_ORIGINS`

### Workspace 模式

现在默认支持一个统一的 runtime workspace 概念：

- `memory/`
- `app.db`
- `chroma/`

都会默认挂在 `INTERVIEW_AGENT_WORKSPACE_DIR` 下。

例如：

```bash
.venv/bin/python -m interview_agent init --workspace ./workspaces/smoke-001
```

这个 workspace 下会初始化：

- `memory/MEMORY.md`
- `memory/SELF.md`
- `memory/HISTORY.md`
- `memory/RECENT_CONTEXT.md`
- `memory/PENDING.md`
- `memory/NOW.md`
- `memory/WORKING_MEMORY.json`
- `app.db`
- `chroma/`

默认 `init` 只创建缺失内容，不覆盖已有数据。

如果你想重写 workspace 模板文件，但保留 `app.db` 和 `chroma` 里的历史数据，可以运行：

```bash
.venv/bin/python -m interview_agent init --workspace ./workspaces/smoke-001 --force
```

如果你想把某个 workspace 重置成“第一次启动”的状态，可以运行：

```bash
.venv/bin/python -m interview_agent reset --workspace ./workspaces/smoke-001
```

这样你就可以为每次 smoke test、回归测试、演示环境切换到全新的 workspace，而不是手动删除本地运行目录。

### 3. 启动服务

```bash
.venv/bin/python -m interview_agent api --workspace ./workspaces/smoke-001 --reload
```

启动后默认地址：

```text
http://127.0.0.1:8000
```

### 4. 启动前端 Workbench

前端代码在 `frontend/` 目录。

先准备一个前端环境变量文件：

```bash
cp frontend/.env.example frontend/.env
```

然后在 `frontend/` 下安装依赖并启动：

```bash
cd frontend
npm install
npm run dev
```

默认地址：

```text
http://127.0.0.1:5173
```

默认会连到：

```text
http://127.0.0.1:8000
```

如果你要改前端所连的 API 地址，可以调整：

```bash
VITE_API_BASE_URL=http://127.0.0.1:8000
```

### 5. Electron 桌面壳

Workbench 是 `web-first` 的，Electron 只是同一套前端的桌面包装层。

在 `frontend/` 下运行：

```bash
npm run dev
```

如果你的本地 Electron/Vite 工作流已经配好，也可以直接用这套前端产物打包桌面壳。

## 测试

```bash
.venv/bin/pytest
```

当前测试覆盖了：

- 题目解析
- chunk 切分
- LLM-first 题库入库与 fallback
- question 增量去重 / 更新 / 失效治理
- SQLite FTS5 lexical retrieval
- hybrid retrieval merge / rerank
- gap priority 计算
- 服务层端到端闭环

## API

### Health

`GET /health`

### Ingest

- `POST /ingest/resume`
- `POST /ingest/jd`
- `POST /ingest/questions`

### Diagnosis

- `POST /diagnosis/gap`
- `GET /diagnosis/current`

### Planning

- `POST /plan/generate`
- `GET /plan/today`
- `POST /plan/sync_ticktick`

### Workbench

- `GET /workspace/overview`
- `GET /documents`
- `GET /documents/{document_id}`

### Dida365 Open API

要启用真实滴答同步，需要在 `.env` 里配置：

```bash
INTERVIEW_AGENT_DIDA365_ENABLED=true
INTERVIEW_AGENT_DIDA365_ACCESS_TOKEN=your_access_token
INTERVIEW_AGENT_DIDA365_PROJECT_ID=
INTERVIEW_AGENT_DIDA365_PROJECT_NAME=Interview Copilot Agent
INTERVIEW_AGENT_DIDA365_REGION=china
```

如果没有 `PROJECT_ID`，系统会直接调用 Dida365 Open API 的 `/project` 接口，按 `PROJECT_NAME` 查找项目。

## 最小演示流程

### 1. 上传简历

```bash
curl -X POST http://127.0.0.1:8000/ingest/resume \
  -H 'Content-Type: application/json' \
  -d '{
    "filename": "resume.md",
    "text": "项目经历：做过 Redis 缓存、RAG 系统和 Agent 工作流。"
  }'
```

### 2. 上传 JD

```bash
curl -X POST http://127.0.0.1:8000/ingest/jd \
  -H 'Content-Type: application/json' \
  -d '{
    "filename": "jd.txt",
    "company": "ByteDance",
    "role": "Backend Intern",
    "text": "熟悉 Redis、MySQL 和高并发系统设计，具备良好的项目表达能力。"
  }'
```

### 3. 上传题目 + 作答

```bash
curl -X POST http://127.0.0.1:8000/ingest/questions \
  -H 'Content-Type: application/json' \
  -d '{
    "filename": "questions.txt",
    "text": "Redis 为什么单线程还这么快？\n我的答案：因为它是内存操作，然后用了 IO 多路复用。"
  }'
```

### 4. 触发短板诊断

```bash
curl -X POST http://127.0.0.1:8000/diagnosis/gap \
  -H 'Content-Type: application/json' \
  -d '{}'
```

### 5. 生成今日计划

```bash
curl -X POST http://127.0.0.1:8000/plan/generate \
  -H 'Content-Type: application/json' \
  -d '{}'
```

### 6. 查看今日任务

```bash
curl http://127.0.0.1:8000/plan/today
```

## 设计取舍

这版刻意收敛在 MVP，不做这些内容：

- 多用户认证
- PostgreSQL / Qdrant / 消息队列

当前重点是先把这四条链路跑通：

1. `JD + 简历入库`
2. `题目 + 作答评估`
3. `Gap Analysis`
4. `计划生成`
5. `Workbench 浏览器 / Electron 入口`

## 当前默认行为

- 默认用户是 `u_demo`
- 默认只做单用户演示
- Chroma metadata 只放简单标量字段
- 完整 metadata 和业务关系以 SQLite 为准
- 未配置 Dida365 Open API 时，`POST /plan/sync_ticktick` 会退回 `dry_run`
- 配置 Dida365 Open API 后，agent 内部和 API 都会直接调用滴答接口
- 再次执行 `POST /plan/sync_ticktick` 时，会按 `ticktick_id` 回写本地任务完成状态

## Smoke Test

如果你已经配置好 `.env`，可以直接运行：

```bash
.venv/bin/python -m interview_agent smoke-sync --workspace ./workspaces/smoke-001
```

这个脚本会：

- 使用项目自己的 `AppContainer`
- 读取 `.env`
- 如果当前默认用户还没有计划，就自动创建一个 demo task
- 直接跑一遍 `planning.sync_ticktick()`

## Telegram Bot

当前建议：把它视为 legacy 辅入口，而不是主产品面。

这版已经可以直接接 Telegram Bot，入口脚本是：

```bash
.venv/bin/python -m interview_agent telegram --workspace ./workspaces/tg-demo
```

需要先在 `.env` 里配置：

```bash
INTERVIEW_AGENT_TELEGRAM_BOT_TOKEN=your_bot_token
INTERVIEW_AGENT_TELEGRAM_API_BASE_URL=https://api.telegram.org
INTERVIEW_AGENT_TELEGRAM_POLL_TIMEOUT_SEC=30
INTERVIEW_AGENT_TELEGRAM_POLL_MAX_BACKOFF_SEC=30
INTERVIEW_AGENT_TELEGRAM_DROP_PENDING_UPDATES=true
INTERVIEW_AGENT_TELEGRAM_ALLOWED_CHAT_IDS=
```

运行后脚本会通过 long polling 拉取消息，并直接调用项目里的 `agent_runtime`。

当前行为：

- 每个 Telegram `chat_id` 会映射为本地 `user_id=tg_<chat_id>`
- 文本消息会直接进入 agent 对话链路
- `/start` 会返回一条欢迎消息
- 启动时默认会跳过历史积压 update，避免 bot 重启后把旧消息重新吃一遍
- 轮询网络异常会指数退避重试；如果遇到 `getUpdates` 冲突会停止接收并保留日志
- 如果配置了 `INTERVIEW_AGENT_TELEGRAM_ALLOWED_CHAT_IDS`，只有白名单里的 chat_id 会被处理

## QQ Bot

当前建议：把它视为 legacy 辅入口，而不是主产品面。

这版还加了一个基于官方 QQBot API 的私聊通道，入口脚本是：

```bash
.venv/bin/python -m interview_agent qq --workspace ./workspaces/qq-demo
```

需要先在 `.env` 里配置：

```bash
INTERVIEW_AGENT_QQBOT_APP_ID=your_app_id
INTERVIEW_AGENT_QQBOT_CLIENT_SECRET=your_client_secret
INTERVIEW_AGENT_QQBOT_API_BASE_URL=https://api.sgroup.qq.com
INTERVIEW_AGENT_QQBOT_TOKEN_URL=https://bots.qq.com/app/getAppAccessToken
INTERVIEW_AGENT_QQBOT_GATEWAY_BACKOFF_SEC=5
INTERVIEW_AGENT_QQBOT_ALLOWED_OPENIDS=
```

当前行为：

- 只支持官方 QQBot 的 `C2C` 私聊文本消息
- 通过 WebSocket gateway 接收入站消息，通过 REST API 发回回复
- 每个 `user_openid` 会映射为本地 `user_id=qqbot_<openid>`
- 如果配置了 `INTERVIEW_AGENT_QQBOT_ALLOWED_OPENIDS`，只有白名单里的 openid 会被处理

## 后续可扩展方向

- 接真实 LLM 做更稳的评估、摘要和计划文案
- 加 `mock interview` 模式
- 加主动提醒和动态重规划
- 增加 Electron 原生能力，例如 tray、deep link、系统通知
