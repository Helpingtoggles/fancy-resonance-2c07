"use client";

import { useCallback, useEffect, useState } from "react";
import Shell from "@/components/Shell";
import { api, ApiError } from "@/lib/api";

type Entry = {
  id: number; actor_email: string | null; actor_role: string | null; action: string;
  resource_type: string | null; resource_id: string | null; detail: unknown;
  created_at: string | null; entry_hash: string;
};

export default function AuditPage() {
  const [entries, setEntries] = useState<Entry[]>([]);
  const [chain, setChain] = useState<{ valid: boolean; entries: number } | null>(null);
  const [action, setAction] = useState("");
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(() => {
    const params = action ? `?action=${encodeURIComponent(action)}` : "";
    api<Entry[]>(`/api/v1/audit${params}`)
      .then((e) => { setEntries(e); setError(null); })
      .catch((err) => setError(err instanceof ApiError ? err.message : String(err)));
    api<{ valid: boolean; entries: number }>("/api/v1/audit/verify").then(setChain).catch(() => {});
  }, [action]);
  useEffect(reload, [reload]);

  return (
    <Shell>
      <h1>Audit log</h1>
      <p className="subtitle">
        Hash-chained, append-only record of every state change.{" "}
        {chain && (chain.valid
          ? <span className="badge badge-success">chain intact · {chain.entries} entries</span>
          : <span className="badge badge-error">CHAIN BROKEN</span>)}
      </p>
      {error && <div className="error-box">{error} (audit access requires QA auditor or RN reviewer role)</div>}

      <div className="field">
        <input placeholder="Filter by action, e.g. review.sign" value={action}
               onChange={(e) => setAction(e.target.value)} style={{ width: 320 }} />
      </div>

      <table className="data">
        <thead>
          <tr><th>#</th><th>When</th><th>Actor</th><th>Action</th><th>Resource</th><th>Detail</th></tr>
        </thead>
        <tbody>
          {entries.map((e) => (
            <tr key={e.id}>
              <td className="mono">{e.id}</td>
              <td>{e.created_at ? new Date(e.created_at).toLocaleString() : "—"}</td>
              <td>{e.actor_email ?? "—"}<br /><span className="muted">{e.actor_role ?? ""}</span></td>
              <td className="mono">{e.action}</td>
              <td className="mono">{e.resource_type}{e.resource_id ? `/${e.resource_id.slice(0, 8)}…` : ""}</td>
              <td className="mono" style={{ fontSize: 11, maxWidth: 320, overflowWrap: "anywhere" }}>
                {e.detail ? JSON.stringify(e.detail) : "—"}
              </td>
            </tr>
          ))}
          {entries.length === 0 && !error && <tr><td colSpan={6} className="muted">No entries.</td></tr>}
        </tbody>
      </table>
    </Shell>
  );
}
