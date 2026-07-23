import { describe, expect, it } from "vitest";

import {
  appendTurn,
  buildContextMessages,
  createTurn,
  patchTurn,
  toggleTurn,
} from "./conversation";

describe("conversation turns", () => {
  it("keeps completed turns when a new turn is appended", () => {
    const first = patchTurn(
      [createTurn("第一轮需求", "turn-1", "2026-07-23T10:00:00Z")],
      "turn-1",
      {
        assistantMessage: "第一轮回复",
        status: "completed",
      },
    )[0];

    const turns = appendTurn(
      [first],
      createTurn("补充预算一万元", "turn-2", "2026-07-23T10:01:00Z"),
    );

    expect(turns).toHaveLength(2);
    expect(turns[0].assistantMessage).toBe("第一轮回复");
    expect(turns[0].expanded).toBe(false);
    expect(turns[1].expanded).toBe(true);
  });

  it("updates only the addressed turn", () => {
    const turns = [
      createTurn("第一轮", "turn-1"),
      createTurn("第二轮", "turn-2"),
    ];

    const updated = patchTurn(turns, "turn-1", { status: "completed" });

    expect(updated[0].status).toBe("completed");
    expect(updated[1].status).toBe("queued");
  });

  it("toggles one turn without changing the others", () => {
    const turns = appendTurn(
      [createTurn("第一轮", "turn-1")],
      createTurn("第二轮", "turn-2"),
    );

    const updated = toggleTurn(turns, "turn-1", true);

    expect(updated[0].expanded).toBe(true);
    expect(updated[1].expanded).toBe(true);
  });

  it("builds a bounded role-safe context window", () => {
    const turns = Array.from({ length: 8 }, (_, index) =>
      patchTurn(
        [createTurn(`用户消息 ${index}`, `turn-${index}`)],
        `turn-${index}`,
        { assistantMessage: `助手回复 ${index}`, status: "completed" },
      )[0],
    );

    const context = buildContextMessages(turns);

    expect(context).toHaveLength(12);
    expect(context[context.length - 1]).toEqual({
      role: "assistant",
      content: "助手回复 7",
    });
    expect(context.every((item) => ["user", "assistant"].includes(item.role))).toBe(true);
  });

  it("drops oldest messages until aggregate context is within 12000 characters", () => {
    const turns = Array.from({ length: 4 }, (_, index) =>
      patchTurn(
        [createTurn(`${index}`.repeat(1800), `turn-${index}`)],
        `turn-${index}`,
        { assistantMessage: `${index}`.repeat(1800), status: "completed" },
      )[0],
    );

    const context = buildContextMessages(turns);

    expect(context.reduce((sum, item) => sum + item.content.length, 0)).toBeLessThanOrEqual(12000);
    expect(context[context.length - 1]?.content).toBe("3".repeat(1800));
  });
});
