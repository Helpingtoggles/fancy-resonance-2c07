"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import Shell from "@/components/Shell";
import { api } from "@/lib/api";
import { formatDate, statusLabel } from "@/lib/format";

type Patient = {
  id: string; mrn: string; first_name: string; last_name: string;
  date_of_birth: string | null; payer: string | null; primary_physician: string | null;
  sex: string | null;
};
type Episode = {
  id: string; status: string; soc_date: string | null; referral_date: string | null;
  cert_period_start: string | null; cert_period_end: string | null;
  primary_diagnosis: string | null;
};

export default function PatientDetail() {
  const { id } = useParams<{ id: string }>();
  const [patient, setPatient] = useState<Patient | null>(null);
  const [episodes, setEpisodes] = useState<Episode[]>([]);

  useEffect(() => {
    api<Patient>(`/api/v1/patients/${id}`).then(setPatient).catch(() => {});
    api<Episode[]>(`/api/v1/patients/${id}/episodes`).then(setEpisodes).catch(() => {});
  }, [id]);

  if (!patient) return <Shell><p className="muted">Loading…</p></Shell>;

  return (
    <Shell>
      <h1>{patient.last_name}, {patient.first_name}</h1>
      <p className="subtitle">
        MRN <span className="mono">{patient.mrn}</span> · DOB {formatDate(patient.date_of_birth)} ·{" "}
        {patient.payer ?? "no payer on file"}
      </p>

      <h2>Episodes</h2>
      <table className="data">
        <thead>
          <tr><th>Status</th><th>Referral</th><th>SOC</th><th>Cert period</th><th>Primary dx</th></tr>
        </thead>
        <tbody>
          {episodes.map((e) => (
            <tr key={e.id}>
              <td>
                <Link href={`/episodes/${e.id}`}>
                  <span className="badge badge-info">{statusLabel(e.status)}</span>
                </Link>
              </td>
              <td>{formatDate(e.referral_date)}</td>
              <td>{formatDate(e.soc_date)}</td>
              <td>{formatDate(e.cert_period_start)} – {formatDate(e.cert_period_end)}</td>
              <td>{e.primary_diagnosis ?? "—"}</td>
            </tr>
          ))}
          {episodes.length === 0 && <tr><td colSpan={5} className="muted">No episodes.</td></tr>}
        </tbody>
      </table>
    </Shell>
  );
}
