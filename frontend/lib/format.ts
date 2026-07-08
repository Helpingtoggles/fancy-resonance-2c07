/** Pure helpers shared across pages (unit-tested in tests/format.test.ts). */

export function formatConfidence(confidence: number | null | undefined): string {
  if (confidence === null || confidence === undefined) return "—";
  return `${Math.round(confidence * 100)}%`;
}

export function confidenceBand(confidence: number | null | undefined): "high" | "medium" | "low" | "none" {
  if (confidence === null || confidence === undefined) return "none";
  if (confidence >= 0.85) return "high";
  if (confidence >= 0.6) return "medium";
  return "low";
}

export function riskBadgeClass(level: string): string {
  return { high: "badge badge-error", medium: "badge badge-warn", low: "badge badge-info" }[level]
    ?? "badge";
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return isNaN(d.getTime()) ? iso : d.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
}

export function statusLabel(status: string): string {
  return status.replaceAll("_", " ");
}
