import { expect, test } from "vitest";

import { pollUntilTerminal } from "../src/lib/polling.ts";

test("keeps polling when a valid agent task needs more than 180 checks", async () => {
  let calls = 0;
  const result = await pollUntilTerminal(
    async () => {
      calls += 1;
      return { status: calls > 180 ? "completed" : "running" };
    },
    async () => undefined,
    { maxAttempts: 600 },
  );

  expect(result.status).toBe("completed");
  expect(calls).toBe(181);
});
