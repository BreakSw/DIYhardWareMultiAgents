export const MIN_SIDEBAR_WIDTH = 260;
export const MAX_SIDEBAR_WIDTH = 460;
export const DEFAULT_SIDEBAR_WIDTH = 292;
export const SIDEBAR_STORAGE_KEY = "buildroom-sidebar-width";

export function clampSidebarWidth(width: number, viewportWidth: number): number {
  const viewportMaximum = Math.floor(viewportWidth * 0.4);
  const maximum = Math.max(
    MIN_SIDEBAR_WIDTH,
    Math.min(MAX_SIDEBAR_WIDTH, viewportMaximum),
  );
  return Math.min(maximum, Math.max(MIN_SIDEBAR_WIDTH, Math.round(width)));
}

export function readStoredSidebarWidth(
  storedValue: string | null,
  viewportWidth: number,
): number {
  const parsed = Number(storedValue);
  const width = storedValue && Number.isFinite(parsed)
    ? parsed
    : DEFAULT_SIDEBAR_WIDTH;
  return clampSidebarWidth(width, viewportWidth);
}
