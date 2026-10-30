# Demo playbook

Target duration: 8–12 minutes. Use synthetic fixtures and a non-production
environment only. Never show `.env`, database credentials, bearer tokens, or
real customer data.

## Preparation

```powershell
cd "C:\Users\Atharva Nilesh Rane\Desktop\Mini-Project- Hackathon\track2-audit-platform"
cd backend
python scripts/seed_demo.py
python -m pytest -q -p no:cacheprovider
python -m uvicorn app.main:app --reload
```

In another terminal:

```powershell
cd "C:\Users\Atharva Nilesh Rane\Desktop\Mini-Project- Hackathon\track2-audit-platform\frontend"
npm run dev
```

Open `http://localhost:3000/dashboard`. The frontend must retain its `PREVIEW
DATA` label until the remaining production adapters are mounted.

## Repeatable sequence

1. **0:00–1:00 — System overview.** Show Finstack navigation, risk summary,
   pipeline status and evidence-first design. State that preview metrics are
   synthetic.
2. **1:00–2:30 — Bounded ingestion.** Open Data ingestion, upload a generated
   P03 CSV, select a source system, and show accepted, rejected and duplicate
   counts. Explain idempotency and quarantine.
3. **2:30–3:30 — Duplicate evidence.** Explain blocking, bounded edit distance,
   deterministic reasons and the rule that evidence is never auto-merged.
4. **3:30–5:00 — Circular and splitting findings.** Use the frozen circular
   cycle and two splitting windows from `expected_findings.json`. Show ordered
   evidence and distinguish financial cycles from workflow cycles.
5. **5:00–6:00 — Rule language.** Validate a typed expression, show exact
   lexer/parser diagnostics, create a draft, and explain immutable activation.
6. **6:00–8:00 — Cases, heap and workflow.** Show priority ordering, one-winner
   claims, stale-version conflict, DAG validation, cycle rejection and task
   unlock after all prerequisites.
7. **8:00–9:00 — RBAC and ledger.** Demonstrate a forbidden action, then show
   append-only activity and hash-chain verification.
8. **9:00–10:30 — Verification evidence.** Open `docs/test-report.md` and
   `docs/benchmark-results.json`; state the workload assumptions and measured
   environment.
9. **10:30–12:00 — Known limitations.** Explicitly disclose that P07,
   production adapters/router composition, Docker runtime, backup confirmation,
   and deployment are not final-release complete.

## Reset and repeatability

- Reuse frozen fixtures; do not edit expected evidence during the demo.
- Generate a new idempotency key only for a genuinely new import.
- Restart the API/frontend if state is uncertain; do not alter Supabase tables
  manually during presentation.
- Run `make release-check` before recording the final demo.
