"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import Confidence from "@/components/Confidence";
import Shell from "@/components/Shell";
import { api, ApiError } from "@/lib/api";
import { formatDate, riskBadgeClass, statusLabel } from "@/lib/format";

type Episode = {
  id: string; patient_id: string; status: string; soc_date: string | null;
  primary_diagnosis: string | null; homebound_narrative: string | null;
  face_to_face_date: string | null;
};
type Doc = { id: string; filename: string; kind: string; status: string; created_at: string };
type Med = {
  id: string; name: string; strength: string | null; route: string | null;
  frequency: string | null; prn: boolean; status: string; is_high_risk: boolean;
};
type Order = {
  id: string; order_type: string | null; order_text: string; ordering_physician: string | null;
  is_verbal: boolean; status: string;
};
type Wound = { id: string; location: string; wound_type: string; pressure_stage: string | null; status: string };
type Infusion = { id: string; drug_name: string; rate_ml_hr: number | null; access_type: string | null; status: string };
type Oasis = { id: string; assessment_type: string; status: string; created_at: string };
type RiskFinding = { id: string; rule_id: string; risk_level: string; rationale: string; remediation: string | null };
type Field = {
  id: string; field_name: string; suggested_value: string | null; confidence: number;
  status: string; final_value: string | null; evidence_id: string;
};

const TABS = ["documents", "medications", "orders", "wounds", "infusion", "oasis", "denial-risk"] as const;
type Tab = (typeof TABS)[number];

export default function EpisodeWorkspace() {
  const { id } = useParams<{ id: string }>();
  const [tab, setTab] = useState<Tab>("documents");
  const [episode, setEpisode] = useState<Episode | null>(null);
  const [docs, setDocs] = useState<Doc[]>([]);
  const [meds, setMeds] = useState<Med[]>([]);
  const [orders, setOrders] = useState<Order[]>([]);
  const [wounds, setWounds] = useState<Wound[]>([]);
  const [infusions, setInfusions] = useState<Infusion[]>([]);
  const [oasis, setOasis] = useState<Oasis[]>([]);
  const [risk, setRisk] = useState<RiskFinding[]>([]);
  const [riskScore, setRiskScore] = useState<{ score: number; level: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const reload = useCallback(() => {
    api<Episode>(`/api/v1/episodes/${id}`).then(setEpisode).catch(() => {});
    api<Doc[]>(`/api/v1/documents?episode_id=${id}`).then(setDocs).catch(() => {});
    api<Med[]>(`/api/v1/medications?episode_id=${id}`).then(setMeds).catch(() => {});
    api<Order[]>(`/api/v1/orders?episode_id=${id}`).then(setOrders).catch(() => {});
    api<Wound[]>(`/api/v1/wounds?episode_id=${id}`).then(setWounds).catch(() => {});
    api<Infusion[]>(`/api/v1/infusion/orders?episode_id=${id}`).then(setInfusions).catch(() => {});
    api<Oasis[]>(`/api/v1/oasis?episode_id=${id}`).then(setOasis).catch(() => {});
    api<RiskFinding[]>(`/api/v1/episodes/${id}/denial-risk`).then(setRisk).catch(() => {});
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

  async function uploadDocument(file: File, kind: string) {
    const form = new FormData();
    form.append("file", file);
    form.append("kind", kind);
    if (episode) form.append("patient_id", episode.patient_id);
    form.append("episode_id", id);
    await run(() => api("/api/v1/documents", { method: "POST", body: form }));
  }

  if (!episode) return <Shell><p className="muted">Loading…</p></Shell>;

  return (
    <Shell>
      <h1>Episode workspace</h1>
      <p className="subtitle">
        {episode.primary_diagnosis ?? "No primary diagnosis"} · SOC {formatDate(episode.soc_date)} ·{" "}
        <span className="badge badge-info">{statusLabel(episode.status)}</span>
      </p>
      {error && <div className="error-box">{error}</div>}

      <div className="tabs">
        {TABS.map((t) => (
          <button key={t} className={tab === t ? "active" : ""} onClick={() => setTab(t)}>
            {statusLabel(t)}
          </button>
        ))}
      </div>

      {tab === "documents" && (
        <>
          <div className="card row">
            <UploadForm onUpload={uploadDocument} busy={busy} />
          </div>
          <table className="data">
            <thead><tr><th>File</th><th>Kind</th><th>Status</th><th>Uploaded</th><th /></tr></thead>
            <tbody>
              {docs.map((d) => (
                <tr key={d.id}>
                  <td>{d.filename}</td>
                  <td>{statusLabel(d.kind)}</td>
                  <td><span className="badge">{statusLabel(d.status)}</span></td>
                  <td>{formatDate(d.created_at)}</td>
                  <td>
                    {(d.status === "ocr_complete" || d.status === "extracted") && (
                      <button className="secondary" disabled={busy}
                              onClick={() => run(() => api(`/api/v1/documents/${d.id}/extract`, { method: "POST" }))}>
                        Extract
                      </button>
                    )}
                  </td>
                </tr>
              ))}
              {docs.length === 0 && <tr><td colSpan={5} className="muted">No documents.</td></tr>}
            </tbody>
          </table>
        </>
      )}

      {tab === "medications" && (
        <>
          <div className="notice">
            Extracted medications require RN reconciliation before becoming active. Review each
            field&apos;s evidence before accepting.
          </div>
          <table className="data">
            <thead><tr><th>Medication</th><th>Sig</th><th>Status</th><th>Flags</th><th>Fields</th><th /></tr></thead>
            <tbody>
              {meds.map((m) => (
                <tr key={m.id}>
                  <td>{m.name} {m.strength ?? ""}</td>
                  <td>{[m.route, m.frequency, m.prn ? "PRN" : null].filter(Boolean).join(" · ") || "—"}</td>
                  <td><span className="badge">{statusLabel(m.status)}</span></td>
                  <td>{m.is_high_risk && <span className="badge badge-error">high-risk</span>}</td>
                  <td><MedFields medId={m.id} /></td>
                  <td>
                    {m.status === "extracted" && (
                      <button className="secondary" disabled={busy}
                              onClick={() => run(() => api(`/api/v1/medications/${m.id}`, {
                                method: "PATCH", body: JSON.stringify({ status: "active" }),
                              }))}>
                        Mark active
                      </button>
                    )}
                  </td>
                </tr>
              ))}
              {meds.length === 0 && <tr><td colSpan={6} className="muted">No medications.</td></tr>}
            </tbody>
          </table>
        </>
      )}

      {tab === "orders" && (
        <table className="data">
          <thead><tr><th>Type</th><th>Order</th><th>Physician</th><th>Status</th></tr></thead>
          <tbody>
            {orders.map((o) => (
              <tr key={o.id}>
                <td>{statusLabel(o.order_type ?? "other")} {o.is_verbal && <span className="badge badge-warn">verbal</span>}</td>
                <td>{o.order_text}</td>
                <td>{o.ordering_physician ?? "—"}</td>
                <td><span className="badge">{statusLabel(o.status)}</span></td>
              </tr>
            ))}
            {orders.length === 0 && <tr><td colSpan={4} className="muted">No orders.</td></tr>}
          </tbody>
        </table>
      )}

      {tab === "wounds" && (
        <table className="data">
          <thead><tr><th>Location</th><th>Type</th><th>Stage</th><th>Status</th></tr></thead>
          <tbody>
            {wounds.map((w) => (
              <tr key={w.id}>
                <td>{w.location}</td>
                <td>{w.wound_type}</td>
                <td>{w.pressure_stage ?? "—"}</td>
                <td><span className="badge">{statusLabel(w.status)}</span></td>
              </tr>
            ))}
            {wounds.length === 0 && <tr><td colSpan={4} className="muted">No wounds documented.</td></tr>}
          </tbody>
        </table>
      )}

      {tab === "infusion" && (
        <table className="data">
          <thead><tr><th>Drug</th><th>Rate (mL/hr)</th><th>Access</th><th>Status</th></tr></thead>
          <tbody>
            {infusions.map((inf) => (
              <tr key={inf.id}>
                <td>{inf.drug_name}</td>
                <td>{inf.rate_ml_hr ?? "—"}</td>
                <td>{inf.access_type ?? "—"}</td>
                <td><span className="badge">{statusLabel(inf.status)}</span></td>
              </tr>
            ))}
            {infusions.length === 0 && <tr><td colSpan={4} className="muted">No infusion orders.</td></tr>}
          </tbody>
        </table>
      )}

      {tab === "oasis" && (
        <>
          <div className="card row">
            <span className="muted">Start a new assessment:</span>
            {["start_of_care", "recertification", "discharge"].map((t) => (
              <button key={t} className="secondary" disabled={busy}
                      onClick={() => run(() => api("/api/v1/oasis", {
                        method: "POST",
                        body: JSON.stringify({ episode_id: id, assessment_type: t }),
                      }))}>
                {statusLabel(t)}
              </button>
            ))}
          </div>
          <table className="data">
            <thead><tr><th>Type</th><th>Status</th><th>Created</th></tr></thead>
            <tbody>
              {oasis.map((a) => (
                <tr key={a.id}>
                  <td><Link href={`/oasis/${a.id}`}>{statusLabel(a.assessment_type)}</Link></td>
                  <td><span className="badge badge-info">{statusLabel(a.status)}</span></td>
                  <td>{formatDate(a.created_at)}</td>
                </tr>
              ))}
              {oasis.length === 0 && <tr><td colSpan={3} className="muted">No assessments.</td></tr>}
            </tbody>
          </table>
        </>
      )}

      {tab === "denial-risk" && (
        <>
          <div className="card row">
            <button disabled={busy}
                    onClick={() => run(async () => {
                      const r = await api<{ score: number; level: string }>(
                        `/api/v1/episodes/${id}/denial-risk`, { method: "POST" });
                      setRiskScore(r);
                    })}>
              Run denial-risk scan
            </button>
            {riskScore && (
              <span>
                Score <b>{riskScore.score}</b>{" "}
                <span className={riskBadgeClass(riskScore.level)}>{riskScore.level}</span>
              </span>
            )}
          </div>
          <table className="data">
            <thead><tr><th>Rule</th><th>Level</th><th>Rationale</th><th>Remediation</th></tr></thead>
            <tbody>
              {risk.map((f) => (
                <tr key={f.id}>
                  <td className="mono">{f.rule_id}</td>
                  <td><span className={riskBadgeClass(f.risk_level)}>{f.risk_level}</span></td>
                  <td>{f.rationale}</td>
                  <td>{f.remediation ?? "—"}</td>
                </tr>
              ))}
              {risk.length === 0 && <tr><td colSpan={4} className="muted">No findings yet — run a scan.</td></tr>}
            </tbody>
          </table>
        </>
      )}
    </Shell>
  );
}

function UploadForm({ onUpload, busy }: { onUpload: (f: File, kind: string) => void; busy: boolean }) {
  const [kind, setKind] = useState("referral");
  const [file, setFile] = useState<File | null>(null);
  return (
    <>
      <select value={kind} onChange={(e) => setKind(e.target.value)}>
        {["referral", "physician_order", "medication_list", "discharge_summary",
          "face_to_face", "wound_photo", "insurance_card", "other"].map((k) => (
          <option key={k} value={k}>{k.replaceAll("_", " ")}</option>
        ))}
      </select>
      <input type="file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
      <button disabled={!file || busy} onClick={() => file && onUpload(file, kind)}>
        Upload &amp; OCR
      </button>
    </>
  );
}

function MedFields({ medId }: { medId: string }) {
  const [fields, setFields] = useState<Field[] | null>(null);
  const [open, setOpen] = useState(false);

  async function load() {
    setOpen(!open);
    if (fields === null) {
      setFields(await api<Field[]>(`/api/v1/evidence/fields/by-entity/medication/${medId}`));
    }
  }

  return (
    <div>
      <button className="secondary" onClick={load}>{open ? "Hide" : "Evidence"}</button>
      {open && fields && (
        <div style={{ marginTop: 6 }}>
          {fields.map((f) => (
            <div key={f.id} style={{ marginBottom: 4 }}>
              <span className="mono">{f.field_name}</span> = {f.suggested_value}{" "}
              <Confidence value={f.confidence} />{" "}
              <span className="badge">{f.status}</span>
            </div>
          ))}
          {fields.length === 0 && <span className="muted">No extracted fields.</span>}
        </div>
      )}
    </div>
  );
}
