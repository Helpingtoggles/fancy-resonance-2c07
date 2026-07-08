"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import Shell from "@/components/Shell";
import { api } from "@/lib/api";
import { formatDate, statusLabel } from "@/lib/format";

type ReviewTask = {
  id: string; title: string; status: string; priority: string;
  subject_type: string; episode_id: string | null; created_at: string;
};
type LedgerStats = { evidence_records: number; extracted_fields: number };

export default function Dashboard() {
  const [tasks, setTasks] = useState<ReviewTask[]>([]);
  const [stats, setStats] = useState<LedgerStats | null>(null);
  const [ledgerValid, setLedgerValid] = useState<boolean | null>(null);

  useEffect(() => {
    api<ReviewTask[]>("/api/v1/review/tasks").then(setTasks).catch(() => {});
    api<LedgerStats>("/api/v1/evidence/ledger/stats").then(setStats).catch(() => {});
    api<{ valid: boolean }>("/api/v1/evidence/ledger/verify")
      .then((r) => setLedgerValid(r.valid)).catch(() => {});
  }, []);

  const urgent = tasks.filter((t) => t.priority === "urgent" || t.priority === "high");

  return (
    <Shell>
      <h1>Dashboard</h1>
      <p className="subtitle">Work queue and platform integrity at a glance.</p>

      <div className="notice">
        This platform never auto-submits or auto-signs documentation, and never generates
        final OASIS codes. Every AI suggestion links to source evidence with a confidence score.
      </div>

      <div className="grid2">
        <div className="card stat">
          <div className="n">{tasks.length}</div>
          <div className="l">Open review tasks</div>
        </div>
        <div className="card stat">
          <div className="n">{urgent.length}</div>
          <div className="l">High priority</div>
        </div>
        <div className="card stat">
          <div className="n">{stats ? stats.extracted_fields : "…"}</div>
          <div className="l">Extracted fields (all evidence-backed)</div>
        </div>
        <div className="card stat">
          <div className="n">
            {ledgerValid === null ? "…" : ledgerValid ? "✓ intact" : "⚠ BROKEN"}
          </div>
          <div className="l">Evidence ledger chain</div>
        </div>
      </div>

      <h2>Review queue</h2>
      <table className="data">
        <thead>
          <tr><th>Task</th><th>Type</th><th>Status</th><th>Priority</th><th>Created</th></tr>
        </thead>
        <tbody>
          {tasks.slice(0, 15).map((t) => (
            <tr key={t.id}>
              <td><Link href={`/review?task=${t.id}`}>{t.title}</Link></td>
              <td>{statusLabel(t.subject_type)}</td>
              <td><span className="badge badge-info">{statusLabel(t.status)}</span></td>
              <td>{t.priority}</td>
              <td>{formatDate(t.created_at)}</td>
            </tr>
          ))}
          {tasks.length === 0 && (
            <tr><td colSpan={5} className="muted">Queue is clear.</td></tr>
          )}
        </tbody>
      </table>
    </Shell>
  );
}
