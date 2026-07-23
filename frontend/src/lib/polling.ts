export type PollOptions<T> = {
  maxAttempts?: number;
  onStatus?: (status: T) => void;
};

const TERMINAL_STATUSES = new Set([
  "completed",
  "needs_clarification",
  "degraded",
  "failed",
]);

export async function pollUntilTerminal<T extends { status: string }>(
  fetchStatus: () => Promise<T>,
  wait: () => Promise<unknown>,
  options: PollOptions<T> = {},
): Promise<T> {
  const maxAttempts = options.maxAttempts ?? 600;
  let latest: T | null = null;

  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    latest = await fetchStatus();
    options.onStatus?.(latest);
    if (TERMINAL_STATUSES.has(latest.status)) return latest;
    await wait();
  }

  throw new Error(
    latest
      ? `任务仍在执行（当前状态：${latest.status}），请稍后继续查看`
      : "无法读取任务状态",
  );
}
