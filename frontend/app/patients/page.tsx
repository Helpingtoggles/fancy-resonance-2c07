"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import Shell from "@/components/Shell";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/format";

type Patient = {
  id: string; mrn: string; first_name: string; last_name: string;
  date_of_birth: string | null; payer: string | null; primary_physician: string | null;
};

export default function PatientsPage() {
  const [patients, setPatients] = useState<Patient[]>([]);
  const [q, setQ] = useState("");

  useEffect(() => {
    const params = q ? `?q=${encodeURIComponent(q)}` : "";
    api<Patient[]>(`/api/v1/patients${params}`).then(setPatients).catch(() => {});
  }, [q]);

  return (
    <Shell>
      <h1>Patients</h1>
      <p className="subtitle">Search by name or MRN.</p>
      <div className="field">
        <input placeholder="Search patients…" value={q} onChange={(e) => setQ(e.target.value)}
               style={{ width: 320 }} />
      </div>
      <table className="data">
        <thead>
          <tr><th>Name</th><th>MRN</th><th>DOB</th><th>Payer</th><th>Physician</th></tr>
        </thead>
        <tbody>
          {patients.map((p) => (
            <tr key={p.id}>
              <td><Link href={`/patients/${p.id}`}>{p.last_name}, {p.first_name}</Link></td>
              <td className="mono">{p.mrn}</td>
              <td>{formatDate(p.date_of_birth)}</td>
              <td>{p.payer ?? "—"}</td>
              <td>{p.primary_physician ?? "—"}</td>
            </tr>
          ))}
          {patients.length === 0 && <tr><td colSpan={5} className="muted">No patients found.</td></tr>}
        </tbody>
      </table>
    </Shell>
  );
}
