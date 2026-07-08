"use client";

import { confidenceBand, formatConfidence } from "@/lib/format";

/** Confidence indicator shown next to every AI-suggested value. */
export default function Confidence({ value }: { value: number | null | undefined }) {
  const band = confidenceBand(value);
  return (
    <span className={`conf conf-${band}`} title="Extraction confidence">
      {formatConfidence(value)}
    </span>
  );
}
