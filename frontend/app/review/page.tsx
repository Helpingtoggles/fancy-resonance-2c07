"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import Shell from "@/components/Shell";
import { api, ApiError, getStoredUser, SIGNING_ROLES } from "@/lib/api";
import { formatDate, statusLabel } from "@/lib/format";

type Task = {
  id: string; subject_type: string; subject_id: string; episode_id: string | null;
  title: string; status: string; priority: string; assigned_to: string | null; created_at: string;
};

const NEXT_ACTIONS: Record<string, string[]> = {
  pending: ["claim", "cancel"],
  in_review: ["approve", "request_changes"],
  changes_requested: ["resume"],
  approved: ["sign"],
};

export default function ReviewQueue() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [attestFor, setAttestFor] = useState<string | null>(null);
  const [attestation, setAttestation] = useState(
    "I have reviewed this documentation in full and attest to its accuracy.",
  );

  const user = getStoredUser();
  const canSign = user ? SIGNING_ROLES.includes(user.role) : false;

  const reload = useCallback(() => {
    api<Task[]>("/api/v1/review/tasks").then(setTasks).catch(() => {});
  }, []);
  useEffect(reload, [reload]);

  async function act(task: Task, action: string, attestationText?: string) {
    setError(null);
    try {
      await api(`/api/v1/review/tasks/${task.id}/act`, {
        method: "POST",
        body: JSON.stringify({ action, attestation: attestationText }),
      });
      setAttestFor(null);
      reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    }
  }

  return (
    <Shell>
      <h1>RN review queue</h1>
      <p className="subtitle">
        All AI output lands here. Nothing is signed or submitted without an explicit RN action
        and attestation.
      </p>
      {error && <div className="error-box">{error}</div>}

      <table className="data">
        <thead>
          <tr><th>Task</th><th>Subject</th><th>Status</th><th>Priority</th><th>Created</th><th>Actions</th></tr>
        </thead>
        <tbody>
          {tasks.map((t) => (
            <tr key={t.id}>
              <td>
                {t.title}
                {t.episode_id && (
                  <>
                    {" "}<Link href={`/episodes/${t.episode_id}`} className="muted">(episode)</Link>
                  </>
                )}
                {t.subject_type === "oasis_assessment" && (
                  <>
                    {" "}<Link href={`/oasis/${t.subject_id}`} className="muted">(open assessment)</Link>
                  </>
                )}
              </td>
              <td>{statusLabel(t.subject_type)}</td>
              <td><span className="badge badge-info">{statusLabel(t.status)}</span></td>
              <td>{t.priority}</td>
              <td>{formatDate(t.created_at)}</td>
              <td>
                <div className="row">
                  {(NEXT_ACTIONS[t.status] ?? []).map((action) => {
                    if (action === "sign") {
                      if (!canSign) return <span key={action} className="muted">RN signature required</span>;
                      return (
                        <button key={action} onClick={() => setAttestFor(t.id)}>
                          Sign…
                        </button>
                      );
                    }
                    return (
                      <button key={action} className="secondary" onClick={() => act(t, action)}>
                        {statusLabel(action)}
                      </button>
                    );
                  })}
                </div>
                {attestFor === t.id && (
                  <div className="card" style={{ marginTop: 8 }}>
                    <label htmlFor={`att-${t.id}`}>Attestation (required to sign)</label>
                    <textarea id={`att-${t.id}`} rows={3} style={{ width: "100%" }}
                              value={attestation} onChange={(e) => setAttestation(e.target.value)} />
                    <div className="row" style={{ marginTop: 8 }}>
                      <button onClick={() => act(t, "sign", attestation)}>Sign with attestation</button>
                      <button className="secondary" onClick={() => setAttestFor(null)}>Cancel</button>
                    </div>
                  </div>
                )}
              </td>
            </tr>
          ))}
          {tasks.length === 0 && <tr><td colSpan={6} className="muted">Queue is clear.</td></tr>}
        </tbody>
      </table>
    </Shell>
  );
}
