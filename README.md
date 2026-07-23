# DIY Multi-Agents

本地优先的电脑装机推荐工作台。后端使用 Python 3.13、FastAPI、LangChain 和 LangGraph，前端使用 React + Vite。

<p align="center">
  <img alt="Python 3.13" src="https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white">
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-0.110%2B-009688?logo=fastapi&logoColor=white">
  <img alt="LangChain" src="https://img.shields.io/badge/LangChain-Agent-1C3C3C?logo=langchain&logoColor=white">
  <img alt="LangGraph" src="https://img.shields.io/badge/LangGraph-Multi--Agent-0F766E">
  <img alt="React" src="https://img.shields.io/badge/React-18%2B-61DAFB?logo=react&logoColor=black">
  <img alt="Vite" src="https://img.shields.io/badge/Vite-Frontend-646CFF?logo=vite&logoColor=white">
</p>

<p align="center">
  <a href="https://github.com/BreakSw/DIYhardWareMultiAgents/commits/main"><img alt="Last Commit" src="https://img.shields.io/github/last-commit/BreakSw/DIYhardWareMultiAgents"></a>
</p>

## 当前基础功能

- 八个独立 AI Agent：监督调度、意图分类、预算解析、需求解析、搜索与知识、硬件选型、兼容与价格、报告整理。
- LangGraph `StateGraph` 负责共享状态、条件分支、节点审计，以及校验失败后最多一次硬件重选。
- 每个 Agent 通过 LangChain `ChatOpenAI` 调用 DeepSeek 的 OpenAI 兼容接口；预算、兼容性、功耗和最终发布资格仍由确定性规则兜底裁决。
- 已接入本地 RAG：当前硬件目录包含 8 个分类、80 条基础记录，使用 Voyage 向量检索与关键词检索进行混合召回，并缓存文档向量。
- Voyage 不可用时会自动退化为本地关键词检索；SerpAPI 是可选的实时价格补充来源，可通过环境配置启停，避免无意消耗额度。
- 推荐请求在 FastAPI 进程内异步执行，前端通过 SSE 接收真实 Agent 状态、分段回答和最终结果，不使用前端假计时器。
- 前端提供对话式装机工作台、最近任务、硬件新讯、八节点执行轨迹、预算校验、硬件图片、价格区间、来源和风险说明。
- MySQL 连接配置和 SQLAlchemy 模型已经准备，但当前任务与目录仓库仍使用内存实现，服务重启后任务会丢失。
- Redis、Celery 和 Qdrant 当前未进入运行链路。

## Agent 工作流

1. `SupervisorAgent`：理解任务并决定执行路径。
2. `IntentClassificationAgent`：由模型判断是否为装机相关请求；闲聊会友好回应并引导到硬件话题。
3. `BudgetParsingAgent`：专门解析中文数字、`w`、预算区间、上限和“不必花满”等表达。
4. `RequirementAgent`：提取用途、分辨率、外设、已有配件和偏好；信息不足时先回应已知条件，再提出追问。
5. `SearchAndKnowledgeAgent`：规划并执行本地 RAG 检索，按配置选择是否补充 SerpAPI 实时证据。
6. `HardwareSelectionAgent`：结合结构化需求和检索证据生成主方案与备选方案。
7. `CompatibilityAndPricingAgent`：检查预算、接口、尺寸、功耗和价格可信度；失败时最多触发一次重选。
8. `ReportAgent`：只整理通过发布校验的结果、证据、风险和升级建议。

每个节点都会记录状态、耗时、模型 token、工具调用、输入摘要、输出摘要和错误信息，前端可查看真实执行轨迹。

## 环境配置

项目读取根目录的 `env` 文件。请勿把真实密钥提交到仓库，至少需要配置：

~~~text
# DeepSeek：八个 Agent 的大模型推理
model-base-url = ...
model-api-key = ...
model-name = ...

# Voyage：RAG 向量化；缺失时使用关键词检索
embedding-base-url = ...
embedding-api-key = ...
embedding-model = ...

# 本地 RAG 与可选实时搜索
rag-enabled = true
live-search-enabled = false
serpapi-key = ...

# MySQL：当前已准备连接配置，但任务仓库尚未切换为 MySQL 实现
mysql-url = ...
~~~

`live-search-enabled` 默认建议保持关闭，仅在确实需要补充最新价格时开启。

## 启动后端

确认终端显示 Python 3.13：

~~~powershell
python --version
~~~

启动服务：

~~~powershell
cd E:\Desktop\DIY_MultiAgents\backend
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
~~~

接口地址：

- Swagger：http://127.0.0.1:8000/docs
- 健康检查：http://127.0.0.1:8000/api/v1/health

## 启动前端

打开第二个 PowerShell：

~~~powershell
cd E:\Desktop\DIY_MultiAgents\frontend
npm install
npm run dev -- --host 127.0.0.1
~~~

浏览器访问 http://127.0.0.1:5173。

## 使用方式

在首页输入自然语言需求，例如：

~~~text
预算 6000 到 8000 元，只要主机，主要玩 2K 3A 游戏，希望安静并方便升级。
我已经有 RTX 4070，剩余预算 8000 元，请配置其他配件，不要重复购买显卡。
我想配一台电脑，但暂时没想好预算，主要用于 Blender 和本地 AI 推理。
~~~

提交后可查看八个 Agent 的实时状态和执行轨迹。信息不足时系统会提出追问；要求不可实现、预算或兼容性校验失败时会明确降级，而不是把不合格方案显示为“全部通过”。

主要接口：

- `POST /api/v1/recommendations`：创建推荐任务。
- `GET /api/v1/recommendations/{task_id}/status`：获取任务和节点状态。
- `GET /api/v1/recommendations/{task_id}/stream`：通过 SSE 接收状态、回答片段和最终结果。
- `GET /api/v1/recommendations/{task_id}`：获取最终推荐结果。
- `GET /api/v1/recommendations/{task_id}/trace`：获取完整 Agent 执行轨迹。

## 代码结构

- backend/app/agents/state.py：共享图状态和八节点名称。
- backend/app/agents/supervisor.py：监督调度 Agent。
- backend/app/agents/intent_classification.py：装机意图与闲聊分类 Agent。
- backend/app/agents/budget_parsing.py：独立预算解析 Agent。
- backend/app/agents/requirement.py：需求解析 Agent。
- backend/app/agents/search_knowledge.py：RAG 与可选实时搜索 Agent。
- backend/app/agents/hardware_selection.py：硬件选型 Agent。
- backend/app/agents/compatibility_pricing.py：兼容与价格 Agent。
- backend/app/agents/report.py：报告 Agent。
- backend/app/agents/workflow.py：LangGraph 节点、边和条件回环。
- backend/app/services/llm_client.py：LangChain DeepSeek 结构化输出。
- backend/app/services/rag_retriever.py：Voyage 向量与关键词混合检索。
- backend/app/services/recommender.py：进程内任务生命周期。
- backend/data/knowledge/hardware/catalog：本地硬件知识目录。
- frontend/src：对话工作台、SSE 流式展示、Agent 轨迹和硬件目录界面。

当前版本面向 localhost 开发。任务存储位于进程内存，服务重启后任务会丢失；在正式部署前需要将仓库实现切换为 MySQL，并增加持久化任务队列。
