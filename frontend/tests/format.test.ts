import { describe, expect, it } from "vitest";
import { confidenceBand, formatConfidence, formatDate, riskBadgeClass, statusLabel } from "../lib/format";

describe("formatConfidence", () => {
  it("renders percentages", () => {
    expect(formatConfidence(0.925)).toBe("93%");
    expect(formatConfidence(0)).toBe("0%");
    expect(formatConfidence(1)).toBe("100%");
  });
  it("handles missing values", () => {
    expect(formatConfidence(null)).toBe("—");
    expect(formatConfidence(undefined)).toBe("—");
  });
});

describe("confidenceBand", () => {
  it("bands thresholds", () => {
    expect(confidenceBand(0.9)).toBe("high");
    expect(confidenceBand(0.85)).toBe("high");
    expect(confidenceBand(0.7)).toBe("medium");
    expect(confidenceBand(0.3)).toBe("low");
    expect(confidenceBand(null)).toBe("none");
  });
});

describe("riskBadgeClass", () => {
  it("maps levels", () => {
    expect(riskBadgeClass("high")).toContain("badge-error");
    expect(riskBadgeClass("medium")).toContain("badge-warn");
    expect(riskBadgeClass("low")).toContain("badge-info");
    expect(riskBadgeClass("unknown")).toBe("badge");
  });
});

describe("formatDate", () => {
  it("formats ISO dates", () => {
    expect(formatDate("2026-06-25")).toMatch(/Jun.*2026/);
  });
  it("handles null and junk", () => {
    expect(formatDate(null)).toBe("—");
    expect(formatDate("not-a-date")).toBe("not-a-date");
  });
});

describe("statusLabel", () => {
  it("humanizes snake_case", () => {
    expect(statusLabel("start_of_care")).toBe("start of care");
  });
});
