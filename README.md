# DIY Multi-Agents

本地优先的电脑装机推荐工作台。后端使用 Python 3.13、FastAPI、LangChain 和 LangGraph，前端使用 React + Vite。

## 当前基础功能

- 六个独立 Agent：监督调度、需求解析、搜索与知识、硬件选型、兼容与价格、报告整理。
- LangGraph StateGraph 负责节点、状态、条件分支、一次模型重选和 fallback 复核。
- LangChain ChatOpenAI 通过 DeepSeek 的 OpenAI 兼容接口生成结构化方案。
- SerpAPI 被封装为 LangChain Tool；预算、兼容性和功耗由确定性代码裁决。
- 推荐请求采用进程内后台任务，前端每秒读取真实节点进度。
- 页面内置 20 条手动测试语句，只会运行当前选择的一条。
- MySQL 保留为持久化目标；当前基础版本使用内存任务和样例目录。
- Redis、RAG 和 Qdrant 暂不启用。

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

## 手动测试

1. 打开“20 条手动测试面板”。
2. 选择一条语句。
3. 点击“只运行当前一条”。
4. 查看六节点状态、预算校验、采购清单、trace 和降级原因。

第 13、17 条可能先要求补充用途或预算；第 18 条应返回降级结果，不应伪造可购买清单。

## 代码结构

- backend/app/agents/state.py：共享图状态和六节点名称。
- backend/app/agents/supervisor.py：监督调度 Agent。
- backend/app/agents/requirement.py：需求解析 Agent。
- backend/app/agents/search_knowledge.py：搜索与知识 Agent。
- backend/app/agents/hardware_selection.py：硬件选型 Agent。
- backend/app/agents/compatibility_pricing.py：兼容与价格 Agent。
- backend/app/agents/report.py：报告 Agent。
- backend/app/agents/workflow.py：LangGraph 节点、边和条件回环。
- backend/app/services/llm_client.py：LangChain DeepSeek 结构化输出。
- backend/app/services/recommender.py：进程内任务生命周期。
- frontend/src：工作台、轮询和手动测试面板。

当前任务存储位于进程内存，重启后任务会丢失，这是 localhost 基础版本的预期行为。
