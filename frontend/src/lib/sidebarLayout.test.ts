import { describe, expect, it } from "vitest";

import {
  DEFAULT_SIDEBAR_WIDTH,
  clampSidebarWidth,
  readStoredSidebarWidth,
} from "./sidebarLayout";

describe("sidebar layout", () => {
  it("clamps the sidebar between 260px and the viewport-safe maximum", () => {
    expect(clampSidebarWidth(120, 1600)).toBe(260);
    expect(clampSidebarWidth(520, 1600)).toBe(460);
    expect(clampSidebarWidth(460, 900)).toBe(360);
  });

  it("uses the default width for invalid persisted values", () => {
    expect(readStoredSidebarWidth(null, 1600)).toBe(DEFAULT_SIDEBAR_WIDTH);
    expect(readStoredSidebarWidth("not-a-number", 1600)).toBe(DEFAULT_SIDEBAR_WIDTH);
  });

  it("clamps a valid persisted width against the current viewport", () => {
    expect(readStoredSidebarWidth("420", 1600)).toBe(420);
    expect(readStoredSidebarWidth("420", 900)).toBe(360);
  });
});
