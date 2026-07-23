import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import type { Recommendation, TaskStatus } from "./lib/api";

const apiMocks = vi.hoisted(() => ({
  createRecommendation: vi.fn(),
  getHardwareCatalog: vi.fn(),
  getHealth: vi.fn(),
  getRecommendation: vi.fn(),
  getRecommendationStatus: vi.fn(),
  streamRecommendation: vi.fn(),
}));

vi.mock("./lib/api", async (importOriginal) => ({
  ...await importOriginal<typeof import("./lib/api")>(),
  ...apiMocks,
}));

function completedStatus(
  taskId: string,
  responseKind: TaskStatus["response_kind"],
  assistantMessage: string,
): TaskStatus {
  return {
    task_id: taskId,
    status: responseKind === "clarification" ? "needs_clarification" : "completed",
    progress: 100,
    current_agent: null,
    degraded_reason: null,
    response_kind: responseKind,
    assistant_message: assistantMessage,
    follow_up_questions: [],
    agent_runs: [],
  };
}

function degradedResult(taskId: string): Recommendation {
  return {
    task_id: taskId,
    status: "degraded",
    score: 0,
    total_price: 0,
    profile: {
      budget: 0,
      budget_min: 0,
      budget_max: 0,
      resolution: "",
      usage: "",
      case_size: "",
      notes: [],
    },
    parts: [],
    checks: [],
    alternatives: [],
    rationale: ["IntentClassificationAgent AI 调用失败"],
    budget_check: {
      budget_min: 0,
      budget_max: 0,
      target_budget: 0,
      estimated_total: 0,
      delta_from_target: 0,
      utilization_rate: 0,
      passed: false,
      allow_under_budget: false,
    },
    agent_runs: [],
    provenance: {
      mode: "ai_failed",
      build_source: "none",
    },
    sources: [],
    risks: [],
  };
}

describe("App conversation", () => {
  afterEach(cleanup);

  beforeEach(() => {
    Object.values(apiMocks).forEach((mock) => mock.mockReset());
    localStorage.clear();
    Element.prototype.scrollIntoView = vi.fn();
    apiMocks.getHealth.mockResolvedValue(true);
    apiMocks.getHardwareCatalog.mockResolvedValue({
      categories: {},
      items: [],
      total: 0,
    });
    apiMocks.createRecommendation
      .mockResolvedValueOnce({ task_id: "task-1", status: "queued" })
      .mockResolvedValueOnce({ task_id: "task-2", status: "queued" });
    apiMocks.streamRecommendation.mockImplementation(
      async (
        taskId: string,
        handlers: {
          onStatus: (status: TaskStatus) => void;
          onAnswer: (chunk: { kind: "message"; content: string }) => void;
        },
      ) => {
        const reply = taskId === "task-1"
          ? "你好，我可以帮你规划装机。"
          : "已有显卡可以继续使用，请补充整机预算。";
        const kind = taskId === "task-1" ? "casual" : "clarification";
        handlers.onStatus(completedStatus(taskId, kind, reply));
        handlers.onAnswer({ kind: "message", content: reply });
      },
    );
  });

  it("keeps two completed turns and sends prior context with the second request", async () => {
    const user = userEvent.setup();
    render(<App />);

    const textbox = screen.getByRole("textbox");
    await user.type(textbox, "你好");
    await user.keyboard("{Enter}");
    await screen.findByText("你好，我可以帮你规划装机。");

    await user.type(screen.getByRole("textbox"), "我已经有 RTX 4070");
    await user.keyboard("{Enter}");
    await screen.findByText("已有显卡可以继续使用，请补充整机预算。");

    expect(screen.getAllByText("你好").length).toBeGreaterThan(0);
    expect(screen.getAllByText("我已经有 RTX 4070").length).toBeGreaterThan(0);
    expect(apiMocks.createRecommendation).toHaveBeenNthCalledWith(
      2,
      "我已经有 RTX 4070",
      [
        { role: "user", content: "你好" },
        { role: "assistant", content: "你好，我可以帮你规划装机。" },
      ],
    );

    await waitFor(() => {
      const turns = document.querySelectorAll<HTMLDetailsElement>(".conversation-turn");
      expect(turns).toHaveLength(2);
      expect(turns[0].open).toBe(false);
      expect(turns[1].open).toBe(true);
    });
  });

  it("resizes the desktop sidebar with the keyboard and persists the width", async () => {
    const user = userEvent.setup();
    render(<App />);

    const separator = screen.getByRole("separator", { name: "调整侧栏宽度" });
    const frame = document.querySelector<HTMLElement>(".app-frame");

    expect(frame?.style.getPropertyValue("--sidebar-width")).toBe("292px");
    await user.click(separator);
    await user.keyboard("{ArrowRight}");

    expect(frame?.style.getPropertyValue("--sidebar-width")).toBe("304px");
    expect(localStorage.getItem("buildroom-sidebar-width")).toBe("304");

    await user.dblClick(separator);
    expect(frame?.style.getPropertyValue("--sidebar-width")).toBe("292px");
  });

  it("keeps resizing when the pointer moves away from the narrow handle", () => {
    render(<App />);

    const separator = screen.getByRole("separator", { name: "调整侧栏宽度" });
    const frame = document.querySelector<HTMLElement>(".app-frame");

    fireEvent.pointerDown(separator, { clientX: 292, pointerId: 1 });
    fireEvent.pointerMove(window, { clientX: 380, pointerId: 1 });
    fireEvent.pointerUp(window, { clientX: 380, pointerId: 1 });

    expect(frame?.style.getPropertyValue("--sidebar-width")).toBe("380px");
  });

  it("shows an agent failure notice instead of an empty build report", async () => {
    const user = userEvent.setup();
    apiMocks.createRecommendation.mockReset().mockResolvedValue({
      task_id: "task-error",
      status: "queued",
    });
    apiMocks.streamRecommendation.mockReset().mockImplementation(
      async (
        _taskId: string,
        handlers: {
          onStatus: (status: TaskStatus) => void;
          onResult: (result: Recommendation) => void;
        },
      ) => {
        handlers.onStatus({
          ...completedStatus("task-error", "error", ""),
          status: "degraded",
          degraded_reason: "意图智能体暂时无法完成判断，请稍后重试。",
        });
        handlers.onResult(degradedResult("task-error"));
      },
    );
    render(<App />);

    await user.type(screen.getByRole("textbox"), "我已经有 RTX 4070");
    await user.keyboard("{Enter}");

    expect(await screen.findByText("意图智能体暂时无法完成判断，请稍后重试。")).toBeTruthy();
    expect(screen.queryByText("PRIMARY BUILD / RAG GROUNDED")).toBeNull();
  });
});
