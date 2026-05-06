下面给你一版可落地的设计草案。我会按“后端系统设计”的方式写，而不是只写产品想法。你的项目可以明确定位为：

Interview Copilot Agent

一个带长期记忆、岗位理解、短板诊断和滴答清单执行闭环的主动式面试准备 Agent。

它不是普通 mock 面试机器人，而是：

JD + 简历/项目经历 + 面经题库 + 历史作答错误 + 滴答清单执行情况
→ 能力缺口诊断
→ 个性化准备计划
→ 自动生成任务
→ 主动提醒
→ 根据完成情况动态调整


你现有草案里已经把核心约束说得很清楚：数据异构，不能用单一 chunking 和单一索引；Gap Analysis 同时依赖非结构化能力证据和结构化历史评分；主动行为需要状态机，而不只是 scheduler。 这三个点应该成为整个项目的架构中心。

1. 总体架构：用 akashic-agent 的 runtime 思想，但业务换成面试准备
https://github.com/kachofugetsu09/akashic-agent
akashic-agent 的后端形式很适合你这个项目，因为它不是一个简单 chatbot，而是有 Passive Turn、Lifecycle Phase、EventBus、Proactive Tick、Drift 后台任务 这些 agent runtime 结构。它的被动回复链路是：

InboundMessage
→ AgentLoop
→ CoreRunner
→ AgentCore / PassiveTurnPipeline
→ BeforeTurn
→ BeforeReasoning
→ Reasoner.run_turn()
→ AfterReasoning
→ AfterTurn
→ OutboundMessage


README 里也明确写了每条被动 turn 会经过 6 个生命周期 phase，并且 Reasoner 内部还有 BeforeStep / AfterStep。(GitHub)

你的项目可以改造成：

User Message / File Upload / TickTick Event
→ InterviewAgentLoop
→ InterviewCoreRunner
→ InterviewTurnPipeline
→ Retrieval + Profile + Gap Analysis
→ Plan / Task / Mock / Resume Action
→ Telegram / Web UI / TickTick


也就是说，你不是做一个“问答机器人”，而是做一个 面试准备 agent runtime。

2. 核心产品闭环

我建议你把系统闭环定义成 6 步：

1. 收集资料
   简历、项目文档、JD、面经、mock 记录、错题、滴答清单

2. 构建画像
   用户项目经历、目标岗位、能力维度、历史错误、学习偏好

3. 多源检索
   根据当前任务检索 JD、项目经历、面经、历史作答、知识点

4. 短板诊断
   判断用户不是“不会什么”，而是“哪类能力证据不足 / 表达不好 / 反复出错”

5. 计划生成
   生成今天、本周、面试前的任务计划

6. 执行反馈
   同步到滴答清单，读取完成情况，主动提醒，动态重排计划


这就是你项目的核心新颖性：从 RAG 问答变成 RAG + Memory + Diagnosis + Planning + Action 的闭环系统。

3. 后端模块设计

我建议拆成 9 个核心模块。

interview_agent/
  app/
    main.py
    config.py
  channels/
    telegram.py
    web_chat.py
    ticktick_webhook.py
  core/
    runner.py
    loop.py
    passive_turn.py
    proactive_tick.py
    state_machine.py
  lifecycle/
    phase.py
    modules/
  ingestion/
    resume_parser.py
    jd_parser.py
    question_ingestor.py
    mock_ingestor.py
    chunker.py
    extractor.py
  retrieval/
    hybrid_retriever.py
    reranker.py
    query_rewriter.py
    source_router.py
  memory/
    profile_store.py
    episodic_memory.py
    working_memory.py
  diagnosis/
    gap_analyzer.py
    scoring.py
    evidence_builder.py
  planning/
    plan_generator.py
    task_prioritizer.py
    review_planner.py
  actions/
    ticktick_client.py
    reminder_dispatcher.py
    resume_editor.py
    mock_interviewer.py
  storage/
    db.py
    vector_store.py
    repositories/


其中最重要的是这四个：

Ingestion Pipeline
Retrieval + Memory
Gap Analyzer
Action Dispatcher


4. 数据流设计

你的主数据流可以写成这样：

[用户输入 / 文件上传 / 滴答清单状态]
        ↓
[Ingestion Pipeline]
        ↓
[Knowledge Store]
  ├─ Vector Store：项目文档、面经、mock 记录、gap_record
  └─ SQL DB：用户画像、JD 要求、能力评分、任务状态
        ↓
[Retrieval Layer]
        ↓
[Reasoner]
        ↓
[Gap Analyzer]
        ↓
[Plan Generator]
        ↓
[Action Dispatcher]
  ├─ 写入滴答清单
  ├─ 发 Telegram 提醒
  ├─ 发起 mock 训练
  └─ 更新 Profile / Memory


你已有草案里提到“结构化字段写 DB，原文 chunks 写向量库，通过 project_id 关联”，这个设计很对。 这也是你和普通 RAG 项目的区别：你不是只有向量库，而是 SQL + Vector 双轨存储。

5. Memory 设计：三层记忆

5.1 Structured Profile

存 DB，适合稳定状态。

{
  "user_id": "u_001",
  "target_roles": ["后端实习", "AI 工程师实习"],
  "target_companies": ["字节跳动", "阿里", "腾讯"],
  "ability_scores": {
    "project_expression": 3.2,
    "backend_basic": 2.8,
    "algorithm": 3.0,
    "system_design": 2.1,
    "rag_llm": 3.8,
    "behavioral": 3.6
  },
  "weak_points": [
    "系统设计 QPS 估算",
    "RAG 评测指标表达",
    "项目量化结果不足"
  ],
  "learning_preference": {
    "reminder_time": "21:00",
    "task_granularity": "small",
    "preferred_mode": "text"
  }
}


5.2 Episodic Memory

存向量库，用自然语言记录历史事件。

2026-05-06：用户在 Redis 单线程问题上知道内存操作和 IO 多路复用，
但不能解释 epoll 机制，属于“部分掌握”。
下次应该追问：select/poll/epoll 区别，Redis event loop。


你题目入库方案里已经强调：不要只记“Redis 不熟”，而要记“Redis IO 多路复用机制表达不清”，这样 Gap Analyzer 才能做精确计划。

5.3 Working Memory

只在当前会话里存在。

{
  "current_jd_id": "jd_042",
  "current_mock_session": "mock_20260506",
  "current_goal": "准备后端一面",
  "temporary_context": ["正在分析用户 B+ 树题目回答"]
}


6. Ingestion Pipeline 设计

这是你的第一个技术重点。你要支持多种输入：

简历 LaTeX / PDF
JD
项目 README / 报告
面经笔记
mock 面试记录
题目 + 我的答案
滴答清单任务状态


每个 chunk 必须有 metadata：

{
  "chunk_id": "chunk_001",
  "user_id": "u_001",
  "source_type": "jd | resume | project_doc | interview_note | mock_record | question | gap_record",
  "company": "ByteDance",
  "role": "Backend Intern",
  "topic": ["database", "redis", "io_multiplexing"],
  "project_id": "proj_rag_001",
  "question_id": "q_redis_001",
  "created_at": "2026-05-06"
}


你的草案里最后也说了，metadata 是所有检索的过滤基础，设计粗糙会导致后期召回质量差且难以修复。 这个点应该放进项目答辩里讲。

7. 题目入库链路

这一部分可以做成你的项目亮点，因为它把“面经题库”变成了“历史错误记忆”。

输入格式：

【来源】字节跳动后端实习，2026 春

Redis 为什么单线程还这么快？
我的答案：因为它是内存操作，然后用了 IO 多路复用，但具体机制说不清。

MySQL 的索引为什么用 B+ 树不用 B 树？
我的答案：不知道。


处理流程：

1. LLM 解析题目和用户作答
2. 向量检索做语义去重
3. 分类打标：database / os_network / system_design / rag_llm ...
4. 生成参考答案框架
5. 评估用户作答
6. 写入 SQL + Vector Store
7. 返回本批诊断摘要


你的设计里已经把这条链路拆得很清楚：切分、去重、分类打标、生成参考答案、作答评估、双轨写入、返回摘要。

关键是评估结果不要只给分，要输出：

{
  "question": "Redis 为什么单线程还这么快？",
  "dimension": "database",
  "topics": ["Redis", "单线程模型", "IO 多路复用", "epoll"],
  "mastery_level": "部分掌握",
  "gaps": [
    "无法解释 IO 多路复用机制",
    "没有提到 Redis 基于事件循环处理连接",
    "没有区分单线程命令执行和后台线程"
  ],
  "next_probe": [
    "select/poll/epoll 区别是什么？",
    "Redis 6.0 引入多线程后多线程处理的是哪一部分？"
  ]
}


这样后面 Gap Analyzer 检索的是 gap_record，不是单纯检索题目原文。你已有方案里也写到，gaps 单独存一条向量，是为了让 Gap Analyzer 在查“用户系统设计哪里薄弱”时召回更精准。

8. Retrieval Layer：不能只做 Top-K 向量检索

你这个项目一定要避免被面试官说成“套壳 RAG”。检索层要讲成 source-aware retrieval。

8.1 Source Router

先判断用户当前问题需要什么数据源。

用户问：“我这个 JD 该怎么准备？”
→ 检索 JD + 简历 + 项目经历 + 历史 gap + 题库

用户问：“Redis 单线程怎么答？”
→ 检索题库 + 用户历史作答 + 参考答案 + gap_record

用户问：“帮我改简历。”
→ 检索 JD + 简历 LaTeX + 项目结构化字段 + 项目原文 chunks

用户问：“今天该学什么？”
→ 检索近期任务 + deadline + gap 趋势 + 滴答清单状态


8.2 Metadata Filter

先缩小范围：

filter = {
    "user_id": user_id,
    "source_type": ["mock_record", "gap_record", "question"],
    "dimension": "database"
}


8.3 Hybrid Retrieval

BM25：适合 Redis、epoll、B+ 树、HNSW 这种关键词
Vector：适合“系统设计表达不好”“项目亮点不清楚”这种语义
Rerank：按当前任务和用户背景重新排序


8.4 Evidence Bundle

最后不要直接把 chunks 扔给 LLM，而是整理成证据包：

{
  "jd_requirements": [
    {
      "text": "熟悉分布式系统设计",
      "weight": 0.8,
      "source": "jd_042"
    }
  ],
  "user_evidence": [
    {
      "text": "项目 A 使用 Redis 做缓存，但简历中没有写缓存一致性策略",
      "source": "resume_proj_a"
    }
  ],
  "historical_errors": [
    {
      "text": "短链系统设计 mock 中未提缓存、限流、QPS 估算",
      "source": "mock_20260501"
    }
  ]
}


这会让 Gap Analysis 更稳。

9. Gap Analyzer 设计

这是整个项目最核心的模块。

它的输入：

JD 结构化要求
用户简历和项目经历
历史面经题表现
mock 面试评分
滴答清单完成情况
近期 deadline


它的输出：

{
  "overall_risk": "medium_high",
  "top_gaps": [
    {
      "dimension": "system_design",
      "severity": "high",
      "why_it_matters": "目标 JD 强调后端系统设计，但用户历史 mock 中多次没有覆盖容量估算和 trade-off",
      "evidence": [
        "JD: 熟悉高并发系统设计",
        "Mock: 短链系统未提 QPS 估算",
        "Question history: 缓存一致性问题连续两次为模糊"
      ],
      "repair_actions": [
        "练习短链系统设计 30 分钟",
        "补充 QPS 估算模板",
        "整理缓存一致性回答框架"
      ]
    },
    {
      "dimension": "rag_llm",
      "severity": "medium",
      "why_it_matters": "用户有 RAG 项目，但简历和 mock 中缺少 eval 指标表达",
      "evidence": [
        "Resume: 项目只写了 RAG 问答系统",
        "Mock: 无法解释 Recall@K 和 Faithfulness"
      ],
      "repair_actions": [
        "补写 RAG eval 简历 bullet",
        "准备 2 分钟 RAG pipeline 项目介绍"
      ]
    }
  ]
}


能力维度建议定为：

project_expression：项目表达
backend_basic：八股基础
algorithm：算法能力
system_design：系统设计
rag_llm：AI / RAG 专项
behavioral：行为面
english：英文表达
execution：计划执行力


你原来的评分公式可以保留，但我建议拆细一点：

gap_priority =
  jd_weight
  × weakness_severity
  × interview_urgency
  × evidence_confidence
  × repeated_failure_factor
  × (1 - recent_improvement)


解释：

jd_weight：JD 是否强调
weakness_severity：当前能力缺口严重程度
interview_urgency：离面试越近越优先
evidence_confidence：证据是否足够
repeated_failure_factor：是否反复错
recent_improvement：最近是否已经明显进步


这样会比简单的 JD 要求权重 × 用户证据覆盖度 × 历史 mock 表现 更适合做计划排序。

10. Plan Generator：从诊断变成滴答清单

这里不要只是“建议你学习 Redis”。要生成可执行任务。

输入：

{
  "gap": "Redis IO 多路复用机制表达不清",
  "deadline": "2026-05-10",
  "available_time_today": 90,
  "preferred_task_size": "small",
  "current_ticktick_status": "数据库任务连续两天未完成"
}


输出：

{
  "tasks": [
    {
      "title": "复习 Redis IO 多路复用：select/poll/epoll 对比",
      "due": "2026-05-06T21:30:00",
      "duration_min": 25,
      "priority": 3,
      "tags": ["数据库", "Redis", "八股"],
      "note": "Gap Analysis 显示你能说出 IO 多路复用，但无法解释 epoll 机制。完成后用 3 句话复述 Redis 为什么快。"
    },
    {
      "title": "口述 Redis 单线程为什么快，录入一次答案",
      "due": "2026-05-06T22:00:00",
      "duration_min": 10,
      "priority": 3,
      "tags": ["mock", "表达"],
      "note": "目标：从内存操作、单线程避免锁、IO 多路复用、事件循环四个角度回答。"
    }
  ]
}


这就从“反馈”变成了“执行系统”。

11. Action Dispatcher：主动行为不是 cron，而是状态机

akashic-agent 的 proactive 链路是在每个 tick 里先做 pre-gate，然后并行预取 alerts、context、feed content，再进入 agent loop。(GitHub) 你的项目也应该这样做，但把数据源换成：

TickTick 今日任务
逾期任务
面试日期
最近 gap 趋势
最近 mock 记录
用户最近在线状态


主动 tick 的流程：

ProactiveTick
→ PreGate
   - 用户是否允许提醒？
   - 现在是否在免打扰时间？
   - 今天是否已经提醒过？
   - 是否存在 urgent gap？
→ DataGateway
   - 拉取滴答清单任务
   - 拉取近期 gap_record
   - 拉取面试 deadline
   - 拉取用户最近学习记录
→ DecisionEngine
   - 是否提醒？
   - 提醒什么？
   - 是否生成新任务？
   - 是否触发 mock？
→ ActionDispatcher
   - Telegram 发消息
   - TickTick 写任务
   - 更新提醒状态


规则引擎负责触发条件：

Rule(
    name="interview_tomorrow",
    condition=lambda ctx: ctx.days_to_interview == 1,
    priority="urgent"
)

Rule(
    name="repeated_fuzzy_gap",
    condition=lambda ctx: ctx.gap_repeated("database", level="模糊", days=7),
    priority="high"
)

Rule(
    name="task_overdue_2days",
    condition=lambda ctx: ctx.overdue_tasks_count >= 2,
    priority="high"
)

Rule(
    name="daily_evening_review",
    condition=lambda ctx: ctx.time == "21:30" and not ctx.review_done_today,
    priority="normal"
)


LLM 只负责生成自然语言和计划内容，不负责判断“该不该提醒”。这个边界很重要：确定性决策用代码，个性化表达用 LLM。

12. Passive Turn Pipeline：普通对话怎么走

参考 akashic-agent 的 phase 思路。它的 PhaseFrame / PhaseModule / Phase 抽象本质上是 middleware pipeline：frame 保存 input、slots、output，module 异步处理 frame，phase 按顺序执行模块链。(GitHub)

你的被动 turn 可以设计成：

InboundMessage
→ BeforeTurn
   - 读取 session
   - 判断 intent
   - 加载 working memory
→ BeforeRetrieval
   - Source Router
   - Query Rewrite
   - Metadata Filter
→ Retrieval
   - SQL 查询
   - Vector 检索
   - BM25
   - Rerank
→ BeforeReasoning
   - 构造 Evidence Bundle
   - 构造 Profile Context
→ Reasoner.run_turn()
   - 回答问题 / 诊断短板 / 生成计划 / 发起 mock
→ AfterReasoning
   - 解析结构化 action
   - 写 memory
   - 写 answer_records / gap_records
→ AfterTurn
   - 同步 TickTick
   - 发消息
   - 记录 observe trace


这样你的项目就有很强的后端味道：请求不是直接进 LLM，而是经过可插拔 pipeline。

13. 数据库表设计草案

MVP 用 SQLite，后面迁 PostgreSQL。

users

CREATE TABLE users (
  id TEXT PRIMARY KEY,
  name TEXT,
  timezone TEXT,
  created_at DATETIME
);


target_jds

CREATE TABLE target_jds (
  id TEXT PRIMARY KEY,
  user_id TEXT,
  company TEXT,
  role TEXT,
  raw_text TEXT,
  structured_requirements JSON,
  created_at DATETIME
);


projects

CREATE TABLE projects (
  id TEXT PRIMARY KEY,
  user_id TEXT,
  name TEXT,
  tech_stack JSON,
  role TEXT,
  metrics JSON,
  raw_source_id TEXT,
  created_at DATETIME
);


ability_scores

CREATE TABLE ability_scores (
  user_id TEXT,
  dimension TEXT,
  score REAL,
  confidence REAL,
  updated_at DATETIME,
  PRIMARY KEY (user_id, dimension)
);


questions

CREATE TABLE questions (
  id TEXT PRIMARY KEY,
  user_id TEXT,
  text TEXT,
  source_company TEXT,
  source_role TEXT,
  dimension TEXT,
  topics JSON,
  reference_answer TEXT,
  latest_mastery_level TEXT,
  last_answered_at DATETIME
);


answer_records

CREATE TABLE answer_records (
  id TEXT PRIMARY KEY,
  question_id TEXT,
  user_id TEXT,
  user_answer TEXT,
  mastery_level TEXT,
  gaps JSON,
  next_probe JSON,
  answered_at DATETIME
);


gap_records

CREATE TABLE gap_records (
  id TEXT PRIMARY KEY,
  user_id TEXT,
  dimension TEXT,
  severity TEXT,
  evidence JSON,
  suggestion TEXT,
  source_ids JSON,
  created_at DATETIME
);


plans

CREATE TABLE plans (
  id TEXT PRIMARY KEY,
  user_id TEXT,
  jd_id TEXT,
  start_date DATE,
  end_date DATE,
  status TEXT,
  created_at DATETIME
);


tasks

CREATE TABLE tasks (
  id TEXT PRIMARY KEY,
  user_id TEXT,
  plan_id TEXT,
  title TEXT,
  dimension TEXT,
  priority INTEGER,
  due_at DATETIME,
  ticktick_id TEXT,
  status TEXT,
  reason TEXT,
  created_at DATETIME
);


14. 向量库 Collection 设计

不要所有东西放一个 collection 里。建议：

collection: interview_chunks
- 简历原文 chunks
- 项目文档 chunks
- JD chunks
- 面经 chunks
- 知识点 chunks

collection: question_bank
- 题目 + 参考答案

collection: gap_memory
- 用户具体薄弱点
- mock 暴露问题
- 历史错误摘要

collection: episodic_memory
- 每次学习 / mock / 复盘事件


其中 gap_memory 最重要。因为你的系统不是回答“Redis 是什么”，而是回答“我为什么老是答不好 Redis”。

15. API 设计草案

即使用 Telegram 做入口，后端也建议抽象成 API，方便后续做 Web UI。

POST /ingest/resume
POST /ingest/jd
POST /ingest/questions
POST /ingest/mock

POST /diagnosis/gap
GET  /diagnosis/current
GET  /profile

POST /plan/generate
GET  /plan/today
POST /plan/sync_ticktick

POST /mock/start
POST /mock/answer
POST /mock/finish

POST /resume/suggest
POST /resume/apply

POST /proactive/tick


16. 高并发和异步设计

这个项目的并发重点不是百万 QPS，而是：

多个用户同时发消息
一次入库几十道题
多个 LLM 分类/评估并发调用
TickTick 同步
向量库写入
后台 proactive tick


题目入库就很适合用 asyncio：

async def ingest_questions(raw_text: str, source: str | None = None):
    items = await parse_questions(raw_text)

    sem = asyncio.Semaphore(5)

    async def limited_process(item):
        async with sem:
            return await process_single_question(item, source)

    results = await asyncio.gather(
        *(limited_process(item) for item in items),
        return_exceptions=True
    )

    return build_summary(results)


注意三个点：

1. 分类和评估可以并发
2. LLM 调用要加 semaphore，防止 rate limit
3. 同一个 user/session 内部涉及 profile 更新时要串行或加锁


17. MVP 不要做太大

我建议 MVP 只做 4 条链路：

1. JD + 简历解析
2. 题目入库 + 作答评估
3. 单次 Gap Analysis
4. 生成今日任务并同步滴答清单


MVP Demo 流程：

用户上传简历
用户上传目标 JD
用户粘贴一批面经题 + 自己的答案
系统输出：
  - 岗位要求摘要
  - 简历匹配点
  - 当前 3 个最大短板
  - 本周准备计划
  - 今日滴答清单任务


这已经足够展示完整闭环。

18. 版本路线

V0：后端骨架

配置系统
SQLite
Vector Store
Telegram Bot
基础 AgentLoop
日志和 trace


V1：MVP

简历 / JD ingest
题目入库
answer evaluation
gap_record 存储
手动触发 Gap Analysis
生成任务
同步 TickTick


V2：项目可展示版

Hybrid Retrieval
Evidence Bundle
简历改写 agent
Mock interview mode
每日复盘
Gap 趋势图


V3：差异化版

主动提醒状态机
任务完成情况动态重规划
多公司 JD 对比
个性化提醒策略
面试前 24 小时冲刺模式


19. 你答辩/面试时怎么讲这个项目

我做了一个主动式面试准备 Agent。
它的核心不是回答八股题，而是把 JD、用户项目经历、历史面试错误和任务执行状态统一建模，
通过长期记忆和多源检索识别能力缺口，
再自动生成可执行计划并同步到滴答清单，形成准备闭环。


技术亮点可以讲 5 个：

1. Agent runtime
   参考 akashic-agent 的 lifecycle pipeline，把一次对话拆成多个 phase。

2. 双轨记忆
   SQL 存结构化能力状态，Vector Store 存项目、面经、历史错误和 episodic memory。

3. Source-aware retrieval
   不做裸 Top-K，而是先按 source_type / company / dimension 过滤，再 hybrid retrieval。

4. Shortcoming diagnosis
   核心输出不是答案，而是带证据的 gap_record。

5. Action loop
   把诊断结果变成 TickTick 任务，并根据完成情况主动提醒和重规划。


