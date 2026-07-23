import { useEffect, useRef, useState, type CSSProperties } from "react";
import {
  createRecommendation,
  getHardwareCatalog,
  getHealth,
  getRecommendation,
  getRecommendationStatus,
  streamRecommendation,
  type AgentRun,
  type AnswerChunk,
  type HardwareCatalog,
  type Part,
  type Recommendation,
  type TaskStatus,
} from "./lib/api";
import {
  appendTurn,
  buildContextMessages,
  createTurn,
  patchTurn,
  toggleTurn,
  type ConversationTurn,
} from "./lib/conversation";
import {
  DEFAULT_SIDEBAR_WIDTH,
  MIN_SIDEBAR_WIDTH,
  SIDEBAR_STORAGE_KEY,
  clampSidebarWidth,
  readStoredSidebarWidth,
} from "./lib/sidebarLayout";

const AGENT_NAMES = [
  "SupervisorAgent",
  "IntentClassificationAgent",
  "BudgetParsingAgent",
  "RequirementAgent",
  "SearchAndKnowledgeAgent",
  "HardwareSelectionAgent",
  "CompatibilityAndPricingAgent",
  "ReportAgent",
] as const;

const agentLabels: Record<string, string> = {
  SupervisorAgent: "监督调度",
  IntentClassificationAgent: "意图识别",
  BudgetParsingAgent: "预算解析",
  RequirementAgent: "需求分析",
  SearchAndKnowledgeAgent: "知识检索",
  HardwareSelectionAgent: "硬件选型",
  CompatibilityAndPricingAgent: "兼容与价格",
  ReportAgent: "报告整理",
};

const categoryLabels: Record<string, string> = {
  cpu: "处理器",
  gpu: "显卡",
  motherboard: "主板",
  memory: "内存",
  storage: "存储",
  psu: "电源",
  cooler: "散热",
  case: "机箱",
  monitor: "显示器",
  keyboard: "键盘",
  mouse: "鼠标",
};

const suggestions = [
  "预算 6000 到 8000 元，主要玩 2K 3A 游戏，只要主机",
  "预算 2w-3w，4K 游戏与直播，优先静音和后续升级",
  "已有 RTX 4070，剩余预算 8000 元，补齐其他配件",
];

const emptyRuns: AgentRun[] = AGENT_NAMES.map((agent_name) => ({
  agent_name,
  status: "pending",
  iterations: 0,
  input_summary: "",
  output_summary: "",
  latency_ms: 0,
  tool_calls: [],
  ai_call: { status: "pending", usage: { input_tokens: 0, output_tokens: 0, total_tokens: 0 } },
}));

type HistoryEntry = {
  taskId: string;
  prompt: string;
  status: string;
  createdAt: string;
};

function App() {
  const [draft, setDraft] = useState("");
  const [turns, setTurns] = useState<ConversationTurn[]>([]);
  const [selectedTurnId, setSelectedTurnId] = useState<string | null>(null);
  const [online, setOnline] = useState(false);
  const [loading, setLoading] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [sidebarWidth, setSidebarWidth] = useState(() =>
    readStoredSidebarWidth(
      localStorage.getItem(SIDEBAR_STORAGE_KEY),
      window.innerWidth,
    )
  );
  const [traceOpen, setTraceOpen] = useState(() => window.innerWidth > 1030);
  const [catalog, setCatalog] = useState<HardwareCatalog | null>(null);
  const [category, setCategory] = useState("");
  const [history, setHistory] = useState<HistoryEntry[]>(() => {
    try {
      return JSON.parse(localStorage.getItem("buildroom-history") ?? "[]");
    } catch {
      return [];
    }
  });
  const endRef = useRef<HTMLDivElement>(null);
  const sidebarDragCleanup = useRef<(() => void) | null>(null);

  useEffect(() => {
    getHealth().then(setOnline);
    getHardwareCatalog().then(setCatalog).catch(() => setCatalog(null));
  }, []);

  useEffect(() => {
    localStorage.setItem("buildroom-history", JSON.stringify(history.slice(0, 12)));
  }, [history]);

  useEffect(() => {
    localStorage.setItem(SIDEBAR_STORAGE_KEY, String(sidebarWidth));
  }, [sidebarWidth]);

  useEffect(() => {
    const onResize = () => {
      setSidebarWidth((width) => clampSidebarWidth(width, window.innerWidth));
    };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  useEffect(() => () => sidebarDragCleanup.current?.(), []);

  useEffect(() => {
    if (loading || turns.length) {
      endRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [loading, turns]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        newConversation();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  async function selectCategory(next: string) {
    setCategory(next);
    setCatalog(await getHardwareCatalog(next || undefined));
  }

  function newConversation() {
    setDraft("");
    setTurns([]);
    setSelectedTurnId(null);
    setSidebarOpen(false);
  }

  async function submit() {
    const text = draft.trim();
    if (loading || text.length < 2) return;
    const turn = createTurn(text);
    const contextMessages = buildContextMessages(turns);
    setTurns((items) => appendTurn(items, turn));
    setSelectedTurnId(turn.id);
    setDraft("");
    setLoading(true);
    try {
      const created = await createRecommendation(text, contextMessages);
      setTurns((items) => patchTurn(items, turn.id, { taskId: created.task_id }));
      const entry: HistoryEntry = {
        taskId: created.task_id,
        prompt: text,
        status: "queued",
        createdAt: new Date().toISOString(),
      };
      setHistory((items) => [entry, ...items.filter((item) => item.taskId !== entry.taskId)]);
      await streamRecommendation(created.task_id, {
        onStatus: (status) => {
          setTurns((items) => items.map((item) =>
            item.id === turn.id
              ? {
                  ...item,
                  status: status.status,
                  responseKind: status.response_kind,
                  assistantMessage: status.assistant_message || item.assistantMessage,
                  taskStatus: status,
                  agentRuns: status.agent_runs,
                  error:
                    status.response_kind === "error"
                      ? status.degraded_reason || "智能体暂时无法完成任务，请稍后重试。"
                      : item.error,
                  recommendation:
                    status.response_kind === "error"
                      ? null
                      : item.recommendation,
                }
              : item
          ));
          setHistory((items) =>
            items.map((item) => item.taskId === status.task_id ? { ...item, status: status.status } : item),
          );
        },
        onAnswer: (chunk) => {
          setTurns((items) => items.map((item) =>
            item.id === turn.id
              ? {
                  ...item,
                  answerChunks: [...item.answerChunks, chunk],
                  assistantMessage:
                    chunk.kind === "message" && typeof chunk.content === "string"
                      ? chunk.content
                      : item.assistantMessage,
                }
              : item
          ));
        },
        onResult: (result) => {
          setTurns((items) => items.map((item) =>
            item.id === turn.id
              ? item.responseKind && item.responseKind !== "recommendation"
                ? {
                    ...item,
                    status: result.status,
                    agentRuns: result.agent_runs,
                  }
                : {
                    ...item,
                    status: result.status,
                    responseKind: "recommendation",
                    recommendation: result,
                    agentRuns: result.agent_runs,
                  }
              : item
          ));
        },
      });
    } catch (reason) {
      setTurns((items) => patchTurn(items, turn.id, {
        status: "failed",
        responseKind: "error",
        error: reason instanceof Error ? reason.message : "任务执行失败",
      }));
    } finally {
      setLoading(false);
    }
  }

  async function openHistory(item: HistoryEntry) {
    setSidebarOpen(false);
    try {
      const status = await getRecommendationStatus(item.taskId);
      let loadedRecommendation: Recommendation | null = null;
      if (
        status.response_kind === "recommendation"
        && (status.status === "completed" || status.status === "degraded")
      ) {
        loadedRecommendation = await getRecommendation(item.taskId);
      }
      const loadedTurn: ConversationTurn = {
        ...createTurn(item.prompt, `history-${item.taskId}`, item.createdAt),
        taskId: item.taskId,
        status: status.status,
        responseKind: status.response_kind,
        assistantMessage: status.assistant_message,
        taskStatus: status,
        agentRuns: status.agent_runs,
        recommendation: loadedRecommendation,
        error:
          status.response_kind === "error"
            ? status.degraded_reason || "智能体暂时无法完成任务，请稍后重试。"
            : "",
      };
      setTurns([loadedTurn]);
      setSelectedTurnId(loadedTurn.id);
      setDraft("");
    } catch (reason) {
      const failedTurn = {
        ...createTurn(item.prompt, `history-${item.taskId}`, item.createdAt),
        taskId: item.taskId,
        status: "failed" as const,
        responseKind: "error" as const,
        error: reason instanceof Error ? reason.message : "无法读取历史任务",
      };
      setTurns([failedTurn]);
      setSelectedTurnId(failedTurn.id);
    }
  }

  const selectedTurn =
    turns.find((turn) => turn.id === selectedTurnId)
    ?? turns[turns.length - 1]
    ?? null;
  const runs = selectedTurn?.agentRuns.length ? selectedTurn.agentRuns : emptyRuns;
  const taskStatus = selectedTurn?.taskStatus ?? null;
  const hasConversation = turns.length > 0;
  const frameStyle = {
    "--sidebar-width": `${sidebarWidth}px`,
  } as CSSProperties;

  return (
    <div className="app-frame" style={frameStyle}>
      <button className="mobile-menu" onClick={() => setSidebarOpen(true)} aria-label="打开侧栏">
        <MenuIcon />
      </button>
      <Sidebar
        open={sidebarOpen}
        online={online}
        history={history}
        catalog={catalog}
        category={category}
        onClose={() => setSidebarOpen(false)}
        onNew={newConversation}
        onHistory={openHistory}
        onCategory={selectCategory}
      />
      <div
        className="sidebar-resizer"
        role="separator"
        aria-label="调整侧栏宽度"
        aria-orientation="vertical"
        aria-valuemin={MIN_SIDEBAR_WIDTH}
        aria-valuemax={clampSidebarWidth(Number.MAX_SAFE_INTEGER, window.innerWidth)}
        aria-valuenow={sidebarWidth}
        tabIndex={0}
        onPointerDown={(event) => {
          event.currentTarget.focus();
          event.preventDefault();
          sidebarDragCleanup.current?.();
          document.body.classList.add("resizing-sidebar");
          const onMove = (moveEvent: PointerEvent) => {
            setSidebarWidth(
              clampSidebarWidth(moveEvent.clientX, window.innerWidth),
            );
          };
          const stopDragging = () => {
            window.removeEventListener("pointermove", onMove);
            window.removeEventListener("pointerup", stopDragging);
            window.removeEventListener("pointercancel", stopDragging);
            document.body.classList.remove("resizing-sidebar");
            sidebarDragCleanup.current = null;
          };
          sidebarDragCleanup.current = stopDragging;
          window.addEventListener("pointermove", onMove);
          window.addEventListener("pointerup", stopDragging);
          window.addEventListener("pointercancel", stopDragging);
        }}
        onKeyDown={(event) => {
          if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
          event.preventDefault();
          const delta = event.key === "ArrowRight" ? 12 : -12;
          setSidebarWidth((width) =>
            clampSidebarWidth(width + delta, window.innerWidth)
          );
        }}
        onDoubleClick={() => {
          setSidebarWidth(
            clampSidebarWidth(DEFAULT_SIDEBAR_WIDTH, window.innerWidth),
          );
        }}
      >
        <span />
      </div>

      <main className={"conversation " + (traceOpen ? "with-trace" : "") }>
        <header className="conversation-bar">
          <div>
            <span className="crumb">BUILDROOM / CONFIGURATION DESK</span>
            <strong>{hasConversation ? "装机方案对话" : "新的装机对话"}</strong>
          </div>
          <button className={traceOpen ? "active" : ""} onClick={() => setTraceOpen((value) => !value)}>
            <TraceIcon /> Agent 轨迹
          </button>
        </header>

        <section className={hasConversation ? "chat-stream active" : "chat-stream welcome"}>
          {!hasConversation && (
            <Welcome prompt={draft} setPrompt={setDraft} onSubmit={submit} loading={loading} />
          )}

          {turns.map((turn, index) => (
            <ConversationTurnCard
              key={turn.id}
              turn={turn}
              index={index}
              active={turn.id === selectedTurn?.id}
              onSelect={() => setSelectedTurnId(turn.id)}
              onToggle={() => setTurns((items) => toggleTurn(items, turn.id))}
            />
          ))}
          <div ref={endRef} />
        </section>

        {hasConversation && (
          <Composer value={draft} setValue={setDraft} onSubmit={submit} loading={loading} />
        )}
      </main>

      {traceOpen && (
        <TracePanel runs={runs} status={taskStatus} onClose={() => setTraceOpen(false)} />
      )}
    </div>
  );
}

function ConversationTurnCard({
  turn,
  index,
  active,
  onSelect,
  onToggle,
}: {
  turn: ConversationTurn;
  index: number;
  active: boolean;
  onSelect: () => void;
  onToggle: () => void;
}) {
  const running = turn.status === "queued" || turn.status === "running";
  const runs = turn.agentRuns.length ? turn.agentRuns : emptyRuns;
  const showAssistantMessage = Boolean(turn.assistantMessage) && !running;
  const showStream = turn.answerChunks.length > 0 && !showAssistantMessage && !turn.recommendation;

  return (
    <details className={`conversation-turn ${active ? "active" : ""}`} open={turn.expanded}>
      <summary
        onClick={(event) => {
          event.preventDefault();
          onSelect();
          onToggle();
        }}
      >
        <span className="turn-number">{String(index + 1).padStart(2, "0")}</span>
        <span className="turn-title">
          <strong>{turn.prompt}</strong>
          <small>{formatDate(turn.createdAt)} · {statusLabel(turn.status)}</small>
        </span>
        <span className="turn-state">{turn.expanded ? "收起" : "展开"}</span>
      </summary>
      <div className="turn-content">
        <article className="message user-message">
          <div className="message-avatar user-avatar">你</div>
          <div className="message-body">
            <span className="message-role">你的需求</span>
            <p>{turn.prompt}</p>
          </div>
        </article>

        <article className="message assistant-message">
          <AgentAvatar />
          <div className="message-body">
            <div className="assistant-heading">
              <div>
                <span className="message-role">Buildroom 装机智能体</span>
                <small>8-Agent · DeepSeek · RAG</small>
              </div>
              {turn.taskStatus && (
                <ProgressPill
                  progress={turn.taskStatus.progress}
                  status={turn.taskStatus.status}
                />
              )}
            </div>

            {running && !turn.answerChunks.length && (
              <div className="working-copy">
                <i />
                <div>
                  <strong>
                    {turn.taskStatus?.current_agent
                      ? agentLabels[turn.taskStatus.current_agent]
                      : "正在建立任务"}
                  </strong>
                  <p>{currentRunSummary(runs)}</p>
                </div>
              </div>
            )}

            {showStream && (
              <div className="streaming-answer">
                {turn.answerChunks.map((chunk, chunkIndex) => (
                  <StreamChunk key={chunkIndex} chunk={chunk} />
                ))}
                {running && <span className="stream-caret" />}
              </div>
            )}

            {showAssistantMessage && (
              <div className={`assistant-copy ${turn.responseKind}`}>
                {turn.assistantMessage.split("\n").map((line, lineIndex) =>
                  line.trim() ? <p key={lineIndex}>{line}</p> : null
                )}
              </div>
            )}
            {turn.error && <NoticeCard title="任务未完成" text={turn.error} danger />}
            {turn.recommendation && <BuildResult result={turn.recommendation} />}
          </div>
        </article>
      </div>
    </details>
  );
}

function Sidebar(props: {
  open: boolean;
  online: boolean;
  history: HistoryEntry[];
  catalog: HardwareCatalog | null;
  category: string;
  onClose: () => void;
  onNew: () => void;
  onHistory: (item: HistoryEntry) => void;
  onCategory: (category: string) => void;
}) {
  return (
    <>
      {props.open && <button className="sidebar-scrim" onClick={props.onClose} aria-label="关闭侧栏" />}
      <aside className={"sidebar " + (props.open ? "open" : "")}>
        <div className="sidebar-brand">
          <span>B</span><div><strong>BUILDROOM</strong><small>AI HARDWARE ATELIER</small></div>
          <button onClick={props.onClose} aria-label="关闭侧栏"><CloseIcon /></button>
        </div>
        <button className="new-task" onClick={props.onNew}><PlusIcon /> 新建装机任务 <kbd>Ctrl K</kbd></button>

        <section className="side-section history-section">
          <div className="side-title"><span>最近任务</span><b>{props.history.length}</b></div>
          <div className="history-list">
            {props.history.length === 0 && <p className="empty-side">还没有任务，先描述你想要的电脑。</p>}
            {props.history.map((item) => (
              <button key={item.taskId} onClick={() => props.onHistory(item)}>
                <ChatIcon />
                <span><strong>{item.prompt}</strong><small>{formatDate(item.createdAt)} · {statusLabel(item.status)}</small></span>
              </button>
            ))}
          </div>
        </section>

        <section className="side-section hardware-section">
          <div className="side-title"><span>硬件新讯</span><b>RAG</b></div>
          <div className="category-tabs">
            <button className={!props.category ? "active" : ""} onClick={() => props.onCategory("")}>全部</button>
            {Object.entries(props.catalog?.categories ?? {}).map(([name, count]) => (
              <button className={props.category === name ? "active" : ""} key={name} onClick={() => props.onCategory(name)}>
                {categoryLabels[name] ?? name}<sup>{count}</sup>
              </button>
            ))}
          </div>
          <div className="hardware-feed">
            {(props.catalog?.items ?? []).slice(0, 8).map((item) => (
              <button key={`${item.category}-${item.model}`} onClick={() => item.source && window.open(item.source, "_blank", "noopener,noreferrer")}>
                <HardwareArtwork category={item.category} compact />
                <span><small>{categoryLabels[item.category] ?? item.category} · {item.quality_level}</small><strong>{hardwareName(item.brand, item.model)}</strong><em>{item.price_cny ? `¥${Math.round(Number(item.price_cny)).toLocaleString()}` : "待核价"}</em></span>
              </button>
            ))}
          </div>
        </section>
        <div className="service-chip"><i className={props.online ? "online" : ""} /><span>{props.online ? "本地服务在线" : "服务离线"}<small>MySQL · Voyage RAG</small></span></div>
      </aside>
    </>
  );
}

function Welcome({ prompt, setPrompt, onSubmit, loading }: { prompt: string; setPrompt: (value: string) => void; onSubmit: () => void; loading: boolean }) {
  return (
    <div className="welcome-inner">
      <div className="welcome-mark"><AgentAvatar large /></div>
      <p className="eyebrow">MULTI-AGENT PC CONFIGURATION</p>
      <h1>把你的设想，<br />装进一台<span>可靠的电脑。</span></h1>
      <p className="welcome-lead">说预算、用途和偏好。八个 AI Agent 会识别意图、解析预算、检索真实知识、完成选型与硬校验。</p>
      <Composer value={prompt} setValue={setPrompt} onSubmit={onSubmit} loading={loading} hero />
      <div className="suggestions">
        {suggestions.map((item, index) => <button key={item} onClick={() => setPrompt(item)}><span>0{index + 1}</span>{item}<ArrowIcon /></button>)}
      </div>
      <div className="trust-row"><span><i />非装机问题会先被识别</span><span><i />RAG 证据可追溯</span><span><i />预算与兼容性硬校验</span></div>
    </div>
  );
}

function Composer({ value, setValue, onSubmit, loading, hero = false }: { value: string; setValue: (value: string) => void; onSubmit: () => void; loading: boolean; hero?: boolean }) {
  return (
    <div className={hero ? "composer hero-composer" : "composer docked-composer"}>
      <textarea
        value={value}
        onChange={(event) => setValue(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            onSubmit();
          }
        }}
        placeholder="例如：预算 1.2 万，只要主机，主要玩 2K 3A 游戏，希望安静且方便升级"
        maxLength={2000}
        aria-label="装机需求"
      />
      <div className="composer-foot"><span>{value.length}/2000 · Enter 发送，Shift+Enter 换行</span><button disabled={loading || value.trim().length < 2} onClick={onSubmit} aria-label="发送需求">{loading ? <LoadingIcon /> : <ArrowUpIcon />}</button></div>
    </div>
  );
}

function TracePanel({ runs, status, onClose }: { runs: AgentRun[]; status: TaskStatus | null; onClose: () => void }) {
  return (
    <aside className="trace-panel">
      <header><div><span>LIVE EXECUTION</span><strong>Agent 行为轨迹</strong></div><button onClick={onClose} aria-label="关闭轨迹"><CloseIcon /></button></header>
      <div className="trace-progress"><span><i style={{ width: `${status?.progress ?? 0}%` }} /></span><b>{status?.progress ?? 0}%</b></div>
      <p className="trace-note">展示结构化输出、工具与耗时，不伪造模型隐藏思维链。</p>
      <div className="trace-list">
        {runs.map((run, index) => (
          <details className={`trace-node ${run.status}`} key={run.agent_name} open={run.status === "running"}>
            <summary>
              <span className="trace-index">{String(index + 1).padStart(2, "0")}</span>
              <span><strong>{agentLabels[run.agent_name] ?? run.agent_name}</strong><small>{run.status} {run.ai_call?.usage?.total_tokens ? `· ${run.ai_call.usage.total_tokens} tok` : ""}</small></span>
              <i />
            </summary>
            <div className="trace-detail">
              {run.input_summary && <p><b>输入</b>{run.input_summary}</p>}
              {run.output_summary && <p><b>返回</b>{run.output_summary}</p>}
              {!!run.tool_calls.length && <p><b>工具</b>{run.tool_calls.join(" · ")}</p>}
              {!!run.events?.length && run.events.map((event, eventIndex) => <p key={eventIndex}><b>{event.phase}</b>{event.summary ?? event.name}</p>)}
              <p><b>耗时</b>{run.latency_ms} ms</p>
            </div>
          </details>
        ))}
      </div>
      <footer><span>DEEPSEEK CALLS</span><strong>{runs.filter((run) => run.ai_call?.status === "success").length}/{runs.length}</strong></footer>
    </aside>
  );
}

function BuildResult({ result }: { result: Recommendation }) {
  const budget = result.budget_check;
  return (
    <div className="build-result">
      <section className="result-hero">
        <div><span className="result-kicker">PRIMARY BUILD / RAG GROUNDED</span><h2>{result.profile.resolution} · {result.profile.usage}</h2><p>{result.rationale[0]}</p></div>
        <div className="score-orb"><strong>{result.score}</strong><span>/ 100<br />FIT SCORE</span></div>
      </section>
      <section className="budget-strip">
        <div><span>预计总价</span><strong>¥{result.total_price.toLocaleString()}</strong></div>
        <div><span>预算区间</span><strong>{budget.budget_max === null ? `¥${budget.budget_min.toLocaleString()}+` : `¥${budget.budget_min.toLocaleString()}–${budget.budget_max.toLocaleString()}`}</strong></div>
        <div><span>目标差额</span><strong>{budget.delta_from_target > 0 ? "+" : ""}¥{budget.delta_from_target.toLocaleString()}</strong></div>
        <div><span>发布校验</span><strong className={budget.passed ? "pass" : "fail"}>{budget.passed ? "已通过" : "未通过"}</strong></div>
      </section>

      {result.parts.length ? (
        <section className="parts-grid">
          {result.parts.map((part, index) => <PartCard part={part} index={index} key={part.id} />)}
        </section>
      ) : <NoticeCard title="未发布采购清单" text={result.rationale.join(" ")} danger />}

      <div className="result-columns">
        <section className="result-section"><div className="section-title"><span>WHY THIS BUILD</span><strong>选择依据</strong></div>{result.rationale.map((line) => <p key={line}>{line}</p>)}</section>
        <section className="result-section"><div className="section-title"><span>HARD GATES</span><strong>兼容审查</strong></div>{result.checks.map((check) => <div className="check-line" key={check.name}><i className={check.passed ? "pass" : "fail"}>{check.passed ? "✓" : "!"}</i><span><strong>{check.name}</strong><small>{check.detail}</small></span></div>)}</section>
      </div>

      <section className="evidence-section">
        <div className="section-title"><span>PROVENANCE</span><strong>知识与价格来源</strong></div>
        <div className="evidence-metrics">
          <span>RAG <b>{result.provenance.search?.rag?.retrieval_mode ?? "unknown"}</b></span>
          <span>知识记录 <b>{result.provenance.search?.rag?.catalog_count ?? 0}</b></span>
          <span>DeepSeek 调用 <b>{result.provenance.llm?.agent_call_count ?? 0}</b></span>
          <span>Token <b>{result.ai_usage?.total_tokens ?? 0}</b></span>
        </div>
        <div className="source-list">{result.sources.map((source) => <button key={source.link || source.title} onClick={() => source.link && window.open(source.link, "_blank", "noopener,noreferrer")}><span>{source.source}</span><strong>{source.title}</strong><small>{source.price ? `参考 ¥${source.price}` : "查看原始来源"}</small><ArrowIcon /></button>)}</div>
      </section>
    </div>
  );
}

function PartCard({ part, index }: { part: Part; index: number }) {
  const range = part.price_range;
  return (
    <article className="part-card">
      <div className="part-visual"><span>{String(index + 1).padStart(2, "0")}</span><HardwareArtwork category={part.category} /></div>
      <div className="part-copy"><small>{categoryLabels[part.category] ?? part.category}</small><h3>{part.name}</h3><div className="spec-pills">{Object.entries(part.specs).slice(0, 3).map(([key, value]) => <span key={key}>{key}: {String(value)}</span>)}</div></div>
      <div className="part-cost"><strong>¥{part.price.toLocaleString()}</strong><small>{range ? `证据范围 ¥${range.min.toLocaleString()}–${range.max.toLocaleString()} · ${range.sample_count} 条` : "当前方案估价"}</small>{part.evidence?.link && <button onClick={() => window.open(part.evidence?.link, "_blank", "noopener,noreferrer")}>查看依据 <ArrowIcon /></button>}</div>
    </article>
  );
}

function HardwareArtwork({ category, compact = false }: { category: string; compact?: boolean }) {
  return <span className={`hardware-art art-${category} ${compact ? "compact" : ""}`} role="img" aria-label={categoryLabels[category] ?? category}><HardwareGlyph category={category} /></span>;
}

function HardwareGlyph({ category }: { category: string }) {
  if (category === "gpu") return <svg viewBox="0 0 120 80"><rect x="8" y="18" width="98" height="48" rx="8"/><circle cx="40" cy="42" r="15"/><circle cx="76" cy="42" r="15"/><path d="M106 31h8v22h-8M18 66v7m12-7v7m12-7v7"/></svg>;
  if (category === "memory") return <svg viewBox="0 0 120 80"><rect x="10" y="24" width="100" height="32" rx="5"/><rect x="22" y="31" width="18" height="16"/><rect x="51" y="31" width="18" height="16"/><rect x="80" y="31" width="18" height="16"/><path d="M24 56v8m12-8v8m48-8v8m12-8v8"/></svg>;
  if (category === "storage") return <svg viewBox="0 0 120 80"><rect x="18" y="18" width="84" height="48" rx="7"/><circle cx="36" cy="42" r="5"/><path d="M50 34h37M50 43h37M50 52h25"/></svg>;
  if (category === "psu") return <svg viewBox="0 0 120 80"><rect x="20" y="12" width="80" height="58" rx="8"/><circle cx="55" cy="41" r="22"/><circle cx="55" cy="41" r="8"/><path d="M82 28h8v9h-8m0 8h8v9h-8"/></svg>;
  if (category === "cooler") return <svg viewBox="0 0 120 80"><rect x="27" y="8" width="66" height="64" rx="8"/><circle cx="60" cy="40" r="24"/><path d="M60 16c8 9 8 17 0 24-8-7-8-15 0-24Zm24 24c-9 8-17 8-24 0 7-8 15-8 24 0ZM60 64c-8-9-8-17 0-24 8 7 8 15 0 24ZM36 40c9-8 17-8 24 0-7 8-15 8-24 0Z"/></svg>;
  if (category === "case") return <svg viewBox="0 0 120 80"><path d="M30 8h60v64H30z"/><path d="M42 18h36v34H42z"/><circle cx="60" cy="35" r="12"/><circle cx="42" cy="63" r="3"/><path d="M51 63h24"/></svg>;
  if (category === "motherboard") return <svg viewBox="0 0 120 80"><rect x="15" y="8" width="90" height="64" rx="6"/><rect x="28" y="18" width="35" height="30"/><path d="M73 18h19M73 27h19M73 36h19M28 58h64M70 48v10"/><circle cx="93" cy="61" r="4"/></svg>;
  return <svg viewBox="0 0 120 80"><rect x="27" y="9" width="66" height="62" rx="9"/><rect x="39" y="21" width="42" height="38" rx="5"/><path d="M18 22h9m-9 12h9m-9 12h9m-9 12h9M93 22h9m-9 12h9m-9 12h9m-9 12h9"/></svg>;
}

function StreamChunk({ chunk }: { chunk: AnswerChunk }) {
  if (chunk.kind === "part") {
    const part = chunk.content as Part;
    return <p><b>{categoryLabels[part.category] ?? part.category}</b> {part.name} · ¥{part.price.toLocaleString()}</p>;
  }
  return <p>{String(chunk.content)}</p>;
}

function ProgressPill({ progress, status }: { progress: number; status: string }) {
  return <span className={`progress-pill ${status}`}><i style={{ width: `${progress}%` }} /><b>{statusLabel(status)} · {progress}%</b></span>;
}

function NoticeCard({ title, text, danger = false }: { title: string; text: string; danger?: boolean }) {
  return <div className={`notice-card ${danger ? "danger" : ""}`}><strong>{title}</strong><p>{text}</p></div>;
}

function AgentAvatar({ large = false }: { large?: boolean }) {
  return <div className={`agent-avatar ${large ? "large" : ""}`}><img src="/brand/buildroom-agent.png" alt="Buildroom 装机智能体" /></div>;
}

function currentRunSummary(runs: AgentRun[]) {
  const current = runs.find((run) => run.status === "running");
  return current?.input_summary || "正在等待下一个 Agent 接手任务…";
}

function statusLabel(status: string) {
  return ({ queued: "排队中", running: "执行中", completed: "已完成", needs_clarification: "待补充", degraded: "已降级", failed: "失败", skipped: "已跳过", pending: "等待中" } as Record<string, string>)[status] ?? status;
}

function formatDate(value: string) {
  const date = new Date(value);
  return `${date.getMonth() + 1}/${date.getDate()} ${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}

function hardwareName(brand: string, model: string) {
  return model.toLowerCase().startsWith(brand.toLowerCase()) ? model : `${brand} ${model}`;
}

function MenuIcon() { return <svg viewBox="0 0 24 24"><path d="M4 7h16M4 12h16M4 17h16" /></svg>; }
function CloseIcon() { return <svg viewBox="0 0 24 24"><path d="m6 6 12 12M18 6 6 18" /></svg>; }
function PlusIcon() { return <svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14" /></svg>; }
function ChatIcon() { return <svg viewBox="0 0 24 24"><path d="M5 5h14v11H9l-4 3V5Z" /></svg>; }
function TraceIcon() { return <svg viewBox="0 0 24 24"><circle cx="6" cy="6" r="2"/><circle cx="18" cy="8" r="2"/><circle cx="8" cy="18" r="2"/><path d="m8 7 8 1M7 8l1 8m2 1 6-7"/></svg>; }
function ArrowIcon() { return <svg viewBox="0 0 24 24"><path d="M7 17 17 7M8 7h9v9" /></svg>; }
function ArrowUpIcon() { return <svg viewBox="0 0 24 24"><path d="m6 11 6-6 6 6M12 5v14" /></svg>; }
function LoadingIcon() { return <svg className="loading-icon" viewBox="0 0 24 24"><path d="M20 12a8 8 0 1 1-2.3-5.7" /></svg>; }

export default App;
