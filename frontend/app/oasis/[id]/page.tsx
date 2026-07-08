"use client";

import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import Confidence from "@/components/Confidence";
import Shell from "@/components/Shell";
import { api, ApiError, getStoredUser, SIGNING_ROLES } from "@/lib/api";
import { statusLabel } from "@/lib/format";

type Assessment = { id: string; assessment_type: string; status: string; episode_id: string };
type Item = {
  item_id: string; section: string | null; label: string | null;
  allowed_values: string[]; value_type: string; required: boolean;
  suggested_value: string | null; suggested_confidence: number | null;
  suggested_rationale: string | null; evidence_ids: string[] | null;
  final_value: string | null; skipped: string | null;
};
type Completeness = {
  required_items: number; finalized: number; suggested_awaiting_review: number;
  missing: string[]; complete: boolean;
};
type ValidationResult = {
  errors: number; warnings: number; clean: boolean;
  findings: { rule_id: string; severity: string; message: string }[];
};
type Evidence = { snippet: string; method: string; confidence: number };

export default function OasisWorkspace() {
  const { id } = useParams<{ id: string }>();
  const [assessment, setAssessment] = useState<Assessment | null>(null);
  const [items, setItems] = useState<Item[]>([]);
  const [completeness, setCompleteness] = useState<Completeness | null>(null);
  const [validation, setValidation] = useState<ValidationResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const user = getStoredUser();
  const canFinalize = user ? SIGNING_ROLES.includes(user.role) : false;
  const frozen = assessment?.status === "signed" || assessment?.status === "exported";

  const reload = useCallback(() => {
    api<Assessment>(`/api/v1/oasis/${id}`).then(setAssessment).catch(() => {});
    api<Item[]>(`/api/v1/oasis/${id}/items`).then(setItems).catch(() => {});
    api<Completeness>(`/api/v1/oasis/${id}/completeness`).then(setCompleteness).catch(() => {});
  }, [id]);

  useEffect(reload, [reload]);

  async function run(fn: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  const sections = Array.from(new Set(items.map((i) => i.section ?? "other")));

  return (
    <Shell>
      <h1>OASIS-E2 · {assessment ? statusLabel(assessment.assessment_type) : "…"}</h1>
      <p className="subtitle">
        Status: <span className="badge badge-info">{assessment ? statusLabel(assessment.status) : "…"}</span>
        {completeness && (
          <> · {completeness.finalized}/{completeness.required_items} items RN-finalized
            {completeness.suggested_awaiting_review > 0 &&
              ` · ${completeness.suggested_awaiting_review} suggestions awaiting review`}
          </>
        )}
      </p>
      {error && <div className="error-box">{error}</div>}

      <div className="notice">
        AI suggestions below are never final. Each carries evidence and confidence.
        Only an RN reviewer can set final values; the assessment can only be signed through
        the review queue after every required item is finalized and validation is clean.
      </div>

      <div className="card row">
        <button disabled={busy || frozen}
                onClick={() => run(() => api(`/api/v1/oasis/${id}/suggest`, { method: "POST" }))}>
          Generate suggestions from evidence
        </button>
        <button className="secondary" disabled={busy}
                onClick={() => run(async () => {
                  setValidation(await api<ValidationResult>(`/api/v1/oasis/${id}/validate`, { method: "POST" }));
                })}>
          Run CMS validation
        </button>
        {validation && (
          <span>
            {validation.clean
              ? <span className="badge badge-success">validation clean</span>
              : <span className="badge badge-error">{validation.errors} errors</span>}{" "}
            <span className="badge badge-warn">{validation.warnings} warnings</span>
          </span>
        )}
      </div>

      {validation && validation.findings.length > 0 && (
        <div className="card">
          {validation.findings.map((f, idx) => (
            <div key={idx} style={{ marginBottom: 6 }}>
              <span className={`badge ${f.severity === "error" ? "badge-error" : "badge-warn"}`}>
                {f.severity}
              </span>{" "}
              <span className="mono">{f.rule_id}</span> {f.message}
            </div>
          ))}
        </div>
      )}

      {sections.map((section) => (
        <div key={section}>
          <h2>{statusLabel(section)}</h2>
          <table className="data">
            <thead>
              <tr>
                <th style={{ width: 90 }}>Item</th><th>Description</th>
                <th>AI suggestion</th><th style={{ width: 220 }}>RN final value</th>
              </tr>
            </thead>
            <tbody>
              {items.filter((i) => (i.section ?? "other") === section).map((item) => (
                <ItemRow key={item.item_id} item={item} assessmentId={id}
                         canFinalize={canFinalize && !frozen} onChange={reload} />
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </Shell>
  );
}

function ItemRow({ item, assessmentId, canFinalize, onChange }: {
  item: Item; assessmentId: string; canFinalize: boolean; onChange: () => void;
}) {
  const [value, setValue] = useState(item.final_value ?? item.suggested_value ?? "");
  const [showEvidence, setShowEvidence] = useState(false);
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    setValue(item.final_value ?? item.suggested_value ?? "");
  }, [item.final_value, item.suggested_value]);

  async function loadEvidence() {
    setShowEvidence(!showEvidence);
    if (evidence.length === 0 && item.evidence_ids?.length) {
      const loaded = await Promise.all(
        item.evidence_ids.map((eid) => api<Evidence>(`/api/v1/evidence/${eid}`)),
      );
      setEvidence(loaded);
    }
  }

  async function finalize() {
    setErr(null);
    try {
      await api(`/api/v1/oasis/${assessmentId}/items/${item.item_id}/finalize`, {
        method: "POST", body: JSON.stringify({ value }),
      });
      onChange();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    }
  }

  if (item.skipped) {
    return (
      <tr style={{ opacity: 0.5 }}>
        <td className="mono">{item.item_id}</td>
        <td>{item.label}</td>
        <td colSpan={2} className="muted">{item.skipped}</td>
      </tr>
    );
  }

  return (
    <tr>
      <td className="mono">{item.item_id}{item.required && "*"}</td>
      <td>{item.label}</td>
      <td>
        {item.suggested_value !== null ? (
          <>
            <b>{item.suggested_value}</b> <Confidence value={item.suggested_confidence} />{" "}
            {item.evidence_ids?.length ? (
              <button className="secondary" onClick={loadEvidence} style={{ padding: "1px 8px", fontSize: 12 }}>
                evidence
              </button>
            ) : null}
            {item.suggested_rationale && <div className="muted">{item.suggested_rationale}</div>}
            {showEvidence && evidence.map((ev, i) => (
              <div key={i} className="evidence">{ev.snippet}<br />
                <span className="muted">{ev.method} · conf {ev.confidence}</span>
              </div>
            ))}
          </>
        ) : (
          <span className="muted">none</span>
        )}
      </td>
      <td>
        {item.final_value !== null && (
          <span className="badge badge-success" style={{ marginRight: 6 }}>final: {item.final_value}</span>
        )}
        {canFinalize && (
          <div className="row" style={{ marginTop: 4 }}>
            {item.allowed_values.length > 0 && item.value_type !== "text" ? (
              <select value={value} onChange={(e) => setValue(e.target.value)}>
                <option value="">—</option>
                {item.allowed_values.map((v) => <option key={v} value={v}>{v}</option>)}
              </select>
            ) : (
              <input value={value} onChange={(e) => setValue(e.target.value)} style={{ width: 120 }} />
            )}
            <button disabled={!value} onClick={finalize} style={{ padding: "4px 10px", fontSize: 12 }}>
              Finalize
            </button>
          </div>
        )}
        {err && <div className="error-box" style={{ padding: "4px 8px", fontSize: 12 }}>{err}</div>}
      </td>
    </tr>
  );
}
