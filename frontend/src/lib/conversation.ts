import type {
  AgentRun,
  AnswerChunk,
  ContextMessage,
  Recommendation,
  TaskStatus,
} from "./api";

export type ConversationTurn = {
  id: string;
  taskId: string | null;
  prompt: string;
  createdAt: string;
  status: TaskStatus["status"];
  responseKind: TaskStatus["response_kind"] | "";
  assistantMessage: string;
  expanded: boolean;
  taskStatus: TaskStatus | null;
  agentRuns: AgentRun[];
  answerChunks: AnswerChunk[];
  recommendation: Recommendation | null;
  error: string;
};

export function createTurn(
  prompt: string,
  id: string = crypto.randomUUID(),
  createdAt: string = new Date().toISOString(),
): ConversationTurn {
  return {
    id,
    taskId: null,
    prompt,
    createdAt,
    status: "queued",
    responseKind: "",
    assistantMessage: "",
    expanded: true,
    taskStatus: null,
    agentRuns: [],
    answerChunks: [],
    recommendation: null,
    error: "",
  };
}

export function appendTurn(
  turns: ConversationTurn[],
  turn: ConversationTurn,
): ConversationTurn[] {
  return [
    ...turns.map((item) => ({ ...item, expanded: false })),
    { ...turn, expanded: true },
  ];
}

export function patchTurn(
  turns: ConversationTurn[],
  turnId: string,
  patch: Partial<ConversationTurn>,
): ConversationTurn[] {
  return turns.map((turn) =>
    turn.id === turnId ? { ...turn, ...patch } : turn
  );
}

export function toggleTurn(
  turns: ConversationTurn[],
  turnId: string,
  expanded?: boolean,
): ConversationTurn[] {
  return turns.map((turn) =>
    turn.id === turnId
      ? { ...turn, expanded: expanded ?? !turn.expanded }
      : turn
  );
}

export function buildContextMessages(
  turns: ConversationTurn[],
): ContextMessage[] {
  const messages = turns.flatMap<ContextMessage>((turn) => {
    const items: ContextMessage[] = [
      { role: "user", content: turn.prompt.trim() },
    ];
    if (turn.assistantMessage.trim()) {
      items.push({
        role: "assistant",
        content: turn.assistantMessage.trim(),
      });
    }
    return items;
  }).filter((message) => message.content.length > 0);

  const bounded = messages.slice(-12);
  while (
    bounded.length > 0
    && bounded.reduce((sum, item) => sum + item.content.length, 0) > 12000
  ) {
    bounded.shift();
  }
  return bounded;
}
