# Start of Care (SOC) Packet — Workflow Guide

This folder contains the reusable forms for a home health **Start of Care** admission.
When a patient is assigned, work through the steps below in order. All patient data is
gathered from the **Data Soft Logic (DSL)** EMR — do **not** store completed forms with
patient identifiers (PHI) in this repository; fill them out in the EMR or in your
agency's secure document system and email the finished packet to the shared mailbox.

## Workflow: from assignment to completed SOC

### 1. Patient assigned — gather information from Data Soft Logic
Pull everything available from the EMR before scheduling the visit:

| Where in DSL | What to pull |
|---|---|
| Intake / Referral | Referral date, referral source, ordered SOC date, disciplines ordered |
| Patient Chart → Demographics | Name, MRN, DOB, address, phone, emergency contact, directions to home |
| Patient Chart → Insurance | Payer, policy/HIC/MBI number, eligibility verification, authorization number |
| Physician / Orders | Certifying physician, face-to-face (F2F) encounter documentation, verbal/standing orders |
| Diagnoses | Primary and secondary diagnoses (ICD-10), surgical history |
| Referral documents | Hospital/SNF discharge summary, H&P, medication list from discharge |
| Prior episodes | Any previous admissions, transfer/discharge OASIS |

Use the gathered data to pre-fill **`soc-template.md`** (everything except the items
that require the in-person assessment).

### 2. Schedule the SOC visit and set a reminder
- SOC visit must occur **within 48 hours of referral** (or of the patient's return home),
  or on the physician-ordered SOC date — CoP §484.55(a).
- Call the patient/caregiver, confirm availability, address, and who will be present.
- Enter the appointment in the DSL scheduler and set a reminder (calendar/phone) for the
  clinician for the day before and the morning of the visit.
- Confirm the visit is on the **route sheet** (`route-sheet.md`) for that day.

### 3. Conduct the SOC visit
- Verify identity, complete consents, privacy notice, patient rights, emergency
  preparedness plan, and advance directive discussion.
- Perform the comprehensive assessment (head-to-toe, functional, psychosocial,
  environmental/safety, and OASIS items — see `oasis-soc-checklist.md`).
- Complete the **medication reconciliation** (`medication-reconciliation.md`) against
  every med in the home, the discharge list, and the EMR profile.

### 4. Complete documentation
- Finish the SOC template with the assessment findings.
- The comprehensive assessment / OASIS must be **completed within 5 calendar days
  after the SOC date** (M0090); complete it in DSL so it can be exported/locked and
  transmitted per agency policy (within 30 days of M0090).
- Resolve all medication issues found during reconciliation (physician contacted the
  same day for clinically significant issues — this feeds OASIS drug regimen review
  items M2001–M2005).
- Complete and sign the route sheet with time in/out and mileage.

### 5. Email the completed packet to the shared mailbox
Send the completed SOC template, medication reconciliation, and route sheet to the
agency shared mailbox. Use the agency's secure/encrypted email — the packet contains
PHI. Suggested subject line:

```
SOC Packet – [Patient last name, first initial] – MRN [xxxx] – SOC [date]
```

Attach: SOC template, med reconciliation, route sheet, and note that OASIS was
completed/locked in DSL (do not attach the raw OASIS unless policy requires it).

## Files in this folder

| File | Purpose |
|---|---|
| `soc-template.md` | Full Start of Care visit template form |
| `medication-reconciliation.md` | Medication reconciliation worksheet + drug regimen review |
| `route-sheet.md` | Daily clinician route sheet (visit log, times, mileage) |
| `oasis-soc-checklist.md` | OASIS-E Start of Care completion checklist |
