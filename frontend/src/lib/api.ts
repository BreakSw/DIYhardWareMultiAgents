const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000/api/v1";

export type TokenUsage = {
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
};

export type AgentEvent = {
  phase: string;
  name: string;
  summary?: string;
  [key: string]: unknown;
};

export type AgentRun = {
  agent_name: string;
  status: "pending" | "queued" | "running" | "completed" | "failed" | "skipped";
  iterations: number;
  input_summary: string;
  output_summary: string;
  latency_ms: number;
  tool_calls: string[];
  events?: AgentEvent[];
  error?: string | null;
  ai_call?: {
    status: "pending" | "success" | "failed";
    provider?: string;
    model?: string;
    latency_ms?: number;
    usage?: TokenUsage;
    error?: string | null;
  };
};

export type PriceRange = {
  min: number;
  max: number;
  currency: "CNY";
  sample_count: number;
};

export type Part = {
  id: string;
  category: string;
  name: string;
  price: number;
  specs: Record<string, string | number | boolean>;
  price_range?: PriceRange;
  evidence?: { title?: string; link?: string; source?: string; retrieval_score?: number };
};

export type TaskStatus = {
  task_id: string;
  status: "queued" | "running" | "completed" | "needs_clarification" | "degraded" | "failed";
  progress: number;
  current_agent: string | null;
  degraded_reason: string | null;
  follow_up_questions: string[];
  agent_runs: AgentRun[];
  ai_usage?: TokenUsage;
};

export type Recommendation = {
  task_id: string;
  status: "completed" | "degraded";
  score: number;
  total_price: number;
  profile: {
    budget: number;
    budget_min: number;
    budget_max: number | null;
    resolution: string;
    usage: string;
    case_size: string;
    include_peripherals?: boolean;
    allow_under_budget?: boolean;
    owned_parts?: Record<string, string>;
    notes: string[];
  };
  parts: Part[];
  checks: { name: string; passed: boolean; severity: string; detail: string }[];
  alternatives: { title: string; detail: string; delta: number }[];
  rationale: string[];
  budget_check: {
    budget_min: number;
    budget_max: number | null;
    target_budget: number;
    estimated_total: number;
    delta_from_target: number;
    utilization_rate: number;
    passed: boolean;
    allow_under_budget: boolean;
  };
  agent_runs: AgentRun[];
  ai_usage?: TokenUsage;
  provenance: {
    mode: "live" | "ai_failed";
    search?: {
      status?: string;
      provider?: string;
      result_count?: number;
      rag?: { retrieval_mode?: string; catalog_count?: number; result_count?: number };
      web?: { status?: string; result_count?: number; error?: string | null };
    };
    llm?: { status?: string; provider?: string; model?: string; agent_call_count?: number };
    build_source: string;
  };
  sources: { title: string; link: string; source: string; price?: string | null }[];
  risks: string[];
};

export type HardwareItem = {
  category: string;
  brand: string;
  model: string;
  market: string;
  specs: Record<string, string | number>;
  price_cny: string | null;
  price_usd: string | null;
  price_usd_min: string | null;
  price_usd_max: string | null;
  quality_level: string;
  source: string | null;
  fetched_at: string | null;
};

export type HardwareCatalog = {
  categories: Record<string, number>;
  items: HardwareItem[];
  total: number;
};

export type AnswerChunk = { kind: "summary" | "part" | "rationale" | "complete"; content: unknown };

type Envelope<T> = { code: number; message: string; data: T };

async function readEnvelope<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const detail = body?.detail?.message ?? body?.detail ?? "后端暂不可用";
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return ((await response.json()) as Envelope<T>).data;
}

export async function createRecommendation(text: string): Promise<{ task_id: string; status: "queued" }> {
  return readEnvelope(
    await fetch(API_BASE + "/recommendations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    }),
  );
}

export async function getRecommendationStatus(taskId: string): Promise<TaskStatus> {
  return readEnvelope(await fetch(`${API_BASE}/recommendations/${taskId}/status`));
}

export async function getRecommendation(taskId: string): Promise<Recommendation> {
  return readEnvelope(await fetch(`${API_BASE}/recommendations/${taskId}`));
}

export async function getHardwareCatalog(category?: string): Promise<HardwareCatalog> {
  const query = category ? `?category=${encodeURIComponent(category)}&limit=18` : "?limit=18";
  return readEnvelope(await fetch(API_BASE + "/hardware/catalog" + query));
}

export async function getHealth(): Promise<boolean> {
  try {
    return (await fetch(API_BASE + "/health")).ok;
  } catch {
    return false;
  }
}

export function streamRecommendation(
  taskId: string,
  handlers: {
    onStatus: (status: TaskStatus) => void;
    onAnswer: (chunk: AnswerChunk) => void;
    onResult: (result: Recommendation) => void;
  },
): Promise<void> {
  return new Promise((resolve, reject) => {
    const source = new EventSource(`${API_BASE}/recommendations/${taskId}/stream`);
    source.addEventListener("status", (event) => handlers.onStatus(JSON.parse(event.data)));
    source.addEventListener("answer", (event) => handlers.onAnswer(JSON.parse(event.data)));
    source.addEventListener("result", (event) => handlers.onResult(JSON.parse(event.data)));
    source.addEventListener("done", () => {
      source.close();
      resolve();
    });
    source.onerror = () => {
      source.close();
      reject(new Error("实时连接中断，请检查后端服务后重试"));
    };
  });
}
